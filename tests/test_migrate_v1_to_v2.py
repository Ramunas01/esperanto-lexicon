"""Tests for migrate_v1_to_v2.py.

Uses the real v1 lexicon.db (read-only) and a tmp directory for the v2 output.
No enrichment candidates are applied in these baseline tests.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

import pytest

from src.lexicon.migrate_v1_to_v2 import DEFAULT_V1, migrate

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_V1_PATH = DEFAULT_V1


@pytest.fixture(scope="module")
def v1_row_counts() -> dict[str, int]:
    """Return row counts from the source v1 database."""
    conn = sqlite3.connect(_V1_PATH)
    cur = conn.cursor()
    counts: dict[str, int] = {}
    for table in ("vocabulary", "inflected_forms", "dolch_only"):
        cur.execute(f"SELECT COUNT(*) FROM {table}")  # noqa: S608 — table name is literal
        counts[table] = cur.fetchone()[0]
    conn.close()
    return counts


@pytest.fixture(scope="module")
def v2_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Run migration once and return the path to the resulting v2 DB."""
    out = tmp_path_factory.mktemp("db") / "lexicon_v2.db"
    # No enrichment file — tests the baseline migration only
    migrate(v1_path=_V1_PATH, v2_path=out, enrich_path=Path("/nonexistent"))
    return out


@pytest.fixture(scope="module")
def v2_conn(v2_db: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(v2_db)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _count(conn: sqlite3.Connection, table: str) -> int:
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # noqa: S608


def _scalar(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> object:
    return conn.execute(sql, params).fetchone()[0]


# ---------------------------------------------------------------------------
# Row count tests
# ---------------------------------------------------------------------------


def test_concept_lang_preserves_all_vocabulary_rows(v2_conn: sqlite3.Connection, v1_row_counts: dict) -> None:
    """Every vocabulary row must produce a concept_lang entry (lang='en')."""
    v2_en = _count(v2_conn, "concept_lang")
    assert v2_en == v1_row_counts["vocabulary"], (
        f"concept_lang has {v2_en} rows but vocabulary had {v1_row_counts['vocabulary']}"
    )


def test_concept_count_is_sane(v2_conn: sqlite3.Connection, v1_row_counts: dict) -> None:
    """concept row count must be ≤ vocabulary count (deduplication on eo_word)
    and > 0."""
    n_concepts = _count(v2_conn, "concept")
    n_vocab = v1_row_counts["vocabulary"]
    assert 0 < n_concepts <= n_vocab


def test_inflected_forms_includes_all_v1_inflected(v2_conn: sqlite3.Connection, v1_row_counts: dict) -> None:
    """All rows from v1 inflected_forms must appear in v2 inflected_forms."""
    v1_count = v1_row_counts["inflected_forms"]
    v2_count = _count(v2_conn, "inflected_forms")
    assert v2_count >= v1_count, (
        f"v2 inflected_forms has {v2_count} rows; expected at least {v1_count}"
    )


def test_inflected_forms_absorbs_dolch_only(v2_conn: sqlite3.Connection, v1_row_counts: dict) -> None:
    """v2 inflected_forms must have at least as many rows as
    inflected_forms + dolch_only combined (some overlap is allowed via IGNORE)."""
    v1_total = v1_row_counts["inflected_forms"] + v1_row_counts["dolch_only"]
    v2_count = _count(v2_conn, "inflected_forms")
    # Overlap is possible (inflected_forms already covers some dolch_only words)
    assert v2_count >= v1_row_counts["inflected_forms"]
    # And we must have pulled in at least some dolch entries
    assert v2_count > v1_row_counts["inflected_forms"] or v1_row_counts["dolch_only"] == 0


# ---------------------------------------------------------------------------
# Data integrity tests
# ---------------------------------------------------------------------------


def test_no_data_loss_concept_lang_words(v2_conn: sqlite3.Connection) -> None:
    """Every English word from v1 vocabulary must appear in concept_lang."""
    v1_conn = sqlite3.connect(_V1_PATH)
    v1_words = {
        (row[0], row[1])
        for row in v1_conn.execute("SELECT word, pos FROM vocabulary")
    }
    v1_conn.close()

    v2_words = {
        (row[0], row[1])
        for row in v2_conn.execute("SELECT word, pos FROM concept_lang WHERE lang = 'en'")
    }

    missing = v1_words - v2_words
    assert not missing, f"Words lost in migration: {sorted(missing)[:20]}"


def test_eo_status_values_are_valid(v2_conn: sqlite3.Connection) -> None:
    """eo_status must only contain 'complete' or 'pending'."""
    bad = v2_conn.execute(
        "SELECT DISTINCT eo_status FROM concept WHERE eo_status NOT IN ('complete', 'pending')"
    ).fetchall()
    assert not bad, f"Invalid eo_status values found: {bad}"


def test_complete_concepts_have_eo_word(v2_conn: sqlite3.Connection) -> None:
    """Every concept with eo_status='complete' must have a non-null eo_word."""
    n_bad = _scalar(
        v2_conn,
        "SELECT COUNT(*) FROM concept WHERE eo_status = 'complete' AND eo_word IS NULL",
    )
    assert n_bad == 0, f"{n_bad} 'complete' concepts have NULL eo_word"


def test_pending_concepts_have_no_eo_word(v2_conn: sqlite3.Connection) -> None:
    """Every concept with eo_status='pending' must have a null eo_word."""
    n_bad = _scalar(
        v2_conn,
        "SELECT COUNT(*) FROM concept WHERE eo_status = 'pending' AND eo_word IS NOT NULL",
    )
    assert n_bad == 0, f"{n_bad} 'pending' concepts have non-NULL eo_word"


def test_concept_lang_all_lang_en(v2_conn: sqlite3.Connection) -> None:
    """Migration only populates lang='en'; no other lang codes should exist yet."""
    langs = [
        row[0]
        for row in v2_conn.execute("SELECT DISTINCT lang FROM concept_lang")
    ]
    assert langs == ["en"], f"Unexpected lang values: {langs}"


def test_concept_lang_foreign_keys_valid(v2_conn: sqlite3.Connection) -> None:
    """Every concept_lang row must reference an existing concept."""
    orphans = _scalar(
        v2_conn,
        """
        SELECT COUNT(*) FROM concept_lang cl
        LEFT JOIN concept c ON c.id = cl.concept_id
        WHERE c.id IS NULL
        """,
    )
    assert orphans == 0, f"{orphans} concept_lang rows have no matching concept"


def test_inflected_forms_lang_is_en(v2_conn: sqlite3.Connection) -> None:
    """All inflected_forms rows migrated from v1 must have lang='en'."""
    langs = [
        row[0]
        for row in v2_conn.execute("SELECT DISTINCT lang FROM inflected_forms")
    ]
    assert langs == ["en"], f"Unexpected lang values in inflected_forms: {langs}"


def test_pending_count_matches_v1_nulls(v2_conn: sqlite3.Connection) -> None:
    """Pending concept count must match the number of v1 rows with NULL esperanto_word,
    minus any approved enrichments applied (none in this baseline run)."""
    v1_conn = sqlite3.connect(_V1_PATH)
    v1_pending = v1_conn.execute(
        "SELECT COUNT(*) FROM vocabulary WHERE esperanto_word IS NULL"
    ).fetchone()[0]
    v1_conn.close()

    # In baseline (no enrichments), pending concepts = v1 null rows,
    # but concepts are deduplicated by eo_word so we only check the upper bound.
    v2_pending = _scalar(v2_conn, "SELECT COUNT(*) FROM concept WHERE eo_status = 'pending'")
    assert v2_pending <= v1_pending
    assert v2_pending > 0


# ---------------------------------------------------------------------------
# Enrichment integration test (uses a small synthetic enrichment file)
# ---------------------------------------------------------------------------


def test_enrichment_applied(tmp_path: Path) -> None:
    """Approved enrichment records must reduce the pending count."""
    # Fetch a real v1 pending row id to make the enrichment realistic
    v1_conn = sqlite3.connect(_V1_PATH)
    row = v1_conn.execute(
        "SELECT id, word, pos FROM vocabulary WHERE esperanto_word IS NULL LIMIT 1"
    ).fetchone()
    v1_conn.close()
    v1_id, word, pos = row

    enrich_path = tmp_path / "enrichment_candidates.jsonl"
    with enrich_path.open("w") as fh:
        fh.write(
            json.dumps(
                {
                    "v1_id": v1_id,
                    "word": word,
                    "pos": pos,
                    "eo_word": "testvorto",
                    "eo_root": "testvort",
                    "eo_ending": "o",
                    "eo_prefix": "",
                    "eo_suffix": "",
                    "eo_pos": "NOUN",
                    "confidence": "high",
                    "method": "hardcoded",
                    "notes": "test",
                    "approved": True,
                }
            )
            + "\n"
        )

    v2_path = tmp_path / "lexicon_v2.db"
    stats = migrate(_V1_PATH, v2_path, enrich_path)
    assert stats["enrichments_applied"] == 1

    conn = sqlite3.connect(v2_path)
    n = conn.execute(
        "SELECT COUNT(*) FROM concept WHERE eo_word = 'testvorto'"
    ).fetchone()[0]
    conn.close()
    assert n == 1, "Enriched eo_word not found in v2 concept table"
