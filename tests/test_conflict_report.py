"""Tests for src/analyzer/conflict_report.py.

All tests use in-memory SQLite databases — no external files required.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from lexicon.schema import create_domain_schema
from analyzer.conflict_report import (
    ConflictDetail,
    CrossConflict,
    detect_common_langs,
    format_conflict_report,
    format_cross_conflict_report,
    get_langs,
    load_conflicts,
    load_cross_conflicts,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _empty_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    create_domain_schema(conn)
    return conn


def _insert_mwe(conn: sqlite3.Connection, domain: str = "test") -> int:
    cur = conn.execute(
        """INSERT INTO mwe (eo_canonical, scope, status, domain, jurisdiction)
           VALUES (NULL, 'domain', 'emerging', ?, 'LT')""",
        (domain,),
    )
    return cur.lastrowid  # type: ignore[return-value]


def _insert_mwe_lang(
    conn: sqlite3.Connection,
    mwe_id: int,
    lang: str,
    phrase: str,
    definition: str = "",
) -> None:
    conn.execute(
        """INSERT INTO mwe_lang (mwe_id, lang, phrase, phrase_normalized, definition_raw)
           VALUES (?, ?, ?, ?, ?)""",
        (mwe_id, lang, phrase, phrase.lower(), definition),
    )


def _insert_occurrence(
    conn: sqlite3.Connection, mwe_id: int, source_doc: str, lang: str = "lt"
) -> None:
    conn.execute(
        """INSERT INTO mwe_occurrence (mwe_id, source_doc, source_lang, date_extracted)
           VALUES (?, ?, ?, '2026-01-01')""",
        (mwe_id, source_doc, lang),
    )


def _insert_conflict(
    conn: sqlite3.Connection,
    mwe_id_a: int,
    mwe_id_b: int,
    detail: str = "A: def_a | B: def_b",
) -> None:
    conn.execute(
        """INSERT INTO mwe_conflict
               (mwe_id_a, mwe_id_b, conflict_type, divergence_detail,
                resolution_status, detected_date)
           VALUES (?, ?, 'text_divergence', ?, 'open', '2026-01-01')""",
        (mwe_id_a, mwe_id_b, detail),
    )


# ---------------------------------------------------------------------------
# load_conflicts
# ---------------------------------------------------------------------------


class TestLoadConflicts:
    def test_empty_db_returns_empty_list(self) -> None:
        conn = _empty_db()
        assert load_conflicts(conn) == []

    def test_single_conflict_loaded(self) -> None:
        conn = _empty_db()
        a = _insert_mwe(conn)
        b = _insert_mwe(conn)
        _insert_mwe_lang(conn, a, "lt", "Rezidentas", "asmuo gyvenantis Lietuvoje")
        _insert_mwe_lang(conn, b, "lt", "Rezidentas", "nuolatinis Lietuvos gyventojas")
        _insert_occurrence(conn, a, "doc_a.txt")
        _insert_occurrence(conn, b, "doc_b.txt")
        _insert_conflict(conn, a, b, "A: asmuo gyvenantis | B: nuolatinis Lietuvos")
        conn.commit()

        conflicts = load_conflicts(conn)
        assert len(conflicts) == 1
        c = conflicts[0]
        assert c.mwe_id_a == a
        assert c.mwe_id_b == b
        assert c.conflict_type == "text_divergence"
        assert c.resolution_status == "open"

    def test_conflict_phrases_loaded_for_both_mwes(self) -> None:
        conn = _empty_db()
        a = _insert_mwe(conn)
        b = _insert_mwe(conn)
        _insert_mwe_lang(conn, a, "lt", "Susiję asmenys", "def_a_lt")
        _insert_mwe_lang(conn, a, "en", "Related persons", "def_a_en")
        _insert_mwe_lang(conn, b, "lt", "Asocijuoti asmenys", "def_b_lt")
        _insert_mwe_lang(conn, b, "en", "Associated persons", "def_b_en")
        _insert_conflict(conn, a, b)
        conn.commit()

        c = load_conflicts(conn)[0]
        phrase_langs_a = {p[0] for p in c.phrases_a}
        phrase_langs_b = {p[0] for p in c.phrases_b}
        assert phrase_langs_a == {"lt", "en"}
        assert phrase_langs_b == {"lt", "en"}

    def test_conflict_sources_loaded(self) -> None:
        conn = _empty_db()
        a = _insert_mwe(conn)
        b = _insert_mwe(conn)
        _insert_mwe_lang(conn, a, "lt", "TermA", "def_a")
        _insert_mwe_lang(conn, b, "lt", "TermA", "def_b")
        _insert_occurrence(conn, a, "law_2023.txt")
        _insert_occurrence(conn, b, "law_2024.txt")
        _insert_conflict(conn, a, b)
        conn.commit()

        c = load_conflicts(conn)[0]
        assert "law_2023.txt" in c.sources_a
        assert "law_2024.txt" in c.sources_b

    def test_multiple_conflicts_returned_in_order(self) -> None:
        conn = _empty_db()
        ids = [_insert_mwe(conn) for _ in range(4)]
        for i in range(0, 4, 2):
            _insert_mwe_lang(conn, ids[i], "lt", f"Term{i}", "def_a")
            _insert_mwe_lang(conn, ids[i + 1], "lt", f"Term{i}", "def_b")
            _insert_conflict(conn, ids[i], ids[i + 1])
        conn.commit()

        conflicts = load_conflicts(conn)
        assert len(conflicts) == 2
        assert conflicts[0].conflict_id < conflicts[1].conflict_id

    def test_divergence_detail_preserved(self) -> None:
        conn = _empty_db()
        a = _insert_mwe(conn)
        b = _insert_mwe(conn)
        _insert_mwe_lang(conn, a, "lt", "TermA", "def_a")
        _insert_mwe_lang(conn, b, "lt", "TermA", "def_b")
        detail = "A: first definition text | B: second definition text"
        _insert_conflict(conn, a, b, detail)
        conn.commit()

        c = load_conflicts(conn)[0]
        assert c.divergence_detail == detail


# ---------------------------------------------------------------------------
# format_conflict_report
# ---------------------------------------------------------------------------


class TestFormatConflictReport:
    def _make_conflict(self) -> ConflictDetail:
        return ConflictDetail(
            conflict_id=1,
            mwe_id_a=18,
            mwe_id_b=31,
            conflict_type="text_divergence",
            divergence_detail="A: first definition | B: second definition",
            resolution_status="open",
            detected_date="2026-01-01",
            phrases_a=[("lt", "Susiję asmenys", "def_a"), ("en", "Related persons", "")],
            phrases_b=[("lt", "Asocijuoti asmenys", "def_b"), ("en", "Associated persons", "")],
            sources_a=["doc_a.txt"],
            sources_b=["doc_b.txt"],
        )

    def test_report_header_contains_db_name(self) -> None:
        report = format_conflict_report([], "gpmi_lt_tax.db")
        assert "gpmi_lt_tax.db" in report

    def test_zero_conflicts_shown(self) -> None:
        report = format_conflict_report([], "test.db")
        assert "0 conflicts found" in report

    def test_one_conflict_shown(self) -> None:
        report = format_conflict_report([self._make_conflict()], "test.db")
        assert "1 conflict found" in report

    def test_phrases_for_both_concepts_appear(self) -> None:
        report = format_conflict_report([self._make_conflict()], "test.db")
        assert "Susiję asmenys" in report
        assert "Asocijuoti asmenys" in report

    def test_divergence_detail_shown(self) -> None:
        report = format_conflict_report([self._make_conflict()], "test.db")
        assert "DIVERGENCE" in report
        assert "first definition" in report

    def test_mwe_ids_shown(self) -> None:
        report = format_conflict_report([self._make_conflict()], "test.db")
        assert "mwe_id=18" in report
        assert "mwe_id=31" in report

    def test_sources_shown(self) -> None:
        report = format_conflict_report([self._make_conflict()], "test.db")
        assert "doc_a.txt" in report
        assert "doc_b.txt" in report

    def test_resolution_status_shown(self) -> None:
        report = format_conflict_report([self._make_conflict()], "test.db")
        assert "open" in report


# ---------------------------------------------------------------------------
# load_cross_conflicts
# ---------------------------------------------------------------------------


class TestLoadCrossConflicts:
    def _make_db(self, entries: list[tuple[str, str, str]]) -> sqlite3.Connection:
        """Build an in-memory DB with mwe_lang rows (lang, phrase_normalized, definition)."""
        conn = _empty_db()
        for lang, phrase_norm, defn in entries:
            mwe_id = _insert_mwe(conn)
            conn.execute(
                """INSERT INTO mwe_lang (mwe_id, lang, phrase, phrase_normalized, definition_raw)
                   VALUES (?, ?, ?, ?, ?)""",
                (mwe_id, lang, phrase_norm, phrase_norm, defn),
            )
        conn.commit()
        return conn

    def test_no_shared_phrases_returns_empty(self) -> None:
        a = self._make_db([("lt", "rezidentas", "def_a")])
        b = self._make_db([("lt", "gyventojas", "def_b")])
        assert load_cross_conflicts(a, b, "lt", "a.db", "b.db") == []

    def test_shared_phrase_same_definition_no_conflict(self) -> None:
        a = self._make_db([("lt", "rezidentas", "asmuo gyvenantis")])
        b = self._make_db([("lt", "rezidentas", "asmuo gyvenantis")])
        assert load_cross_conflicts(a, b, "lt", "a.db", "b.db") == []

    def test_shared_phrase_different_definition_is_conflict(self) -> None:
        a = self._make_db([("lt", "rezidentas", "def_a")])
        b = self._make_db([("lt", "rezidentas", "def_b")])
        conflicts = load_cross_conflicts(a, b, "lt", "a.db", "b.db")
        assert len(conflicts) == 1
        c = conflicts[0]
        assert c.phrase_normalized == "rezidentas"
        assert c.definition_a == "def_a"
        assert c.definition_b == "def_b"

    def test_conflict_attributes_populated(self) -> None:
        a = self._make_db([("lt", "rezidentas", "def_a")])
        b = self._make_db([("lt", "rezidentas", "def_b")])
        c = load_cross_conflicts(a, b, "lt", "db_a.db", "db_b.db")[0]
        assert c.lang == "lt"
        assert c.db_a == "db_a.db"
        assert c.db_b == "db_b.db"

    def test_case_insensitive_definition_comparison(self) -> None:
        a = self._make_db([("lt", "rezidentas", "Asmuo Gyvenantis")])
        b = self._make_db([("lt", "rezidentas", "asmuo gyvenantis")])
        # Same content, different case → no conflict
        assert load_cross_conflicts(a, b, "lt", "a.db", "b.db") == []

    def test_lang_filter_applied(self) -> None:
        a = self._make_db([("lt", "rezidentas", "def_lt"), ("en", "resident", "def_en_a")])
        b = self._make_db([("lt", "rezidentas", "def_lt"), ("en", "resident", "def_en_b")])
        # Only lt requested — "resident" EN conflict not returned
        lt_conflicts = load_cross_conflicts(a, b, "lt", "a.db", "b.db")
        en_conflicts = load_cross_conflicts(a, b, "en", "a.db", "b.db")
        assert lt_conflicts == []
        assert len(en_conflicts) == 1

    def test_multiple_conflicts_found(self) -> None:
        a = self._make_db([("lt", "term_x", "def_a"), ("lt", "term_y", "def_a")])
        b = self._make_db([("lt", "term_x", "def_b"), ("lt", "term_y", "def_b")])
        conflicts = load_cross_conflicts(a, b, "lt", "a.db", "b.db")
        assert len(conflicts) == 2

    def test_nonempty_vs_nonempty_not_incomplete(self) -> None:
        a = self._make_db([("en", "carrier", "the person transporting")])
        b = self._make_db([("en", "carrier", "person responsible for carriage")])
        c = load_cross_conflicts(a, b, "en", "a.db", "b.db")[0]
        assert c.incomplete is False

    def test_empty_definition_on_b_side_marked_incomplete(self) -> None:
        a = self._make_db([("fr", "transporteur", "la personne qui transporte")])
        b = self._make_db([("fr", "transporteur", "")])
        conflicts = load_cross_conflicts(a, b, "fr", "a.db", "b.db")
        assert len(conflicts) == 1
        assert conflicts[0].incomplete is True

    def test_empty_definition_on_a_side_marked_incomplete(self) -> None:
        a = self._make_db([("fr", "transporteur", "")])
        b = self._make_db([("fr", "transporteur", "la personne qui transporte")])
        conflicts = load_cross_conflicts(a, b, "fr", "a.db", "b.db")
        assert len(conflicts) == 1
        assert conflicts[0].incomplete is True

    def test_both_empty_definitions_not_a_conflict(self) -> None:
        # Both sides have no definition → they are equal → not returned at all
        a = self._make_db([("fr", "transporteur", "")])
        b = self._make_db([("fr", "transporteur", "")])
        assert load_cross_conflicts(a, b, "fr", "a.db", "b.db") == []


# ---------------------------------------------------------------------------
# format_cross_conflict_report
# ---------------------------------------------------------------------------


class TestFormatCrossConflictReport:
    def _conflict(self) -> CrossConflict:
        return CrossConflict(
            phrase_normalized="rezidentas",
            lang="lt",
            definition_a="first definition",
            definition_b="second definition",
            db_a="db_a.db",
            db_b="db_b.db",
        )

    def test_header_contains_both_db_names(self) -> None:
        report = format_cross_conflict_report([], "db_a.db", "db_b.db", "lt")
        assert "db_a.db" in report
        assert "db_b.db" in report

    def test_zero_conflicts_message(self) -> None:
        report = format_cross_conflict_report([], "a.db", "b.db", "lt")
        assert "0 shared phrases" in report

    def test_phrase_appears_in_report(self) -> None:
        report = format_cross_conflict_report([self._conflict()], "a.db", "b.db", "lt")
        assert "rezidentas" in report

    def test_both_definitions_shown(self) -> None:
        report = format_cross_conflict_report([self._conflict()], "a.db", "b.db", "lt")
        assert "first definition" in report
        assert "second definition" in report

    def _incomplete_conflict(self) -> CrossConflict:
        return CrossConflict(
            phrase_normalized="transporteur",
            lang="fr",
            definition_a="la personne qui transporte",
            definition_b="",
            db_a="db_a.db",
            db_b="db_b.db",
            incomplete=True,
        )

    def test_incomplete_not_counted_as_conflict(self) -> None:
        report = format_cross_conflict_report([self._incomplete_conflict()], "a.db", "b.db", "fr")
        assert "0 shared phrases with diverging definitions" in report

    def test_incomplete_count_shown(self) -> None:
        report = format_cross_conflict_report([self._incomplete_conflict()], "a.db", "b.db", "fr")
        assert "1 phrase where one side has no definition (incomplete)" in report

    def test_incomplete_phrase_not_in_detail_sections(self) -> None:
        report = format_cross_conflict_report([self._incomplete_conflict()], "a.db", "b.db", "fr")
        assert "PHRASE:" not in report

    def test_real_conflict_and_incomplete_separated(self) -> None:
        conflicts = [self._conflict(), self._incomplete_conflict()]
        report = format_cross_conflict_report(conflicts, "a.db", "b.db", "lt")
        assert "1 shared phrase with diverging definitions" in report
        assert "1 phrase where one side has no definition (incomplete)" in report
        assert "rezidentas" in report        # real conflict shown in detail
        assert "transporteur" not in report  # incomplete not shown in detail

    def test_no_incomplete_line_when_none(self) -> None:
        report = format_cross_conflict_report([self._conflict()], "a.db", "b.db", "lt")
        assert "incomplete" not in report


# ---------------------------------------------------------------------------
# get_langs / detect_common_langs
# ---------------------------------------------------------------------------


class TestGetLangs:
    def test_empty_db_returns_empty_set(self) -> None:
        conn = _empty_db()
        assert get_langs(conn) == set()

    def test_single_lang(self) -> None:
        conn = _empty_db()
        mwe_id = _insert_mwe(conn)
        _insert_mwe_lang(conn, mwe_id, "lt", "rezidentas")
        conn.commit()
        assert get_langs(conn) == {"lt"}

    def test_multiple_langs(self) -> None:
        conn = _empty_db()
        mwe_id = _insert_mwe(conn)
        _insert_mwe_lang(conn, mwe_id, "lt", "rezidentas")
        _insert_mwe_lang(conn, mwe_id, "en", "resident")
        _insert_mwe_lang(conn, mwe_id, "fr", "résident")
        conn.commit()
        assert get_langs(conn) == {"lt", "en", "fr"}


class TestDetectCommonLangs:
    def _db_with_langs(self, langs: list[str]) -> sqlite3.Connection:
        conn = _empty_db()
        mwe_id = _insert_mwe(conn)
        for lang in langs:
            _insert_mwe_lang(conn, mwe_id, lang, f"term_{lang}")
        conn.commit()
        return conn

    def test_no_common_langs_returns_empty(self) -> None:
        a = self._db_with_langs(["lt"])
        b = self._db_with_langs(["en"])
        assert detect_common_langs(a, b) == []

    def test_one_common_lang(self) -> None:
        a = self._db_with_langs(["lt", "en"])
        b = self._db_with_langs(["en", "fr"])
        assert detect_common_langs(a, b) == ["en"]

    def test_multiple_common_langs_sorted(self) -> None:
        a = self._db_with_langs(["lt", "en", "fr"])
        b = self._db_with_langs(["lt", "en", "fr"])
        assert detect_common_langs(a, b) == ["en", "fr", "lt"]

    def test_both_empty_returns_empty(self) -> None:
        a = _empty_db()
        b = _empty_db()
        assert detect_common_langs(a, b) == []

    def test_wco_vs_ucc_pattern(self) -> None:
        """WCO (EN+FR only) vs UCC (EN+LT+FR) — common langs are EN and FR, not LT."""
        wco = self._db_with_langs(["en", "fr"])
        ucc = self._db_with_langs(["en", "lt", "fr"])
        common = detect_common_langs(wco, ucc)
        assert "lt" not in common
        assert "en" in common
        assert "fr" in common
