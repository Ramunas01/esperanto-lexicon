#!/usr/bin/env python3
"""Extract defined terms from legal plain-text files.

Parses definition clauses of the form:
    N. TERM – definition text.
    N. TERM (toliau – ABBREV) – definition text.
    N. TERM (ĉi-poste nomata – ABBREV) – definition text.

Only clauses that contain a ' – ' or ' - ' separator (outside parentheses) are
extracted; clauses without one (expired clauses, umbrella references, colon-listed
items) are silently skipped, which yields the expected 38 definitions from
Article 2 of GPMI-LT / GPMI-EO.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
import re


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_CLAUSE_RE = re.compile(r"^(\d+(?:\s\d+)?)\.\s+(.+)")

_ARTICLE_HEADER_RES: dict[str, re.Pattern[str]] = {
    "lt": re.compile(r"^(\d+)\s+straipsnis\."),
    "eo": re.compile(r"^[Aa]rtikolo\s+(\d+)\."),
    "en": re.compile(r"^[Aa]rticle\s+(\d+)\."),
}

# Lines signalling an amendment block or legal metadata — do not extract.
# Prefix patterns matched at the start of the stripped line.
# N-ro is the Esperanto equivalent of Lithuanian Nr. (law reference numbers).
_SKIP_LINE_RE = re.compile(
    r"^(?:Nr\.|Straipsnio|Papildyta|Ŝanĝoj|Aldonita|TAR pastaba|Noto pri|N-ro)",
    re.IGNORECASE,
)

# Mid-line content patterns that also signal amendment markers.
_SKIP_CONTENT_RE = re.compile(r"publikigita en la TAR", re.IGNORECASE)


def _should_skip(line: str) -> bool:
    """True when a line is a legal amendment marker or metadata that must not be extracted."""
    return bool(_SKIP_LINE_RE.match(line)) or bool(_SKIP_CONTENT_RE.search(line))

# Sub-item lines such as "1) ...", "2) ..."
_SUBITEM_RE = re.compile(r"^\d+\)\s")

# Abbreviation clause patterns
# Lithuanian: (toliau – X) or (toliau šioje dalyje vadinama – X)
# [^)–-] = not closing-paren, not em-dash (U+2013), not hyphen-minus
_ABBREV_LT_RE = re.compile(r"\(toliau[^)–-]*(?:–|-)\s*(.+?)\)")

# Esperanto with separator: (ĉi-poste nomata – X) or (ĉi-poste nomata en ... – X)
# [^)]+ prevents crossing the closing paren of the abbreviation clause.
_ABBREV_EO_DASH_RE = re.compile(
    r"\(ĉi-poste\s+nomata(?:\s+[^)]+?)?\s*(?:–|-)\s+([^)]+?)\)"
)
# Esperanto without separator: (ĉi-poste nomata X) or (ĉi-poste nomata "X")
_ABBREV_EO_NODASH_RE = re.compile(r"\(ĉi-poste\s+nomata\s+(.+?)\)")

# By-reference detection — applied to the START of the definition text
_BY_REF_RES: dict[str, list[re.Pattern[str]]] = {
    "lt": [
        re.compile(
            r"^kaip\s+ši\s+sąvoka\s+apibrėžta\s+(.+?)(?:\s*\(|[,.]|$)",
            re.IGNORECASE,
        )
    ],
    "eo": [
        re.compile(
            r"^kiel\s+(?:difinita|difinite)\s+en\s+(.+?)(?:\s*\(|[,.]|$)",
            re.IGNORECASE,
        ),
        re.compile(
            r"^kiel\s+ĉi\s+tiu\s+koncepto\s+estas\s+difinita\s+en\s+(.+?)(?:\s*\(|[,.]|$)",
            re.IGNORECASE,
        ),
    ],
    "en": [
        re.compile(
            r"^as\s+defined\s+in\s+(.+?)(?:\s*\(|[,.]|$)",
            re.IGNORECASE,
        )
    ],
}


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------


def _normalize_clause_num(raw: str) -> str:
    """Remove internal spaces from compound clause numbers: '27 1' → '271'."""
    return raw.replace(" ", "")


def _find_separator(text: str) -> tuple[int, int] | None:
    """Find the first ' – ' (em-dash) or ' - ' (hyphen) separator outside parentheses.

    Returns (start_index, end_index) of the separator or None if absent.
    """
    depth = 0
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif depth == 0:
            for sep in (" – ", " - "):
                end = i + len(sep)
                if text[i:end] == sep:
                    return i, end
        i += 1
    return None


def _extract_abbrev(text: str, lang: str) -> str | None:
    """Return the first abbreviation found in the clause line, or None.

    Searches for (toliau – X) / (ĉi-poste nomata – X) anywhere in the line,
    including inside the definition part (e.g. clause 27 LT).
    """
    if lang == "lt":
        m = _ABBREV_LT_RE.search(text)
        return m.group(1).strip() if m else None
    if lang == "eo":
        m = _ABBREV_EO_DASH_RE.search(text)
        if m:
            return m.group(1).strip()
        m = _ABBREV_EO_NODASH_RE.search(text)
        if m:
            return m.group(1).strip().strip('"').strip()
        return None
    return None


def _detect_definition_type(definition: str, lang: str) -> tuple[str, str | None]:
    """Return (definition_type, by_reference_law).

    definition_type is 'by_reference' when the definition text *starts* with a
    phrase meaning "as defined in [Law]".  Otherwise returns ('direct', None).
    """
    for pat in _BY_REF_RES.get(lang, []):
        m = pat.match(definition.strip())
        if m:
            return "by_reference", m.group(1).strip()
    return "direct", None


# ---------------------------------------------------------------------------
# Article boundary detection
# ---------------------------------------------------------------------------


def find_article_bounds(lines: list[str], article_num: str, lang: str) -> tuple[int, int]:
    """Return (start_idx, end_idx) for the content of the specified article.

    start_idx points to the line after the article header.
    end_idx points to the start of the next article header (exclusive).

    Raises ValueError if the article cannot be found.
    """
    header_re = _ARTICLE_HEADER_RES.get(lang)
    if header_re is None:
        raise ValueError(f"Unsupported language: {lang!r}")

    start = -1
    end = len(lines)

    for i, line in enumerate(lines):
        m = header_re.match(line.strip())
        if m:
            if m.group(1) == article_num:
                start = i + 1
            elif start >= 0:
                end = i
                break

    if start < 0:
        raise ValueError(f"Article {article_num!r} not found (lang={lang!r})")

    return start, end


# ---------------------------------------------------------------------------
# Clause parsing
# ---------------------------------------------------------------------------


def _parse_clause(
    clause_num: str,
    body_lines: list[str],
    lang: str,
    source_file: str,
    article: str,
) -> dict | None:
    """Parse a collected clause body into an output record.

    Returns None if the clause lacks the required TERM–definition structure
    (e.g. expired clauses, colon-enumerated items, umbrella reference clauses).
    """
    if not body_lines:
        return None

    main_line = body_lines[0]
    m = _CLAUSE_RE.match(main_line)
    if not m:
        return None
    rest = m.group(2)

    sep = _find_separator(rest)
    if sep is None:
        return None

    sep_start, sep_end = sep
    term_part = rest[:sep_start].strip()
    definition_first = rest[sep_end:].strip()

    # term_raw: text before any opening parenthesis in the term part
    paren_pos = term_part.find("(")
    term_raw = term_part[:paren_pos].strip() if paren_pos > 0 else term_part

    # Search full main line for abbreviation (may be in term or definition part)
    abbrev = _extract_abbrev(main_line, lang)

    # Build definition_raw: first-line text + any non-skip continuation lines
    extra: list[str] = []
    for line in body_lines[1:]:
        s = line.strip()
        if not s:
            continue
        if _should_skip(s):
            continue
        extra.append(s)

    definition_raw = " ".join([definition_first] + extra) if extra else definition_first

    definition_type, by_reference_law = _detect_definition_type(definition_first, lang)

    return {
        "source_file": source_file,
        "lang": lang,
        "article": article,
        "clause_num": clause_num,
        "term_raw": term_raw,
        "term_normalized": term_raw.lower(),
        "abbrev": abbrev,
        "definition_raw": definition_raw,
        "definition_type": definition_type,
        "by_reference_law": by_reference_law,
        "cross_lang_num": clause_num,
        "approved": False,
    }


# ---------------------------------------------------------------------------
# Main extraction function
# ---------------------------------------------------------------------------


def extract_definitions(
    lines: list[str],
    article_num: str,
    lang: str,
    source_file: str,
) -> list[dict]:
    """Extract all defined terms from the specified article.

    Args:
        lines: Lines of the source file (e.g. as returned by file.readlines()).
        article_num: The article to extract from, e.g. "2".
        lang: Language code: 'lt', 'eo', or 'en'.
        source_file: Source filename to embed in every output record.

    Returns:
        List of definition records, one per extracted term.
    """
    start, end = find_article_bounds(lines, article_num, lang)

    results: list[dict] = []
    current_num: str | None = None
    current_body: list[str] = []

    def flush() -> None:
        if current_num is not None:
            rec = _parse_clause(current_num, current_body, lang, source_file, article_num)
            if rec is not None:
                results.append(rec)

    for i in range(start, end):
        stripped = lines[i].rstrip("\n").strip().replace("**", "")

        if _should_skip(stripped):
            continue

        m = _CLAUSE_RE.match(stripped)
        if m:
            flush()
            current_num = _normalize_clause_num(m.group(1))
            current_body = [stripped]
            continue

        if _SUBITEM_RE.match(stripped):
            if current_body:
                current_body.append(stripped)
            continue

        # Blank line or ordinary continuation — attach to current clause
        if current_body is not None:
            current_body.append(stripped)

    flush()
    return results


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------


def _load_existing_keys(output_path: Path) -> set[tuple[str, str, str, str]]:
    """Load (source_file, lang, article, clause_num) keys from an existing JSONL file."""
    keys: set[tuple[str, str, str, str]] = set()
    if not output_path.exists():
        return keys
    with output_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                keys.add(
                    (rec["source_file"], rec["lang"], rec["article"], rec["clause_num"])
                )
            except (json.JSONDecodeError, KeyError):
                pass
    return keys


def write_records(
    records: list[dict],
    output_path: Path,
    *,
    append: bool = False,
) -> int:
    """Write records to output_path as JSONL, optionally deduplicating.

    In append mode, records whose (source_file, lang, article, clause_num) key
    already exists in the file are skipped.

    Returns the number of records actually written.
    """
    existing_keys = _load_existing_keys(output_path) if append else set()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if append else "w"
    written = 0
    with output_path.open(mode, encoding="utf-8") as fh:
        for rec in records:
            key = (rec["source_file"], rec["lang"], rec["article"], rec["clause_num"])
            if key in existing_keys:
                continue
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            written += 1
    return written


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    """Command-line interface for extract_definitions."""
    parser = argparse.ArgumentParser(
        description="Extract defined terms from legal plain-text files."
    )
    parser.add_argument("--input", required=True, type=Path, help="Path to input .txt file")
    parser.add_argument(
        "--lang", required=True, choices=["lt", "eo", "en"], help="Language code"
    )
    parser.add_argument(
        "--article", required=True, help="Article number to extract (e.g. 2)"
    )
    parser.add_argument(
        "--output", required=True, type=Path, help="Path to output .jsonl file"
    )
    parser.add_argument(
        "--append",
        action="store_true",
        help="Append to existing output file instead of overwriting",
    )
    args = parser.parse_args(argv)

    if not args.input.exists():
        print(f"Error: input file not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    with args.input.open(encoding="utf-8") as fh:
        lines = fh.readlines()

    try:
        records = extract_definitions(
            lines=lines,
            article_num=args.article,
            lang=args.lang,
            source_file=args.input.name,
        )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    written = write_records(records, args.output, append=args.append)
    print(
        f"Extracted {len(records)} definitions; wrote {written} new records to {args.output}"
    )


if __name__ == "__main__":
    main()
