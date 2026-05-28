"""Single source of truth for all SQLite schemas used by the lexicon system."""

from __future__ import annotations

import sqlite3


def create_common_lexicon_schema(conn: sqlite3.Connection) -> None:
    """Create v2 common lexicon tables: concept, concept_lang, inflected_forms."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS concept (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            eo_root             TEXT,
            eo_word             TEXT,
            eo_pos              TEXT,
            eo_prefix           TEXT,
            eo_suffix           TEXT,
            eo_status           TEXT DEFAULT 'pending',
            wordnet_synset      TEXT,
            wordnet_definition  TEXT,
            hypernym_chain      TEXT,
            immediate_hypernym  TEXT
        );

        CREATE TABLE IF NOT EXISTS concept_lang (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            concept_id  INTEGER NOT NULL REFERENCES concept(id),
            lang        TEXT NOT NULL,
            word        TEXT NOT NULL,
            pos         TEXT,
            cefr_level  TEXT,
            tier        INTEGER,
            source      TEXT
        );

        CREATE TABLE IF NOT EXISTS inflected_forms (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            inflected_word   TEXT NOT NULL,
            lemma            TEXT NOT NULL,
            lang             TEXT NOT NULL,
            form_description TEXT,
            tier             INTEGER
        );
        """
    )
    conn.commit()


def create_domain_schema(conn: sqlite3.Connection) -> None:
    """Create domain lexicon tables and indexes for a per-domain SQLite database."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS mwe (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            eo_canonical        TEXT,
            eo_status           TEXT DEFAULT 'pending',
            scope               TEXT NOT NULL,
            status              TEXT NOT NULL,
            first_seen_source   TEXT,
            first_seen_date     TEXT,
            current_tier        INTEGER DEFAULT 4,
            domain              TEXT,
            jurisdiction        TEXT,
            promotable          INTEGER DEFAULT 0,
            source_type         TEXT,
            definition_status   TEXT,
            attestation_count   INTEGER DEFAULT 1,
            authority           TEXT
        );

        CREATE TABLE IF NOT EXISTS mwe_lang (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            mwe_id              INTEGER NOT NULL REFERENCES mwe(id),
            lang                TEXT NOT NULL,
            phrase              TEXT NOT NULL,
            phrase_normalized   TEXT NOT NULL,
            phrase_base         TEXT,
            definition_raw      TEXT,
            pos_pattern         TEXT,
            abbrev              TEXT,
            UNIQUE(mwe_id, lang)
        );

        CREATE TABLE IF NOT EXISTS mwe_occurrence (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            mwe_id          INTEGER NOT NULL REFERENCES mwe(id),
            source_doc      TEXT NOT NULL,
            source_lang     TEXT NOT NULL,
            clause_ref      TEXT,
            date_extracted  TEXT,
            context_snippet TEXT
        );

        -- conflict_type valid values: 'text_divergence', 'context_divergence', 'synonym'
        --   text_divergence:    same phrase, different definitions across documents
        --   context_divergence: same phrase, same definition, different usage context
        --   synonym:            different phrases expressing the same concept
        CREATE TABLE IF NOT EXISTS mwe_conflict (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            mwe_id_a            INTEGER NOT NULL REFERENCES mwe(id),
            mwe_id_b            INTEGER NOT NULL REFERENCES mwe(id),
            conflict_type       TEXT NOT NULL,
            divergence_detail   TEXT,
            resolution_status   TEXT DEFAULT 'open',
            resolution_notes    TEXT,
            detected_date       TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_mwe_lang_phrase
            ON mwe_lang(phrase_normalized, lang);

        CREATE INDEX IF NOT EXISTS idx_mwe_occurrence_mwe_id
            ON mwe_occurrence(mwe_id);

        CREATE INDEX IF NOT EXISTS idx_mwe_conflict_a
            ON mwe_conflict(mwe_id_a);

        CREATE INDEX IF NOT EXISTS idx_mwe_conflict_b
            ON mwe_conflict(mwe_id_b);
        """
    )
    conn.commit()
