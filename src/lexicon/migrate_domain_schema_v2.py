#!/usr/bin/env python3
"""Migrate existing domain DBs to mwe schema v2.

Adds four provenance columns to the mwe table in each domain DB:

  source_type       TEXT  -- 'normative' | 'wco_glossary' |
                              'expert_corpus' | 'statistical_mwe'
  definition_status TEXT  -- 'defined' | 'undefined'
  attestation_count INTEGER DEFAULT 1
  authority         TEXT  -- celex_id or source reference for normative entries

Classification rules applied to first_seen_source:
  Starts with 'wco-glossary/'      → wco_glossary / defined
  Contains '#' (EUR-Lex structural) → normative    / defined
  Non-empty string (corpus file)   → normative    / defined
  NULL or empty                    → statistical_mwe / undefined

authority is set to:
  wco_glossary: the part before '#' (i.e. 'wco-glossary/2024-06')
  normative:    the part before '#' (i.e. the celex_id), or the source string
  statistical:  NULL

attestation_count is set to the count of distinct source_doc values in
mwe_occurrence for each entry.

Usage:
    # Auto-discover all *.db files under data/domain_db/:
    python3 src/lexicon/migrate_domain_schema_v2.py

    # Explicit paths:
    python3 src/lexicon/migrate_domain_schema_v2.py \\
        data/domain_db/ucc_customs.db data/domain_db/wco_intl.db
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

_NEW_COLUMNS = [
    ("source_type", "TEXT"),
    ("definition_status", "TEXT"),
    ("attestation_count", "INTEGER DEFAULT 1"),
    ("authority", "TEXT"),
]

_ADD_COLUMNS_SQL = """
    UPDATE mwe SET
        source_type = CASE
            WHEN first_seen_source LIKE 'wco-glossary/%' THEN 'wco_glossary'
            WHEN INSTR(COALESCE(first_seen_source, ''), '#') > 0 THEN 'normative'
            WHEN first_seen_source IS NOT NULL AND first_seen_source != '' THEN 'normative'
            ELSE 'statistical_mwe'
        END,
        definition_status = CASE
            WHEN first_seen_source IS NULL OR first_seen_source = '' THEN 'undefined'
            ELSE 'defined'
        END,
        authority = CASE
            WHEN INSTR(COALESCE(first_seen_source, ''), '#') > 0
                THEN SUBSTR(first_seen_source, 1, INSTR(first_seen_source, '#') - 1)
            ELSE first_seen_source
        END
"""

_UPDATE_ATTESTATION_SQL = """
    UPDATE mwe SET attestation_count = (
        SELECT COUNT(DISTINCT source_doc)
        FROM mwe_occurrence
        WHERE mwe_occurrence.mwe_id = mwe.id
    )
"""


def _existing_columns(conn: sqlite3.Connection) -> set[str]:
    return {row[1] for row in conn.execute("PRAGMA table_info(mwe)")}


def migrate_db(db_path: Path) -> dict:
    """Apply schema v2 migration to *db_path*. Returns a stats dict."""
    conn = sqlite3.connect(db_path)
    existing = _existing_columns(conn)

    added: list[str] = []
    for col_name, col_def in _NEW_COLUMNS:
        if col_name not in existing:
            conn.execute(f"ALTER TABLE mwe ADD COLUMN {col_name} {col_def}")
            added.append(col_name)

    conn.execute(_ADD_COLUMNS_SQL)
    conn.execute(_UPDATE_ATTESTATION_SQL)
    conn.commit()

    counts = conn.execute(
        "SELECT source_type, COUNT(*) FROM mwe GROUP BY source_type"
    ).fetchall()
    total = conn.execute("SELECT COUNT(*) FROM mwe").fetchone()[0]
    conn.close()

    return {
        "path": db_path,
        "total": total,
        "added_columns": added,
        "source_type_counts": dict(counts),
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Migrate domain DBs to mwe schema v2 (provenance columns)."
    )
    parser.add_argument(
        "dbs",
        nargs="*",
        type=Path,
        help="Domain DB paths. Defaults to all *.db files under data/domain_db/.",
    )
    args = parser.parse_args(argv)

    if args.dbs:
        db_paths = args.dbs
    else:
        root = Path("data/domain_db")
        if not root.exists():
            print(f"Error: {root} not found. Run from the repo root.", file=sys.stderr)
            sys.exit(1)
        db_paths = sorted(root.glob("*.db"))

    if not db_paths:
        print("No .db files found.", file=sys.stderr)
        sys.exit(1)

    for db_path in db_paths:
        if not db_path.exists():
            print(f"Warning: {db_path} not found — skipping.", file=sys.stderr)
            continue
        stats = migrate_db(db_path)
        added = (
            f"  added columns: {', '.join(stats['added_columns'])}"
            if stats["added_columns"]
            else "  columns already present"
        )
        print(f"{db_path.name}  ({stats['total']} entries)")
        print(added)
        for stype, count in sorted(stats["source_type_counts"].items()):
            print(f"  {stype}: {count}")


if __name__ == "__main__":
    main()
