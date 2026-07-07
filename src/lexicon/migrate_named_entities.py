#!/usr/bin/env python3
"""Migrate lexicon_v2.db to add the named-entity inventory tables (v0).

Purely additive: creates, idempotently, the sibling table set that holds the
physically-permanent named-entity core (celestial + physical-geographic). It
**never touches** ``concept`` / ``concept_root`` / ``concept_lang`` and never
drops anything — the table/index creations all use ``IF NOT EXISTS``.

Tables created (see ``schema.create_named_entity_schema`` for the authoritative
definition and the R8 "no tier column" rule):
  * ``named_entity``        — id, qid UNIQUE, label_eo, label_en, sitelinks,
                              sitelinks_asof, source, global_core, status
  * ``named_entity_type``   — junction (entity_id, ne_type, validation)
  * ``named_entity_alias``  — (entity_id, alias, lang)

Backs up the DB before touching it. Running it twice does nothing harmful.

Usage:
    python3 src/lexicon/migrate_named_entities.py
    python3 src/lexicon/migrate_named_entities.py --lexicon path/to/lexicon_v2.db
    python3 src/lexicon/migrate_named_entities.py --no-backup   # e.g. for CI
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from schema import create_named_entity_schema  # noqa: E402

_NE_TABLES = ("named_entity", "named_entity_type", "named_entity_alias")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def migrate_db(db_path: Path) -> dict:
    """Apply the named-entity migration to *db_path*. Returns a stats dict."""
    conn = sqlite3.connect(db_path)
    try:
        before = {t: _table_exists(conn, t) for t in _NE_TABLES}
        create_named_entity_schema(conn)
        after = {t: _table_exists(conn, t) for t in _NE_TABLES}
    finally:
        conn.close()
    created = [t for t in _NE_TABLES if after[t] and not before[t]]
    return {"created": created, "already_present": [t for t in _NE_TABLES if before[t]]}


def _backup(db_path: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup = db_path.with_name(f"{db_path.stem}.bak-ne-{stamp}{db_path.suffix}")
    shutil.copy2(db_path, backup)
    return backup


def main(argv: list[str] | None = None) -> int:
    root = _repo_root()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--lexicon",
        type=Path,
        default=root / "data" / "lexicon_db" / "lexicon_v2.db",
        help="path to lexicon_v2.db",
    )
    ap.add_argument("--no-backup", action="store_true", help="skip the DB backup")
    args = ap.parse_args(argv)

    if not args.lexicon.exists():
        print(f"ERROR: DB not found: {args.lexicon}", file=sys.stderr)
        return 2

    if not args.no_backup:
        print(f"backup: {_backup(args.lexicon)}")
    stats = migrate_db(args.lexicon)
    print(f"created: {stats['created'] or '(none — already present)'}")
    if stats["already_present"]:
        print(f"already present: {stats['already_present']}")
    print("OK — named-entity inventory tables ready.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
