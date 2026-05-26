"""Tests for src/extractor/link_synonyms.py and synonym support in coverage_report.py."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from lexicon.schema import create_domain_schema
from extractor.link_synonyms import link_synonyms, load_synonyms, load_synonym_map
from analyzer.coverage_report import (
    SimpleToken,
    TokenResult,
    classify_tokens,
    load_synonym_map as coverage_load_synonym_map,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _empty_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    create_domain_schema(conn)
    return conn


def _insert_mwe_with_lang(conn: sqlite3.Connection, phrase: str, lang: str) -> int:
    cur = conn.execute(
        """INSERT INTO mwe (eo_canonical, eo_status, scope, status, first_seen_source,
               first_seen_date, current_tier, domain, jurisdiction, promotable)
           VALUES (NULL, 'pending', 'domain', 'emerging', '', '2026-01-01', 4, 'test', 'LT', 0)"""
    )
    mwe_id = cur.lastrowid
    conn.execute(
        """INSERT INTO mwe_lang (mwe_id, lang, phrase, phrase_normalized, definition_raw)
           VALUES (?, ?, ?, ?, '')""",
        (mwe_id, lang, phrase, phrase.lower()),
    )
    conn.commit()
    return mwe_id


# ---------------------------------------------------------------------------
# link_synonyms (record creation)
# ---------------------------------------------------------------------------


class TestLinkSynonyms:
    def test_synonym_record_created(self) -> None:
        conn = _empty_db()
        id_a = _insert_mwe_with_lang(conn, "individualia veikla besiverčiantys", "lt")
        id_b = _insert_mwe_with_lang(conn, "verčiasi individualia veikla", "lt")

        mwe_a, mwe_b = link_synonyms(
            conn,
            "individualia veikla besiverčiantys",
            "verčiasi individualia veikla",
            "lt",
            "participial vs verbal form",
        )
        assert mwe_a == id_a
        assert mwe_b == id_b

        row = conn.execute(
            "SELECT conflict_type, resolution_status FROM mwe_conflict WHERE mwe_id_a=? AND mwe_id_b=?",
            (id_a, id_b),
        ).fetchone()
        assert row is not None
        assert row[0] == "synonym"
        assert row[1] == "open"

    def test_duplicate_link_not_created(self) -> None:
        conn = _empty_db()
        _insert_mwe_with_lang(conn, "phrase a", "lt")
        _insert_mwe_with_lang(conn, "phrase b", "lt")
        link_synonyms(conn, "phrase a", "phrase b", "lt", "first")
        link_synonyms(conn, "phrase a", "phrase b", "lt", "duplicate")
        count = conn.execute("SELECT COUNT(*) FROM mwe_conflict WHERE conflict_type='synonym'").fetchone()[0]
        assert count == 1

    def test_phrase_not_found_raises_value_error(self) -> None:
        conn = _empty_db()
        _insert_mwe_with_lang(conn, "phrase a", "lt")
        with pytest.raises(ValueError, match="phrase_b not found"):
            link_synonyms(conn, "phrase a", "nonexistent phrase", "lt", "test")

    def test_divergence_detail_stored(self) -> None:
        conn = _empty_db()
        _insert_mwe_with_lang(conn, "phrase a", "lt")
        _insert_mwe_with_lang(conn, "phrase b", "lt")
        link_synonyms(conn, "phrase a", "phrase b", "lt", "reason text here")
        row = conn.execute("SELECT divergence_detail FROM mwe_conflict").fetchone()
        assert row[0] == "reason text here"


# ---------------------------------------------------------------------------
# load_synonyms (list)
# ---------------------------------------------------------------------------


class TestLoadSynonyms:
    def test_no_synonyms_returns_empty(self) -> None:
        conn = _empty_db()
        assert load_synonyms(conn) == []

    def test_synonym_listed_with_phrases(self) -> None:
        conn = _empty_db()
        _insert_mwe_with_lang(conn, "Phrase A", "lt")
        _insert_mwe_with_lang(conn, "Phrase B", "lt")
        link_synonyms(conn, "Phrase A", "Phrase B", "lt", "reason")
        synonyms = load_synonyms(conn)
        assert len(synonyms) == 1
        s = synonyms[0]
        assert s["lang"] == "lt"
        assert s["phrase_a"] == "Phrase A"
        assert s["phrase_b"] == "Phrase B"
        assert s["reason"] == "reason"
        assert s["resolution_status"] == "open"

    def test_only_synonym_conflicts_listed(self) -> None:
        conn = _empty_db()
        id_a = _insert_mwe_with_lang(conn, "term a", "lt")
        id_b = _insert_mwe_with_lang(conn, "term b", "lt")
        # Insert a text_divergence conflict — should NOT appear in load_synonyms
        conn.execute(
            """INSERT INTO mwe_conflict (mwe_id_a, mwe_id_b, conflict_type, divergence_detail,
                   resolution_status, detected_date)
               VALUES (?, ?, 'text_divergence', 'diff', 'open', '2026-01-01')""",
            (id_a, id_b),
        )
        conn.commit()
        assert load_synonyms(conn) == []


# ---------------------------------------------------------------------------
# load_synonym_map
# ---------------------------------------------------------------------------


class TestLoadSynonymMap:
    def test_map_returns_canonical_for_matched_phrase(self) -> None:
        conn = _empty_db()
        _insert_mwe_with_lang(conn, "Phrase A", "lt")
        _insert_mwe_with_lang(conn, "Phrase B", "lt")
        link_synonyms(conn, "Phrase A", "Phrase B", "lt", "test")
        # phrase_b (mwe_id_b) → phrase_a (canonical / mwe_id_a)
        synonym_map = load_synonym_map(conn, "lt")
        assert "phrase b" in synonym_map
        assert synonym_map["phrase b"] == "Phrase A"

    def test_wrong_lang_returns_empty(self) -> None:
        conn = _empty_db()
        _insert_mwe_with_lang(conn, "Phrase A", "lt")
        _insert_mwe_with_lang(conn, "Phrase B", "lt")
        link_synonyms(conn, "Phrase A", "Phrase B", "lt", "test")
        synonym_map = load_synonym_map(conn, "en")
        assert synonym_map == {}

    def test_no_synonyms_returns_empty(self) -> None:
        conn = _empty_db()
        synonym_map = load_synonym_map(conn, "lt")
        assert synonym_map == {}


# ---------------------------------------------------------------------------
# coverage_report synonym notation
# ---------------------------------------------------------------------------


class TestCoverageReportSynonymNotation:
    def _make_token(self, text: str, lemma: str = "", skip: bool = False) -> SimpleToken:
        return SimpleToken(text=text, lemma=lemma or text.lower(), is_skip=skip)

    def test_synonym_of_set_on_tier4_match(self) -> None:
        tokens = [self._make_token("phrase", "phrase"), self._make_token("b", "b")]
        mwe_phrases = {"phrase b"}
        synonym_map = {"phrase b": "Phrase A"}
        results = classify_tokens(tokens, mwe_phrases, set(), set(), synonym_map=synonym_map)
        tier4 = [r for r in results if r.category == "TIER4"]
        assert len(tier4) == 1
        assert tier4[0].synonym_of == "Phrase A"

    def test_no_synonym_when_map_empty(self) -> None:
        tokens = [self._make_token("phrase", "phrase"), self._make_token("b", "b")]
        mwe_phrases = {"phrase b"}
        results = classify_tokens(tokens, mwe_phrases, set(), set(), synonym_map={})
        tier4 = [r for r in results if r.category == "TIER4"]
        assert tier4[0].synonym_of is None

    def test_non_tier4_tokens_unaffected(self) -> None:
        tokens = [self._make_token("labas", "labas")]
        tier1 = {"labas"}
        results = classify_tokens(tokens, set(), tier1, set(), synonym_map={"labas": "irrelevant"})
        assert results[0].category == "TIER1"
        assert results[0].synonym_of is None
