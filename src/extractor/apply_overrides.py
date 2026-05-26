#!/usr/bin/env python3
"""Apply manual_overrides.jsonl corrections to an existing domain DB without re-running the pipeline.

Usage:
    python3 src/extractor/apply_overrides.py \\
        --db data/domain_db/gpmi_lt_tax.db \\
        --overrides data/domain_db/manual_overrides.jsonl
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from extractor.domain_db_writer import load_overrides


def apply_overrides_to_db(
    conn: sqlite3.Connection,
    overrides: dict[tuple[str, str], dict],
) -> int:
    """Apply all overrides to mwe_lang rows in *conn*.

    Returns the number of rows updated.
    """
    updated = 0
    for (phrase_normalized, lang), override in overrides.items():
        rows = conn.execute(
            "SELECT id, phrase, phrase_normalized FROM mwe_lang WHERE phrase_normalized = ? AND lang = ?",
            (phrase_normalized, lang),
        ).fetchall()
        if not rows:
            print(f"  WARNING: no match for phrase_normalized={phrase_normalized!r} lang={lang!r}")
            continue
        for row_id, old_phrase, old_norm in rows:
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
            print(f"  Updated: {old_phrase!r} → {new_phrase!r}  (lang={lang})")
            updated += 1
    return updated


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
    overrides = load_overrides(overrides_path)
    if not overrides:
        print(f"No overrides found in {overrides_path}")
        return

    print(f"Applying {len(overrides)} override(s) from {overrides_path.name} to {args.db.name}")
    conn = sqlite3.connect(args.db)
    conn.execute("PRAGMA foreign_keys = ON")
    n = apply_overrides_to_db(conn, overrides)
    conn.commit()
    conn.close()
    print(f"\nDone. {n} row(s) updated.")


if __name__ == "__main__":
    main()
