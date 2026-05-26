"""Tests for manual_overrides support in domain_db_writer.py and apply_overrides.py."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from lexicon.schema import create_domain_schema
from extractor.domain_db_writer import (
    apply_override,
    load_overrides,
    process_group,
    run as db_writer_run,
)
from extractor.apply_overrides import apply_overrides_to_db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _overrides_file(tmp_path: Path, entries: list[dict]) -> Path:
    p = tmp_path / "manual_overrides.jsonl"
    with p.open("w", encoding="utf-8") as fh:
        for entry in entries:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return p


def _empty_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    create_domain_schema(conn)
    return conn


def _insert_mwe_lang(conn: sqlite3.Connection, phrase: str, lang: str, definition: str = "") -> int:
    cur = conn.execute(
        """INSERT INTO mwe (eo_canonical, eo_status, scope, status, first_seen_source,
               first_seen_date, current_tier, domain, jurisdiction, promotable)
           VALUES (NULL, 'pending', 'domain', 'emerging', '', '2026-01-01', 4, 'test', 'LT', 0)"""
    )
    mwe_id = cur.lastrowid
    conn.execute(
        """INSERT INTO mwe_lang (mwe_id, lang, phrase, phrase_normalized, definition_raw)
           VALUES (?, ?, ?, ?, ?)""",
        (mwe_id, lang, phrase, phrase.lower(), definition),
    )
    conn.commit()
    return mwe_id


# ---------------------------------------------------------------------------
# load_overrides
# ---------------------------------------------------------------------------


class TestLoadOverrides:
    def test_absent_file_returns_empty_dict(self, tmp_path: Path) -> None:
        result = load_overrides(tmp_path / "nonexistent.jsonl")
        assert result == {}

    def test_single_override_loaded(self, tmp_path: Path) -> None:
        p = _overrides_file(tmp_path, [
            {
                "match_on": {"phrase_normalized": "rilataj personoj", "lang": "eo"},
                "override": {"phrase": "Asociitaj personoj", "phrase_normalized": "asociitaj personoj"},
                "reason": "wrong EO translation",
                "overridden_by": "ramunas",
                "override_date": "2026-05-26",
            }
        ])
        result = load_overrides(p)
        assert ("rilataj personoj", "eo") in result
        assert result[("rilataj personoj", "eo")]["phrase"] == "Asociitaj personoj"

    def test_multiple_overrides_loaded(self, tmp_path: Path) -> None:
        p = _overrides_file(tmp_path, [
            {"match_on": {"phrase_normalized": "a", "lang": "lt"}, "override": {"phrase": "A"}},
            {"match_on": {"phrase_normalized": "b", "lang": "lt"}, "override": {"phrase": "B"}},
        ])
        result = load_overrides(p)
        assert len(result) == 2

    def test_blank_lines_ignored(self, tmp_path: Path) -> None:
        p = tmp_path / "o.jsonl"
        p.write_text(
            '{"match_on": {"phrase_normalized": "x", "lang": "lt"}, "override": {"phrase": "X"}}\n'
            '\n'
            '\n',
            encoding="utf-8",
        )
        result = load_overrides(p)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# apply_override
# ---------------------------------------------------------------------------


class TestApplyOverride:
    def test_override_applied_when_match(self) -> None:
        overrides = {("test phrase", "lt"): {"phrase": "Corrected Phrase", "phrase_normalized": "corrected phrase"}}
        rec = {"lang": "lt", "term_raw": "test phrase", "definition_raw": "def"}
        new_rec, new_norm = apply_override(rec, "test phrase", overrides)
        assert new_rec["phrase"] == "Corrected Phrase"
        assert new_norm == "corrected phrase"

    def test_override_not_applied_when_no_match(self) -> None:
        overrides = {("other phrase", "lt"): {"phrase": "Other"}}
        rec = {"lang": "lt", "term_raw": "test phrase"}
        new_rec, new_norm = apply_override(rec, "test phrase", overrides)
        assert new_rec is rec  # unchanged object
        assert new_norm == "test phrase"

    def test_override_not_applied_wrong_lang(self) -> None:
        overrides = {("test phrase", "en"): {"phrase": "English Override"}}
        rec = {"lang": "lt", "term_raw": "test phrase"}
        new_rec, new_norm = apply_override(rec, "test phrase", overrides)
        assert new_norm == "test phrase"
        assert new_rec.get("phrase") is None  # no override field added

    def test_definition_raw_overridden(self) -> None:
        overrides = {("phrase", "lt"): {"phrase": "Phrase", "definition_raw": "New def"}}
        rec = {"lang": "lt", "definition_raw": "Old def"}
        new_rec, _ = apply_override(rec, "phrase", overrides)
        assert new_rec["definition_raw"] == "New def"

    def test_empty_overrides_dict_noop(self) -> None:
        rec = {"lang": "lt"}
        new_rec, new_norm = apply_override(rec, "phrase", {})
        assert new_rec is rec
        assert new_norm == "phrase"


# ---------------------------------------------------------------------------
# apply_overrides_to_db (apply_overrides.py utility)
# ---------------------------------------------------------------------------


class TestApplyOverridesToDb:
    def test_existing_row_updated(self) -> None:
        conn = _empty_db()
        _insert_mwe_lang(conn, "rilataj personoj", "eo", "susiję asmenys")
        overrides = {
            ("rilataj personoj", "eo"): {
                "phrase": "Asociitaj personoj",
                "phrase_normalized": "asociitaj personoj",
            }
        }
        n = apply_overrides_to_db(conn, overrides)
        assert n == 1
        row = conn.execute(
            "SELECT phrase, phrase_normalized FROM mwe_lang WHERE lang='eo'"
        ).fetchone()
        assert row[0] == "Asociitaj personoj"
        assert row[1] == "asociitaj personoj"

    def test_no_match_prints_warning(self, capsys) -> None:
        conn = _empty_db()
        overrides = {("nonexistent phrase", "eo"): {"phrase": "X"}}
        n = apply_overrides_to_db(conn, overrides)
        assert n == 0
        captured = capsys.readouterr()
        assert "WARNING" in captured.out

    def test_definition_raw_updated_when_provided(self) -> None:
        conn = _empty_db()
        _insert_mwe_lang(conn, "some term", "lt", "old definition")
        overrides = {
            ("some term", "lt"): {
                "phrase": "Some Term",
                "phrase_normalized": "some term",
                "definition_raw": "new definition",
            }
        }
        apply_overrides_to_db(conn, overrides)
        row = conn.execute("SELECT definition_raw FROM mwe_lang WHERE lang='lt'").fetchone()
        assert row[0] == "new definition"

    def test_definition_raw_unchanged_when_not_in_override(self) -> None:
        conn = _empty_db()
        _insert_mwe_lang(conn, "some term", "lt", "original definition")
        overrides = {("some term", "lt"): {"phrase": "Some Term", "phrase_normalized": "some term"}}
        apply_overrides_to_db(conn, overrides)
        row = conn.execute("SELECT definition_raw FROM mwe_lang WHERE lang='lt'").fetchone()
        assert row[0] == "original definition"


# ---------------------------------------------------------------------------
# Integration: override applied during process_group
# ---------------------------------------------------------------------------


class TestProcessGroupWithOverrides:
    def _make_rec(self, term: str, lang: str, definition: str = "def", clause: str = "1") -> dict:
        return {
            "term_raw": term,
            "lang": lang,
            "definition_raw": definition,
            "approved": True,
            "clause_num": clause,
            "cross_lang_num": clause,
            "source_file": "test.txt",
        }

    def test_override_applied_before_insert(self) -> None:
        conn = _empty_db()
        overrides = {
            ("rilataj personoj", "eo"): {
                "phrase": "Asociitaj personoj",
                "phrase_normalized": "asociitaj personoj",
            }
        }
        rec = self._make_rec("Rilataj personoj", "eo", "associated persons")
        process_group(conn, [rec], "1", "test", "LT", overrides)
        conn.commit()

        row = conn.execute("SELECT phrase, phrase_normalized FROM mwe_lang WHERE lang='eo'").fetchone()
        assert row is not None
        assert row[0] == "Asociitaj personoj"
        assert row[1] == "asociitaj personoj"

    def test_no_override_unchanged(self) -> None:
        conn = _empty_db()
        rec = self._make_rec("Rezidentas", "lt", "resident person")
        process_group(conn, [rec], "1", "test", "LT", {})
        conn.commit()

        row = conn.execute("SELECT phrase FROM mwe_lang WHERE lang='lt'").fetchone()
        assert row[0] == "Rezidentas"
