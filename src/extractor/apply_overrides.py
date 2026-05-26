#!/usr/bin/env python3
"""Apply manual_overrides.jsonl corrections to an existing domain DB without re-running the pipeline.

Usage:
    python3 src/extractor/apply_overrides.py \\
        --db data/domain_db/gpmi_lt_tax.db \\
        --overrides data/domain_db/manual_overrides.jsonl

Supported match_on fields (all optional, AND-combined):
    phrase_normalized   — exact match on phrase_normalized column
    lang                — exact match on lang column
    definition_contains — case-insensitive substring match on definition_raw
    mwe_id              — exact match on mwe_id (most precise)
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


# ---------------------------------------------------------------------------
# Loader (full entries — distinct from domain_db_writer.load_overrides)
# ---------------------------------------------------------------------------


def load_override_entries(overrides_path: Path) -> list[dict]:
    """Load manual_overrides.jsonl → list of full override records.

    Each record retains the original structure: {match_on: …, override: …, …}.
    Returns an empty list if the file does not exist.
    """
    if not overrides_path.exists():
        return []
    entries: list[dict] = []
    with overrides_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


# ---------------------------------------------------------------------------
# Core apply logic
# ---------------------------------------------------------------------------


def _build_match_query(match_on: dict) -> tuple[str, list]:
    """Build a SELECT query from match_on criteria.

    Returns (sql_fragment, params) where sql_fragment is the WHERE clause body.
    Raises ValueError if match_on is empty (would match all rows).
    """
    conditions: list[str] = []
    params: list = []

    if "phrase_normalized" in match_on:
        conditions.append("phrase_normalized = ?")
        params.append(match_on["phrase_normalized"])
    if "lang" in match_on:
        conditions.append("lang = ?")
        params.append(match_on["lang"])
    if "mwe_id" in match_on:
        conditions.append("mwe_id = ?")
        params.append(match_on["mwe_id"])
    if "definition_contains" in match_on:
        conditions.append("LOWER(definition_raw) LIKE ?")
        params.append(f"%{match_on['definition_contains'].lower()}%")

    if not conditions:
        raise ValueError("match_on must contain at least one criterion")

    return " AND ".join(conditions), params


def _match_description(match_on: dict) -> str:
    parts = []
    if "phrase_normalized" in match_on:
        parts.append(f"phrase={match_on['phrase_normalized']!r}")
    if "lang" in match_on:
        parts.append(f"lang={match_on['lang']!r}")
    if "mwe_id" in match_on:
        parts.append(f"mwe_id={match_on['mwe_id']}")
    if "definition_contains" in match_on:
        parts.append(f"definition_contains={match_on['definition_contains']!r}")
    return ", ".join(parts) if parts else "(empty)"


def apply_overrides_to_db(
    conn: sqlite3.Connection,
    entries: list[dict],
) -> int:
    """Apply all override entries to mwe_lang rows in *conn*.

    Each entry must have:
      "match_on": dict  — criteria to identify rows (phrase_normalized, lang,
                          definition_contains, mwe_id — AND-combined)
      "override": dict  — fields to set (phrase, phrase_normalized, definition_raw)

    Warnings:
      Zero matches    → prints warning, skips entry.
      Multiple matches → prints warning, applies to all matched rows.

    Returns the number of rows updated.
    """
    updated = 0

    for entry in entries:
        match_on = entry.get("match_on", {})
        override = entry.get("override", {})
        desc = _match_description(match_on)

        try:
            where_clause, params = _build_match_query(match_on)
        except ValueError:
            print(f"  WARNING: empty match_on — skipping entry")
            continue

        sql = (
            "SELECT id, phrase, phrase_normalized, lang "
            f"FROM mwe_lang WHERE {where_clause}"
        )
        rows = conn.execute(sql, params).fetchall()

        if not rows:
            print(f"  WARNING: no rows matched override for {desc}")
            continue

        if len(rows) > 1:
            print(
                f"  WARNING: {len(rows)} rows matched override for {desc} — "
                f"consider adding definition_contains or mwe_id to make match more specific"
            )

        for row_id, old_phrase, old_norm, row_lang in rows:
            new_phrase = override.get("phrase", old_phrase)
            new_norm = override.get("phrase_normalized", old_norm)
            new_def = override.get("definition_raw")
            if new_def is not None:
                conn.execute(
                    "UPDATE mwe_lang SET phrase=?, phrase_normalized=?, definition_raw=? WHERE id=?",
                    (new_phrase, new_norm, new_def, row_id),
                )
            else:
                conn.execute(
                    "UPDATE mwe_lang SET phrase=?, phrase_normalized=? WHERE id=?",
                    (new_phrase, new_norm, row_id),
                )
            print(f"  Updated: {old_phrase!r} → {new_phrase!r}  (lang={row_lang})")
            updated += 1

    return updated


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Apply manual_overrides.jsonl corrections to an existing domain DB."
    )
    parser.add_argument("--db", required=True, type=Path, help="Path to domain .db file")
    parser.add_argument(
        "--overrides", type=Path, default=None,
        help="Path to manual_overrides.jsonl (default: <db_dir>/manual_overrides.jsonl)",
    )
    args = parser.parse_args(argv)

    if not args.db.exists():
        print(f"Error: DB not found: {args.db}", file=sys.stderr)
        sys.exit(1)

    overrides_path = args.overrides or (args.db.parent / "manual_overrides.jsonl")
    entries = load_override_entries(overrides_path)
    if not entries:
        print(f"No overrides found in {overrides_path}")
        return

    print(f"Applying {len(entries)} override(s) from {overrides_path.name} to {args.db.name}")
    conn = sqlite3.connect(args.db)
    conn.execute("PRAGMA foreign_keys = ON")
    n = apply_overrides_to_db(conn, entries)
    conn.commit()
    conn.close()
    print(f"\nDone. {n} row(s) updated.")


if __name__ == "__main__":
    main()
