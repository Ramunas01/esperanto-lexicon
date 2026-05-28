#!/usr/bin/env python3
"""Batch coverage report across a corpus tree.

Walks every ``.txt`` file under ``--corpus`` recursively (skipping files
directly in the corpus root — those are metadata, not evaluation texts),
runs the coverage_report classification pipeline on each, and emits:

  1. A CSV summary (one row per file) at ``--output``.
  2. A pooled UNKNOWN-token frequency file alongside the CSV
     (``unknown_tokens_pooled.txt``) — input for Tier 3 triage.
  3. A stratum-grouped summary table printed to stdout.
  4. A comparison block showing all four expertise measures side by side.

Each file's ``stratum`` is the name of its immediate parent directory, which
lets the corpus encode proficiency strata as subdirectories
(``corpus/control/``, ``corpus/novice/``, ``corpus/expert/`` …).

Expertise measures:
  density (existing):
    T4_ratio = T4_hits / (T1+T2 hits)
  variety (new):
    distinct_t4 = count of unique matched phrase_normalized keys
    t4_variety  = distinct_t4 / total_content_tokens
  relational (new):
    cooccur_pairs = Σ C(k,2) over sentences where k = distinct T4 concepts
    cooccur_density = cooccur_pairs / n_sentences
    multi_concept_ratio = sentences(k≥2) / sentences(k≥1)

Usage:
    python3 src/analyzer/batch_coverage_report.py \\
        --corpus ~/projects/esperanto-lexicon-corpus/proficiency_eval/ \\
        --lang en \\
        --lexicon data/lexicon_db/lexicon_v2.db \\
        --domain-dbs data/domain_db/ucc_customs.db \\
                     data/domain_db/wco_intl.db \\
                     data/domain_db/cbam.db \\
                     data/domain_db/dualuse.db \\
        --output data/analysis/proficiency_baseline_v2.csv
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
    load_inflected_forms,
    load_mwe_phrases,
    load_synonym_map,
    load_tier_words,
    spacy_tokenise_sentences,
)


# ---------------------------------------------------------------------------
# Measure computation — pure functions (importable for tests)
# ---------------------------------------------------------------------------


def distinct_t4_count(results: list[TokenResult]) -> int:
    """Count distinct T4 concepts by matched phrase_normalized key.

    A concept appearing multiple times still counts as 1 distinct concept.
    """
    return len({
        r.matched_phrase or r.text.lower()
        for r in results
        if r.category == "TIER4"
    })


def sentence_cooccur_stats(
    per_sentence_results: list[list[TokenResult]],
) -> tuple[int, int, int]:
    """Compute co-occurrence stats across sentences.

    Returns:
        cooccur_pairs:           Σ C(k, 2) over sentences with k ≥ 2 distinct T4 concepts.
        sentences_with_any_t4:   sentences containing ≥ 1 distinct T4 concept.
        sentences_with_multi_t4: sentences containing ≥ 2 distinct T4 concepts.
    """
    cooccur_pairs = 0
    n_any = 0
    n_multi = 0
    for sent_results in per_sentence_results:
        t4_concepts = {
            r.matched_phrase or r.text.lower()
            for r in sent_results
            if r.category == "TIER4"
        }
        k = len(t4_concepts)
        if k >= 1:
            n_any += 1
        if k >= 2:
            n_multi += 1
            cooccur_pairs += k * (k - 1) // 2
    return cooccur_pairs, n_any, n_multi


# ---------------------------------------------------------------------------
# Per-file analysis
# ---------------------------------------------------------------------------


def _collect_unknown_texts(results: list[TokenResult]) -> list[str]:
    """Return lowercased text of every UNKNOWN-classified result (with repeats)."""
    return [r.text.lower() for r in results if r.category == "UNKNOWN"]


def _classify_sent(
    sent_tokens,
    mwe_phrases,
    tier1,
    tier2,
    synonym_map,
    inflected,
    fallback_tier1,
    fallback_tier2,
):
    """Run classify_tokens on one sentence's token list."""
    return classify_tokens(
        sent_tokens,
        mwe_phrases,
        tier1,
        tier2,
        fallback_tier1=fallback_tier1,
        fallback_tier2=fallback_tier2,
        synonym_map=synonym_map or None,
        inflected_forms=inflected or None,
    )


def analyse_file(
    path: Path,
    nlp,
    mwe_phrases: set[str],
    tier1: set[str],
    tier2: set[str],
    synonym_map: dict[str, str],
    inflected: dict[str, str],
    *,
    fallback_tier1: set[str] | None = None,
    fallback_tier2: set[str] | None = None,
    measures: str = "all",
) -> tuple[dict, list[str]]:
    """Classify one file's tokens and compute all enabled expertise measures.

    Returns ``(row, unknown_texts)`` where ``row`` is the CSV record.
    """
    text = path.read_text(encoding="utf-8").strip()
    all_tokens, sentences = spacy_tokenise_sentences(text, nlp)

    # Full-text classification (density + variety measures)
    results = classify_tokens(
        all_tokens,
        mwe_phrases,
        tier1,
        tier2,
        fallback_tier1=fallback_tier1,
        fallback_tier2=fallback_tier2,
        synonym_map=synonym_map or None,
        inflected_forms=inflected or None,
    )
    summary = compute_summary(results)
    counts = summary["counts"]
    es = summary["expertise_signal"]
    total_classified = (
        counts["TIER1"] + counts["TIER2"] + counts["TIER4"] + counts["UNKNOWN"]
    )
    unknown_texts = _collect_unknown_texts(results)
    n_sentences = len(sentences)

    # --- Variety measure ---
    distinct_t4 = 0
    t4_variety = 0.0
    if measures in ("variety", "all"):
        distinct_t4 = distinct_t4_count(results)
        t4_variety = round(distinct_t4 / max(total_classified, 1), 4)

    # --- Relational measures ---
    cooccur_pairs = 0
    cooccur_density = 0.0
    multi_concept_ratio = 0.0
    if measures in ("relational", "all"):
        per_sentence_results = [
            _classify_sent(
                sent, mwe_phrases, tier1, tier2, synonym_map, inflected,
                fallback_tier1, fallback_tier2,
            )
            for sent in sentences
        ]
        cooccur_pairs, n_any, n_multi = sentence_cooccur_stats(per_sentence_results)
        cooccur_density = round(cooccur_pairs / max(n_sentences, 1), 4)
        multi_concept_ratio = round(n_multi / max(n_any, 1), 4)

    row = {
        "filename": path.name,
        "stratum": path.parent.name,
        "total_tokens": total_classified,
        "t1_count": counts["TIER1"],
        "t2_count": counts["TIER2"],
        "t3_count": 0,
        "t4_count": counts["TIER4"],
        "unknown_count": counts["UNKNOWN"],
        "n_sentences": n_sentences,
        "t4_ratio": round(es["ratio"], 4),
        "common_ratio": round(es["common_pct"], 4),
        "distinct_t4": distinct_t4,
        "t4_variety": t4_variety,
        "cooccur_pairs": cooccur_pairs,
        "cooccur_density": cooccur_density,
        "multi_concept_ratio": multi_concept_ratio,
        "unknown_tokens": json.dumps(sorted(set(unknown_texts)), ensure_ascii=False),
    }
    return row, unknown_texts


# ---------------------------------------------------------------------------
# Domain DB aggregation
# ---------------------------------------------------------------------------


def load_domain_data(
    domain_dbs: list[Path], lang: str
) -> tuple[set[str], dict[str, str]]:
    """Union MWE phrases and merge synonym maps across multiple domain DBs."""
    mwe_phrases: set[str] = set()
    synonym_map: dict[str, str] = {}
    for db in domain_dbs:
        mwe_phrases |= load_mwe_phrases(db, lang)
        synonym_map.update(load_synonym_map(db, lang))
    return mwe_phrases, synonym_map


# ---------------------------------------------------------------------------
# Output: CSV, pooled UNKNOWN, summary table, comparison block
# ---------------------------------------------------------------------------


CSV_FIELDS = [
    "filename", "stratum", "total_tokens",
    "t1_count", "t2_count", "t3_count", "t4_count", "unknown_count",
    "n_sentences",
    "t4_ratio", "common_ratio",
    "distinct_t4", "t4_variety",
    "cooccur_pairs", "cooccur_density", "multi_concept_ratio",
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
    lines = [f"{count}\t{token}" for token, count in unknown_counter.most_common()]
    body = "\n".join(lines) + ("\n" if lines else "")
    path.write_text(body, encoding="utf-8")


def _unknown_pct(row: dict) -> float:
    total = row["total_tokens"] or 1
    return row["unknown_count"] / total


def print_summary_table(rows: list[dict], measures: str = "all") -> None:
    """Print per-file table then per-stratum averages."""
    if not rows:
        print("(no files analysed)")
        return

    rows_sorted = sorted(rows, key=lambda r: (r["stratum"], r["filename"]))
    stratum_w = max(len("Stratum"), max(len(r["stratum"]) for r in rows_sorted))
    file_w = max(len("File"), max(len(r["filename"]) for r in rows_sorted))

    # Build header based on enabled measures
    header = (
        f"{'Stratum':<{stratum_w}}  {'File':<{file_w}}  "
        f"{'T4_ratio':>8}  {'T1+T2%':>7}  {'UNKNOWN%':>8}"
    )
    if measures in ("variety", "all"):
        header += f"  {'dist_t4':>7}  {'variety':>7}"
    if measures in ("relational", "all"):
        header += f"  {'coc_dens':>8}  {'mc_ratio':>8}"

    sep = "─" * len(header)
    print(header)
    print(sep)

    for r in rows_sorted:
        line = (
            f"{r['stratum']:<{stratum_w}}  {r['filename']:<{file_w}}  "
            f"{r['t4_ratio']:>8.3f}  {r['common_ratio'] * 100:>6.1f}%  "
            f"{_unknown_pct(r) * 100:>7.1f}%"
        )
        if measures in ("variety", "all"):
            line += f"  {r['distinct_t4']:>7d}  {r['t4_variety']:>7.4f}"
        if measures in ("relational", "all"):
            line += f"  {r['cooccur_density']:>8.4f}  {r['multi_concept_ratio']:>8.4f}"
        print(line)

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
        line = (
            f"{stratum:<{stratum_w}}  {label:<{file_w}}  "
            f"{avg_ratio:>8.3f}  {avg_common * 100:>6.1f}%  "
            f"{avg_unknown * 100:>7.1f}%"
        )
        if measures in ("variety", "all"):
            avg_dt4 = mean(r["distinct_t4"] for r in group)
            avg_var = mean(r["t4_variety"] for r in group)
            line += f"  {avg_dt4:>7.1f}  {avg_var:>7.4f}"
        if measures in ("relational", "all"):
            avg_coc = mean(r["cooccur_density"] for r in group)
            avg_mcr = mean(r["multi_concept_ratio"] for r in group)
            line += f"  {avg_coc:>8.4f}  {avg_mcr:>8.4f}"
        print(line)


def _ratio_str(control_val: float, expert_val: float) -> str:
    if control_val == 0:
        return "∞"
    return f"{expert_val / control_val:.1f}x"


def print_comparison_block(rows: list[dict], measures: str = "all") -> None:
    """Print the measure-comparison block and failure-case tables."""
    by_stratum: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_stratum[r["stratum"]].append(r)

    strata = sorted(by_stratum)
    control = by_stratum.get("control", [])
    expert = by_stratum.get("expert", [])
    novice = by_stratum.get("novice", [])

    def avg(group: list[dict], key: str) -> float:
        return mean(r[key] for r in group) if group else 0.0

    print()
    print("=" * 78)
    print("MEASURE COMPARISON")
    print("=" * 78)

    measure_specs = [
        ("T4_ratio",            "t4_ratio",             "density"),
        ("t4_variety",          "t4_variety",           "variety"),
        ("cooccur_density",     "cooccur_density",      "relational"),
        ("multi_concept_ratio", "multi_concept_ratio",  "relational"),
    ]
    enabled = {
        "density": measures in ("density", "all"),
        "variety": measures in ("variety", "all"),
        "relational": measures in ("relational", "all"),
    }

    header = f"{'Measure':<26}  {'control':>8}  {'novice':>8}  {'expert':>8}  {'expert/ctrl':>11}"
    print(header)
    print("─" * len(header))
    for label, key, mtype in measure_specs:
        if not enabled.get(mtype, False):
            continue
        ctrl = avg(control, key)
        nov  = avg(novice, key)
        exp  = avg(expert, key)
        print(
            f"{label:<26}  {ctrl:>8.4f}  {nov:>8.4f}  {exp:>8.4f}  "
            f"{_ratio_str(ctrl, exp):>11}"
        )

    # --- Failure-case table ---
    failure_files = {"expert_04.txt", "expert_06.txt", "expert_07.txt"}
    failure_rows = [r for r in rows if r["filename"] in failure_files]
    if failure_rows:
        print()
        print("Failure-case check (low T4_ratio expert texts):")
        col = f"{'File':<20}  {'T4_ratio':>8}"
        if enabled["variety"]:
            col += f"  {'dist_t4':>7}  {'t4_variety':>10}"
        if enabled["relational"]:
            col += f"  {'coc_density':>11}  {'mc_ratio':>8}"
        print(col)
        print("─" * len(col))
        for r in sorted(failure_rows, key=lambda x: x["filename"]):
            line = f"{r['filename']:<20}  {r['t4_ratio']:>8.3f}"
            if enabled["variety"]:
                line += f"  {r['distinct_t4']:>7d}  {r['t4_variety']:>10.4f}"
            if enabled["relational"]:
                line += f"  {r['cooccur_density']:>11.4f}  {r['multi_concept_ratio']:>8.4f}"
            print(line)

    # --- Control-ceiling check ---
    if control:
        top_ctrl = max(control, key=lambda r: r["t4_ratio"])
        print()
        print("Control-ceiling check (highest-T4_ratio control text):")
        col2 = f"{'File':<20}  {'T4_ratio':>8}"
        if enabled["variety"]:
            col2 += f"  {'dist_t4':>7}  {'t4_variety':>10}"
        if enabled["relational"]:
            col2 += f"  {'coc_density':>11}  {'mc_ratio':>8}"
        print(col2)
        print("─" * len(col2))
        line = f"{top_ctrl['filename']:<20}  {top_ctrl['t4_ratio']:>8.3f}"
        if enabled["variety"]:
            line += f"  {top_ctrl['distinct_t4']:>7d}  {top_ctrl['t4_variety']:>10.4f}"
        if enabled["relational"]:
            line += f"  {top_ctrl['cooccur_density']:>11.4f}  {top_ctrl['multi_concept_ratio']:>8.4f}"
        print(line)

    print("=" * 78)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run coverage_report classification on every .txt file under a "
            "corpus tree, emit a CSV summary and pooled UNKNOWN-token file."
        )
    )
    parser.add_argument("--corpus", required=True, type=Path,
                        help="Corpus root; walked recursively for .txt files in subdirs")
    parser.add_argument("--lang", required=True, choices=["lt", "en", "eo"])
    parser.add_argument("--lexicon", required=True, type=Path,
                        help="Path to lexicon_v2.db")
    parser.add_argument("--domain-dbs", dest="domain_dbs", nargs="+", type=Path, default=[],
                        help="One or more domain .db files; mwe_lang phrases are unioned")
    parser.add_argument("--output", required=True, type=Path, help="CSV output path")
    parser.add_argument("--fallback-lang", dest="fallback_lang", default=None,
                        help="Fallback language for Tier 1/2 lookup")
    parser.add_argument(
        "--measures",
        choices=["density", "variety", "relational", "all"],
        default="all",
        help=(
            "Which expertise measures to compute (default: all). "
            "'density'=T4_ratio only; 'variety'=adds distinct_t4/t4_variety; "
            "'relational'=adds co-occurrence stats; 'all'=everything."
        ),
    )
    args = parser.parse_args(argv)

    corpus = args.corpus.expanduser()
    if not corpus.exists() or not corpus.is_dir():
        print(f"--corpus is not an existing directory: {corpus}", file=sys.stderr)
        sys.exit(1)

    # Only process .txt files inside stratum subdirectories (skip corpus root files).
    txt_files = sorted(
        p for p in corpus.rglob("*.txt") if p.parent != corpus
    )
    if not txt_files:
        print(f"No .txt files found in subdirectories of {corpus}", file=sys.stderr)
        sys.exit(1)

    tier1, tier2 = load_tier_words(args.lexicon, args.lang)
    fb_t1: set[str] = set()
    fb_t2: set[str] = set()
    if args.fallback_lang:
        fb_t1, fb_t2 = load_tier_words(args.lexicon, args.fallback_lang)

    inflected = load_inflected_forms(args.lexicon, args.lang)
    mwe_phrases, synonym_map = load_domain_data(args.domain_dbs, args.lang)
    nlp = _load_nlp(args.lang)

    rows: list[dict] = []
    unknown_counter: Counter[str] = Counter()
    excluded: list[str] = []

    for path in corpus.rglob("*.txt"):
        if path.parent == corpus:
            excluded.append(path.name)
            continue
        try:
            row, unknowns = analyse_file(
                path, nlp, mwe_phrases, tier1, tier2, synonym_map, inflected,
                fallback_tier1=fb_t1 if args.fallback_lang else None,
                fallback_tier2=fb_t2 if args.fallback_lang else None,
                measures=args.measures,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"WARN: failed to analyse {path}: {exc}", file=sys.stderr)
            continue
        rows.append(row)
        unknown_counter.update(unknowns)

    if excluded:
        print(f"Excluded from corpus root (not stratum data): {', '.join(excluded)}")

    rows.sort(key=lambda r: (r["stratum"], r["filename"]))

    output_path = args.output.expanduser()
    write_csv(rows, output_path)
    pool_path = output_path.parent / "unknown_tokens_pooled.txt"
    write_unknown_pool(unknown_counter, pool_path)

    print_summary_table(rows, args.measures)
    print()
    print(f"CSV written : {output_path}")
    print(f"Unknown pool: {pool_path}")

    if args.measures in ("variety", "relational", "all"):
        print_comparison_block(rows, args.measures)


if __name__ == "__main__":
    main()
