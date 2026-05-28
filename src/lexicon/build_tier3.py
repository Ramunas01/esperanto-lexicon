#!/usr/bin/env python3
"""Insert reviewed Tier 3 phrases into the common lexicon DB.

Tier 3 covers generic adult-level multi-word expressions and formal connectors
that sit above Oxford 3000 (Tier 2) but are not domain-specific (Tier 4).
Candidates are reviewed by hand offline; this script commits the approved set
into ``lexicon_v2.db`` as new ``concept`` + ``concept_lang`` rows.

Each new entry is created with:
  * ``concept.eo_root``   = NULL          (Esperanto anchor not yet assigned)
  * ``concept.eo_status`` = 'pending'     (flag for later Esperanto enrichment)
  * ``concept_lang.tier`` = 3
  * ``concept_lang.cefr_level`` = 'C1'
  * ``concept_lang.source``     = 'tier3_manual'

Input TSV format (tab-separated, one phrase per line)::

    phrase<TAB>pos<TAB>notes

  - ``phrase`` : surface form (required)
  - ``pos``    : POS tag (optional; defaults to ``PHRASE``)
  - ``notes``  : reviewer notes (optional; not stored in the DB)

Blank lines and lines starting with ``#`` are ignored.

Usage::

    python3 src/lexicon/build_tier3.py \\
        --input data/tier3_candidates/tier3_approved.tsv \\
        --lexicon data/lexicon_db/lexicon_v2.db \\
        --lang en
"""

from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from pathlib import Path


DEFAULT_POS = "PHRASE"
TIER = 3
CEFR_LEVEL = "C1"
SOURCE = "tier3_manual"


# ---------------------------------------------------------------------------
# TSV parsing
# ---------------------------------------------------------------------------


def parse_tsv(path: Path) -> list[tuple[str, str, str]]:
    """Parse the reviewed phrase TSV into ``(phrase, pos, notes)`` tuples.

    Blank lines and ``#`` comment lines are skipped. Missing ``pos`` falls back
    to :data:`DEFAULT_POS`. Missing ``notes`` becomes the empty string.
    """
    rows: list[tuple[str, str, str]] = []
    with path.open(encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh, delimiter="\t", quoting=csv.QUOTE_NONE)
        for raw in reader:
            if not raw:
                continue
            phrase = raw[0].strip()
            if not phrase or phrase.startswith("#"):
                continue
            pos = (raw[1].strip() if len(raw) > 1 else "") or DEFAULT_POS
            notes = raw[2].strip() if len(raw) > 2 else ""
            rows.append((phrase, pos, notes))
    return rows


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def existing_words(conn: sqlite3.Connection, lang: str) -> set[str]:
    """Return lowercased ``word`` values already in ``concept_lang`` for *lang*."""
    return {
        row[0]
        for row in conn.execute(
            "SELECT LOWER(word) FROM concept_lang WHERE lang = ?", (lang,)
        )
    }


def insert_tier3_phrase(
    conn: sqlite3.Connection, lang: str, phrase: str, pos: str
) -> int:
    """Insert a new ``concept`` + ``concept_lang`` pair. Return the new concept id."""
    cur = conn.execute(
        "INSERT INTO concept (eo_root, eo_status) VALUES (NULL, 'pending')"
    )
    concept_id = cur.lastrowid
    conn.execute(
        """
        INSERT INTO concept_lang
            (concept_id, lang, word, pos, cefr_level, tier, source)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (concept_id, lang, phrase, pos, CEFR_LEVEL, TIER, SOURCE),
    )
    return concept_id


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------


def run(input_path: Path, lexicon_db: Path, lang: str) -> tuple[int, int]:
    """Insert Tier 3 phrases from *input_path* into *lexicon_db*.

    Returns ``(inserted, skipped)``. Existing-phrase detection is
    case-insensitive against ``concept_lang.word`` for *lang*; duplicates
    within the input TSV are also collapsed.
    """
    if not input_path.exists():
        print(f"Error: input TSV not found: {input_path}", file=sys.stderr)
        sys.exit(1)
    if not lexicon_db.exists():
        print(f"Error: lexicon database not found: {lexicon_db}", file=sys.stderr)
        sys.exit(1)

    phrases = parse_tsv(input_path)
    if not phrases:
        print(f"No phrases found in {input_path}", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(lexicon_db)
    try:
        existing = existing_words(conn, lang)
        inserted = 0
        skipped = 0
        for phrase, pos, _notes in phrases:
            key = phrase.lower()
            if key in existing:
                skipped += 1
                continue
            insert_tier3_phrase(conn, lang, phrase, pos)
            existing.add(key)
            inserted += 1
        conn.commit()
    finally:
        conn.close()

    return inserted, skipped


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Insert reviewed Tier 3 phrases (one per line, TSV) into "
            "lexicon_v2.db. Each phrase becomes a new concept "
            "(eo_status='pending') plus a concept_lang row at tier=3, "
            "cefr_level='C1', source='tier3_manual'."
        )
    )
    parser.add_argument(
        "--input", required=True, type=Path,
        help="Path to reviewed phrase TSV (phrase[\\tpos[\\tnotes]])",
    )
    parser.add_argument(
        "--lexicon", required=True, type=Path,
        help="Path to lexicon_v2.db",
    )
    parser.add_argument(
        "--lang", required=True,
        help="Language code for the concept_lang rows (e.g. 'en', 'lt', 'fr')",
    )
    args = parser.parse_args(argv)

    inserted, skipped = run(args.input, args.lexicon, args.lang)
    print(f"Inserted: {inserted} new Tier 3 entries")
    print(f"Skipped:  {skipped} already present")


if __name__ == "__main__":
    main()
