#!/usr/bin/env python3
"""Extract the WCO Glossary of International Customs Terms into JSONL.

One-off extractor for the 2024-06 edition.

Usage:
    python3 src/extractor/extract_wco_glossary.py \\
        --input ~/projects/esperanto-lexicon-corpus/customs/WCO/glossary-of-international-customs-terms.pdf \\
        --output data/domain_db/wco_glossary.jsonl
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:
    import pdfplumber
except ImportError:
    print("Error: pdfplumber not installed. Run: pip install pdfplumber", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# PDF extraction
# ---------------------------------------------------------------------------

_HEADER_LEFT = "TERMS"


def _collect_raw_rows(pdf: "pdfplumber.PDF") -> tuple[list[tuple[str, str, int]], int]:
    """Return all content rows as (left, right, page_num) after merging all splits.

    Handles three kinds of row splits produced by pdfplumber on this PDF:

    1. Right-cell overflow: empty left, non-empty right → appended to previous entry.
    2. Page-break left-cell split: last row on a page has an unclosed '(' in the
       left cell; first row on the next page has ')' but no '(' → merge left+right.
    3. French-paren on next row: left cell has no '(' at all, the very next row's
       left is a simple '(French term)' with no newlines → merge left+right.
       (Only one known case in the 2024 edition: RESILIENCE / (Résilience).)

    Skips the cover page (index 0), header rows, and fully-blank rows.
    """
    flat: list[tuple[str, str, int]] = []
    for pg_idx, page in enumerate(pdf.pages[1:], start=2):  # skip cover (page 1)
        tables = page.extract_tables()
        for table in tables:
            for row in table:
                left = (row[0] or "").strip()
                right = (row[1] or "").strip()
                if left == _HEADER_LEFT:
                    continue
                if not left and not right:
                    continue
                flat.append((left, right, pg_idx))

    merged: list[tuple[str, str, int]] = []
    page_break_joins = 0
    i = 0
    while i < len(flat):
        left, right, pg = flat[i]

        # Case 1: empty left, non-empty right → right-cell overflow onto new row
        if not left and right and merged:
            prev_l, prev_r, prev_pg = merged[-1]
            merged[-1] = (prev_l, (prev_r + " " + right).strip(), prev_pg)
            i += 1
            continue

        opens = left.count("(")
        closes = left.count(")")

        if i + 1 < len(flat):
            next_left, next_right, _ = flat[i + 1]

            # Case 2: page-break left-cell split (unbalanced open paren in left)
            if opens > closes and ")" in next_left and "(" not in next_left:
                merged_left = left + " " + next_left
                merged_right = (right + " " + next_right).strip()
                merged.append((merged_left, merged_right, pg))
                page_break_joins += 1
                i += 2
                continue

            # Case 3: French paren on next row (left has no parens at all;
            # next left is a simple '(term)' with no embedded newlines)
            if (
                opens == 0
                and closes == 0
                and left  # not empty
                and next_left.startswith("(")
                and next_left.endswith(")")
                and "\n" not in next_left
            ):
                merged_left = left + "\n" + next_left
                merged_right = (right + " " + next_right).strip()
                merged.append((merged_left, merged_right, pg))
                i += 2
                continue

        merged.append((left, right, pg))
        i += 1

    return merged, page_break_joins


# ---------------------------------------------------------------------------
# Left-cell parser
# ---------------------------------------------------------------------------


def _parse_left(left: str) -> tuple[str, str | None, str | None]:
    """Parse left cell into (en_term_display, fr_term | None, warning | None).

    en_term_display: normalised English headword (may include abbreviation).
    fr_term: French equivalent, stripped of outer parens, normalised whitespace.
    warning: non-fatal parse issue string, or None.
    """
    # Find the last occurrence of a newline followed by an opening paren.
    # In the standard format this is the start of the French parenthetical.
    last_np = left.rfind("\n(")
    if last_np < 0:
        # No French parenthetical found
        return " ".join(left.split()), None, "no French parenthetical"

    en_raw = left[:last_np]
    fr_raw = left[last_np + 1:]  # starts with '('

    # Special case: fr_raw is a short abbreviation like '(nCEN)\n...'
    # followed by the actual French text on subsequent lines.
    abbrev_m = re.match(r"\(([^()\n]{1,25})\)\n(.+)", fr_raw, re.DOTALL)
    if abbrev_m:
        abbrev = abbrev_m.group(1)
        fr_rest = abbrev_m.group(2)
        # The abbreviation belongs to the English term; fr_rest is the French
        en_term = " ".join(en_raw.split()) + f" ({abbrev})"
        fr_term = " ".join(fr_rest.split())
        warn = f"French not in outer parens (non-standard format); extracted: {fr_term[:40]!r}"
        return en_term, fr_term or None, warn

    # Normal case: fr_raw is a parenthetical (may have nested parens)
    if fr_raw.startswith("(") and fr_raw.endswith(")"):
        fr_inner = fr_raw[1:-1]
    elif fr_raw.startswith("("):
        # Truncated — missing closing paren (PDF extraction artifact)
        fr_inner = fr_raw[1:]
    else:
        fr_inner = fr_raw

    fr_term = " ".join(fr_inner.split())
    en_term = " ".join(en_raw.split())
    return en_term, fr_term or None, None


# ---------------------------------------------------------------------------
# Entry-ID derivation
# ---------------------------------------------------------------------------

_PAREN_RE = re.compile(r"\([^)]*\)")


def _entry_id(en_term: str) -> str:
    """Derive a stable slug from the English headword.

    'ADVANCE RULINGS'                     → 'advance-rulings'
    'AUTHORIZED ECONOMIC OPERATOR (AEO)'  → 'authorized-economic-operator'
    'Time Release Study(TRS)'             → 'time-release-study'
    """
    s = _PAREN_RE.sub("", en_term)  # remove parentheticals
    s = s.lower().strip()
    s = re.sub(r"[^\w\s-]", "-", s)   # non-word chars (/, ') → hyphen
    s = re.sub(r"\s+", "-", s)        # spaces → hyphens
    s = re.sub(r"-+", "-", s).strip("-")
    return s


# ---------------------------------------------------------------------------
# Right-cell parser
# ---------------------------------------------------------------------------

_NOTE_SIGNAL = re.compile(r"^Notes?:?\s*$", re.IGNORECASE | re.MULTILINE)
# Numbered note paragraph, e.g. "1. Text..." or "(*) Text..."
_NOTE_PARA = re.compile(r"(?m)^(?:\d+\.|[\(*]+\)?)\s+")


def _parse_right(right: str) -> tuple[str, list[str]]:
    """Split right cell into (definition_body, notes_list).

    Everything before the first 'Note'/'Notes'/'Notes:' line is the definition.
    Everything after is one or more note paragraphs.
    """
    m = _NOTE_SIGNAL.search(right)
    if m:
        body = right[: m.start()].strip()
        notes_text = right[m.end():].strip()
        notes = _split_notes(notes_text)
    else:
        body = right.strip()
        notes = []
    return body, notes


def _split_notes(text: str) -> list[str]:
    """Split notes text into individual paragraphs."""
    # Try numeric split: "1. ...\n2. ..."
    parts = _NOTE_PARA.split(text)
    parts = [p.strip() for p in parts if p.strip()]
    if len(parts) > 1:
        return parts
    return [text.strip()] if text.strip() else []


# ---------------------------------------------------------------------------
# Cross-reference extraction
# ---------------------------------------------------------------------------

_XREF_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"Annex\s+\w+(?:\.\w+)?\s+to\s+the\s+Kyoto\s+Convention(?:\s+of\s+\d{4})?"),
    re.compile(r"(?:General|Specific)\s+Annex\s+[A-Z],?\s+Chapter\s+\d+(?:\s+of\s+the\s+revised\s+Kyoto\s+Convention)?"),
    re.compile(r"General\s+Annex,?\s+Standard\s+[\d.]+"),
    re.compile(r"Article\s+\d+\s+of\s+the\s+[\w\s]+(?:Convention|Agreement|Framework|Protocol)"),
    re.compile(r"[\w\s]+Convention(?:\s+of\s+\d{4})?(?=[\s,.]|$)"),
    re.compile(r"[\w\s]+Agreement(?:\s+on\s+[\w\s]+)?(?=[\s,.]|$)"),
    re.compile(r"[\w\s]+Framework(?:\s+of\s+Standards)?(?=[\s,.]|$)"),
    re.compile(r"WCO\s+[\w\s]+"),
    re.compile(r"TRIPS"),
    re.compile(r"WTO\s+[\w\s]+"),
]

_MIN_XREF_LEN = 8


def _extract_cross_refs(text: str) -> list[str]:
    """Extract cross-reference strings from definition/notes text.

    Returns deduplicated list preserving first-occurrence order.
    """
    seen: set[str] = set()
    refs: list[str] = []
    for pat in _XREF_PATTERNS:
        for m in pat.finditer(text):
            ref = m.group(0).strip().rstrip(",.")
            if len(ref) >= _MIN_XREF_LEN and ref not in seen:
                seen.add(ref)
                refs.append(ref)
    return refs


# ---------------------------------------------------------------------------
# Record builder
# ---------------------------------------------------------------------------


def _make_source_ref(entry_id: str, page: int, edition: str) -> dict:
    return {
        "source": "wco-glossary",
        "edition": edition,
        "publisher": "World Customs Organization",
        "entry_id": entry_id,
        "page": page,
    }


def _build_records(
    en_term_display: str,
    fr_term: str | None,
    definition: str,
    notes: list[str],
    xrefs: list[str],
    page: int,
    edition: str,
    warnings: list[str],
) -> tuple[dict, dict | None]:
    """Return (en_record, fr_record). fr_record is None if no French term."""
    eid = _entry_id(en_term_display)
    source_ref = _make_source_ref(eid, page, edition)

    en_rec = {
        "record_type": "definition",
        "lang": "en",
        "term": en_term_display.lower(),
        "term_original": en_term_display,
        "definition": definition or None,
        "notes": notes,
        "cross_references": xrefs,
        "source_ref": source_ref,
        "approved": True,
    }

    if fr_term:
        fr_rec = {
            "record_type": "definition",
            "lang": "fr",
            "term": fr_term.lower(),
            "term_original": fr_term,
            "definition": None,
            "notes": [],
            "cross_references": [],
            "source_ref": source_ref,
            "approved": True,
        }
    else:
        fr_rec = None

    return en_rec, fr_rec


# ---------------------------------------------------------------------------
# Top-level extraction
# ---------------------------------------------------------------------------


def extract_entries(pdf_path: Path, edition: str = "2024-06") -> tuple[list[dict], dict]:
    """Extract all glossary entries from the PDF.

    Returns (records, stats) where records is a flat list of JSONL-ready dicts
    and stats is a summary dict.
    """
    records: list[dict] = []
    stats: dict = {
        "pages_processed": 0,
        "page_break_joins": 0,
        "entries_extracted": 0,
        "warnings": 0,
        "duplicate_ids": [],
    }

    with pdfplumber.open(pdf_path) as pdf:
        stats["pages_processed"] = len(pdf.pages) - 1  # exclude cover
        raw_rows, stats["page_break_joins"] = _collect_raw_rows(pdf)

    seen_ids: dict[str, str] = {}  # entry_id → en_term_display
    warn_lines: list[str] = []

    for left, right, page_num in raw_rows:
        en_term, fr_term, parse_warn = _parse_left(left)
        definition, notes = _parse_right(right)
        all_text = " ".join([definition] + notes)
        xrefs = _extract_cross_refs(all_text)

        entry_warn: list[str] = []
        if parse_warn:
            msg = f"page {page_num} '{en_term[:40]}': {parse_warn}"
            warn_lines.append(f"  WARN: {msg}")
            entry_warn.append(parse_warn)

        eid = _entry_id(en_term)
        if eid in seen_ids:
            msg = f"duplicate entry_id '{eid}' for '{en_term}' (first: '{seen_ids[eid]}')"
            warn_lines.append(f"  WARN: {msg}")
            stats["duplicate_ids"].append(eid)
            stats["warnings"] += 1
        else:
            seen_ids[eid] = en_term

        en_rec, fr_rec = _build_records(
            en_term, fr_term, definition, notes, xrefs, page_num, edition, entry_warn
        )
        records.append(en_rec)
        if fr_rec:
            records.append(fr_rec)
        stats["entries_extracted"] += 1

    stats["warnings"] += len(warn_lines)
    stats["_warn_lines"] = warn_lines
    return records, stats


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description="Extract the WCO Glossary of International Customs Terms into JSONL."
    )
    ap.add_argument("--input", required=True, type=Path, help="Path to the PDF")
    ap.add_argument("--output", required=True, type=Path, help="Path for output .jsonl")
    ap.add_argument("--edition", default="2024-06", help="Edition tag (default: 2024-06)")
    args = ap.parse_args(argv)

    if not args.input.exists():
        print(f"Error: PDF not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    records, stats = extract_entries(args.input, args.edition)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    warn_lines = stats.pop("_warn_lines", [])
    for w in warn_lines:
        print(w, file=sys.stderr)

    n_fr = sum(1 for r in records if r["lang"] == "fr")
    n_en = len(records) - n_fr

    print(f"Pages processed   : {stats['pages_processed']}")
    print(f"Entries extracted : {stats['entries_extracted']}")
    print(f"Page-break joins  : {stats['page_break_joins']}")
    print(f"Records written   : {len(records)}  (EN={n_en}, FR={n_fr})")
    print(f"Warnings          : {stats['warnings']}")
    print(f"Output written to : {args.output}")


if __name__ == "__main__":
    main()
