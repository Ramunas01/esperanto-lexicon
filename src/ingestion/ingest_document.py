#!/usr/bin/env python3
"""Pipeline wrapper: docx → corpus → definitions → (optional) domain DB.

Runs the extraction pipeline for a single language+document pair.  Stops after
each stage so you can review outputs before committing to the domain DB.

Two-pass workflow
-----------------
Pass 1 — extract and review (default):

    python3 src/ingestion/ingest_document.py \\
        --docx data/corpus/new_domain/lt.docx \\
        --lang lt \\
        --domain personal_income_tax \\
        --jurisdiction LT \\
        --lexicon data/lexicon_db/lexicon_v2.db \\
        --work-dir data/ingestion/new_domain_lt

    Produces:
      <work-dir>/corpus.txt          — clean text
      <work-dir>/amendments.txt      — stripped amendment records
      <work-dir>/definitions.jsonl   — extracted definition candidates
      <work-dir>/mwe_candidates.jsonl — statistical MWE candidates
      <work-dir>/ne_candidates.jsonl  — named-entity candidates

    Then review with:
      python3 src/extractor/review_cli.py --input <work-dir>/definitions.jsonl --lang lt
      python3 src/extractor/review_cli.py --input <work-dir>/mwe_candidates.jsonl --lang lt

Pass 2 — commit reviewed records to domain DB (--post-review):

    python3 src/ingestion/ingest_document.py \\
        --work-dir data/ingestion/new_domain_lt \\
        --domain personal_income_tax \\
        --jurisdiction LT \\
        --db data/domain_db/personal_income_tax.db \\
        --post-review

Options
-------
--skip-docx       Skip the docx→corpus step (corpus.txt already exists).
--skip-extract    Skip extract_definitions (definitions.jsonl already exists).
--skip-stats      Skip statistical MWE detection.
--article N       Article number to extract (default: 2).
--min-freq N      Minimum frequency for statistical candidates (default: 3).
--min-pmi F       Minimum PMI for statistical candidates (default: 2.0).
--top-n N         Maximum statistical candidates per run (default: 200).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(cmd: list[str], label: str) -> None:
    """Run a subprocess command, printing a header and exiting on failure."""
    print(f"\n{'─' * 60}")
    print(f"STAGE: {label}")
    print(f"CMD  : {' '.join(cmd)}")
    print("─" * 60)
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print(f"\nError: stage '{label}' failed (exit {result.returncode}).", file=sys.stderr)
        sys.exit(result.returncode)


# ---------------------------------------------------------------------------
# Stage runners
# ---------------------------------------------------------------------------


def stage_docx(args: argparse.Namespace, work_dir: Path) -> None:
    corpus_txt = work_dir / "corpus.txt"
    amendments_txt = work_dir / "amendments.txt"
    _run(
        [
            sys.executable,
            "src/ingestion/docx_to_corpus.py",
            "--input", str(args.docx),
            "--output", str(corpus_txt),
            "--amendments", str(amendments_txt),
        ],
        "docx → corpus",
    )


def stage_extract(args: argparse.Namespace, work_dir: Path) -> None:
    corpus_txt = work_dir / "corpus.txt"
    definitions_jsonl = work_dir / "definitions.jsonl"
    _run(
        [
            sys.executable,
            "src/extractor/extract_definitions.py",
            "--input", str(corpus_txt),
            "--lang", args.lang,
            "--article", args.article,
            "--output", str(definitions_jsonl),
        ],
        "extract definitions",
    )


def stage_stats(args: argparse.Namespace, work_dir: Path) -> None:
    corpus_txt = work_dir / "corpus.txt"
    mwe_jsonl = work_dir / "mwe_candidates.jsonl"
    ne_jsonl = work_dir / "ne_candidates.jsonl"
    _run(
        [
            sys.executable,
            "src/extractor/statistical_mwe_detector.py",
            "--input", str(corpus_txt),
            "--lang", args.lang,
            "--lexicon", str(args.lexicon),
            "--output", str(mwe_jsonl),
            "--output-ne", str(ne_jsonl),
            "--min-freq", str(args.min_freq),
            "--min-pmi", str(args.min_pmi),
            "--top-n", str(args.top_n),
        ],
        "statistical MWE detection",
    )


def stage_db_write(args: argparse.Namespace, work_dir: Path) -> None:
    definitions_jsonl = work_dir / "definitions.jsonl"
    if not definitions_jsonl.exists():
        print(f"Error: {definitions_jsonl} not found — run Pass 1 first.", file=sys.stderr)
        sys.exit(1)
    _run(
        [
            sys.executable,
            "src/extractor/domain_db_writer.py",
            "--input", str(definitions_jsonl),
            "--db", str(args.db),
            "--domain", args.domain,
            "--jurisdiction", args.jurisdiction,
        ],
        "write definitions → domain DB",
    )

    mwe_jsonl = work_dir / "mwe_candidates.jsonl"
    if mwe_jsonl.exists():
        _run(
            [
                sys.executable,
                "src/extractor/domain_db_writer.py",
                "--input", str(mwe_jsonl),
                "--db", str(args.db),
                "--domain", args.domain,
                "--jurisdiction", args.jurisdiction,
            ],
            "write MWE candidates → domain DB",
        )
    else:
        print(f"  (no {mwe_jsonl.name} found — skipping MWE write)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Run the ingestion pipeline for one language+document.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Work directory (always required)
    parser.add_argument(
        "--work-dir", dest="work_dir", required=True, type=Path,
        help="Directory for intermediate files (created if absent)",
    )

    # Pass 1 inputs
    parser.add_argument("--docx", type=Path, default=None, help="Input .docx file (Pass 1)")
    parser.add_argument(
        "--lang", choices=["lt", "en", "eo"], default=None,
        help="Language code (required for Pass 1 and --post-review)",
    )
    parser.add_argument(
        "--lexicon", type=Path, default=None,
        help="Path to lexicon_v2.db (required for statistical MWE detection)",
    )
    parser.add_argument("--article", default="2", help="Article number to extract (default: 2)")
    parser.add_argument("--min-freq", dest="min_freq", type=int, default=3)
    parser.add_argument("--min-pmi", dest="min_pmi", type=float, default=2.0)
    parser.add_argument("--top-n", dest="top_n", type=int, default=200)

    # Pass 2 inputs
    parser.add_argument(
        "--post-review", dest="post_review", action="store_true",
        help="Commit reviewed records to domain DB (Pass 2)",
    )
    parser.add_argument("--db", type=Path, default=None, help="Domain DB path (required for Pass 2)")
    parser.add_argument("--domain", default=None, help="Domain label, e.g. personal_income_tax")
    parser.add_argument("--jurisdiction", default=None, help="Jurisdiction code, e.g. LT")

    # Skip flags
    parser.add_argument("--skip-docx", dest="skip_docx", action="store_true")
    parser.add_argument("--skip-extract", dest="skip_extract", action="store_true")
    parser.add_argument("--skip-stats", dest="skip_stats", action="store_true")

    args = parser.parse_args(argv)

    work_dir: Path = args.work_dir
    work_dir.mkdir(parents=True, exist_ok=True)

    if args.post_review:
        # Pass 2: commit reviewed files to domain DB
        for flag, name in [("--db", args.db), ("--domain", args.domain), ("--jurisdiction", args.jurisdiction)]:
            if name is None:
                parser.error(f"{flag} is required for --post-review")
        stage_db_write(args, work_dir)
        print(f"\nPass 2 complete.  Domain DB: {args.db}")
        return

    # Pass 1: extract pipeline
    if args.lang is None:
        parser.error("--lang is required for Pass 1")
    if not args.skip_docx:
        if args.docx is None:
            parser.error("--docx is required unless --skip-docx is set")
        stage_docx(args, work_dir)
    if not args.skip_extract:
        stage_extract(args, work_dir)
    if not args.skip_stats:
        if args.lexicon is None:
            print("  (--lexicon not provided — skipping statistical MWE detection)")
        else:
            stage_stats(args, work_dir)

    print(f"\n{'═' * 60}")
    print("Pass 1 complete.  Next steps:")
    print(f"  1. Review definitions:")
    print(f"     python3 src/extractor/review_cli.py \\")
    print(f"         --input {work_dir}/definitions.jsonl --lang {args.lang}")
    if not args.skip_stats and args.lexicon:
        print(f"  2. Review MWE candidates:")
        print(f"     python3 src/extractor/review_cli.py \\")
        print(f"         --input {work_dir}/mwe_candidates.jsonl --lang {args.lang}")
    print(f"  3. Commit reviewed records:")
    print(f"     python3 src/ingestion/ingest_document.py \\")
    print(f"         --work-dir {work_dir} \\")
    print(f"         --domain <domain> --jurisdiction <JUR> --db <db> --post-review")
    print(f"{'═' * 60}")


if __name__ == "__main__":
    main()
