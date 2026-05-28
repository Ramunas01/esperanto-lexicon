#!/usr/bin/env python3
"""Batch coverage report across a corpus tree.

Walks every ``.txt`` file under ``--corpus`` recursively, runs the
``coverage_report`` classification pipeline on each, and emits:

  1. A CSV summary (one row per file) at ``--output``.
  2. A pooled UNKNOWN-token frequency file alongside the CSV
     (``unknown_tokens_pooled.txt``) — input for Tier 3 triage.
  3. A stratum-grouped summary table printed to stdout.

Each file's ``stratum`` is the name of its immediate parent directory, which
lets the corpus encode proficiency strata as subdirectories
(``corpus/control/``, ``corpus/novice/``, ``corpus/expert/`` …).

Usage:
    python3 src/analyzer/batch_coverage_report.py \\
        --corpus ~/projects/esperanto-lexicon-corpus/proficiency_eval/ \\
        --lang en \\
        --lexicon data/lexicon_db/lexicon_v2.db \\
        --domain-dbs data/domain_db/ucc_customs.db \\
                     data/domain_db/wco_intl.db \\
                     data/domain_db/cbam.db \\
                     data/domain_db/dualuse.db \\
        --output data/analysis/proficiency_baseline.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean

# Allow `python3 src/analyzer/batch_coverage_report.py …` (sibling import).
sys.path.insert(0, str(Path(__file__).resolve().parent))

from coverage_report import (  # noqa: E402
    TokenResult,
    _load_nlp,
    classify_tokens,
    compute_summary,
    load_mwe_phrases,
    load_synonym_map,
    load_tier_words,
    spacy_tokenise,
)


# ---------------------------------------------------------------------------
# Per-file analysis
# ---------------------------------------------------------------------------


def _collect_unknown_texts(results: list[TokenResult]) -> list[str]:
    """Return lowercased text of every UNKNOWN-classified result (with repeats)."""
    return [r.text.lower() for r in results if r.category == "UNKNOWN"]


def analyse_file(
    path: Path,
    nlp,
    mwe_phrases: set[str],
    tier1: set[str],
    tier2: set[str],
    synonym_map: dict[str, str],
    *,
    fallback_tier1: set[str] | None = None,
    fallback_tier2: set[str] | None = None,
) -> tuple[dict, list[str]]:
    """Classify one file's tokens.

    Returns a ``(row, unknown_texts)`` pair where ``row`` is the CSV record
    and ``unknown_texts`` is the (possibly repeating) list of UNKNOWN token
    surface forms to fold into the pooled frequency counter.
    """
    text = path.read_text(encoding="utf-8").strip()
    tokens = spacy_tokenise(text, nlp)
    results = classify_tokens(
        tokens,
        mwe_phrases,
        tier1,
        tier2,
        fallback_tier1=fallback_tier1,
        fallback_tier2=fallback_tier2,
        synonym_map=synonym_map if synonym_map else None,
    )
    summary = compute_summary(results)
    counts = summary["counts"]
    es = summary["expertise_signal"]

    total_classified = (
        counts["TIER1"] + counts["TIER2"] + counts["TIER4"] + counts["UNKNOWN"]
    )
    unknown_texts = _collect_unknown_texts(results)

    row = {
        "filename": path.name,
        "stratum": path.parent.name,
        "total_tokens": total_classified,
        "t1_count": counts["TIER1"],
        "t2_count": counts["TIER2"],
        # Tier 3 is not yet built (see CLAUDE.md); column reserved for future use.
        "t3_count": 0,
        "t4_count": counts["TIER4"],
        "unknown_count": counts["UNKNOWN"],
        "t4_ratio": round(es["ratio"], 4),
        "common_ratio": round(es["common_pct"], 4),
        "unknown_tokens": json.dumps(
            sorted(set(unknown_texts)), ensure_ascii=False
        ),
    }
    return row, unknown_texts


# ---------------------------------------------------------------------------
# Domain DB aggregation
# ---------------------------------------------------------------------------


def load_domain_data(
    domain_dbs: list[Path], lang: str
) -> tuple[set[str], dict[str, str]]:
    """Union MWE phrases and merge synonym maps across multiple domain DBs.

    Synonym entries from later DBs overwrite earlier ones on key collision.
    """
    mwe_phrases: set[str] = set()
    synonym_map: dict[str, str] = {}
    for db in domain_dbs:
        mwe_phrases |= load_mwe_phrases(db, lang)
        synonym_map.update(load_synonym_map(db, lang))
    return mwe_phrases, synonym_map


# ---------------------------------------------------------------------------
# Output: CSV, pooled UNKNOWN, summary table
# ---------------------------------------------------------------------------


CSV_FIELDS = [
    "filename",
    "stratum",
    "total_tokens",
    "t1_count",
    "t2_count",
    "t3_count",
    "t4_count",
    "unknown_count",
    "t4_ratio",
    "common_ratio",
    "unknown_tokens",
]


def write_csv(rows: list[dict], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_unknown_pool(unknown_counter: Counter[str], path: Path) -> None:
    """Write ``COUNT\\tTOKEN`` lines sorted by count descending."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"{count}\t{token}"
        for token, count in unknown_counter.most_common()
    ]
    body = "\n".join(lines) + ("\n" if lines else "")
    path.write_text(body, encoding="utf-8")


def _unknown_pct(row: dict) -> float:
    total = row["total_tokens"] or 1
    return row["unknown_count"] / total


def print_summary_table(rows: list[dict]) -> None:
    """Print per-file table sorted by (stratum, filename), then per-stratum averages."""
    if not rows:
        print("(no files analysed)")
        return

    rows_sorted = sorted(rows, key=lambda r: (r["stratum"], r["filename"]))

    stratum_w = max(len("Stratum"), max(len(r["stratum"]) for r in rows_sorted))
    file_w = max(len("File"), max(len(r["filename"]) for r in rows_sorted))

    header = (
        f"{'Stratum':<{stratum_w}}  "
        f"{'File':<{file_w}}  "
        f"{'T4_ratio':>8}  "
        f"{'T1+T2%':>7}  "
        f"{'UNKNOWN%':>8}"
    )
    sep = "─" * len(header)
    print(header)
    print(sep)

    for r in rows_sorted:
        print(
            f"{r['stratum']:<{stratum_w}}  "
            f"{r['filename']:<{file_w}}  "
            f"{r['t4_ratio']:>8.3f}  "
            f"{r['common_ratio'] * 100:>6.1f}%  "
            f"{_unknown_pct(r) * 100:>7.1f}%"
        )

    by_stratum: dict[str, list[dict]] = defaultdict(list)
    for r in rows_sorted:
        by_stratum[r["stratum"]].append(r)

    print(sep)
    print("Stratum averages:")
    print(sep)
    for stratum, group in sorted(by_stratum.items()):
        avg_ratio = mean(r["t4_ratio"] for r in group)
        avg_common = mean(r["common_ratio"] for r in group)
        avg_unknown = mean(_unknown_pct(r) for r in group)
        label = f"(n={len(group)})"
        print(
            f"{stratum:<{stratum_w}}  "
            f"{label:<{file_w}}  "
            f"{avg_ratio:>8.3f}  "
            f"{avg_common * 100:>6.1f}%  "
            f"{avg_unknown * 100:>7.1f}%"
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run coverage_report classification on every .txt file under a "
            "corpus tree, then emit a CSV summary and a pooled UNKNOWN-token "
            "frequency file."
        )
    )
    parser.add_argument(
        "--corpus",
        required=True,
        type=Path,
        help="Corpus root directory; walked recursively for .txt files",
    )
    parser.add_argument(
        "--lang",
        required=True,
        choices=["lt", "en", "eo"],
        help="Language code",
    )
    parser.add_argument(
        "--lexicon",
        required=True,
        type=Path,
        help="Path to lexicon_v2.db",
    )
    parser.add_argument(
        "--domain-dbs",
        dest="domain_dbs",
        nargs="+",
        type=Path,
        default=[],
        help="One or more domain .db files; their mwe_lang phrases are unioned",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="CSV output path. The pooled UNKNOWN file is written next to it.",
    )
    parser.add_argument(
        "--fallback-lang",
        dest="fallback_lang",
        default=None,
        help=(
            "Fallback language for Tier 1/2 lookup when primary lang has no "
            "common lexicon entries"
        ),
    )
    args = parser.parse_args(argv)

    corpus = args.corpus.expanduser()
    if not corpus.exists() or not corpus.is_dir():
        print(
            f"--corpus is not an existing directory: {corpus}",
            file=sys.stderr,
        )
        sys.exit(1)

    txt_files = sorted(corpus.rglob("*.txt"))
    if not txt_files:
        print(f"No .txt files found under {corpus}", file=sys.stderr)
        sys.exit(1)

    tier1, tier2 = load_tier_words(args.lexicon, args.lang)
    fb_t1: set[str] = set()
    fb_t2: set[str] = set()
    if args.fallback_lang:
        fb_t1, fb_t2 = load_tier_words(args.lexicon, args.fallback_lang)

    mwe_phrases, synonym_map = load_domain_data(args.domain_dbs, args.lang)
    nlp = _load_nlp(args.lang)

    rows: list[dict] = []
    unknown_counter: Counter[str] = Counter()

    for path in txt_files:
        try:
            row, unknowns = analyse_file(
                path,
                nlp,
                mwe_phrases,
                tier1,
                tier2,
                synonym_map,
                fallback_tier1=fb_t1 if args.fallback_lang else None,
                fallback_tier2=fb_t2 if args.fallback_lang else None,
            )
        except Exception as exc:  # noqa: BLE001 — surface per-file failures, keep going
            print(f"WARN: failed to analyse {path}: {exc}", file=sys.stderr)
            continue
        rows.append(row)
        unknown_counter.update(unknowns)

    rows.sort(key=lambda r: (r["stratum"], r["filename"]))

    output_path = args.output.expanduser()
    write_csv(rows, output_path)
    pool_path = output_path.parent / "unknown_tokens_pooled.txt"
    write_unknown_pool(unknown_counter, pool_path)

    print_summary_table(rows)
    print()
    print(f"CSV written : {output_path}")
    print(f"Unknown pool: {pool_path}")


if __name__ == "__main__":
    main()
