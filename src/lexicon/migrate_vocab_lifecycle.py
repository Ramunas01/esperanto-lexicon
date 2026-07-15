#!/usr/bin/env python3
"""Migrate for the R9 vocabulary lifecycle: the two out-of-band homes.

Adds, idempotently and additively:

  * To the **common lexicon** (``lexicon_v2.db``): table ``concept_lifecycle``
    — the ``unplaced`` staging status (rising/new vocabulary), EXCLUDED from the
    expertise metric. See :func:`schema.create_lifecycle_schema`.
  * The **philology-T4 domain** DB (``data/domain_db/philology.db``): a genuine
    Tier-4 domain (same shape as the other ``data/domain_db/*.db``) for
    obsolete/archaic/dialectal/scholarly roots, COUNTED as expertise like any
    T4. Built with the shared :func:`schema.create_domain_schema`.

Purely additive and non-destructive: table creation uses ``IF NOT EXISTS`` and
no existing row is ever touched. Running it twice does nothing harmful. With the
``concept_lifecycle`` table empty, every existing analysis is byte-identical —
the metric only changes once a concept is explicitly staged ``unplaced``.

**This migration is human-review-gated (Effort B B1): review the DDL before
applying it to the real DBs.** Nothing here authors lexicon content; movement
into a home is a status/domain assignment only, reversible and provenance-
stamped (R8 derived-not-fixed). No root ever leaves the inventory.

Usage:
    # Dry run — print what WOULD change, touch nothing:
    python3 src/lexicon/migrate_vocab_lifecycle.py --dry-run

    # Apply (after human review of the DDL):
    python3 src/lexicon/migrate_vocab_lifecycle.py \\
        --lexicon data/lexicon_db/lexicon_v2.db \\
        --philology-db data/domain_db/philology.db
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

# Allow running as a script (mirrors the sibling migration scripts).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lexicon.schema import (  # noqa: E402
    create_domain_schema,
    create_lifecycle_schema,
)

PHILOLOGY_DOMAIN = "philology"


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone()
        is not None
    )


def migrate_lexicon(lexicon_db: Path, *, dry_run: bool = False) -> dict:
    """Add ``concept_lifecycle`` to the common lexicon DB. Returns a stats dict."""
    conn = sqlite3.connect(lexicon_db)
    try:
        existed = _table_exists(conn, "concept_lifecycle")
        if not dry_run:
            create_lifecycle_schema(conn)
        rows = (
            conn.execute("SELECT COUNT(*) FROM concept_lifecycle").fetchone()[0]
            if _table_exists(conn, "concept_lifecycle")
            else 0
        )
    finally:
        conn.close()
    return {"path": lexicon_db, "table_existed": existed, "unplaced_rows": rows}


def scaffold_philology_domain(philology_db: Path, *, dry_run: bool = False) -> dict:
    """Scaffold the philology-T4 domain DB (empty, same shape as other domains)."""
    existed = philology_db.exists()
    if not dry_run:
        philology_db.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(philology_db)
        try:
            create_domain_schema(conn)
        finally:
            conn.close()
    mwe_rows = 0
    if philology_db.exists():
        conn = sqlite3.connect(philology_db)
        try:
            if _table_exists(conn, "mwe"):
                mwe_rows = conn.execute("SELECT COUNT(*) FROM mwe").fetchone()[0]
        finally:
            conn.close()
    return {"path": philology_db, "db_existed": existed, "mwe_rows": mwe_rows}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--lexicon", type=Path, default=Path("data/lexicon_db/lexicon_v2.db"))
    ap.add_argument(
        "--philology-db", type=Path, default=Path("data/domain_db/philology.db")
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change without writing anything.",
    )
    args = ap.parse_args(argv)

    tag = "[dry-run] " if args.dry_run else ""

    if not args.lexicon.exists():
        print(f"Error: lexicon DB {args.lexicon} not found.", file=sys.stderr)
        sys.exit(1)

    lex = migrate_lexicon(args.lexicon, dry_run=args.dry_run)
    verb = "already present" if lex["table_existed"] else (
        "would be created" if args.dry_run else "created"
    )
    print(f"{tag}{args.lexicon.name}")
    print(f"  concept_lifecycle table : {verb} ({lex['unplaced_rows']} unplaced rows)")

    phil = scaffold_philology_domain(args.philology_db, dry_run=args.dry_run)
    verb = "already present" if phil["db_existed"] else (
        "would be scaffolded" if args.dry_run else "scaffolded"
    )
    print(f"{tag}{args.philology_db.name}")
    print(f"  philology-T4 domain DB  : {verb} ({phil['mwe_rows']} mwe rows)")


if __name__ == "__main__":
    main()
