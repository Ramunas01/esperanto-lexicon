"""Migrate lexicon.db (v1) to lexicon_v2.db (v2 schema).

v1 schema: single flat 'vocabulary' table (English-primary) +
           'inflected_forms' + 'dolch_only'

v2 schema (Esperanto-primary):
  concept        — one row per unique Esperanto word (or pending placeholder)
  concept_lang   — one row per language per concept (lang='en' for now)
  inflected_forms — one row per inflected form (adds lang='en' column)

The original lexicon.db is never modified.
Enrichment candidates from enrichment_candidates.jsonl are applied when the
file exists and individual records have "approved": true.

Usage:
    python migrate_v1_to_v2.py [--v1 PATH] [--v2 PATH] [--enrich PATH]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Optional

_REPO = Path(__file__).parents[2]
DEFAULT_V1 = _REPO / "data" / "lexicon_db" / "lexicon.db"
DEFAULT_V2 = _REPO / "data" / "lexicon_db" / "lexicon_v2.db"
DEFAULT_ENRICH = _REPO / "data" / "lexicon_db" / "enrichment_candidates.jsonl"


# ---------------------------------------------------------------------------
# Schema DDL
# ---------------------------------------------------------------------------

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE concept (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    eo_root             TEXT,
    eo_word             TEXT,
    eo_pos              TEXT,
    eo_prefix           TEXT,
    eo_suffix           TEXT,
    eo_status           TEXT NOT NULL CHECK (eo_status IN ('complete', 'pending')),
    wordnet_synset      TEXT,
    wordnet_definition  TEXT,
    hypernym_chain      TEXT,   -- JSON array stored as text
    immediate_hypernym  TEXT
);

CREATE INDEX idx_concept_eo_word ON concept (eo_word);
CREATE INDEX idx_concept_eo_root ON concept (eo_root);
CREATE INDEX idx_concept_eo_status ON concept (eo_status);

CREATE TABLE concept_lang (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    concept_id  INTEGER NOT NULL REFERENCES concept (id),
    lang        TEXT NOT NULL,
    word        TEXT NOT NULL,
    pos         TEXT NOT NULL,
    cefr_level  TEXT,
    tier        INTEGER,
    source      TEXT,
    UNIQUE (concept_id, lang, word, pos)
);

CREATE INDEX idx_concept_lang_word ON concept_lang (lang, word);

CREATE TABLE inflected_forms (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    inflected_word   TEXT NOT NULL,
    lemma            TEXT NOT NULL,
    lang             TEXT NOT NULL DEFAULT 'en',
    form_description TEXT,
    tier             INTEGER,
    UNIQUE (inflected_word, lemma, lang)
);

CREATE INDEX idx_inflected_word ON inflected_forms (lang, inflected_word);
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_enrichments(path: Path) -> dict[int, dict]:
    """Return approved enrichment records keyed by v1 vocabulary id."""
    if not path.exists():
        return {}
    approved: dict[int, dict] = {}
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if rec.get("approved") and rec.get("eo_word"):
                approved[rec["v1_id"]] = rec
    return approved


def _read_v1_vocabulary(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, word, pos, cefr_level, tier, source,
               esperanto_word, esperanto_root, esperanto_deep_root,
               esperanto_ending, esperanto_pos, esperanto_prefix, esperanto_suffix,
               wordnet_synset, wordnet_definition, hypernym_chain, immediate_hypernym
        FROM vocabulary
        ORDER BY id
        """
    )
    return cur.fetchall()


def _read_v1_inflected(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    cur = conn.cursor()
    cur.execute("SELECT inflected_word, lemma, form_description, tier FROM inflected_forms")
    return cur.fetchall()


def _read_v1_dolch_only(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    cur = conn.cursor()
    cur.execute("SELECT word, note FROM dolch_only")
    return cur.fetchall()


# ---------------------------------------------------------------------------
# Core migration
# ---------------------------------------------------------------------------


def migrate(
    v1_path: Path = DEFAULT_V1,
    v2_path: Path = DEFAULT_V2,
    enrich_path: Path = DEFAULT_ENRICH,
) -> dict[str, int]:
    """Run the migration and return summary counts."""
    if v2_path.exists():
        v2_path.unlink()

    enrichments = _load_enrichments(enrich_path)

    v1_conn = sqlite3.connect(v1_path)
    v1_conn.row_factory = sqlite3.Row
    vocabulary = _read_v1_vocabulary(v1_conn)
    inflected = _read_v1_inflected(v1_conn)
    dolch_only = _read_v1_dolch_only(v1_conn)
    v1_conn.close()

    v2_conn = sqlite3.connect(v2_path)
    v2_conn.executescript(SCHEMA_SQL)

    stats = {
        "concept_complete": 0,
        "concept_pending": 0,
        "concept_lang_rows": 0,
        "inflected_rows": 0,
        "enrichments_applied": 0,
    }

    # concept dedup: eo_word -> concept_id (for rows that have Esperanto data).
    # Rows without data each get their own concept (keyed by v1 id as sentinel).
    eo_word_to_id: dict[str, int] = {}

    for row in vocabulary:
        v1_id = row["id"]
        eo_word = row["esperanto_word"]
        eo_root = row["esperanto_root"]
        eo_pos = row["esperanto_pos"]
        eo_prefix = row["esperanto_prefix"]
        eo_suffix = row["esperanto_suffix"]
        wordnet_synset = row["wordnet_synset"]
        wordnet_definition = row["wordnet_definition"]
        hypernym_chain = row["hypernym_chain"]
        immediate_hypernym = row["immediate_hypernym"]

        # Apply approved enrichment if available
        if eo_word is None and v1_id in enrichments:
            enrich = enrichments[v1_id]
            eo_word = enrich.get("eo_word")
            eo_root = enrich.get("eo_root")
            eo_pos = enrich.get("eo_pos")
            eo_prefix = enrich.get("eo_prefix") or ""
            eo_suffix = enrich.get("eo_suffix") or ""
            stats["enrichments_applied"] += 1

        eo_status = "complete" if eo_word else "pending"

        # Find or create concept
        concept_id: Optional[int] = None
        if eo_word:
            concept_id = eo_word_to_id.get(eo_word)

        if concept_id is None:
            cur = v2_conn.execute(
                """
                INSERT INTO concept
                    (eo_root, eo_word, eo_pos, eo_prefix, eo_suffix, eo_status,
                     wordnet_synset, wordnet_definition, hypernym_chain, immediate_hypernym)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    eo_root,
                    eo_word,
                    eo_pos,
                    eo_prefix or "",
                    eo_suffix or "",
                    eo_status,
                    wordnet_synset,
                    wordnet_definition,
                    hypernym_chain,
                    immediate_hypernym,
                ),
            )
            concept_id = cur.lastrowid
            if eo_word:
                eo_word_to_id[eo_word] = concept_id

            if eo_status == "complete":
                stats["concept_complete"] += 1
            else:
                stats["concept_pending"] += 1

        # Insert concept_lang row (English)
        v2_conn.execute(
            """
            INSERT OR IGNORE INTO concept_lang
                (concept_id, lang, word, pos, cefr_level, tier, source)
            VALUES (?, 'en', ?, ?, ?, ?, ?)
            """,
            (
                concept_id,
                row["word"],
                row["pos"],
                row["cefr_level"],
                row["tier"],
                row["source"],
            ),
        )
        stats["concept_lang_rows"] += 1

    # Migrate inflected_forms (add lang='en')
    seen_inflected: set[tuple[str, str]] = set()
    for row in inflected:
        key = (row["inflected_word"], row["lemma"])
        if key in seen_inflected:
            continue
        seen_inflected.add(key)
        v2_conn.execute(
            """
            INSERT OR IGNORE INTO inflected_forms
                (inflected_word, lemma, lang, form_description, tier)
            VALUES (?, ?, 'en', ?, ?)
            """,
            (row["inflected_word"], row["lemma"], row["form_description"], row["tier"]),
        )
        stats["inflected_rows"] += 1

    # Absorb dolch_only: add any words not already in inflected_forms
    for row in dolch_only:
        word = row["word"]
        key = (word, word)  # self-referential lemma for bare Dolch entries
        if key in seen_inflected:
            continue
        seen_inflected.add(key)
        v2_conn.execute(
            """
            INSERT OR IGNORE INTO inflected_forms
                (inflected_word, lemma, lang, form_description, tier)
            VALUES (?, ?, 'en', ?, 1)
            """,
            (word, word, row["note"]),
        )
        stats["inflected_rows"] += 1

    v2_conn.commit()
    v2_conn.close()
    return stats


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Migrate lexicon.db v1 → v2")
    parser.add_argument("--v1", type=Path, default=DEFAULT_V1)
    parser.add_argument("--v2", type=Path, default=DEFAULT_V2)
    parser.add_argument("--enrich", type=Path, default=DEFAULT_ENRICH)
    return parser.parse_args()


def main() -> None:
    """CLI entry point."""
    args = _parse_args()
    print(f"Source : {args.v1}")
    print(f"Target : {args.v2}")
    print(f"Enrich : {args.enrich}")
    print()

    stats = migrate(args.v1, args.v2, args.enrich)

    total_concepts = stats["concept_complete"] + stats["concept_pending"]
    print(f"Migration complete")
    print(f"  concept rows      : {total_concepts}")
    print(f"    complete (eo)   : {stats['concept_complete']}")
    print(f"    pending (no eo) : {stats['concept_pending']}")
    print(f"  concept_lang rows : {stats['concept_lang_rows']}")
    print(f"  inflected_forms   : {stats['inflected_rows']}")
    if stats["enrichments_applied"]:
        print(f"  enrichments used  : {stats['enrichments_applied']}")


if __name__ == "__main__":
    main()
