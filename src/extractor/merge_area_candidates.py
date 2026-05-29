#!/usr/bin/env python3
"""Merge per-area statistical-MWE candidate JSONLs into one master candidate file.

Each input file is the output of a statistical_mwe_detector run over one mining
corpus, tagged with the customs area that corpus represents. This tool joins
them on phrase_normalized, attaching per-area attestation evidence to every
unique phrase and deriving an area signature + specificity for at-a-glance
review.

The seven canonical areas (peer-level body-of-knowledge topics) are passed via
--area <area>:<path>. Cross-cutting/overlay corpora (compliance, sustainability,
tech, other) are passed via --cross-cutting cross_cutting:<path>; they all share
the single 'cross_cutting' area tag and are excluded from signature/specificity,
but their per-file evidence is preserved in attestation rows via source_file.

Usage:
    python3 src/extractor/merge_area_candidates.py \\
        --area law:data/domain_db/candidates_law.jsonl \\
        --area origin:data/domain_db/candidates_origin.jsonl \\
        --cross-cutting cross_cutting:data/domain_db/candidates_compliance.jsonl \\
        --output data/domain_db/merged_candidates.jsonl

    # Single-area adapter (e.g. re-homing an older single-corpus run):
    python3 src/extractor/merge_area_candidates.py \\
        --area origin:data/domain_db/candidates_roo.jsonl \\
        --output data/domain_db/candidates_roo_merged.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

# area_signature.py lives in src/lexicon/; resolve relative to this file
sys.path.insert(0, str(Path(__file__).parent.parent))
from lexicon.area_signature import (
    CANONICAL_AREAS,
    CROSS_CUTTING,
    compute_signature,
    compute_specificity,
)

_MAX_CONTEXT = 200


def _parse_area_pair(value: str) -> tuple[str, Path]:
    """Parse an '<area>:<filepath>' CLI argument into (area, path).

    Splits on the first ':' only, so Windows-style or otherwise colon-bearing
    paths survive intact.
    """
    if ":" not in value:
        raise argparse.ArgumentTypeError(
            f"expected '<area>:<filepath>', got {value!r}"
        )
    area, _, path = value.partition(":")
    area = area.strip()
    path = path.strip()
    if not area or not path:
        raise argparse.ArgumentTypeError(
            f"expected non-empty '<area>:<filepath>', got {value!r}"
        )
    return area, Path(path)


def _load_jsonl(path: Path) -> list[dict]:
    records: list[dict] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _best_context(existing: str | None, candidate: str | None) -> str | None:
    """Return the more informative (longer, capped at _MAX_CONTEXT) context."""
    cand = (candidate or "").strip()
    if cand:
        cand = cand[:_MAX_CONTEXT]
    cur = existing or ""
    return cand if len(cand) > len(cur) else (cur or None)


def merge(
    area_inputs: list[tuple[str, Path]],
    cross_inputs: list[tuple[str, Path]],
) -> list[dict]:
    """Merge per-area candidate files into one list of merged records.

    Keyed on phrase_normalized. Each phrase gets one attestation row per
    (area, source_file) it was mined from; doc_count/frequency are summed when
    a phrase recurs for the same (area, source_file) pair.
    """
    # phrase -> accumulator
    acc: dict[str, dict] = {}
    # phrase -> {(area, source_file): {doc_count, frequency}}
    att: dict[str, dict[tuple[str, str], dict]] = defaultdict(dict)

    for area, path in [*area_inputs, *cross_inputs]:
        default_source = path.name
        for rec in _load_jsonl(path):
            phrase = rec.get("phrase_normalized") or (rec.get("phrase") or "").lower()
            if not phrase:
                continue
            source_file = rec.get("source_file") or default_source

            slot = acc.setdefault(
                phrase,
                {
                    "phrase_normalized": phrase,
                    "phrase_inflected": None,
                    "lang": None,
                    "pos_patterns": Counter(),
                    "sample_context": None,
                },
            )
            if slot["phrase_inflected"] is None and rec.get("phrase_inflected"):
                slot["phrase_inflected"] = rec["phrase_inflected"]
            if slot["lang"] is None and rec.get("lang"):
                slot["lang"] = rec["lang"]
            if rec.get("pos_pattern"):
                slot["pos_patterns"][rec["pos_pattern"]] += 1
            slot["sample_context"] = _best_context(
                slot["sample_context"], rec.get("sample_context")
            )

            key = (area, source_file)
            row = att[phrase].setdefault(
                key, {"doc_count": 0, "frequency": 0}
            )
            row["doc_count"] += int(rec.get("doc_count") or 0)
            row["frequency"] += int(rec.get("frequency") or 0)

    merged: list[dict] = []
    for phrase, slot in acc.items():
        attestation = [
            {
                "area": area,
                "doc_count": vals["doc_count"],
                "frequency": vals["frequency"],
                "source_file": source_file,
            }
            for (area, source_file), vals in sorted(
                att[phrase].items(), key=lambda kv: (-kv[1]["doc_count"], kv[0][0])
            )
        ]

        pos_counter: Counter = slot["pos_patterns"]
        pos_pattern = pos_counter.most_common(1)[0][0] if pos_counter else None
        pos_inconsistent = len(pos_counter) > 1

        total_doc_count = sum(r["doc_count"] for r in attestation)
        total_frequency = sum(r["frequency"] for r in attestation)

        record = {
            "phrase_normalized": phrase,
            "phrase_inflected": slot["phrase_inflected"],
            "pos_pattern": pos_pattern,
            "lang": slot["lang"],
            "total_doc_count": total_doc_count,
            "total_frequency": total_frequency,
            "attestation": attestation,
            "area_signature": compute_signature(attestation),
            "area_specificity": round(compute_specificity(attestation), 4),
            "sample_context": slot["sample_context"],
        }
        if pos_inconsistent:
            record["pos_pattern_inconsistent"] = True
        merged.append(record)

    # Area-discriminators (high specificity) first, general/cross-cutting last.
    merged.sort(
        key=lambda r: (r["area_specificity"], r["total_doc_count"]), reverse=True
    )
    return merged


def _count_canonical_areas(record: dict) -> int:
    """Number of distinct canonical areas a merged record is attested in."""
    return len(
        {
            r["area"]
            for r in record["attestation"]
            if r["area"] in CANONICAL_AREAS
        }
    )


def _print_summary(
    merged: list[dict],
    n_canonical_files: int,
    n_cross_files: int,
) -> None:
    one = two_three = four_plus = cross_only = 0
    for rec in merged:
        n = _count_canonical_areas(rec)
        if n == 0:
            cross_only += 1
        elif n == 1:
            one += 1
        elif n <= 3:
            two_three += 1
        else:
            four_plus += 1

    total_files = n_canonical_files + n_cross_files
    print()
    print(
        f"    Inputs                  : {total_files} files "
        f"({n_canonical_files} canonical + {n_cross_files} cross_cutting)"
    )
    print(f"    Unique phrases          : {len(merged):,}")
    print(f"    Phrases in 1 area only  : {one:,}   (likely area-specific)")
    print(f"    Phrases in 2-3 areas    : {two_three:,}   (likely sub-domain or general)")
    print(f"    Phrases in 4-7 areas    : {four_plus:,}   (general customs vocabulary)")
    print(f"    Phrases cross-cutting   : {cross_only:,}   (compliance/sustainability/tech only)")


def run(
    area_inputs: list[tuple[str, Path]],
    cross_inputs: list[tuple[str, Path]],
    output: Path,
) -> list[dict]:
    """Merge inputs, write output JSONL, print the summary. Returns merged records."""
    merged = merge(area_inputs, cross_inputs)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as fh:
        for rec in merged:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    _print_summary(merged, len(area_inputs), len(cross_inputs))
    print(f"    Output                  : {output}")
    return merged


def main(argv: list[str] | None = None) -> None:
    """Entry point for merge_area_candidates."""
    parser = argparse.ArgumentParser(
        description="Merge per-area candidate JSONLs into one master candidate file."
    )
    parser.add_argument(
        "--area",
        action="append",
        default=[],
        metavar="AREA:PATH",
        type=_parse_area_pair,
        help="Canonical-area candidate file as '<area_name>:<filepath>'. Repeatable.",
    )
    parser.add_argument(
        "--cross-cutting",
        action="append",
        default=[],
        dest="cross_cutting",
        metavar="TAG:PATH",
        type=_parse_area_pair,
        help="Cross-cutting candidate file as 'cross_cutting:<filepath>'. Repeatable.",
    )
    parser.add_argument(
        "--output", required=True, type=Path, help="Path for merged JSONL output."
    )
    args = parser.parse_args(argv)

    if not args.area and not args.cross_cutting:
        parser.error("at least one --area or --cross-cutting input is required")

    # Validate area names and file existence up front.
    unknown = sorted(
        {area for area, _ in args.area if area not in CANONICAL_AREAS}
    )
    if unknown:
        parser.error(
            f"unknown canonical area(s): {', '.join(unknown)}. "
            f"Valid areas: {', '.join(CANONICAL_AREAS)}"
        )
    bad_cross = sorted({tag for tag, _ in args.cross_cutting if tag != CROSS_CUTTING})
    if bad_cross:
        parser.error(
            f"--cross-cutting tag must be {CROSS_CUTTING!r}; got: {', '.join(bad_cross)}"
        )
    for _, path in [*args.area, *args.cross_cutting]:
        if not path.exists():
            parser.error(f"input file not found: {path}")

    run(args.area, args.cross_cutting, args.output)


if __name__ == "__main__":
    main()
