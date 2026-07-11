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
            tier             INTEGER,
            UNIQUE (inflected_word, lemma, lang)
        );

        -- Ordered set of content roots making up each concept's eo_word.
        -- A simple word produces one row (is_head=1); a compound produces
        -- one row per content root with is_head=1 only on the final root
        -- (Esperanto's semantic head). Maintained by eo_root_decomposer.py.
        CREATE TABLE IF NOT EXISTS concept_root (
            concept_id INTEGER NOT NULL REFERENCES concept(id),
            root       TEXT    NOT NULL,
            position   INTEGER NOT NULL,
            is_head    INTEGER NOT NULL DEFAULT 0,
            tier       TEXT,
            PRIMARY KEY (concept_id, position)
        );

        CREATE INDEX IF NOT EXISTS idx_concept_root_root
            ON concept_root(root);
        """
    )
    conn.commit()


def create_named_entity_schema(conn: sqlite3.Connection) -> None:
    """Create the named-entity inventory tables (v0: physically-permanent core).

    A sibling table set co-located in ``lexicon_v2.db`` for free resolver joins,
    but **strictly separate** from ``concept`` / ``concept_root`` / ``concept_lang``
    — this function never touches those. Populated by
    ``src/lexicon/load_named_entities.py`` from the D7 Wikidata sample.

    Design rule (roadmap **R8**) — enforced here by omission: these entities do
    **NOT** carry a stored ``tier``. Their tier is *derived later* against a
    reference group, so the inventory records only sourced ``sitelinks`` salience
    (dated via ``sitelinks_asof``). **Do not add a ``tier`` column to any of these
    tables.** ``global_core`` is a group-*invariance* flag (truly reference-group-
    independent entities: the Moon, oceans, continents) — it is NOT a tier and
    carries no numeric level; it merely marks the entities a future tier-derivation
    step will promote wholesale into the common set.
    """
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS named_entity (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            qid            TEXT NOT NULL UNIQUE,   -- Wikidata QID (CC0 provenance)
            label_eo       TEXT,                   -- primary EO label (NULL for ~0.4%)
            label_en       TEXT,                   -- EN label / documented fallback
            sitelinks      INTEGER,                -- salience datum (sourced, not derived)
            sitelinks_asof TEXT,                   -- ISO date the salience was captured
            source         TEXT DEFAULT 'wikidata',
            global_core    INTEGER NOT NULL DEFAULT 0,  -- group-invariance flag (NOT a tier)
            status         TEXT DEFAULT 'active'
            -- NO tier column, by design (R8). Do not add one.
        );

        -- Junction: an entity may hold >1 coarse type (rare in this physical
        -- subset). validation = R6 regime; 'correspondence' for every row here
        -- because all entities in the permanent-physical set have physical referents.
        CREATE TABLE IF NOT EXISTS named_entity_type (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_id  INTEGER NOT NULL REFERENCES named_entity(id) ON DELETE CASCADE,
            ne_type    TEXT NOT NULL,   -- 'celestial' | 'physical_geographic'
            validation TEXT NOT NULL,   -- R6 regime; 'correspondence' here
            UNIQUE(entity_id, ne_type)
        );

        -- EO aliases where present (thin), plus the EN label carried as a
        -- fallback alias for the handful of rows with no EO primary label.
        CREATE TABLE IF NOT EXISTS named_entity_alias (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_id  INTEGER NOT NULL REFERENCES named_entity(id) ON DELETE CASCADE,
            alias      TEXT NOT NULL,
            lang       TEXT NOT NULL,   -- 'eo' | 'en'
            UNIQUE(entity_id, alias, lang)
        );

        CREATE INDEX IF NOT EXISTS idx_named_entity_label_eo
            ON named_entity(label_eo);
        CREATE INDEX IF NOT EXISTS idx_named_entity_label_en
            ON named_entity(label_en);
        CREATE INDEX IF NOT EXISTS idx_named_entity_type_entity
            ON named_entity_type(entity_id);
        CREATE INDEX IF NOT EXISTS idx_named_entity_alias_entity
            ON named_entity_alias(entity_id);
        CREATE INDEX IF NOT EXISTS idx_named_entity_alias_alias
            ON named_entity_alias(alias);
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
            authority           TEXT,
            area_signature      TEXT
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

        -- Per-area attestation: evidence of which canonical customs area(s) a
        -- term appears in, and how strongly. One row per (mwe, area, source_file).
        -- Cross-cutting/overlay corpora share the single 'cross_cutting' area tag;
        -- source_file preserves which specific mining file the row came from.
        -- Raw doc_count + frequency are stored; weights/signatures are derived at
        -- query/display time, never baked into the schema.
        CREATE TABLE IF NOT EXISTS mwe_area_attestation (
            id          INTEGER PRIMARY KEY,
            mwe_id      INTEGER NOT NULL,
            area        TEXT    NOT NULL,    -- canonical area name OR 'cross_cutting'
            doc_count   INTEGER NOT NULL,    -- documents in that area where the term appeared
            frequency   INTEGER NOT NULL,    -- total occurrences in that area's corpus
            source_file TEXT,                -- filename of the mining corpus that produced this row
            mined_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (mwe_id) REFERENCES mwe(id) ON DELETE CASCADE,
            UNIQUE (mwe_id, area, source_file)
        );

        CREATE INDEX IF NOT EXISTS idx_mwe_lang_phrase
            ON mwe_lang(phrase_normalized, lang);

        CREATE INDEX IF NOT EXISTS idx_mwe_area_attestation_term
            ON mwe_area_attestation(mwe_id);

        CREATE INDEX IF NOT EXISTS idx_mwe_area_attestation_area
            ON mwe_area_attestation(area);

        CREATE INDEX IF NOT EXISTS idx_mwe_occurrence_mwe_id
            ON mwe_occurrence(mwe_id);

        CREATE INDEX IF NOT EXISTS idx_mwe_conflict_a
            ON mwe_conflict(mwe_id_a);

        CREATE INDEX IF NOT EXISTS idx_mwe_conflict_b
            ON mwe_conflict(mwe_id_b);
        """
    )
    conn.commit()
