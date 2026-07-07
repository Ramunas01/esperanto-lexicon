"""Tests for the named-entity inventory loader (load_named_entities.py)."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "lexicon"))

from schema import create_named_entity_schema  # noqa: E402
from load_named_entities import (  # noqa: E402
    GLOBAL_CORE_QIDS,
    JUNK_QID,
    _parse_aliases,
    _upsert_rows,
    load_rows,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

TSV_HEADER = "qid\tlabel_en\tlabel_eo\tcoarse_type\tsitelinks\taliases"

# Kept rows (permanent types) + rows that must be filtered out.
TSV_ROWS = [
    # celestial, global_core (Moon)
    "Q405\tMoon\tLuno\tcelestial\t300\ten:Luna;eo:la Luno",
    # celestial, not global_core
    "Q111\tMars\tMarso\tcelestial\t290\ten:Red Planet;eo:ruĝa planedo",
    # physical_geographic, global_core (Atlantic Ocean)
    "Q97\tAtlantic Ocean\tAtlantiko\tphysical_geographic\t200\ten:The Atlantic",
    # physical_geographic, not global_core
    "Q513\tMount Everest\tEveresto\tphysical_geographic\t180\teo:Ĉomolungmo",
    # physical_geographic, EMPTY label_eo → EN fallback alias + NULL label_eo
    "Q9999\tNoname Ridge\t\tphysical_geographic\t5\ten:The Ridge",
    # institutional — must be filtered out
    "Q458\tEuropean Union\tEŭropa Unio\tinstitutional\t400\ten:EU",
    # settlement — must be filtered out
    "Q1731\tCardiff\t\tsettlement\t120\ten:Caerdydd",
    # the known junk row: institutional mis-typed sovereign state — filtered out
    f"{JUNK_QID}\tTschardakenhof\t\tinstitutional\t2\t",
]


def _write_tsv(tmp_path: Path) -> Path:
    p = tmp_path / "gaz.tsv"
    p.write_text("\n".join([TSV_HEADER, *TSV_ROWS]) + "\n", encoding="utf-8")
    return p


def _fresh_db(tmp_path: Path) -> Path:
    db = tmp_path / "lex.db"
    conn = sqlite3.connect(db)
    create_named_entity_schema(conn)
    conn.close()
    return db


def _load(db: Path, rows: list[dict], asof: str = "2026-07-06") -> dict:
    """Run the upsert against *db* inside a committed transaction."""
    conn = sqlite3.connect(db)
    try:
        conn.execute("BEGIN")
        stats = _upsert_rows(conn, rows, asof)
        conn.commit()
    finally:
        conn.close()
    return stats


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------


def test_type_filter_keeps_only_permanent(tmp_path):
    rows = load_rows(_write_tsv(tmp_path))
    types = {r["coarse_type"] for r in rows}
    assert types == {"celestial", "physical_geographic"}
    qids = {r["qid"] for r in rows}
    assert JUNK_QID not in qids  # Tschardakenhof excluded
    assert "Q458" not in qids  # institutional excluded
    assert "Q1731" not in qids  # settlement excluded


def test_duplicate_qid_rows_collapse(tmp_path):
    # append an exact duplicate of the Mars row; load_rows keeps first only
    p = tmp_path / "gaz.tsv"
    p.write_text(
        "\n".join([TSV_HEADER, *TSV_ROWS, TSV_ROWS[1]]) + "\n", encoding="utf-8"
    )
    rows = load_rows(p)
    assert [r["qid"] for r in rows].count("Q111") == 1
    assert len(rows) == 5


def test_counts_by_type(tmp_path):
    rows = load_rows(_write_tsv(tmp_path))
    by_type: dict[str, int] = {}
    for r in rows:
        by_type[r["coarse_type"]] = by_type.get(r["coarse_type"], 0) + 1
    assert by_type == {"celestial": 2, "physical_geographic": 3}
    assert len(rows) == 5


# ---------------------------------------------------------------------------
# validation regime + no tier column
# ---------------------------------------------------------------------------


def test_validation_is_correspondence_on_every_type_row(tmp_path):
    db = _fresh_db(tmp_path)
    _load(db, load_rows(_write_tsv(tmp_path)))
    conn = sqlite3.connect(db)
    regimes = [r[0] for r in conn.execute("SELECT validation FROM named_entity_type")]
    conn.close()
    assert regimes and all(v == "correspondence" for v in regimes)


def test_no_tier_column_anywhere(tmp_path):
    db = _fresh_db(tmp_path)
    _load(db, load_rows(_write_tsv(tmp_path)))
    conn = sqlite3.connect(db)
    for table in ("named_entity", "named_entity_type", "named_entity_alias"):
        cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        assert "tier" not in cols, f"{table} unexpectedly has a tier column"
    conn.close()


# ---------------------------------------------------------------------------
# global_core allowlist
# ---------------------------------------------------------------------------


def test_global_core_flagged_for_allowlist_only(tmp_path):
    db = _fresh_db(tmp_path)
    _load(db, load_rows(_write_tsv(tmp_path)))
    conn = sqlite3.connect(db)
    flagged = {
        r[0] for r in conn.execute("SELECT qid FROM named_entity WHERE global_core = 1")
    }
    zero = {
        r[0] for r in conn.execute("SELECT qid FROM named_entity WHERE global_core = 0")
    }
    conn.close()
    assert flagged == {"Q405", "Q97"}  # Moon + Atlantic, both in the allowlist
    assert flagged <= GLOBAL_CORE_QIDS
    assert "Q111" in zero and "Q513" in zero  # Mars, Everest not group-invariant


# ---------------------------------------------------------------------------
# Aliases
# ---------------------------------------------------------------------------


def test_parse_aliases_splits_lang_and_first_colon():
    pairs = _parse_aliases("en:Red Planet;eo:ruĝa planedo")
    assert pairs == [("en", "Red Planet"), ("eo", "ruĝa planedo")]
    # first-colon split preserves colons in the alias text
    assert _parse_aliases("en:Sol b: I") == [("en", "Sol b: I")]
    assert _parse_aliases("") == []
    assert _parse_aliases("no-lang-tag") == []


def test_aliases_land_with_correct_lang(tmp_path):
    db = _fresh_db(tmp_path)
    _load(db, load_rows(_write_tsv(tmp_path)))
    conn = sqlite3.connect(db)
    mars_id = conn.execute(
        "SELECT id FROM named_entity WHERE qid = 'Q111'"
    ).fetchone()[0]
    aliases = {
        (r[0], r[1])
        for r in conn.execute(
            "SELECT alias, lang FROM named_entity_alias WHERE entity_id = ?", (mars_id,)
        )
    }
    conn.close()
    assert ("Red Planet", "en") in aliases
    assert ("ruĝa planedo", "eo") in aliases


def test_empty_eo_label_gets_en_fallback_alias(tmp_path):
    db = _fresh_db(tmp_path)
    _load(db, load_rows(_write_tsv(tmp_path)))
    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT id, label_eo FROM named_entity WHERE qid = 'Q9999'"
    ).fetchone()
    entity_id, label_eo = row
    assert label_eo is None  # empty EO label stored as NULL
    aliases = {
        (r[0], r[1])
        for r in conn.execute(
            "SELECT alias, lang FROM named_entity_alias WHERE entity_id = ?",
            (entity_id,),
        )
    }
    conn.close()
    assert ("Noname Ridge", "en") in aliases  # EN label carried as fallback


def test_empty_eo_label_stored_as_null(tmp_path):
    db = _fresh_db(tmp_path)
    _load(db, load_rows(_write_tsv(tmp_path)))
    conn = sqlite3.connect(db)
    label_eo = conn.execute(
        "SELECT label_eo FROM named_entity WHERE qid = 'Q9999'"
    ).fetchone()[0]
    # a present EO label is stored intact
    marso = conn.execute(
        "SELECT label_eo FROM named_entity WHERE qid = 'Q111'"
    ).fetchone()[0]
    conn.close()
    assert label_eo is None
    assert marso == "Marso"


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


def test_rerun_is_idempotent_no_duplicates(tmp_path):
    db = _fresh_db(tmp_path)
    rows = load_rows(_write_tsv(tmp_path))
    _load(db, rows)
    counts_1 = _table_counts(db)
    _load(db, rows)  # second run
    counts_2 = _table_counts(db)
    assert counts_1 == counts_2


def test_rerun_updates_sitelinks_in_place(tmp_path):
    db = _fresh_db(tmp_path)
    rows = load_rows(_write_tsv(tmp_path))
    _load(db, rows)
    before = _table_counts(db)

    # bump Mars salience and reload with a new asof date
    for r in rows:
        if r["qid"] == "Q111":
            r["sitelinks"] = 555
    _load(db, rows, asof="2027-01-01")

    conn = sqlite3.connect(db)
    sitelinks, asof = conn.execute(
        "SELECT sitelinks, sitelinks_asof FROM named_entity WHERE qid = 'Q111'"
    ).fetchone()
    conn.close()
    assert sitelinks == 555  # updated in place
    assert asof == "2027-01-01"
    assert _table_counts(db) == before  # no new rows


def _table_counts(db: Path) -> dict:
    conn = sqlite3.connect(db)
    try:
        return {
            t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in ("named_entity", "named_entity_type", "named_entity_alias")
        }
    finally:
        conn.close()
