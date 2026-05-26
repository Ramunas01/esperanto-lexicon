#!/usr/bin/env python3
"""Manually link two domain phrases as synonyms.

Usage (create link):
    python3 src/extractor/link_synonyms.py \\
        --db data/domain_db/gpmi_lt_tax.db \\
        --phrase-a "individualia veikla besiverčiantys" \\
        --phrase-b "verčiasi individualia veikla" \\
        --lang lt \\
        --reason "participial vs verbal form of same concept"

Usage (list existing synonyms):
    python3 src/extractor/link_synonyms.py \\
        --db data/domain_db/gpmi_lt_tax.db \\
        --list
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import date
from pathlib import Path


def _lookup_mwe_id(conn: sqlite3.Connection, phrase: str, lang: str) -> int | None:
    """Return mwe_id for the phrase (looked up by phrase_normalized), or None."""
    row = conn.execute(
        "SELECT mwe_id FROM mwe_lang WHERE phrase_normalized = ? AND lang = ?",
        (phrase.strip().lower(), lang),
    ).fetchone()
    return row[0] if row else None


def link_synonyms(
    conn: sqlite3.Connection,
    phrase_a: str,
    phrase_b: str,
    lang: str,
    reason: str,
) -> tuple[int, int]:
    """Create a synonym mwe_conflict record linking phrase_a and phrase_b.

    Returns (mwe_id_a, mwe_id_b).
    Raises ValueError if either phrase is not found in mwe_lang for *lang*.
    """
    mwe_id_a = _lookup_mwe_id(conn, phrase_a, lang)
    mwe_id_b = _lookup_mwe_id(conn, phrase_b, lang)

    if mwe_id_a is None:
        raise ValueError(f"phrase_a not found: {phrase_a!r} (lang={lang})")
    if mwe_id_b is None:
        raise ValueError(f"phrase_b not found: {phrase_b!r} (lang={lang})")

    # Check for existing synonym link in either direction
    existing = conn.execute(
        """SELECT id FROM mwe_conflict
           WHERE conflict_type = 'synonym'
             AND ((mwe_id_a = ? AND mwe_id_b = ?) OR (mwe_id_a = ? AND mwe_id_b = ?))""",
        (mwe_id_a, mwe_id_b, mwe_id_b, mwe_id_a),
    ).fetchone()
    if existing:
        print(f"  Synonym link already exists (conflict id={existing[0]}). No change made.")
        return mwe_id_a, mwe_id_b

    conn.execute(
        """INSERT INTO mwe_conflict
               (mwe_id_a, mwe_id_b, conflict_type, divergence_detail,
                resolution_status, detected_date)
           VALUES (?, ?, 'synonym', ?, 'open', ?)""",
        (mwe_id_a, mwe_id_b, reason, date.today().isoformat()),
    )
    conn.commit()
    return mwe_id_a, mwe_id_b


def load_synonyms(conn: sqlite3.Connection) -> list[dict]:
    """Return all synonym conflict records with phrase text for both sides."""
    rows = conn.execute(
        """
        SELECT c.id, la.lang, la.phrase, lb.phrase, c.divergence_detail, c.resolution_status
        FROM mwe_conflict c
        JOIN mwe_lang la ON la.mwe_id = c.mwe_id_a
        JOIN mwe_lang lb ON lb.mwe_id = c.mwe_id_b AND lb.lang = la.lang
        WHERE c.conflict_type = 'synonym'
        ORDER BY c.id
        """
    ).fetchall()
    return [
        {
            "conflict_id": r[0],
            "lang": r[1],
            "phrase_a": r[2],
            "phrase_b": r[3],
            "reason": r[4],
            "resolution_status": r[5],
        }
        for r in rows
    ]


def load_synonym_map(conn: sqlite3.Connection, lang: str) -> dict[str, str]:
    """Return {phrase_normalized → canonical_synonym_phrase} for *lang*.

    Only the first synonym link is followed per phrase (arbitrarily picks phrase_a
    as the canonical form when two entries are linked).
    """
    rows = conn.execute(
        """
        SELECT la.phrase_normalized, lb.phrase
        FROM mwe_conflict c
        JOIN mwe_lang la ON la.mwe_id = c.mwe_id_b AND la.lang = ?
        JOIN mwe_lang lb ON lb.mwe_id = c.mwe_id_a AND lb.lang = ?
        WHERE c.conflict_type = 'synonym'
        """,
        (lang, lang),
    ).fetchall()
    return {row[0]: row[1] for row in rows}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Link two domain MWE phrases as synonyms."
    )
    parser.add_argument("--db", required=True, type=Path, help="Domain DB path")
    parser.add_argument("--phrase-a", dest="phrase_a", default=None)
    parser.add_argument("--phrase-b", dest="phrase_b", default=None)
    parser.add_argument("--lang", default=None, help="Language code (e.g. lt)")
    parser.add_argument("--reason", default="", help="Human-readable explanation")
    parser.add_argument("--list", dest="list_mode", action="store_true",
                        help="List all existing synonym pairs")
    args = parser.parse_args(argv)

    if not args.db.exists():
        print(f"Error: DB not found: {args.db}", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(args.db)
    conn.execute("PRAGMA foreign_keys = ON")

    if args.list_mode:
        synonyms = load_synonyms(conn)
        if not synonyms:
            print("No synonym pairs found.")
        else:
            print(f"{len(synonyms)} synonym pair(s):")
            for s in synonyms:
                print(f"  [{s['conflict_id']}] ({s['lang']}) {s['phrase_a']!r} ≡ {s['phrase_b']!r}")
                if s["reason"]:
                    print(f"       reason: {s['reason']}")
        conn.close()
        return

    for flag, val in [("--phrase-a", args.phrase_a), ("--phrase-b", args.phrase_b), ("--lang", args.lang)]:
        if val is None:
            parser.error(f"{flag} is required when not using --list")

    try:
        mwe_id_a, mwe_id_b = link_synonyms(conn, args.phrase_a, args.phrase_b, args.lang, args.reason)
        print(f"Synonym link created: mwe_id={mwe_id_a} ≡ mwe_id={mwe_id_b}")
        print(f"  A: {args.phrase_a!r}")
        print(f"  B: {args.phrase_b!r}")
        if args.reason:
            print(f"  Reason: {args.reason}")
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
