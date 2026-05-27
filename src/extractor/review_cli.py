#!/usr/bin/env python3
"""Interactive CLI to review extracted definition candidates.

Usage (single language):
    python3 src/extractor/review_cli.py \\
        --input data/domain_db/gpmi_definitions.jsonl \\
        --lang lt

Usage (two languages side by side):
    python3 src/extractor/review_cli.py \\
        --input data/domain_db/gpmi_definitions.jsonl \\
        --lang lt eo
"""

from __future__ import annotations

import argparse
import json
import sys
import termios
import tty
from pathlib import Path


VALID_LANGS = ["lt", "eo", "en"]


def _read_key() -> str:
    """Read a single keypress from stdin without requiring Enter."""
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        return sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _load_records(path: Path) -> list[dict]:
    records = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _save_records(path: Path, records: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _is_pending(approved: object) -> bool:
    """True when a record has not been explicitly approved or rejected."""
    return approved not in (True, "rejected")


def _pending_idxs(records: list[dict], lang: str) -> list[int]:
    """Return indexes of records for lang that are not yet approved or rejected."""
    return [
        i
        for i, r in enumerate(records)
        if r.get("lang") == lang and _is_pending(r.get("approved"))
    ]


# ---------------------------------------------------------------------------
# Format detection
# ---------------------------------------------------------------------------


def _detect_format(records: list[dict]) -> str:
    """Return 'statistical', 'eurlex', or 'definition' based on first record's keys."""
    for rec in records:
        rt = rec.get("record_type")
        if rt == "definition" and "source_ref" in rec:
            return "eurlex"
        if "phrase" in rec:
            return "statistical"
        if rt is None or rt == "definition":
            return "definition"
    return "definition"


# ---------------------------------------------------------------------------
# Single-language display (definition format)
# ---------------------------------------------------------------------------


def _display_single(rec: dict, position: int, total: int) -> None:
    abbrev = rec.get("abbrev") or "(none)"
    clause = f"Clause {rec.get('clause_num', '?')}"
    lang = rec.get("lang", "?")
    term = rec.get("term_raw", "?")
    defn = rec.get("definition_raw", "?")
    dtype = rec.get("definition_type", "?")

    print()
    print("  " + "─" * 61)
    print(f"  [{position} of {total}]  {clause}  |  {lang}")
    print(f"  TERM:   {term}")
    print(f"  DEF:    {defn}")
    print(f"  TYPE:   {dtype}")
    print(f"  ABBREV: {abbrev}")
    print("  " + "─" * 61)


# ---------------------------------------------------------------------------
# Single-language display (statistical format)
# ---------------------------------------------------------------------------


def _display_statistical(rec: dict, position: int, total: int) -> None:
    lang = rec.get("lang", "?")
    method = rec.get("extraction_method", "?")
    phrase = rec.get("phrase", "?")
    freq = rec.get("frequency", "?")
    pmi = rec.get("pmi")
    ngram = rec.get("ngram_size", "?")
    novel: list[str] = rec.get("novel_components") or []
    common: list[str] = rec.get("common_components") or []

    pmi_str = f"{pmi:.2f}" if isinstance(pmi, (int, float)) else "?"
    novel_str = ", ".join(novel) if novel else "(none)"
    common_str = ", ".join(common) if common else "(none)"

    print()
    print("  " + "─" * 61)
    print(f"  [{position} of {total}]  {lang}  |  {method}")
    print(f"  {'PHRASE:':<10}{phrase}")
    print(f"  {'FREQ:':<10}{freq}   PMI: {pmi_str}   [{ngram}-gram]")
    print(f"  {'NOVEL:':<10}{novel_str}")
    print(f"  {'COMMON:':<10}{common_str}")
    print("  " + "─" * 61)


_TRIVIAL_DEFS = {"", ":", "–", "—"}


def _eurlex_def_lines(rec: dict) -> list[str]:
    """Return display lines for a EUR-Lex definition.

    When definition is empty or trivial (colon/dash placeholder) and sub_items
    are present, formats sub_items as '(marker) text' lines instead.  At most
    5 sub_items are shown; a count line is appended when more exist.
    """
    defn = (rec.get("definition") or "").strip()
    sub_items = rec.get("sub_items") or []

    if defn in _TRIVIAL_DEFS and sub_items:
        lines: list[str] = []
        for item in sub_items[:5]:
            marker = item.get("marker", "")
            text = (item.get("text") or "")[:80]
            prefix = f"({marker}) " if marker else ""
            lines.append(f"{prefix}{text}")
        if len(sub_items) > 5:
            lines.append(f"... ({len(sub_items) - 5} more)")
        return lines or ["(no definition)"]

    return [defn if defn else "?"]


def _display_eurlex(rec: dict, position: int, total: int) -> None:
    """Display a single EUR-Lex definition record."""
    src = rec.get("source_ref", {})
    amendment = rec.get("amendment", {})
    ctx = rec.get("context", {})
    lang = rec.get("lang", "?")
    term = rec.get("term", "?")
    list_path = src.get("list_path", "?")
    celex = src.get("celex_id", "?")
    art_num = ctx.get("article_number") or "?"
    marker = amendment.get("marker", "B")
    amend_celex = amendment.get("celex", celex)

    def_lines = _eurlex_def_lines(rec)

    print()
    print("  " + "─" * 61)
    print(f"  [{position} of {total}]  Art.{art_num} item {list_path}  |  {lang}  [▼{marker} {amend_celex}]")
    print(f"  TERM:   {term}")
    print(f"  DEF:    {def_lines[0]}")
    for line in def_lines[1:]:
        print(f"          {line}")
    print(f"  TYPE:   (none)")
    print(f"  ABBREV: (none)")
    print("  " + "─" * 61)


def _pending_idxs_eurlex(records: list[dict], lang: str) -> list[int]:
    """Return indexes of EUR-Lex definition records for lang that are not yet reviewed."""
    return [
        i
        for i, r in enumerate(records)
        if r.get("lang") == lang
        and r.get("record_type") == "definition"
        and "source_ref" in r
        and _is_pending(r.get("approved"))
    ]


def review(input_path: Path, lang: str) -> None:
    """Run the interactive review loop for a single language.

    Auto-detects record format: definition records show TERM/DEF/TYPE/ABBREV;
    statistical records show PHRASE/FREQ/PMI/NOVEL/COMMON.
    """
    records = _load_records(input_path)
    fmt = _detect_format(records)
    if fmt == "eurlex":
        display_fn = _display_eurlex
        pending = _pending_idxs_eurlex(records, lang)
    elif fmt == "statistical":
        display_fn = _display_statistical
        pending = _pending_idxs(records, lang)
    else:
        display_fn = _display_single
        pending = _pending_idxs(records, lang)

    if not pending:
        print(f"No pending records for lang={lang!r}.")
        return

    total = len(pending)
    approved_count = 0
    rejected_count = 0
    skipped_count = 0

    for pos, rec_idx in enumerate(pending, start=1):
        rec = records[rec_idx]
        display_fn(rec, pos, total)
        print("  [a] approve   [r] reject   [s] skip   [q] quit  > ", end="", flush=True)

        key = _read_key()
        print(key)

        if key == "a":
            rec["approved"] = True
            _save_records(input_path, records)
            approved_count += 1
        elif key == "r":
            rec["approved"] = "rejected"
            _save_records(input_path, records)
            rejected_count += 1
        elif key == "s":
            skipped_count += 1
        elif key == "q":
            print("\n  Session ended early.")
            break
        else:
            print(f"  (unknown key {key!r}, treating as skip)")
            skipped_count += 1

    if fmt == "eurlex":
        remaining = _pending_idxs_eurlex(records, lang)
    else:
        remaining = _pending_idxs(records, lang)
    print()
    print("  ── Session summary ──────────────────")
    print(f"  Approved  : {approved_count}")
    print(f"  Rejected  : {rejected_count}")
    print(f"  Skipped   : {skipped_count}")
    print(f"  Remaining : {len(remaining)}")
    print()


# ---------------------------------------------------------------------------
# Two-language helpers
# ---------------------------------------------------------------------------


def _build_clause_groups(
    records: list[dict], langs: list[str], fmt: str = "definition"
) -> list[tuple[str, dict[str, int | None]]]:
    """Group records by clause key for the given languages.

    Returns a sorted list of (key, {lang: record_index_or_None}).
    For EUR-Lex records, key is source_ref.list_path; otherwise cross_lang_num/clause_num.
    Sorting is numeric where key is an integer string, lexicographic otherwise.
    """
    groups: dict[str, dict[str, int | None]] = {}
    for i, rec in enumerate(records):
        lang = rec.get("lang")
        if lang not in langs:
            continue
        if fmt == "eurlex":
            if rec.get("record_type") != "definition":
                continue
            key = str(rec.get("source_ref", {}).get("list_path") or "?")
        else:
            key = str(rec.get("cross_lang_num") or rec.get("clause_num") or "?")
        if key not in groups:
            groups[key] = {L: None for L in langs}
        groups[key][lang] = i

    def _sort_key(k: str) -> tuple:
        try:
            return (0, int(k))
        except ValueError:
            return (1, k)

    return sorted(groups.items(), key=lambda item: _sort_key(item[0]))


def _group_is_pending(group: dict[str, int | None], records: list[dict]) -> bool:
    """True if at least one record in the group is not yet approved or rejected."""
    return any(
        idx is not None and _is_pending(records[idx].get("approved"))
        for idx in group.values()
    )


def _display_two(
    clause_num: str,
    group: dict[str, int | None],
    records: list[dict],
    langs: list[str],
    position: int,
    total: int,
    fmt: str = "definition",
) -> None:
    print()
    print("  " + "─" * 65)
    if fmt == "eurlex":
        print(f"  [{position} of {total}]  item {clause_num}")
    else:
        print(f"  [{position} of {total}]  Clause {clause_num}")

    for lang in langs:
        idx = group[lang]
        tag = lang.upper()
        indent = " " * 6
        if idx is None:
            print(f"\n  {tag}  (no {tag} equivalent found)")
            continue
        rec = records[idx]
        if fmt == "eurlex":
            term = rec.get("term", "?")
            def_lines = _eurlex_def_lines(rec)
            dtype = "(none)"
            abbrev = "(none)"
        else:
            term = rec.get("term_raw", "?")
            def_lines = [rec.get("definition_raw", "?")]
            dtype = rec.get("definition_type", "?")
            abbrev = rec.get("abbrev") or "(none)"
        print(f"\n  {tag}  TERM:  {term}")
        print(f"{indent}DEF:   {def_lines[0]}")
        for line in def_lines[1:]:
            print(f"{indent}       {line}")
        print(f"{indent}TYPE:  {dtype}")
        print(f"{indent}ABBREV: {abbrev}")

    print()
    print("  " + "─" * 65)


def _set_approved(
    group: dict[str, int | None], records: list[dict], lang: str, value: bool | str
) -> None:
    idx = group[lang]
    if idx is not None:
        records[idx]["approved"] = value


# ---------------------------------------------------------------------------
# Two-language review
# ---------------------------------------------------------------------------


def review_two(input_path: Path, langs: list[str], fmt: str = "definition") -> None:
    """Run the interactive review loop for two languages side by side."""
    records = _load_records(input_path)
    all_groups = _build_clause_groups(records, langs, fmt)
    pending_groups = [(k, g) for k, g in all_groups if _group_is_pending(g, records)]

    if not pending_groups:
        print(f"No pending groups for langs={langs!r}.")
        return

    total = len(pending_groups)
    counts: dict[str, dict[str, int]] = {
        lang: {"approved": 0, "rejected": 0, "skipped": 0} for lang in langs
    }
    lang0, lang1 = langs[0], langs[1]
    tag0, tag1 = lang0.upper(), lang1.upper()

    for pos, (clause_num, group) in enumerate(pending_groups, start=1):
        _display_two(clause_num, group, records, langs, pos, total, fmt)
        print(
            f"  [a] approve both   [r] reject both   [1] approve {tag0} only\n"
            f"  [2] approve {tag1} only   [s] skip   [q] quit  > ",
            end="",
            flush=True,
        )

        key = _read_key()
        print(key)

        has0 = group[lang0] is not None
        has1 = group[lang1] is not None

        if key == "a":
            _set_approved(group, records, lang0, True)
            _set_approved(group, records, lang1, True)
            _save_records(input_path, records)
            if has0:
                counts[lang0]["approved"] += 1
            if has1:
                counts[lang1]["approved"] += 1
        elif key == "r":
            _set_approved(group, records, lang0, "rejected")
            _set_approved(group, records, lang1, "rejected")
            _save_records(input_path, records)
            if has0:
                counts[lang0]["rejected"] += 1
            if has1:
                counts[lang1]["rejected"] += 1
        elif key == "1":
            _set_approved(group, records, lang0, True)
            _set_approved(group, records, lang1, "rejected")
            _save_records(input_path, records)
            if has0:
                counts[lang0]["approved"] += 1
            if has1:
                counts[lang1]["rejected"] += 1
        elif key == "2":
            _set_approved(group, records, lang1, True)
            _set_approved(group, records, lang0, "rejected")
            _save_records(input_path, records)
            if has1:
                counts[lang1]["approved"] += 1
            if has0:
                counts[lang0]["rejected"] += 1
        elif key == "s":
            if has0:
                counts[lang0]["skipped"] += 1
            if has1:
                counts[lang1]["skipped"] += 1
        elif key == "q":
            print("\n  Session ended early.")
            break
        else:
            print(f"  (unknown key {key!r}, treating as skip)")
            if has0:
                counts[lang0]["skipped"] += 1
            if has1:
                counts[lang1]["skipped"] += 1

    remaining_groups = [
        (k, g)
        for k, g in _build_clause_groups(records, langs, fmt)
        if _group_is_pending(g, records)
    ]
    print()
    print("  ── Session summary ──────────────────")
    for lang in langs:
        c = counts[lang]
        print(
            f"  {lang.upper()}: {c['approved']} approved, "
            f"{c['rejected']} rejected, {c['skipped']} skipped"
        )
    print(f"  Remaining groups: {len(remaining_groups)}")
    print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    """Entry point for review_cli."""
    parser = argparse.ArgumentParser(
        description="Interactively approve or reject extracted definition records."
    )
    parser.add_argument("--input", required=True, type=Path, help="Path to .jsonl file")
    parser.add_argument(
        "--lang",
        required=True,
        nargs="+",
        choices=VALID_LANGS,
        metavar="LANG",
        help=f"Language(s) to review: one or two of {VALID_LANGS}. "
        "Single value for single-lang mode; two values for side-by-side mode.",
    )
    args = parser.parse_args(argv)

    if len(args.lang) > 2:
        parser.error("--lang accepts at most two languages")
    if len(set(args.lang)) != len(args.lang):
        parser.error("--lang languages must be distinct")
    if not args.input.exists():
        print(f"Error: file not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    if len(args.lang) == 1:
        review(args.input, args.lang[0])
    else:
        # Two-language mode: definition records are grouped by cross_lang_num and
        # reviewed side by side.  Statistical records have no cross-language groups,
        # so each language is reviewed sequentially in single-lang mode.
        records = _load_records(args.input)
        fmt = _detect_format(records)
        if fmt == "statistical":
            print(
                "  (statistical format: no cross-language groups — "
                "reviewing each language separately)"
            )
            for lang in args.lang:
                review(args.input, lang)
        else:
            review_two(args.input, args.lang, fmt)


if __name__ == "__main__":
    main()
