#!/usr/bin/env python3
"""Enrich and bucket merged MWE candidates for fast, prioritised human review.

This is a post-processing step on top of ``merge_area_candidates``. It does NOT
modify the merge tool, the schema, or the signature logic; it reads the existing
``merged_candidates.jsonl`` and produces:

  1. ``merged_candidates_enriched.jsonl`` — every candidate, plus two new
     fields: ``ne_risk`` (heuristic named-entity probability) and
     ``appears_in_low_scorers`` (which known low-scoring expert texts the phrase
     occurs in — direct coverage-uplift opportunities).
  2. Four bucketed review files of decreasing priority, each pre-sorted and with
     a human-readable comment line above every JSON record.

Candidates that already have an exact (normalised) match in any of the five
domain DBs (ucc, wco, cbam, dualuse, customs_expert_vocab) are excluded from the
buckets — they are already committed and would not lift coverage if "approved".
They still appear in the enriched file; the skip happens only at bucketing.

Usage:
    python3 src/extractor/bucket_candidates.py
    python3 src/extractor/bucket_candidates.py \\
        --input data/domain_db/merged_candidates.jsonl \\
        --outdir data/domain_db \\
        --corpus-root ~/projects/esperanto-lexicon-corpus
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

# area_signature.py lives in src/lexicon/; resolve relative to this file.
sys.path.insert(0, str(Path(__file__).parent.parent))
from lexicon.area_signature import CANONICAL_AREAS, CROSS_CUTTING

# ---------------------------------------------------------------------------
# Configuration / constants
# ---------------------------------------------------------------------------

DOMAIN_DBS = [
    "ucc_customs",
    "wco_intl",
    "cbam",
    "dualuse",
    "customs_expert_vocab",
]

LOW_SCORER_FILES = ["expert_04", "expert_06", "expert_07"]

# Case-insensitive substring triggers for the country/region NE signal.
COUNTRY_TERMS = [
    "ireland", "irish", "ukraine", "ukrainian", "russia", "russian", "china",
    "chinese", "japan", "japanese", "korea", "korean", "india", "indian",
    "brazil", "brazilian", "germany", "german", "france", "french", "italy",
    "italian", "spain", "spanish", "portugal", "portuguese", "netherlands",
    "dutch", "belgium", "belgian", "poland", "polish", "lithuania",
    "lithuanian", "latvia", "latvian", "estonia", "estonian", "finland",
    "finnish", "sweden", "swedish", "denmark", "danish", "norway",
    "norwegian", "kingdom", "united kingdom", "uk", "eu", "european",
    "united states", "america", "american", "canada", "canadian", "mexico",
    "mexican", "africa", "african", "asia", "asian",
]

# Standalone organisation acronyms (matched token-wise, case-insensitive).
ORG_ACRONYMS = {
    "afcfta", "ecowas", "asean", "ceta", "nafta", "usmca", "mercosur",
    "efta", "oecd", "wto", "wco", "un", "eu",
}

TOP_N_PER_AREA = 30


# ---------------------------------------------------------------------------
# Text normalisation
# ---------------------------------------------------------------------------

def normalise(text: str | None) -> str:
    """Lowercase, strip punctuation to spaces, and collapse whitespace.

    Used uniformly for phrase matching against both the DB and the expert
    texts so that hyphenation and punctuation never cause spurious misses.
    """
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", (text or "").lower())).strip()


# ---------------------------------------------------------------------------
# Enrichment: ne_risk
# ---------------------------------------------------------------------------

def compute_ne_risk(record: dict) -> float:
    """Heuristic estimate (0..1) that a phrase is a named entity, not vocabulary.

    Higher = more likely an NE = lower confidence in approval. Signals are
    summed (each adds its weight if true) and the result is clamped to [0, 1].
    """
    score = 0.0

    pos = record.get("pos_pattern") or ""
    pos_tokens = pos.split()
    if pos_tokens and pos_tokens[0] == "PROPN":
        score += 0.35
        if all(t == "PROPN" for t in pos_tokens):
            score += 0.25

    # ALL-CAPS token (>=3 chars) in the inflected form -> likely acronym.
    surface = record.get("phrase_inflected") or record.get("phrase_normalized") or ""
    for tok in re.findall(r"[A-Za-z]+", surface):
        if len(tok) >= 3 and tok.isupper():
            score += 0.20
            break

    phrase = (record.get("phrase_normalized") or "").lower()
    if any(term in phrase for term in COUNTRY_TERMS):
        score += 0.30

    if ORG_ACRONYMS.intersection(phrase.split()):
        score += 0.30

    if record.get("area_specificity") == 1.0 and record.get("total_doc_count", 0) <= 4:
        score += 0.20

    return max(0.0, min(1.0, round(score, 4)))


# ---------------------------------------------------------------------------
# Enrichment: appears_in_low_scorers
# ---------------------------------------------------------------------------

def find_low_scorers(
    phrase_normalized: str, low_scorer_texts: dict[str, str]
) -> list[str]:
    """Return the low-scorer file labels whose (normalised) text contains the phrase.

    Args:
        phrase_normalized: the candidate phrase.
        low_scorer_texts: {label: already-normalised text}.
    """
    needle = normalise(phrase_normalized)
    if not needle:
        return []
    return [label for label, text in low_scorer_texts.items() if needle in text]


# ---------------------------------------------------------------------------
# Loading helpers
# ---------------------------------------------------------------------------

def load_jsonl(path: Path) -> list[dict]:
    """Load a JSONL file into a list of dicts."""
    records: list[dict] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def load_db_phrases(domain_db_dir: Path) -> set[str]:
    """Collect normalised mwe_lang phrases across all five domain DBs."""
    phrases: set[str] = set()
    for name in DOMAIN_DBS:
        path = domain_db_dir / f"{name}.db"
        if not path.exists():
            continue
        conn = sqlite3.connect(str(path))
        try:
            for (phrase,) in conn.execute("SELECT phrase FROM mwe_lang"):
                phrases.add(normalise(phrase))
        finally:
            conn.close()
    return phrases


def load_low_scorer_texts(corpus_root: Path) -> dict[str, str]:
    """Load and normalise the three known low-scoring expert texts."""
    base = corpus_root / "proficiency_eval" / "expert"
    texts: dict[str, str] = {}
    for label in LOW_SCORER_FILES:
        path = base / f"{label}.txt"
        texts[label] = normalise(path.read_text(encoding="utf-8")) if path.exists() else ""
    return texts


# ---------------------------------------------------------------------------
# Enrichment driver
# ---------------------------------------------------------------------------

def enrich(records: list[dict], low_scorer_texts: dict[str, str]) -> list[dict]:
    """Return records with ne_risk and appears_in_low_scorers added in place."""
    for rec in records:
        rec["ne_risk"] = compute_ne_risk(rec)
        rec["appears_in_low_scorers"] = find_low_scorers(
            rec.get("phrase_normalized", ""), low_scorer_texts
        )
    return records


# ---------------------------------------------------------------------------
# Bucketing
# ---------------------------------------------------------------------------

def _canonical_doc_counts(record: dict) -> dict[str, int]:
    """Sum doc_count per canonical area for one record (cross-cutting dropped)."""
    sums: dict[str, int] = {}
    for row in record.get("attestation", []):
        area = row.get("area")
        if area in CANONICAL_AREAS:
            sums[area] = sums.get(area, 0) + int(row.get("doc_count") or 0)
    return sums


def _count_canonical_areas(record: dict) -> int:
    """Number of distinct canonical areas a record is attested in."""
    return len(_canonical_doc_counts(record))


def _dominant_area(record: dict) -> str:
    """Canonical area with the highest doc_count (ties broken by area order)."""
    sums = _canonical_doc_counts(record)
    if not sums:
        return CROSS_CUTTING
    return max(sums.items(), key=lambda kv: (kv[1], -CANONICAL_AREAS.index(kv[0])))[0]


def _low_scorer_numbers(record: dict) -> list[str]:
    """File numbers ('04','07') from appears_in_low_scorers labels."""
    out = []
    for label in record.get("appears_in_low_scorers", []):
        m = re.search(r"(\d+)", label)
        if m:
            out.append(m.group(1))
    return out


def assign_buckets(
    enriched: list[dict], skip_phrases: set[str]
) -> dict[str, list[dict]]:
    """Assign enriched candidates to the four review buckets.

    Candidates whose normalised phrase is in ``skip_phrases`` (already committed
    to a domain DB) are excluded entirely. Rules are applied first-match-wins in
    bucket order; bucket 3 is then capped at the top 30 per dominant area, with
    the tail spilling into bucket 4.
    """
    b1: list[dict] = []
    b2: list[dict] = []
    b3_candidates: list[dict] = []
    b4: list[dict] = []

    for rec in enriched:
        if normalise(rec.get("phrase_normalized", "")) in skip_phrases:
            continue

        n_areas = _count_canonical_areas(rec)

        # Bucket 1 — attested in 4+ canonical areas (general customs vocab).
        if n_areas >= 4:
            b1.append(rec)
            continue

        # Bucket 2 — appears in a known low-scoring expert text (uplift targets).
        if rec.get("appears_in_low_scorers"):
            b2.append(rec)
            continue

        # Bucket 3 candidate — area discriminator (1-3 areas, specific, low NE).
        if (
            1 <= n_areas <= 3
            and rec.get("area_specificity", 0.0) >= 0.5
            and rec.get("ne_risk", 0.0) < 0.5
        ):
            b3_candidates.append(rec)
            continue

        # Bucket 4 — everything else.
        b4.append(rec)

    # Bucket 3: group by dominant area, keep top 30 per area; spill the rest.
    by_area: dict[str, list[dict]] = {}
    for rec in b3_candidates:
        by_area.setdefault(_dominant_area(rec), []).append(rec)

    b3: list[dict] = []
    for area in sorted(
        by_area, key=lambda a: sum(r["total_doc_count"] for r in by_area[a]), reverse=True
    ):
        group = sorted(
            by_area[area],
            key=lambda r: (r.get("area_specificity", 0.0), r["total_doc_count"]),
            reverse=True,
        )
        b3.extend(group[:TOP_N_PER_AREA])
        b4.extend(group[TOP_N_PER_AREA:])

    # Final per-bucket sorts.
    b1.sort(key=lambda r: r["total_doc_count"], reverse=True)
    b2.sort(key=lambda r: (len(r["appears_in_low_scorers"]), r["total_doc_count"]), reverse=True)
    b4.sort(key=lambda r: r["total_doc_count"], reverse=True)

    return {"bucket_1": b1, "bucket_2": b2, "bucket_3": b3, "bucket_4": b4}


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

def comment_line(record: dict) -> str:
    """One-line human-readable summary prepended above each bucketed record."""
    nums = _low_scorer_numbers(record)
    low = ",".join(nums) if nums else "none"
    return (
        f"# [{record.get('area_signature', '?')} "
        f"spec={record.get('area_specificity', 0.0):.2f} "
        f"ne_risk={record.get('ne_risk', 0.0):.2f} "
        f"low={low}] "
        f"{record.get('phrase_normalized', '')} "
        f"({record.get('pos_pattern') or '?'}, "
        f"doc={record.get('total_doc_count', 0)} "
        f"freq={record.get('total_frequency', 0)})"
    )


def write_bucket(path: Path, records: list[dict]) -> None:
    """Write a bucket file: a comment line then the JSON record, per candidate."""
    with path.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(comment_line(rec) + "\n")
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def _ne_risk_distribution(records: list[dict]) -> tuple[int, int, int]:
    """Counts of ne_risk in [0,0.2), [0.2,0.5), [0.5,1.0]."""
    low = mid = high = 0
    for rec in records:
        v = rec.get("ne_risk", 0.0)
        if v < 0.2:
            low += 1
        elif v < 0.5:
            mid += 1
        else:
            high += 1
    return low, mid, high


def print_report(
    enriched: list[dict],
    buckets: dict[str, list[dict]],
    skipped: int,
    low_scorer_texts: dict[str, str],
) -> None:
    """Print the enrichment distribution, bucket counts, and sample entries."""
    low, mid, high = _ne_risk_distribution(enriched)
    print()
    print("Enrichment summary")
    print(f"    ne_risk 0.0-0.2 : {low:>5}")
    print(f"    ne_risk 0.2-0.5 : {mid:>5}")
    print(f"    ne_risk 0.5-1.0 : {high:>5}")
    print()
    for label in LOW_SCORER_FILES:
        n = sum(1 for r in enriched if label in r.get("appears_in_low_scorers", []))
        print(f"    appears in {label} : {n:>5}")

    n1 = len(buckets["bucket_1"])
    n2 = len(buckets["bucket_2"])
    n3 = len(buckets["bucket_3"])
    n4 = len(buckets["bucket_4"])
    bucketed = n1 + n2 + n3 + n4
    print()
    print(f"    Bucket 1 (general, all areas)       :  {n1} candidates")
    print(f"    Bucket 2 (low-scorer targeted)      :  {n2} candidates")
    print(f"    Bucket 3 (area-specific top-30/area) :  {n3} candidates")
    print(f"    Bucket 4 (defer)                    :  {n4} candidates")
    print("                                           -----")
    print(f"    Bucketed                            :  {bucketed}")
    print(f"    Skipped (already in a domain DB)    :  {skipped}")
    print(f"    Total input                         :  {bucketed + skipped}")
    print()
    print("    Recommended review order: 1, 2, 3, stop when attention flags.")
    print("    Bucket 4 can be revisited later or after future mining.")

    for key in ("bucket_1", "bucket_2", "bucket_3", "bucket_4"):
        print()
        print(f"--- {key} sample (first 5) ---")
        for rec in buckets[key][:5]:
            print(comment_line(rec))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(input_path: Path, outdir: Path, corpus_root: Path) -> dict:
    """Enrich, bucket, write all files, print the report. Returns the buckets."""
    records = load_jsonl(input_path)
    low_scorer_texts = load_low_scorer_texts(corpus_root)
    skip_phrases = load_db_phrases(outdir)

    enriched = enrich(records, low_scorer_texts)

    enriched_path = outdir / "merged_candidates_enriched.jsonl"
    with enriched_path.open("w", encoding="utf-8") as fh:
        for rec in enriched:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    buckets = assign_buckets(enriched, skip_phrases)
    names = {
        "bucket_1": "review_bucket_1_general.jsonl",
        "bucket_2": "review_bucket_2_low_scorer_targeted.jsonl",
        "bucket_3": "review_bucket_3_area_specific.jsonl",
        "bucket_4": "review_bucket_4_defer.jsonl",
    }
    for key, fname in names.items():
        write_bucket(outdir / fname, buckets[key])

    skipped = sum(
        1 for r in records if normalise(r.get("phrase_normalized", "")) in skip_phrases
    )
    print_report(enriched, buckets, skipped, low_scorer_texts)
    return buckets


def main(argv: list[str] | None = None) -> None:
    """CLI entry point for bucket_candidates."""
    parser = argparse.ArgumentParser(
        description="Enrich and bucket merged MWE candidates for review."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("data/domain_db/merged_candidates.jsonl"),
        help="Merged candidates JSONL (output of merge_area_candidates).",
    )
    parser.add_argument(
        "--outdir",
        type=Path,
        default=Path("data/domain_db"),
        help="Directory for enriched + bucket files; also holds the domain DBs.",
    )
    parser.add_argument(
        "--corpus-root",
        type=Path,
        default=Path("~/projects/esperanto-lexicon-corpus").expanduser(),
        help="Root of the corpus repo (holds proficiency_eval/expert/).",
    )
    args = parser.parse_args(argv)
    run(args.input, args.outdir, args.corpus_root.expanduser())


if __name__ == "__main__":
    main()
