#!/usr/bin/env python3
"""Driver for the inventory-vs-tier root coverage diagnostic (read-only).

Loads ``eo_inventory.json`` + ``lexicon_v2.db`` (read-only), classifies every root
with :mod:`root_tier_coverage`, and emits the review TSVs + a per-tier / bet summary.
Authors nothing.

Usage::

    python3 src/analyzer/build_root_coverage.py \\
        --lexicon data/lexicon_db/lexicon_v2.db \\
        --inventory data/lexicon_db/eo_inventory.json \\
        --out-dir data/analysis/root_coverage
"""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent / "lexicon"))

from root_tier_coverage import (  # noqa: E402
    RootRecord,
    classify_root,
    summarise,
)


def load_covered_tiers(conn: sqlite3.Connection) -> dict[str, list[int]]:
    """Map each concept_root.root to the pedagogical tiers (1-3) anchoring it."""
    out: dict[str, set[int]] = defaultdict(set)
    for root, tier in conn.execute(
        """SELECT cr.root, cl.tier
           FROM concept_root cr JOIN concept_lang cl ON cl.concept_id = cr.concept_id
           WHERE cl.lang='en' AND cl.tier IN (1,2,3)"""
    ):
        out[root].add(tier)
    return {r: sorted(t) for r, t in out.items()}


def load_en_words(conn: sqlite3.Connection) -> frozenset[str]:
    return frozenset(
        w.lower() for (w,) in conn.execute(
            "SELECT DISTINCT word FROM concept_lang WHERE lang='en'"
        )
    )


def load_inflected_map(conn: sqlite3.Connection) -> dict[str, str]:
    """{inflected_word -> lemma} in en (surface->concept lemma; incl. british fold)."""
    return {
        i.lower(): l.lower() for i, l in conn.execute(
            "SELECT inflected_word, lemma FROM inflected_forms "
            "WHERE lang='en' AND LOWER(inflected_word) != LOWER(lemma)"
        )
    }


def make_lemma_fn(use_spacy: bool):
    """A memoized English lemmatizer (spaCy en_core_web_sm), or identity if disabled."""
    if not use_spacy:
        return lambda w: w
    import spacy

    nlp = spacy.load("en_core_web_sm", disable=["parser", "ner"])

    @lru_cache(maxsize=None)
    def lemma(word: str) -> str:
        doc = nlp(word)
        return doc[0].lemma_.lower() if doc else word

    return lemma


def write_full_tsv(records: list[RootRecord], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = ["root", "bucket", "covered_tiers", "inv_tier", "prod",
            "gloss_head", "gloss_zipf", "suggested_tier", "matched_word", "gloss"]
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow(cols)
        for r in records:
            w.writerow([
                r.root, r.bucket, "/".join(map(str, r.covered_tiers)), r.inv_tier,
                r.prod, r.gloss_head, r.gloss_zipf,
                r.suggested_tier if r.suggested_tier else "", r.matched_word, r.gloss,
            ])


def write_candidate_gaps(records: list[RootRecord], path: Path) -> None:
    gaps = [r for r in records if r.bucket == "candidate_gap"]
    gaps.sort(key=lambda r: (-r.gloss_zipf, r.root))
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow(["root", "gloss_head", "gloss_zipf", "suggested_tier",
                    "inv_tier", "prod", "gloss"])
        for r in gaps:
            w.writerow([r.root, r.gloss_head, r.gloss_zipf, r.suggested_tier,
                        r.inv_tier, r.prod, r.gloss])


def write_shade_mismatches(records: list[RootRecord], path: Path) -> None:
    shades = [r for r in records if r.bucket == "shade_mismatch"]
    shades.sort(key=lambda r: (-r.gloss_zipf, r.root))
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow(["root", "gloss_head", "matched_covered_word", "gloss_zipf",
                    "inv_tier", "prod", "gloss"])
        for r in shades:
            w.writerow([r.root, r.gloss_head, r.matched_word, r.gloss_zipf,
                        r.inv_tier, r.prod, r.gloss])


def main(argv: list[str] | None = None) -> int:
    root = _HERE.parent.parent
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--lexicon", type=Path, default=root / "data" / "lexicon_db" / "lexicon_v2.db")
    ap.add_argument("--inventory", type=Path, default=root / "data" / "lexicon_db" / "eo_inventory.json")
    ap.add_argument("--out-dir", type=Path, default=root / "data" / "analysis" / "root_coverage")
    ap.add_argument("--no-spacy", action="store_true", help="identity lemmatizer (faster; tests)")
    args = ap.parse_args(argv)

    from wordfreq import zipf_frequency  # mandatory commonness gate
    sys.path.insert(0, str(root / "src" / "lexicon"))
    from build_gapfill_worksheet import uk_to_us

    inv = json.loads(args.inventory.read_text(encoding="utf-8"))["roots"]
    conn = sqlite3.connect(f"file:{args.lexicon}?mode=ro", uri=True)
    covered = load_covered_tiers(conn)
    en_words = load_en_words(conn)
    inflected_map = load_inflected_map(conn)
    conn.close()
    lemma_fn = make_lemma_fn(not args.no_spacy)

    print(f"inventory roots: {len(inv)} | covered T1-3 roots: {len(covered)} | "
          f"en concept words: {len(en_words)} | inflected map: {len(inflected_map)}")

    records: list[RootRecord] = []
    for r, entry in inv.items():
        records.append(classify_root(
            r, entry, covered.get(r, []), en_words,
            lambda w: zipf_frequency(w, "en"), lemma_fn, inflected_map, uk_to_us,
        ))

    out = args.out_dir.expanduser()
    out.mkdir(parents=True, exist_ok=True)
    write_full_tsv(records, out / "root_tier_coverage.tsv")
    write_candidate_gaps(records, out / "candidate_gaps.tsv")
    write_shade_mismatches(records, out / "shade_mismatches.tsv")

    _report(records, covered)
    print(f"\nwrote -> {out}/ (root_tier_coverage.tsv, candidate_gaps.tsv, shade_mismatches.tsv)")
    return 0


def _report(records: list[RootRecord], covered: dict[str, list[int]]) -> None:
    s = summarise(records)
    print("\n" + "=" * 68)
    print("BUCKETS")
    print("=" * 68)
    for b, n in s["buckets"].items():
        print(f"  {b:16} {n:>6}")
    # covered roots by MIN tier (disjoint) and ANY tier
    min_tier = Counter(min(t) for t in covered.values())
    any_tier = Counter()
    for t in covered.values():
        for x in t:
            any_tier[x] += 1
    print("-" * 68)
    print("COVERED roots by MIN tier :", {t: min_tier.get(t, 0) for t in (1, 2, 3)})
    print("COVERED roots by ANY tier :", {t: any_tier.get(t, 0) for t in (1, 2, 3)})
    gap_t = s["candidate_gap_by_suggested_tier"]
    print("candidate_gap by SUGGESTED tier:", gap_t)
    print("candidate_gap by inventory tier:", s["candidate_gap_by_inventory_tier"])
    print("-" * 68)
    print("THE BET — gap(suggested tier) / covered(that tier):")
    for t in (1, 2, 3):
        cov_min = min_tier.get(t, 0)
        cov_any = any_tier.get(t, 0)
        g = gap_t.get(t, 0)
        rmin = f"{g/cov_min:.2f}x" if cov_min else "n/a"
        rany = f"{g/cov_any:.2f}x" if cov_any else "n/a"
        print(f"  T{t}: gap={g:>4}  vs covered(min={cov_min},any={cov_any})  "
              f"-> ratio min={rmin} any={rany}")


if __name__ == "__main__":
    sys.exit(main())
