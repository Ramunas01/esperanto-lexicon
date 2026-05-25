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
# Single-language display and review
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


def review(input_path: Path, lang: str) -> None:
    """Run the interactive review loop for a single language."""
    records = _load_records(input_path)
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
        _display_single(rec, pos, total)
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
    records: list[dict], langs: list[str]
) -> list[tuple[str, dict[str, int | None]]]:
    """Group records by cross_lang_num for the given languages.

    Returns a sorted list of (cross_lang_num, {lang: record_index_or_None}).
    Sorting is numeric where cross_lang_num is an integer string, lexicographic otherwise.
    """
    groups: dict[str, dict[str, int | None]] = {}
    for i, rec in enumerate(records):
        lang = rec.get("lang")
        if lang not in langs:
            continue
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
) -> None:
    print()
    print("  " + "─" * 65)
    print(f"  [{position} of {total}]  Clause {clause_num}")

    for lang in langs:
        idx = group[lang]
        tag = lang.upper()
        indent = " " * 6
        if idx is None:
            print(f"\n  {tag}  (no {tag} equivalent found)")
            continue
        rec = records[idx]
        abbrev = rec.get("abbrev") or "(none)"
        print(f"\n  {tag}  TERM:  {rec.get('term_raw', '?')}")
        print(f"{indent}DEF:   {rec.get('definition_raw', '?')}")
        print(f"{indent}TYPE:  {rec.get('definition_type', '?')}")
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


def review_two(input_path: Path, langs: list[str]) -> None:
    """Run the interactive review loop for two languages side by side."""
    records = _load_records(input_path)
    all_groups = _build_clause_groups(records, langs)
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
        _display_two(clause_num, group, records, langs, pos, total)
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
        for k, g in _build_clause_groups(records, langs)
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
        review_two(args.input, args.lang)


if __name__ == "__main__":
    main()
