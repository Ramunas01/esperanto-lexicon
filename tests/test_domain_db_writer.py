"""Tests for domain_db_writer and schema.py domain schema."""

from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from lexicon.schema import create_domain_schema
from extractor.domain_db_writer import _group_records, process_group, run


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fresh_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    create_domain_schema(conn)
    return conn


def _make_record(
    term: str,
    definition: str,
    lang: str = "lt",
    source: str = "GPMI-LT.txt",
    clause: str = "1",
    cross_lang_num: str | None = None,
) -> dict:
    """Return a pending (unreviewed) record with no 'approved' key."""
    return {
        "lang": lang,
        "term_raw": term,
        "term_normalized": term.lower(),
        "definition_raw": definition,
        "source_file": source,
        "article": "2",
        "clause_num": clause,
        "cross_lang_num": cross_lang_num if cross_lang_num is not None else clause,
        "abbrev": None,
    }


def _table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    return {r[0] for r in rows}


def _index_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index'"
    ).fetchall()
    return {r[0] for r in rows}


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


class TestCreateDomainSchema:
    def test_runs_without_error_on_fresh_db(self) -> None:
        conn = sqlite3.connect(":memory:")
        create_domain_schema(conn)
        conn.close()

    def test_all_tables_exist(self) -> None:
        conn = sqlite3.connect(":memory:")
        create_domain_schema(conn)
        assert {"mwe", "mwe_lang", "mwe_occurrence", "mwe_conflict"} <= _table_names(conn)

    def test_all_indexes_exist(self) -> None:
        conn = sqlite3.connect(":memory:")
        create_domain_schema(conn)
        indexes = _index_names(conn)
        assert "idx_mwe_lang_phrase" in indexes
        assert "idx_mwe_occurrence_mwe_id" in indexes
        assert "idx_mwe_conflict_a" in indexes
        assert "idx_mwe_conflict_b" in indexes

    def test_idempotent(self) -> None:
        conn = sqlite3.connect(":memory:")
        create_domain_schema(conn)
        create_domain_schema(conn)


# ---------------------------------------------------------------------------
# _group_records helper
# ---------------------------------------------------------------------------


class TestGroupRecords:
    def test_groups_by_cross_lang_num(self) -> None:
        records = [
            _make_record("A", "def", lang="lt", cross_lang_num="1"),
            _make_record("B", "def", lang="eo", cross_lang_num="1"),
            _make_record("C", "def", lang="lt", cross_lang_num="2"),
        ]
        groups = _group_records(records)
        assert len(groups) == 2
        assert [k for k, _ in groups] == ["1", "2"]

    def test_sorted_numerically(self) -> None:
        records = [
            _make_record("Z", "def", clause="10", cross_lang_num="10"),
            _make_record("A", "def", clause="2", cross_lang_num="2"),
            _make_record("M", "def", clause="271", cross_lang_num="271"),
        ]
        groups = _group_records(records)
        assert [k for k, _ in groups] == ["2", "10", "271"]

    def test_group_members(self) -> None:
        records = [
            _make_record("A", "def", lang="lt", cross_lang_num="1"),
            _make_record("B", "def", lang="eo", cross_lang_num="1"),
        ]
        groups = dict(_group_records(records))
        assert len(groups["1"]) == 2
        langs = {r["lang"] for r in groups["1"]}
        assert langs == {"lt", "eo"}


# ---------------------------------------------------------------------------
# New concept (two languages in one group → one mwe row)
# ---------------------------------------------------------------------------


class TestNewConcept:
    def _two_lang_group(self) -> list[dict]:
        return [
            _make_record("Gyventojas", "nuolatinis Lietuvos gyventojas", lang="lt"),
            _make_record("Loĝanto", "permanenta loĝanto de Litovio", lang="eo"),
        ]

    def test_one_mwe_row_created(self) -> None:
        conn = _fresh_conn()
        process_group(conn, self._two_lang_group(), "1", "personal_income_tax", "LT")
        conn.commit()
        assert conn.execute("SELECT COUNT(*) FROM mwe").fetchone()[0] == 1

    def test_two_mwe_lang_rows_created(self) -> None:
        conn = _fresh_conn()
        process_group(conn, self._two_lang_group(), "1", "personal_income_tax", "LT")
        conn.commit()
        assert conn.execute("SELECT COUNT(*) FROM mwe_lang").fetchone()[0] == 2

    def test_two_occurrence_rows_created(self) -> None:
        conn = _fresh_conn()
        process_group(conn, self._two_lang_group(), "1", "personal_income_tax", "LT")
        conn.commit()
        assert conn.execute("SELECT COUNT(*) FROM mwe_occurrence").fetchone()[0] == 2

    def test_mwe_defaults(self) -> None:
        conn = _fresh_conn()
        process_group(conn, self._two_lang_group(), "1", "personal_income_tax", "LT")
        conn.commit()
        # columns: id(0), eo_canonical(1), eo_status(2), scope(3), status(4),
        #          first_seen_source(5), first_seen_date(6), current_tier(7),
        #          domain(8), jurisdiction(9), promotable(10)
        mwe = conn.execute("SELECT * FROM mwe WHERE id=1").fetchone()
        assert mwe[3] == "document_specific"  # scope
        assert mwe[4] == "emerging"           # status
        assert mwe[10] == 0                   # promotable

    def test_both_langs_in_mwe_lang(self) -> None:
        conn = _fresh_conn()
        process_group(conn, self._two_lang_group(), "1", "personal_income_tax", "LT")
        conn.commit()
        langs = {r[0] for r in conn.execute("SELECT lang FROM mwe_lang").fetchall()}
        assert langs == {"lt", "eo"}

    def test_both_mwe_lang_linked_to_same_mwe(self) -> None:
        conn = _fresh_conn()
        process_group(conn, self._two_lang_group(), "1", "personal_income_tax", "LT")
        conn.commit()
        mwe_ids = {r[0] for r in conn.execute("SELECT mwe_id FROM mwe_lang").fetchall()}
        assert mwe_ids == {1}

    def test_result_counts(self) -> None:
        conn = _fresh_conn()
        result = process_group(conn, self._two_lang_group(), "1", "personal_income_tax", "LT")
        assert result["new_concepts"] == 1
        assert result["lang_counts"].get("lt") == 1
        assert result["lang_counts"].get("eo") == 1
        assert result["merged"] == 0
        assert result["conflicts"] == 0

    def test_single_lang_group_creates_one_mwe_one_lang(self) -> None:
        conn = _fresh_conn()
        process_group(
            conn,
            [_make_record("Gyventojas", "nuolatinis gyventojas", lang="lt")],
            "1", "personal_income_tax", "LT",
        )
        conn.commit()
        assert conn.execute("SELECT COUNT(*) FROM mwe").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM mwe_lang").fetchone()[0] == 1


# ---------------------------------------------------------------------------
# Merge: same concept from a second source document
# ---------------------------------------------------------------------------


class TestMergedSameConcept:
    def setup_method(self) -> None:
        self.conn = _fresh_conn()
        first_group = [
            _make_record("Pajamos", "gautos lėšos", lang="lt", source="doc_a.txt"),
            _make_record("Enspezo", "ricevitaj financo", lang="eo", source="doc_a.txt"),
        ]
        process_group(self.conn, first_group, "2", "personal_income_tax", "LT")
        self.conn.commit()

    def _second_group(self) -> list[dict]:
        return [
            _make_record("Pajamos", "gautos lėšos", lang="lt", source="doc_b.txt"),
            _make_record("Enspezo", "ricevitaj financo", lang="eo", source="doc_b.txt"),
        ]

    def test_mwe_count_unchanged(self) -> None:
        process_group(self.conn, self._second_group(), "2", "personal_income_tax", "LT")
        self.conn.commit()
        assert self.conn.execute("SELECT COUNT(*) FROM mwe").fetchone()[0] == 1

    def test_mwe_lang_count_unchanged(self) -> None:
        process_group(self.conn, self._second_group(), "2", "personal_income_tax", "LT")
        self.conn.commit()
        assert self.conn.execute("SELECT COUNT(*) FROM mwe_lang").fetchone()[0] == 2

    def test_four_occurrences_after_second_source(self) -> None:
        process_group(self.conn, self._second_group(), "2", "personal_income_tax", "LT")
        self.conn.commit()
        assert self.conn.execute(
            "SELECT COUNT(*) FROM mwe_occurrence WHERE mwe_id=1"
        ).fetchone()[0] == 4

    def test_status_upgraded_to_established(self) -> None:
        process_group(self.conn, self._second_group(), "2", "personal_income_tax", "LT")
        self.conn.commit()
        mwe = self.conn.execute(
            "SELECT status, scope, promotable FROM mwe WHERE id=1"
        ).fetchone()
        assert mwe[0] == "established"
        assert mwe[1] == "domain"
        assert mwe[2] == 1

    def test_third_source_upgrades_to_crystallized(self) -> None:
        third_group = [
            _make_record("Pajamos", "gautos lėšos", lang="lt", source="doc_c.txt"),
            _make_record("Enspezo", "ricevitaj financo", lang="eo", source="doc_c.txt"),
        ]
        process_group(self.conn, self._second_group(), "2", "personal_income_tax", "LT")
        process_group(self.conn, third_group, "2", "personal_income_tax", "LT")
        self.conn.commit()
        status = self.conn.execute("SELECT status FROM mwe WHERE id=1").fetchone()[0]
        assert status == "crystallized"


# ---------------------------------------------------------------------------
# Conflict: same term + same lang, different definition text
# ---------------------------------------------------------------------------


class TestConflictDifferentDefinition:
    def _insert_first(self, conn: sqlite3.Connection) -> None:
        process_group(
            conn,
            [_make_record("Rezidentas", "asmuo gyvenantis Lietuvoje", source="doc_a.txt")],
            "1", "personal_income_tax", "LT",
        )
        conn.commit()

    def test_two_mwe_rows_created(self) -> None:
        conn = _fresh_conn()
        self._insert_first(conn)
        process_group(
            conn,
            [_make_record("Rezidentas", "nuolatinis Lietuvos gyventojas", source="doc_b.txt")],
            "1", "personal_income_tax", "LT",
        )
        conn.commit()
        assert conn.execute("SELECT COUNT(*) FROM mwe").fetchone()[0] == 2

    def test_one_conflict_record_created(self) -> None:
        conn = _fresh_conn()
        self._insert_first(conn)
        process_group(
            conn,
            [_make_record("Rezidentas", "nuolatinis Lietuvos gyventojas", source="doc_b.txt")],
            "1", "personal_income_tax", "LT",
        )
        conn.commit()
        assert conn.execute("SELECT COUNT(*) FROM mwe_conflict").fetchone()[0] == 1

    def test_conflict_type_and_status(self) -> None:
        conn = _fresh_conn()
        self._insert_first(conn)
        process_group(
            conn,
            [_make_record("Rezidentas", "nuolatinis Lietuvos gyventojas", source="doc_b.txt")],
            "1", "personal_income_tax", "LT",
        )
        conn.commit()
        conflict = conn.execute(
            "SELECT conflict_type, resolution_status FROM mwe_conflict"
        ).fetchone()
        assert conflict[0] == "text_divergence"
        assert conflict[1] == "open"

    def test_conflict_links_correct_mwe_ids(self) -> None:
        conn = _fresh_conn()
        self._insert_first(conn)
        process_group(
            conn,
            [_make_record("Rezidentas", "nuolatinis Lietuvos gyventojas", source="doc_b.txt")],
            "1", "personal_income_tax", "LT",
        )
        conn.commit()
        conflict = conn.execute(
            "SELECT mwe_id_a, mwe_id_b FROM mwe_conflict"
        ).fetchone()
        assert conflict[0] == 1
        assert conflict[1] == 2


# ---------------------------------------------------------------------------
# Integration: run() with multi-lang JSONL
# ---------------------------------------------------------------------------


class TestRunIntegration:
    def test_two_groups_produce_two_mwe_four_mwe_lang(self) -> None:
        records = [
            _make_record("Gyventojas", "nuolatinis", lang="lt", clause="1", cross_lang_num="1") | {"approved": True},
            _make_record("Loĝanto", "permanenta", lang="eo", clause="1", cross_lang_num="1") | {"approved": True},
            _make_record("Pajamos", "gautos", lang="lt", clause="2", cross_lang_num="2") | {"approved": True},
            _make_record("Enspezo", "ricevitaj", lang="eo", clause="2", cross_lang_num="2") | {"approved": True},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            jsonl = Path(tmp) / "test.jsonl"
            db = Path(tmp) / "test.db"
            with jsonl.open("w", encoding="utf-8") as fh:
                for r in records:
                    fh.write(json.dumps(r, ensure_ascii=False) + "\n")

            run(jsonl, db, "test_domain", "LT")

            conn = sqlite3.connect(db)
            mwe_count = conn.execute("SELECT COUNT(*) FROM mwe").fetchone()[0]
            mwe_lang_count = conn.execute("SELECT COUNT(*) FROM mwe_lang").fetchone()[0]
            # Verification query from the spec
            join_count = conn.execute("""
                SELECT COUNT(*) FROM mwe_lang ml1
                JOIN mwe_lang ml2 ON ml1.mwe_id = ml2.mwe_id
                WHERE ml1.lang='lt' AND ml2.lang='eo'
            """).fetchone()[0]
            conn.close()

        assert mwe_count == 2
        assert mwe_lang_count == 4
        assert join_count == 2

    def test_run_writes_approved_only(self) -> None:
        records = [
            _make_record("Gyventojas", "nuolatinis", lang="lt", cross_lang_num="1") | {"approved": True},
            _make_record("Loĝanto", "permanenta", lang="eo", cross_lang_num="1") | {"approved": False},
            _make_record("Pajamos", "gautos", lang="lt", cross_lang_num="2"),  # no approved key
        ]
        with tempfile.TemporaryDirectory() as tmp:
            jsonl = Path(tmp) / "test.jsonl"
            db = Path(tmp) / "test.db"
            with jsonl.open("w", encoding="utf-8") as fh:
                for r in records:
                    fh.write(json.dumps(r, ensure_ascii=False) + "\n")

            run(jsonl, db, "test_domain", "LT")

            conn = sqlite3.connect(db)
            mwe_count = conn.execute("SELECT COUNT(*) FROM mwe").fetchone()[0]
            mwe_lang_count = conn.execute("SELECT COUNT(*) FROM mwe_lang").fetchone()[0]
            conn.close()

        # Only the lt clause-1 record is approved; eo and clause-2 are excluded
        assert mwe_count == 1
        assert mwe_lang_count == 1
