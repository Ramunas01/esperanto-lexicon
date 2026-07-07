"""Tests for the read-only named-entity query helper.

No network, no real ``lexicon_v2.db``. Each test builds a temp SQLite DB on
``tmp_path`` via ``create_named_entity_schema`` and inserts representative rows
directly (the loader is deliberately NOT imported — these tests are disjoint).
"""

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "lexicon"))

from query_named_entities import resolve  # noqa: E402
from schema import create_named_entity_schema  # noqa: E402

ASOF = "2026-07-06"


def _insert_entity(
    conn: sqlite3.Connection,
    qid: str,
    label_eo,
    label_en,
    ne_type: str,
    sitelinks: int,
    global_core: int = 0,
    aliases: tuple = (),
) -> int:
    """Insert one entity plus its type and aliases; return its id."""
    cur = conn.execute(
        """
        INSERT INTO named_entity
            (qid, label_eo, label_en, sitelinks, sitelinks_asof,
             source, global_core, status)
        VALUES (?, ?, ?, ?, ?, 'wikidata', ?, 'active')
        """,
        (qid, label_eo, label_en, sitelinks, ASOF, global_core),
    )
    entity_id = cur.lastrowid
    conn.execute(
        """
        INSERT INTO named_entity_type (entity_id, ne_type, validation)
        VALUES (?, ?, 'correspondence')
        """,
        (entity_id, ne_type),
    )
    for alias, lang in aliases:
        conn.execute(
            """
            INSERT INTO named_entity_alias (entity_id, alias, lang)
            VALUES (?, ?, ?)
            """,
            (entity_id, alias, lang),
        )
    conn.commit()
    return entity_id


@pytest.fixture()
def conn(tmp_path):
    """A temp DB seeded with a representative slice of the permanent core."""
    db_path = tmp_path / "test_names.db"
    connection = sqlite3.connect(db_path)
    create_named_entity_schema(connection)

    # Q111 Mars — celestial, sitelinks 290.
    _insert_entity(connection, "Q111", "Marso", "Mars", "celestial", 290)
    # Q97 Atlantic Ocean — physical_geographic, global_core.
    _insert_entity(
        connection,
        "Q97",
        "Atlantiko",
        "Atlantic Ocean",
        "physical_geographic",
        269,
        global_core=1,
    )
    # Q513 Mount Everest — primary EO label Ĉomolungmo; Everesto is an eo alias.
    _insert_entity(
        connection,
        "Q513",
        "Ĉomolungmo",
        "Mount Everest",
        "physical_geographic",
        233,
        aliases=(("Everesto", "eo"), ("Mt Everest", "en")),
    )
    # Q3392 Nile — physical_geographic.
    _insert_entity(connection, "Q3392", "Nilo", "Nile", "physical_geographic", 241)
    # Synthetic EN-fallback row: no EO primary label, only an EN label + en alias.
    _insert_entity(
        connection,
        "Q999999",
        None,
        "Farville",
        "physical_geographic",
        12,
        aliases=(("Farrville", "en"),),
    )

    yield connection
    connection.close()


def test_resolve_by_qid(conn):
    hit = resolve(conn, "Q111")
    assert hit is not None
    assert hit.qid == "Q111"
    assert hit.match_field == "qid"


def test_resolve_by_label_eo(conn):
    hit = resolve(conn, "Marso")
    assert hit is not None
    assert hit.qid == "Q111"
    assert hit.match_field == "label_eo"


def test_resolve_by_label_en(conn):
    hit = resolve(conn, "Nile")
    assert hit is not None
    assert hit.qid == "Q3392"
    assert hit.match_field == "label_en"


def test_resolve_by_eo_alias(conn):
    # Everesto is NOT a primary label (Ĉomolungmo is) — alias lookup required.
    hit = resolve(conn, "Everesto")
    assert hit is not None
    assert hit.qid == "Q513"
    assert hit.match_field == "alias:eo"
    assert hit.label_eo == "Ĉomolungmo"


def test_eo_alias_preferred_over_en_alias(tmp_path):
    # Same surface string is both an eo and an en alias on the same entity —
    # the eo alias must win the match_field.
    db_path = tmp_path / "pref.db"
    c = sqlite3.connect(db_path)
    create_named_entity_schema(c)
    _insert_entity(
        c,
        "Q7000",
        "Ekzemplo",
        "Example",
        "physical_geographic",
        5,
        aliases=(("Kolizio", "en"), ("Kolizio", "eo")),
    )
    hit = resolve(c, "Kolizio")
    assert hit is not None
    assert hit.qid == "Q7000"
    assert hit.match_field == "alias:eo"
    c.close()


def test_case_insensitive_fallback(conn):
    hit = resolve(conn, "marso")
    assert hit is not None
    assert hit.qid == "Q111"
    assert hit.match_field == "label_eo:ci"


def test_exact_preferred_over_case_insensitive(conn):
    # Exact EO label must win before any case-insensitive pass runs.
    hit = resolve(conn, "Marso")
    assert hit.match_field == "label_eo"


def test_hit_carries_types_validation_salience_global_core(conn):
    hit = resolve(conn, "Atlantiko")
    assert hit is not None
    assert hit.types == [("physical_geographic", "correspondence")]
    assert hit.sitelinks == 269
    assert hit.sitelinks_asof == ASOF
    assert hit.global_core == 1
    assert hit.source == "wikidata"
    assert hit.status == "active"


def test_hit_carries_aliases(conn):
    hit = resolve(conn, "Q513")
    assert ("Everesto", "eo") in hit.aliases
    assert ("Mt Everest", "en") in hit.aliases


def test_en_fallback_row_resolves_by_en_label(conn):
    hit = resolve(conn, "Farville")
    assert hit is not None
    assert hit.qid == "Q999999"
    assert hit.label_eo is None
    assert hit.match_field == "label_en"


def test_en_fallback_row_resolves_by_en_alias(conn):
    hit = resolve(conn, "Farrville")
    assert hit is not None
    assert hit.qid == "Q999999"
    assert hit.match_field == "alias:en"


def test_unknown_term_returns_none(conn):
    assert resolve(conn, "Nenieblo") is None


def test_empty_term_returns_none(conn):
    assert resolve(conn, "") is None
    assert resolve(conn, "   ") is None
