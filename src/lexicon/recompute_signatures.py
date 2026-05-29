#!/usr/bin/env python3
"""Recompute the cached mwe.area_signature column from attestation rows.

The signature is a derived display affordance: raw doc_count + frequency live
in mwe_area_attestation, and the 7-hex-digit signature is computed from them.
The loader caches the signature inline as it writes attestation rows, but this
utility recomputes every mwe_id's signature in bulk. Use it to:

  * backfill signatures for rows that predate the attestation feature, and
  * re-derive signatures after changing the bucketing scheme in
    area_signature.compute_signature.

A term with no attestation rows is left with whatever signature it had (no
attestation → nothing to derive); pass --null-empty to instead set such rows
to NULL.

Usage:
    # Auto-discover all *.db files under data/domain_db/:
    python3 src/lexicon/recompute_signatures.py

    # Explicit paths:
    python3 src/lexicon/recompute_signatures.py data/domain_db/customs_expert_vocab.db
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from lexicon.area_signature import compute_signature


def recompute_db(db_path: Path, null_empty: bool = False) -> dict:
    """Recompute area_signature for every mwe in *db_path*. Returns a stats dict."""
    conn = sqlite3.connect(db_path)

    # Group attestation rows by mwe_id.
    by_mwe: dict[int, list[dict]] = {}
    for mwe_id, area, doc_count, frequency in conn.execute(
        "SELECT mwe_id, area, doc_count, frequency FROM mwe_area_attestation"
    ):
        by_mwe.setdefault(mwe_id, []).append(
            {"area": area, "doc_count": doc_count, "frequency": frequency}
        )

    updated = 0
    for mwe_id, rows in by_mwe.items():
        signature = compute_signature(rows)
        conn.execute(
            "UPDATE mwe SET area_signature = ? WHERE id = ?", (signature, mwe_id)
        )
        updated += 1

    nulled = 0
    if null_empty:
        cur = conn.execute(
            """
            UPDATE mwe SET area_signature = NULL
            WHERE id NOT IN (SELECT DISTINCT mwe_id FROM mwe_area_attestation)
              AND area_signature IS NOT NULL
            """
        )
        nulled = cur.rowcount

    conn.commit()
    total = conn.execute("SELECT COUNT(*) FROM mwe").fetchone()[0]
    conn.close()
    return {"path": db_path, "total": total, "updated": updated, "nulled": nulled}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Recompute cached mwe.area_signature from attestation rows."
    )
    parser.add_argument(
        "dbs",
        nargs="*",
        type=Path,
        help="Domain DB paths. Defaults to all *.db files under data/domain_db/.",
    )
    parser.add_argument(
        "--null-empty",
        action="store_true",
        help="Set area_signature to NULL for mwe rows with no attestation.",
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
        stats = recompute_db(db_path, null_empty=args.null_empty)
        msg = f"{db_path.name}  ({stats['total']} mwe): {stats['updated']} signature(s) recomputed"
        if args.null_empty:
            msg += f", {stats['nulled']} nulled"
        print(msg)


if __name__ == "__main__":
    main()
