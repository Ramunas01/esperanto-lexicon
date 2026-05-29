#!/usr/bin/env python3
"""Migrate domain DBs to add per-area attestation infrastructure.

Adds, idempotently, to each domain DB:

  * Table  mwe_area_attestation  — one row per (mwe_id, area, source_file),
    recording the raw doc_count + frequency of a term in a given customs area.
    Cross-cutting/overlay corpora share the single 'cross_cutting' area tag;
    source_file preserves the originating mining file.
  * Indexes idx_mwe_area_attestation_term / idx_mwe_area_attestation_area.
  * Column mwe.area_signature TEXT — denormalised 7-hex-digit display cache,
    NULL for already-existing rows (backfill is a separate task; see
    recompute_signatures.py).

The migration is purely additive: it never touches mwe or mwe_lang data and
never drops anything. Running it twice does nothing harmful — the table/index
creations use IF NOT EXISTS and the column is only added when absent.

Usage:
    # Auto-discover all *.db files under data/domain_db/:
    python3 src/lexicon/migrate_area_attestation.py

    # Explicit paths:
    python3 src/lexicon/migrate_area_attestation.py \\
        data/domain_db/customs_expert_vocab.db data/domain_db/ucc_customs.db
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

_CREATE_SQL = """
    CREATE TABLE IF NOT EXISTS mwe_area_attestation (
        id          INTEGER PRIMARY KEY,
        mwe_id      INTEGER NOT NULL,
        area        TEXT    NOT NULL,
        doc_count   INTEGER NOT NULL,
        frequency   INTEGER NOT NULL,
        source_file TEXT,
        mined_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (mwe_id) REFERENCES mwe(id) ON DELETE CASCADE,
        UNIQUE (mwe_id, area, source_file)
    );

    CREATE INDEX IF NOT EXISTS idx_mwe_area_attestation_term
        ON mwe_area_attestation(mwe_id);

    CREATE INDEX IF NOT EXISTS idx_mwe_area_attestation_area
        ON mwe_area_attestation(area);
"""


def _existing_mwe_columns(conn: sqlite3.Connection) -> set[str]:
    return {row[1] for row in conn.execute("PRAGMA table_info(mwe)")}


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def migrate_db(db_path: Path) -> dict:
    """Apply the area-attestation migration to *db_path*. Returns a stats dict."""
    conn = sqlite3.connect(db_path)
    table_existed = _table_exists(conn, "mwe_area_attestation")

    conn.executescript(_CREATE_SQL)

    added_column = False
    if "area_signature" not in _existing_mwe_columns(conn):
        conn.execute("ALTER TABLE mwe ADD COLUMN area_signature TEXT")
        added_column = True

    conn.commit()
    rows = conn.execute("SELECT COUNT(*) FROM mwe_area_attestation").fetchone()[0]
    conn.close()

    return {
        "path": db_path,
        "table_created": not table_existed,
        "column_added": added_column,
        "attestation_rows": rows,
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Add mwe_area_attestation table and mwe.area_signature column "
        "to domain DBs (idempotent)."
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
        table_note = "created" if stats["table_created"] else "already present"
        col_note = "added" if stats["column_added"] else "already present"
        print(f"{db_path.name}")
        print(f"  mwe_area_attestation table : {table_note} ({stats['attestation_rows']} rows)")
        print(f"  mwe.area_signature column  : {col_note}")


if __name__ == "__main__":
    main()
