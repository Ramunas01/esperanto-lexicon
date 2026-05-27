#!/usr/bin/env python3
"""Multi-language EUR-Lex HTML ingestion pipeline.

Convenience wrapper for extracting definitions from EUR-Lex consolidated HTML
files in multiple language versions.  Runs in two phases so you can review
bilingual candidates between extraction and DB commit.

Phase 1 (default) — extract:
    Run extract_eurlex_definitions.py on each language HTML → per-lang JSONL
    Extract clean corpus text from each HTML → per-lang corpus .txt
    Combine per-lang JSONL files → {domain}_definitions_combined.jsonl
    Print: "Phase 1 complete. N EN + N LT candidates written."
    Print: "Next: review with review_cli.py, then run with --phase 2"

Phase 2 (--phase 2) — commit:
    Check at least 1 approved record exists in combined JSONL
    Run domain_db_writer.py → {db}
    Run statistical_mwe_detector.py for each language (if --lexicon provided
    and corpus text file exists from Phase 1)
    Print final summary

Usage:
  python3 src/ingestion/ingest_eurlex.py \\
      --input-en ~/projects/esperanto-lexicon-corpus/customs/CBAM/raw/cbam_en.html \\
      --input-lt ~/projects/esperanto-lexicon-corpus/customs/CBAM/raw/cbam_lt.html \\
      --celex 02023R0956-20230516 \\
      --domain cbam \\
      --jurisdiction EU \\
      --db data/domain_db/cbam.db \\
      --definitions-article 2 \\
      --output-dir data/domain_db/
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


def _count_records(path: Path) -> tuple[int, int]:
    """Return (total_definitions, approved_definitions) for a JSONL file."""
    total = approved = 0
    if not path.exists():
        return 0, 0
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if rec.get("record_type") == "definition":
                total += 1
                if rec.get("approved") is True:
                    approved += 1
    return total, approved


def _combine_jsonl(sources: list[Path], dest: Path) -> None:
    """Concatenate multiple JSONL files into dest, skipping missing sources."""
    with dest.open("w", encoding="utf-8") as out:
        for src in sources:
            if not src.exists():
                continue
            with src.open(encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        out.write(line + "\n")


def _html_to_corpus_text(html_path: Path, output_path: Path) -> None:
    """Extract clean plain text from a EUR-Lex HTML file for corpus analysis.

    Removes script/style tags and short lines (navigation, UI noise).
    Output is suitable as input to statistical_mwe_detector.py.
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        print("  (beautifulsoup4 not installed — skipping corpus text extraction)", file=sys.stderr)
        return

    html = html_path.read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "head", "nav"]):
        tag.decompose()
    raw_lines = soup.get_text(separator="\n").splitlines()
    # Keep lines long enough to be legal text (discard navigation noise)
    lines = [ln.strip() for ln in raw_lines if len(ln.strip()) >= 20]
    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"  Corpus text: {len(lines)} lines → {output_path.name}")


# ---------------------------------------------------------------------------
# Phase 1
# ---------------------------------------------------------------------------


def phase1(args: argparse.Namespace, output_dir: Path) -> None:
    """Extract definitions from EN and/or LT HTML and combine for review."""
    lang_inputs: list[tuple[str, Path]] = []
    if args.input_en:
        lang_inputs.append(("en", Path(args.input_en).expanduser()))
    if args.input_lt:
        lang_inputs.append(("lt", Path(args.input_lt).expanduser()))

    if not lang_inputs:
        print(
            "Error: at least one of --input-en or --input-lt is required for Phase 1.",
            file=sys.stderr,
        )
        sys.exit(1)

    for _lang, html_path in lang_inputs:
        if not html_path.exists():
            print(f"Error: input file not found: {html_path}", file=sys.stderr)
            sys.exit(1)

    lang_jsonls: list[Path] = []
    lang_counts: dict[str, int] = {}

    for lang, html_path in lang_inputs:
        out_jsonl = output_dir / f"{args.domain}_definitions_{lang}.jsonl"
        lang_jsonls.append(out_jsonl)

        # Extract definitions
        cmd = [
            sys.executable, "src/extractor/extract_eurlex_definitions.py",
            "--input", str(html_path),
            "--celex", args.celex,
            "--lang", lang,
            "--output", str(out_jsonl),
        ]
        if args.definitions_article:
            cmd += ["--article", str(args.definitions_article)]
        _run(cmd, f"EUR-Lex HTML ({lang.upper()}) → definitions")

        total, _ = _count_records(out_jsonl)
        lang_counts[lang] = total

        # Extract corpus text for Phase 2 statistical detection
        corpus_txt = output_dir / f"{args.domain}_corpus_{lang}.txt"
        print(f"  Extracting corpus text from {html_path.name} …")
        _html_to_corpus_text(html_path, corpus_txt)

    # Combine JSONL files for bilingual review
    combined = output_dir / f"{args.domain}_definitions_combined.jsonl"
    _combine_jsonl(lang_jsonls, combined)

    # Summary
    print(f"\n{'═' * 60}")
    print("Phase 1 complete.")
    counts_str = " + ".join(
        f"{lang_counts[lang]} {lang.upper()}" for lang, _ in lang_inputs
    )
    print(f"  {counts_str} candidates written.")
    for jsonl in lang_jsonls:
        print(f"    {jsonl}")
    print(f"  Combined: {combined}")
    print()
    langs_str = " ".join(lang for lang, _ in lang_inputs)
    print("Next:")
    print(f"  1. Review bilingual candidates:")
    print(f"     python3 src/extractor/review_cli.py \\")
    print(f"         --input {combined} \\")
    print(f"         --lang {langs_str}")
    print()
    print("  2. Commit reviewed records (Phase 2):")
    print(f"     python3 src/ingestion/ingest_eurlex.py --phase 2 \\")
    print(f"         --domain {args.domain} --jurisdiction {args.jurisdiction} \\")
    print(f"         --db {args.db} --output-dir {output_dir} --celex {args.celex}")
    print(f"{'═' * 60}")


# ---------------------------------------------------------------------------
# Phase 2
# ---------------------------------------------------------------------------


def phase2(args: argparse.Namespace, output_dir: Path) -> None:
    """Write approved records to domain DB and run statistical detection."""
    combined = output_dir / f"{args.domain}_definitions_combined.jsonl"
    if not combined.exists():
        print(
            f"Error: {combined} not found — run Phase 1 first.",
            file=sys.stderr,
        )
        sys.exit(1)

    _, approved = _count_records(combined)
    if approved == 0:
        print(
            f"Error: no approved records in {combined.name}.\n"
            f"Review with:\n"
            f"  python3 src/extractor/review_cli.py --input {combined} --lang en lt",
            file=sys.stderr,
        )
        sys.exit(1)

    _run(
        [
            sys.executable, "src/extractor/domain_db_writer.py",
            "--input", str(combined),
            "--db", str(args.db),
            "--domain", args.domain,
            "--jurisdiction", args.jurisdiction,
        ],
        "write definitions → domain DB",
    )

    # Statistical MWE detection (requires --lexicon and Phase-1 corpus text)
    lexicon = getattr(args, "lexicon", None)
    if lexicon:
        for lang in ("en", "lt"):
            corpus_txt = output_dir / f"{args.domain}_corpus_{lang}.txt"
            if not corpus_txt.exists():
                print(f"  (no corpus text for {lang} — skipping statistical MWE detection)")
                continue
            mwe_out = output_dir / f"{args.domain}_mwe_{lang}.jsonl"
            ne_out = output_dir / f"{args.domain}_ne_{lang}.jsonl"
            _run(
                [
                    sys.executable, "src/extractor/statistical_mwe_detector.py",
                    "--input", str(corpus_txt),
                    "--lang", lang,
                    "--lexicon", str(lexicon),
                    "--domain-db", str(args.db),
                    "--output", str(mwe_out),
                    "--output-ne", str(ne_out),
                ],
                f"statistical MWE detection ({lang.upper()})",
            )
    else:
        print("  (--lexicon not provided — skipping statistical MWE detection)")

    print(f"\n{'═' * 60}")
    print(f"Phase 2 complete. Domain DB: {args.db}")
    print(f"{'═' * 60}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    """Entry point for EUR-Lex ingestion pipeline."""
    parser = argparse.ArgumentParser(
        description="Multi-language EUR-Lex HTML ingestion pipeline.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--phase", type=int, default=1, choices=[1, 2],
        help="1=extract (default), 2=commit reviewed records to DB",
    )
    parser.add_argument(
        "--input-en", dest="input_en", type=Path, default=None,
        help="Path to English EUR-Lex HTML file",
    )
    parser.add_argument(
        "--input-lt", dest="input_lt", type=Path, default=None,
        help="Path to Lithuanian EUR-Lex HTML file",
    )
    parser.add_argument(
        "--celex", required=True,
        help="CELEX identifier, e.g. 02023R0956-20230516",
    )
    parser.add_argument(
        "--domain", required=True,
        help="Domain label, e.g. cbam",
    )
    parser.add_argument(
        "--jurisdiction", required=True,
        help="Jurisdiction code, e.g. EU",
    )
    parser.add_argument(
        "--db", type=Path, required=True,
        help="Domain DB path (.db file)",
    )
    parser.add_argument(
        "--definitions-article", dest="definitions_article", default=None,
        help="Article number containing definitions (e.g. 2); omit to extract all",
    )
    parser.add_argument(
        "--output-dir", dest="output_dir", type=Path, required=True,
        help="Directory for JSONL and corpus text output files",
    )
    parser.add_argument(
        "--lexicon", type=Path, default=None,
        help="Path to lexicon_v2.db (enables statistical MWE detection in Phase 2)",
    )
    args = parser.parse_args(argv)

    output_dir = args.output_dir.expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.phase == 1:
        phase1(args, output_dir)
    else:
        phase2(args, output_dir)


if __name__ == "__main__":
    main()
