#!/usr/bin/env python3
"""Bulk-approve .jsonl records by language.

Convenience tool for promoting records that were reviewed in a prior session
but left with approved=false (e.g. after a bilingual review_cli pass).

Usage:
    python3 src/extractor/bulk_approve.py \\
        --input data/domain_db/gpmi_definitions.jsonl \\
        --lang lt eo
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def run(input_path: Path, langs: list[str]) -> None:
    """Load records, approve all matching langs, write back in place."""
    records: list[dict] = []
    with input_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    counts: dict[str, int] = {lang: 0 for lang in langs}
    for rec in records:
        lang = rec.get("lang", "")
        if lang in langs and rec.get("approved") is not True:
            rec["approved"] = True
            counts[lang] += 1

    with input_path.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    for lang in langs:
        print(f"Approved {lang}: {counts[lang]} records")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Bulk-approve .jsonl records by language code."
    )
    parser.add_argument("--input", required=True, type=Path, help="Path to .jsonl file")
    parser.add_argument(
        "--lang", required=True, nargs="+", metavar="LANG",
        help="Language codes to approve (e.g. lt eo)",
    )
    args = parser.parse_args(argv)

    if not args.input.exists():
        import sys
        print(f"Error: input file not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    run(args.input, args.lang)


if __name__ == "__main__":
    main()
