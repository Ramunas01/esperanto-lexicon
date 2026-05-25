#!/usr/bin/env python3
"""Convert a Lithuanian legal .docx file to a clean plain-text corpus.

Uses python-docx to read document structure directly rather than relying on
text-conversion artefacts.  Amendment metadata is stripped from the main output
and written to a separate file.

Usage:
    python3 src/ingestion/docx_to_corpus.py \\
        --input  path/to/law.docx \\
        --output path/to/law_clean.txt \\
        --amendments path/to/law_amendments.txt
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

try:
    from docx import Document
except ImportError:
    print(
        "python-docx is not installed.  Run:\n"
        "  pip install python-docx --break-system-packages",
        file=sys.stderr,
    )
    sys.exit(1)


# ---------------------------------------------------------------------------
# Compiled patterns
# ---------------------------------------------------------------------------

# Detects an amendment reference in paragraph text
_AMENDMENT_REF_RE = re.compile(r"Nr\.\s+[IVXLCDM\w]+-\d+")

# Extracts the amendment reference token (for the amendments file)
_AMENDMENT_REF_EXTRACT_RE = re.compile(r"(Nr\.\s+[\w]+-\d+(?:-\d+)?)")

# Extracts an ISO date from amendment text
_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")

# Detects article headings like "7 straipsnis." or "7 1 straipsnis."
_ARTICLE_NUM_RE = re.compile(r"^(\d+(?:\s+\d+)?)\s+straipsn", re.IGNORECASE)

# Keywords that mark amendment metadata paragraphs
_AMENDMENT_KEYWORDS = (
    "paskelbta TAR",
    "Straipsnio pakeitimai",
    "Straipsnio dalies pakeitimai",
    "Straipsnio punkto pakeitimai",
)


# ---------------------------------------------------------------------------
# Paragraph classifiers
# ---------------------------------------------------------------------------


def _runs_text(para) -> str:
    """Return the full text assembled from runs (same as para.text for normal paragraphs)."""
    return "".join(r.text for r in para.runs)


def _is_italic_only(para) -> bool:
    """True when every non-empty run in the paragraph is explicitly italic."""
    runs = [r for r in para.runs if r.text.strip()]
    if not runs:
        return False
    return all(r.italic is True for r in runs)


def is_amendment(para) -> bool:
    """True when the paragraph is an amendment metadata line to be stripped."""
    text = para.text
    if _is_italic_only(para):
        return True
    if _AMENDMENT_REF_RE.search(text):
        return True
    return any(kw in text for kw in _AMENDMENT_KEYWORDS)


def is_table_note(text: str) -> bool:
    return text.startswith("TAR pastaba")


def is_heading(para) -> bool:
    """True for style-based headings OR short all-bold paragraphs without ' – '."""
    if para.style.name.startswith("Heading"):
        return True
    text = para.text.strip()
    if not text or len(text) >= 80:
        return False
    runs = [r for r in para.runs if r.text.strip()]
    return bool(runs) and all(r.bold is True for r in runs) and " – " not in text


def extract_definition(para) -> str | None:
    """Return the paragraph formatted as **BOLD_TERM** – definition, or None.

    A paragraph qualifies when ALL of the following hold:
      1. It contains bold runs before ' – ' (em dash, U+2013)
         Plain hyphens do not qualify — they appear in headings like "13 (1) - Title"
      2. The term text before the dash is ≤ 120 characters
         (guards against full sentences where a dash appears far into the text)
    """
    full_text = ""
    bold_map: list[bool] = []
    for run in para.runs:
        full_text += run.text
        bold_map.extend([run.bold is True] * len(run.text))

    # Only the em dash (U+2013) qualifies as a definition separator
    dash_pos = full_text.find(" – ")

    if dash_pos < 0:
        return None

    if not any(bold_map[i] for i in range(dash_pos)):
        return None

    term_part = full_text[:dash_pos].strip()

    if len(term_part) > 120:
        return None

    rest = full_text[dash_pos:]  # keeps ' – definition text'
    return f"**{term_part}**{rest}"


# ---------------------------------------------------------------------------
# Amendment record formatting
# ---------------------------------------------------------------------------


def _format_amendment(text: str, current_article: str) -> str:
    """Return 'ARTICLE_NUM | AMENDMENT_REF | DATE' for the amendments file."""
    ref_m = _AMENDMENT_REF_EXTRACT_RE.search(text)
    ref = ref_m.group(1) if ref_m else "?"
    date_m = _DATE_RE.search(text)
    date = date_m.group(1) if date_m else "?"
    return f"{current_article} | {ref} | {date}"


# ---------------------------------------------------------------------------
# Main conversion pipeline
# ---------------------------------------------------------------------------


def convert(input_path: Path, output_path: Path, amendments_path: Path) -> dict:
    """Convert *input_path* (.docx) to a clean corpus text file.

    Returns a stats dict with keys: n_processed, n_definitions,
    n_amendments, n_table_notes.
    """
    doc = Document(str(input_path))

    output_lines: list[str] = []
    amendment_lines: list[str] = []

    n_processed = 0
    n_definitions = 0
    n_amendments = 0
    n_table_notes = 0
    current_article = "?"

    for para in doc.paragraphs:
        stripped = para.text.strip()
        n_processed += 1

        if not stripped:
            continue  # EMPTY

        if is_table_note(stripped):
            n_table_notes += 1
            continue  # TABLE_NOTE

        if is_amendment(para):
            n_amendments += 1
            amendment_lines.append(_format_amendment(stripped, current_article))
            continue  # AMENDMENT — do NOT update article tracking

        # Update article tracking from non-amendment paragraphs
        m = _ARTICLE_NUM_RE.match(stripped)
        if m:
            current_article = m.group(1).replace(" ", "")

        if is_heading(para):
            # Blank line before and after each heading
            if output_lines and output_lines[-1] != "":
                output_lines.append("")
            output_lines.append(stripped)
            output_lines.append("")
            continue

        definition = extract_definition(para)
        if definition is not None:
            n_definitions += 1
            output_lines.append(definition)
            continue

        output_lines.append(stripped)  # NORMAL

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(output_lines) + "\n", encoding="utf-8")

    amendments_path.parent.mkdir(parents=True, exist_ok=True)
    amendments_path.write_text("\n".join(amendment_lines) + "\n", encoding="utf-8")

    return {
        "n_processed": n_processed,
        "n_definitions": n_definitions,
        "n_amendments": n_amendments,
        "n_table_notes": n_table_notes,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Convert a Lithuanian legal .docx file to a clean plain-text corpus."
    )
    parser.add_argument("--input", required=True, type=Path, help="Input .docx file")
    parser.add_argument("--output", required=True, type=Path, help="Output plain-text file")
    parser.add_argument(
        "--amendments", required=True, type=Path, help="Output file for stripped amendment records"
    )
    args = parser.parse_args(argv)

    if not args.input.exists():
        print(f"Error: input file not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    stats = convert(args.input, args.output, args.amendments)

    print(f"Paragraphs processed : {stats['n_processed']}")
    print(f"Definitions found    : {stats['n_definitions']}")
    print(f"Amendments stripped  : {stats['n_amendments']}")
    print(f"Tables skipped       : {stats['n_table_notes']}")
    print(f"Output written to    : {args.output}")


if __name__ == "__main__":
    main()
