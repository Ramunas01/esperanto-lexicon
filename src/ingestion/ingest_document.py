#!/usr/bin/env python3
"""Pipeline wrapper: ingest a legal document through the full extraction pipeline.

Runs in two phases so you can review candidates between extraction and DB commit.

Phase 1 — extract (default):
    For --source docx:
        docx_to_corpus.py  → <work-dir>/corpus.txt + amendments.txt
        extract_definitions.py → <work-dir>/definitions.jsonl
    For --source eurlex:
        extract_eurlex_definitions.py → <work-dir>/definitions.jsonl
    Print: "Phase 1 complete. N candidates written to PATH"
    Print: "Next: review candidates, then re-run with --phase 2"

Phase 2 — commit (--phase 2):
    Checks that at least one record is approved.
    domain_db_writer.py  (definitions + statistical candidates)
    statistical_mwe_detector.py → <work-dir>/mwe_candidates.jsonl

Usage (national law, docx source):
    python3 src/ingestion/ingest_document.py \\
        --source docx \\
        --input path/to/law_lt.docx \\
        --lang lt \\
        --domain corporate_tax \\
        --jurisdiction LT \\
        --primary-lang lt \\
        --corpus-dir ~/projects/esperanto-lexicon-corpus/ \\
        --db data/domain_db/corporate_tax_lt.db

Usage (EUR-Lex, html source):
    python3 src/ingestion/ingest_document.py \\
        --source eurlex \\
        --input path/to/ucc_en.html \\
        --celex 02013R0952-20221212 \\
        --lang en \\
        --domain customs_ucc \\
        --jurisdiction EU \\
        --primary-lang en \\
        --corpus-dir ~/projects/esperanto-lexicon-corpus/ \\
        --db data/domain_db/ucc_customs.db

Usage (Phase 2 — commit):
    python3 src/ingestion/ingest_document.py \\
        --phase 2 \\
        --lang lt \\
        --domain corporate_tax \\
        --jurisdiction LT \\
        --corpus-dir ~/projects/esperanto-lexicon-corpus/ \\
        --db data/domain_db/corporate_tax_lt.db \\
        --lexicon data/lexicon_db/lexicon_v2.db
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(cmd: list[str], label: str) -> None:
    print(f"\n{'─' * 60}")
    print(f"STAGE: {label}")
    print(f"CMD  : {' '.join(str(c) for c in cmd)}")
    print("─" * 60)
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print(f"\nError: stage '{label}' failed (exit {result.returncode}).", file=sys.stderr)
        sys.exit(result.returncode)


def _work_dir(args: argparse.Namespace) -> Path:
    corpus_dir = Path(args.corpus_dir).expanduser()
    return corpus_dir / args.domain


def _count_candidates(jsonl_path: Path) -> tuple[int, int]:
    """Return (total, approved) record counts in a jsonl file."""
    total = approved = 0
    if not jsonl_path.exists():
        return 0, 0
    with jsonl_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rec = json.loads(line)
                total += 1
                if rec.get("approved") is True:
                    approved += 1
    return total, approved


# ---------------------------------------------------------------------------
# Phase 1 stages
# ---------------------------------------------------------------------------


def stage_docx(args: argparse.Namespace, work_dir: Path) -> None:
    corpus_txt = work_dir / "corpus.txt"
    amendments_txt = work_dir / "amendments.txt"
    _run(
        [
            sys.executable, "src/ingestion/docx_to_corpus.py",
            "--input", str(args.input),
            "--output", str(corpus_txt),
            "--amendments", str(amendments_txt),
        ],
        "docx → corpus",
    )


def stage_eurlex(args: argparse.Namespace, work_dir: Path) -> None:
    definitions_jsonl = work_dir / "definitions.jsonl"
    celex = getattr(args, "celex", None) or ""
    _run(
        [
            sys.executable, "src/ingestion/extract_eurlex_definitions.py",
            "--input", str(args.input),
            "--lang", args.lang,
            "--output", str(definitions_jsonl),
        ] + (["--celex", celex] if celex else []),
        "EUR-Lex HTML → definitions",
    )


def stage_extract_definitions(args: argparse.Namespace, work_dir: Path) -> None:
    corpus_txt = work_dir / "corpus.txt"
    definitions_jsonl = work_dir / "definitions.jsonl"
    _run(
        [
            sys.executable, "src/extractor/extract_definitions.py",
            "--input", str(corpus_txt),
            "--lang", args.lang,
            "--article", getattr(args, "article", "2"),
            "--output", str(definitions_jsonl),
        ],
        "extract definitions",
    )


# ---------------------------------------------------------------------------
# Phase 2 stages
# ---------------------------------------------------------------------------


def stage_db_write(args: argparse.Namespace, work_dir: Path) -> None:
    definitions_jsonl = work_dir / "definitions.jsonl"
    if not definitions_jsonl.exists():
        print(f"Error: {definitions_jsonl} not found — run Phase 1 first.", file=sys.stderr)
        sys.exit(1)

    _, approved = _count_candidates(definitions_jsonl)
    if approved == 0:
        print(
            f"Error: no approved records in {definitions_jsonl.name}.\n"
            "Review with: python3 src/extractor/review_cli.py "
            f"--input {definitions_jsonl} --lang {args.lang}",
            file=sys.stderr,
        )
        sys.exit(1)

    _run(
        [
            sys.executable, "src/extractor/domain_db_writer.py",
            "--input", str(definitions_jsonl),
            "--db", str(args.db),
            "--domain", args.domain,
            "--jurisdiction", args.jurisdiction,
        ],
        "write definitions → domain DB",
    )

    mwe_jsonl = work_dir / "mwe_candidates.jsonl"
    if mwe_jsonl.exists():
        _, mwe_approved = _count_candidates(mwe_jsonl)
        if mwe_approved > 0:
            _run(
                [
                    sys.executable, "src/extractor/domain_db_writer.py",
                    "--input", str(mwe_jsonl),
                    "--db", str(args.db),
                    "--domain", args.domain,
                    "--jurisdiction", args.jurisdiction,
                ],
                "write statistical MWE candidates → domain DB",
            )


def stage_stats(args: argparse.Namespace, work_dir: Path) -> None:
    corpus_txt = work_dir / "corpus.txt"
    if not corpus_txt.exists():
        print(f"  (corpus.txt not found at {corpus_txt} — skipping statistical MWE detection)")
        return
    lexicon = getattr(args, "lexicon", None)
    if not lexicon:
        print("  (--lexicon not provided — skipping statistical MWE detection)")
        return
    mwe_jsonl = work_dir / "mwe_candidates.jsonl"
    ne_jsonl = work_dir / "ne_candidates.jsonl"
    _run(
        [
            sys.executable, "src/extractor/statistical_mwe_detector.py",
            "--input", str(corpus_txt),
            "--lang", args.lang,
            "--lexicon", str(lexicon),
            "--output", str(mwe_jsonl),
            "--output-ne", str(ne_jsonl),
        ],
        "statistical MWE detection",
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Ingest a legal document through the extraction pipeline.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--phase", type=int, default=1, choices=[1, 2],
                        help="1=extract (default), 2=commit reviewed records to DB")
    parser.add_argument("--source", choices=["docx", "eurlex"], default="docx",
                        help="Document source format (default: docx)")
    parser.add_argument("--input", type=Path, default=None,
                        help="Input file path (required for Phase 1)")
    parser.add_argument("--lang", required=True, choices=["lt", "en", "eo"],
                        help="Language code")
    parser.add_argument("--domain", required=True,
                        help="Domain label, e.g. corporate_tax")
    parser.add_argument("--jurisdiction", required=True,
                        help="Jurisdiction code, e.g. LT")
    parser.add_argument("--primary-lang", dest="primary_lang", default=None,
                        help="Primary language for the document (informational)")
    parser.add_argument("--corpus-dir", dest="corpus_dir", required=True,
                        help="Root directory for corpus files (work files placed here)")
    parser.add_argument("--db", type=Path, default=None,
                        help="Domain DB path (required for Phase 2)")
    parser.add_argument("--lexicon", type=Path, default=None,
                        help="Path to lexicon_v2.db (for statistical MWE detection)")
    parser.add_argument("--celex", default=None,
                        help="EUR-Lex CELEX identifier (for --source eurlex)")
    parser.add_argument("--article", default="2",
                        help="Article number to extract definitions from (default: 2)")
    args = parser.parse_args(argv)

    work_dir = _work_dir(args)
    work_dir.mkdir(parents=True, exist_ok=True)

    if args.phase == 1:
        if args.input is None:
            parser.error("--input is required for Phase 1")

        if args.source == "docx":
            stage_docx(args, work_dir)
            stage_extract_definitions(args, work_dir)
        elif args.source == "eurlex":
            stage_eurlex(args, work_dir)

        definitions_jsonl = work_dir / "definitions.jsonl"
        total, _ = _count_candidates(definitions_jsonl)

        print(f"\n{'═' * 60}")
        print(f"Phase 1 complete. {total} candidate(s) written to:")
        print(f"  {definitions_jsonl}")
        print()
        print("Next steps:")
        print(f"  1. Review candidates:")
        print(f"     python3 src/extractor/review_cli.py \\")
        print(f"         --input {definitions_jsonl} --lang {args.lang}")
        print(f"  2. Commit reviewed records (Phase 2):")
        print(f"     python3 src/ingestion/ingest_document.py --phase 2 \\")
        print(f"         --lang {args.lang} --domain {args.domain} \\")
        print(f"         --jurisdiction {args.jurisdiction} \\")
        print(f"         --corpus-dir {args.corpus_dir} \\")
        print(f"         --db <path-to-domain.db>")
        print(f"{'═' * 60}")

    elif args.phase == 2:
        if args.db is None:
            parser.error("--db is required for Phase 2")
        stage_db_write(args, work_dir)
        stage_stats(args, work_dir)
        print(f"\n{'═' * 60}")
        print(f"Phase 2 complete. Domain DB: {args.db}")
        print(f"{'═' * 60}")


if __name__ == "__main__":
    main()
