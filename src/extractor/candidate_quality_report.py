#!/usr/bin/env python3
"""Quality report for statistical MWE candidates.

Analyses a statistical candidates file and prints a structured quality report
with confidence tiers, named-entity overlap, and cross-domain matches.

Usage:
  python3 src/extractor/candidate_quality_report.py \\
      --input data/domain_db/ucc_statistical_candidates.jsonl \\
      --domain-db data/domain_db/ucc_customs.db \\
      [--ne-file data/domain_db/ucc_ne_candidates.jsonl] \\
      [--cross-db data/domain_db/gpmi_lt_tax.db] \\
      [--auto-approve-high]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Confidence thresholds
# ---------------------------------------------------------------------------

HIGH_FREQ: int = 5
HIGH_PMI: float = 15.0
MED_FREQ: int = 3
MED_PMI: float = 10.0


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def load_candidates(path: Path) -> list[dict]:
    """Load all records from a JSONL candidates file."""
    records: list[dict] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def load_ne_phrases(ne_path: Path | None) -> set[str]:
    """Return normalised phrases from a named-entity candidates JSONL file."""
    if ne_path is None or not ne_path.exists():
        return set()
    phrases: set[str] = set()
    with ne_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rec = json.loads(line)
                pn = rec.get("phrase_normalized") or rec.get("phrase", "").lower()
                phrases.add(pn)
    return phrases


def load_cross_db_phrases(cross_db: Path | None, lang: str) -> dict[str, str]:
    """Return {phrase_normalized: domain_label} for phrases in a cross-domain DB.

    Uses the domain column of the mwe table as the label; falls back to the
    DB filename stem if the table is empty.
    """
    if cross_db is None or not cross_db.exists():
        return {}
    conn = sqlite3.connect(cross_db)
    try:
        row = conn.execute("SELECT domain FROM mwe LIMIT 1").fetchone()
        domain_label = row[0] if row else cross_db.stem
        rows = conn.execute(
            "SELECT DISTINCT phrase_normalized FROM mwe_lang WHERE lang = ?",
            (lang,),
        ).fetchall()
        return {r[0]: domain_label for r in rows}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Bucketing
# ---------------------------------------------------------------------------


def bucket(rec: dict) -> str:
    """Return 'high', 'medium', or 'low' confidence tier for a candidate record."""
    freq = rec.get("frequency", 0)
    pmi = float(rec.get("pmi") or 0.0)
    if freq >= HIGH_FREQ and pmi >= HIGH_PMI:
        return "high"
    if freq >= MED_FREQ and pmi >= MED_PMI:
        return "medium"
    return "low"


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def _noise_words(phrase: str) -> bool:
    """Heuristic: True if phrase looks like a UI/CSS artifact rather than legal text."""
    noise_tokens = {
        "css", "flex", "display", "align", "font", "color", "border",
        "padding", "margin", "webkit", "html", "http", "www", "img",
        "javascript", "svg", "aria", "href", "src", "class",
    }
    words = set(phrase.lower().split())
    return bool(words & noise_tokens)


def _fmt_row(rec: dict) -> str:
    phrase = rec.get("phrase", "?")
    freq = rec.get("frequency", 0)
    pmi = float(rec.get("pmi") or 0.0)
    return f"  {phrase:<42} | freq={freq:>3}  pmi={pmi:>7.3f}"


def generate_report(
    candidates: list[dict],
    ne_phrases: set[str],
    cross_db_phrases: dict[str, str],
    input_path: Path,
) -> tuple[list[dict], list[dict], list[dict]]:
    """Print the quality report and return (high, medium, low) candidate lists."""
    high: list[dict] = []
    medium: list[dict] = []
    low: list[dict] = []

    for rec in candidates:
        b = bucket(rec)
        if b == "high":
            high.append(rec)
        elif b == "medium":
            medium.append(rec)
        else:
            low.append(rec)

    # NE overlaps: MWE candidates that also appear in the NE candidates file
    ne_overlaps = [
        rec for rec in candidates
        if (rec.get("phrase_normalized") or rec.get("phrase", "").lower()) in ne_phrases
    ]

    # Cross-domain matches: candidates whose phrase exists in another domain DB
    cross_matches: list[tuple[dict, str]] = []
    for rec in candidates:
        pn = rec.get("phrase_normalized") or rec.get("phrase", "").lower()
        if pn in cross_db_phrases:
            cross_matches.append((rec, cross_db_phrases[pn]))

    # ── Print ────────────────────────────────────────────────────────────────
    print()
    print("═" * 51)
    print("CANDIDATE QUALITY REPORT")
    print(f"Input: {input_path.name}")
    print(f"Total candidates: {len(candidates)}")
    print("═" * 51)

    print(
        f"\nHIGH CONFIDENCE (freq >= {HIGH_FREQ}, pmi >= {HIGH_PMI}): "
        f"{len(high)} candidates"
    )
    for rec in high:
        print(_fmt_row(rec))

    print(
        f"\nMEDIUM CONFIDENCE (freq >= {MED_FREQ}, pmi >= {MED_PMI}): "
        f"{len(medium)} candidates"
    )
    for rec in medium:
        print(_fmt_row(rec))

    print(f"\nLOW CONFIDENCE (everything else): {len(low)} candidates")
    for rec in low:
        print(_fmt_row(rec))

    print(f"\nLIKELY NAMED ENTITIES (also in NE file): {len(ne_overlaps)}")
    for rec in ne_overlaps:
        print(f"  {rec.get('phrase', '?')}")

    print(
        f"\nCROSS-DOMAIN MATCHES (phrase in another domain DB): "
        f"{len(cross_matches)}"
    )
    for rec, domain in cross_matches:
        print(f"  {rec.get('phrase', '?'):<42} | appears_in: {domain}")

    # ── Recommendation ───────────────────────────────────────────────────────
    noise_in_high = sum(1 for r in high if _noise_words(r.get("phrase", "")))
    auto_ok = len(high) > 0 and noise_in_high == 0
    if auto_ok:
        auto_str = f"Y — {len(high)} candidates look clean"
    elif noise_in_high > 0:
        auto_str = f"N — {noise_in_high} of {len(high)} HIGH candidates appear to be HTML/CSS noise"
    else:
        auto_str = "N — no HIGH confidence candidates"

    # ~2 min per 6 candidates for medium + 1 min per 3 for high (closer inspection)
    est_minutes = max(1, len(medium) // 6 + (len(high) + 2) // 3)

    print("\nRECOMMENDATION:")
    print(f"  Auto-approve HIGH CONFIDENCE? {auto_str}")
    print(f"  Estimated review time: ~{est_minutes} minute(s) for high+medium tier")

    return high, medium, low


# ---------------------------------------------------------------------------
# Auto-approve
# ---------------------------------------------------------------------------


def auto_approve_high(input_path: Path, high_records: list[dict]) -> int:
    """Set approved=True on all HIGH CONFIDENCE records and rewrite the file.

    Returns the number of records approved.
    """
    high_phrases = {r.get("phrase") for r in high_records}
    all_records = load_candidates(input_path)
    n_approved = 0
    updated: list[dict] = []
    for rec in all_records:
        if rec.get("phrase") in high_phrases:
            rec = {**rec, "approved": True}
            n_approved += 1
        updated.append(rec)
    with input_path.open("w", encoding="utf-8") as fh:
        for rec in updated:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return n_approved


# ---------------------------------------------------------------------------
# Auto-detect NE file
# ---------------------------------------------------------------------------


def _auto_ne_path(input_path: Path) -> Path | None:
    """Guess the NE candidates path from the MWE candidates filename.

    'ucc_statistical_candidates.jsonl' → 'ucc_ne_candidates.jsonl'
    'ucc_mwe_en.jsonl' → 'ucc_ne_en.jsonl'
    """
    stem = input_path.stem
    replacements = {"statistical_candidates": "ne_candidates", "mwe": "ne"}
    for fragment, replacement in replacements.items():
        if fragment in stem:
            candidate = input_path.parent / (stem.replace(fragment, replacement) + ".jsonl")
            if candidate.exists():
                return candidate
    return None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    """Entry point for the candidate quality report."""
    parser = argparse.ArgumentParser(
        description="Quality report for statistical MWE candidates."
    )
    parser.add_argument(
        "--input", required=True, type=Path,
        help="Path to statistical candidates .jsonl file",
    )
    parser.add_argument(
        "--domain-db", dest="domain_db", type=Path, default=None,
        help="Path to domain DB (for context; not used in bucketing)",
    )
    parser.add_argument(
        "--ne-file", dest="ne_file", type=Path, default=None,
        help="Path to NE candidates .jsonl file (auto-detected if omitted)",
    )
    parser.add_argument(
        "--cross-db", dest="cross_db", type=Path, default=None,
        help="Path to another domain DB for cross-domain match detection",
    )
    parser.add_argument(
        "--auto-approve-high", dest="auto_approve_high", action="store_true",
        help="Set approved=True on all HIGH CONFIDENCE candidates and write back to file",
    )
    args = parser.parse_args(argv)

    if not args.input.exists():
        print(f"Error: input file not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    candidates = load_candidates(args.input)
    if not candidates:
        print("No candidates found.", file=sys.stderr)
        sys.exit(0)

    lang = candidates[0].get("lang", "en")

    # Auto-detect NE file if not given
    ne_path = args.ne_file or _auto_ne_path(args.input)
    ne_phrases = load_ne_phrases(ne_path)
    cross_db_phrases = load_cross_db_phrases(args.cross_db, lang)

    high, _medium, _low = generate_report(
        candidates, ne_phrases, cross_db_phrases, args.input
    )

    if args.auto_approve_high:
        n = auto_approve_high(args.input, high)
        print(f"\nAuto-approved {n} high-confidence candidates")


if __name__ == "__main__":
    main()
