"""Tests for src/extractor/candidate_quality_report.py."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from extractor.candidate_quality_report import (
    _auto_ne_path,
    _noise_words,
    auto_approve_high,
    bucket,
    generate_report,
    load_candidates,
    load_cross_db_phrases,
    load_ne_phrases,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_candidate(
    phrase: str = "customs territory",
    frequency: int = 5,
    pmi: float = 15.0,
    lang: str = "en",
    approved: bool | None = None,
) -> dict:
    rec: dict = {
        "phrase": phrase,
        "phrase_normalized": phrase.lower(),
        "frequency": frequency,
        "pmi": pmi,
        "lang": lang,
    }
    if approved is not None:
        rec["approved"] = approved
    return rec


def _write_jsonl(path: Path, records: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _make_domain_db(path: Path, phrases: list[str], lang: str = "en", domain: str = "test") -> None:
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS mwe (
            id INTEGER PRIMARY KEY,
            domain TEXT
        );
        CREATE TABLE IF NOT EXISTS mwe_lang (
            id INTEGER PRIMARY KEY,
            mwe_id INTEGER,
            lang TEXT,
            phrase TEXT,
            phrase_normalized TEXT
        );
    """)
    for i, phrase in enumerate(phrases, start=1):
        conn.execute("INSERT INTO mwe (id, domain) VALUES (?, ?)", (i, domain))
        conn.execute(
            "INSERT INTO mwe_lang (mwe_id, lang, phrase, phrase_normalized) VALUES (?, ?, ?, ?)",
            (i, lang, phrase, phrase.lower()),
        )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# bucket()
# ---------------------------------------------------------------------------


class TestBucket:
    def test_high_confidence(self) -> None:
        assert bucket({"frequency": 5, "pmi": 15.0}) == "high"

    def test_high_confidence_above_threshold(self) -> None:
        assert bucket({"frequency": 10, "pmi": 20.0}) == "high"

    def test_medium_confidence(self) -> None:
        assert bucket({"frequency": 3, "pmi": 10.0}) == "medium"

    def test_medium_frequency_high_pmi(self) -> None:
        # freq=3 doesn't reach HIGH_FREQ=5; pmi=15 does reach HIGH_PMI; still medium
        assert bucket({"frequency": 3, "pmi": 15.0}) == "medium"

    def test_high_frequency_medium_pmi(self) -> None:
        # freq=5 reaches HIGH_FREQ; pmi=10 doesn't reach HIGH_PMI=15.0; still medium
        assert bucket({"frequency": 5, "pmi": 10.0}) == "medium"

    def test_low_confidence(self) -> None:
        assert bucket({"frequency": 1, "pmi": 5.0}) == "low"

    def test_low_frequency_zero_pmi(self) -> None:
        assert bucket({"frequency": 2, "pmi": 0.0}) == "low"

    def test_missing_pmi_treated_as_zero(self) -> None:
        assert bucket({"frequency": 1}) == "low"

    def test_none_pmi_treated_as_zero(self) -> None:
        assert bucket({"frequency": 5, "pmi": None}) == "low"

    def test_boundary_high_inclusive(self) -> None:
        assert bucket({"frequency": 5, "pmi": 15.0}) == "high"

    def test_just_below_medium(self) -> None:
        assert bucket({"frequency": 2, "pmi": 9.9}) == "low"


# ---------------------------------------------------------------------------
# _noise_words()
# ---------------------------------------------------------------------------


class TestNoiseWords:
    def test_css_artifact_detected(self) -> None:
        assert _noise_words("flex display align") is True

    def test_clean_phrase(self) -> None:
        assert _noise_words("customs territory") is False

    def test_partial_noise(self) -> None:
        assert _noise_words("border flex") is True

    def test_html_artifact(self) -> None:
        assert _noise_words("http javascript") is True


# ---------------------------------------------------------------------------
# load_ne_phrases()
# ---------------------------------------------------------------------------


class TestLoadNePhrases:
    def test_returns_empty_for_none(self) -> None:
        assert load_ne_phrases(None) == set()

    def test_returns_empty_for_missing_file(self, tmp_path: Path) -> None:
        assert load_ne_phrases(tmp_path / "missing.jsonl") == set()

    def test_loads_phrase_normalized(self, tmp_path: Path) -> None:
        p = tmp_path / "ne.jsonl"
        _write_jsonl(p, [{"phrase_normalized": "european union", "phrase": "European Union"}])
        phrases = load_ne_phrases(p)
        assert "european union" in phrases

    def test_falls_back_to_lowercased_phrase(self, tmp_path: Path) -> None:
        p = tmp_path / "ne.jsonl"
        _write_jsonl(p, [{"phrase": "European Union"}])
        phrases = load_ne_phrases(p)
        assert "european union" in phrases


# ---------------------------------------------------------------------------
# load_cross_db_phrases()
# ---------------------------------------------------------------------------


class TestLoadCrossDbPhrases:
    def test_returns_empty_for_none(self) -> None:
        assert load_cross_db_phrases(None, "en") == {}

    def test_returns_empty_for_missing_db(self, tmp_path: Path) -> None:
        assert load_cross_db_phrases(tmp_path / "missing.db", "en") == {}

    def test_loads_phrases_for_lang(self, tmp_path: Path) -> None:
        db = tmp_path / "other.db"
        _make_domain_db(db, ["customs territory", "free zone"], lang="en", domain="ucc")
        result = load_cross_db_phrases(db, "en")
        assert "customs territory" in result
        assert "free zone" in result
        assert result["customs territory"] == "ucc"

    def test_lang_filter_respected(self, tmp_path: Path) -> None:
        db = tmp_path / "other.db"
        _make_domain_db(db, ["muitinė teritorija"], lang="lt", domain="ucc")
        en_result = load_cross_db_phrases(db, "en")
        assert en_result == {}
        lt_result = load_cross_db_phrases(db, "lt")
        assert "muitinė teritorija" in lt_result


# ---------------------------------------------------------------------------
# generate_report()
# ---------------------------------------------------------------------------


class TestGenerateReport:
    def test_buckets_candidates_correctly(self, tmp_path: Path) -> None:
        candidates = [
            _make_candidate("high term", frequency=5, pmi=15.0),
            _make_candidate("medium term", frequency=3, pmi=10.0),
            _make_candidate("low term", frequency=1, pmi=2.0),
        ]
        p = tmp_path / "cands.jsonl"
        _write_jsonl(p, candidates)
        high, medium, low = generate_report(candidates, set(), {}, p)
        assert len(high) == 1
        assert len(medium) == 1
        assert len(low) == 1
        assert high[0]["phrase"] == "high term"

    def test_cross_domain_matches_detected(self, tmp_path: Path) -> None:
        candidates = [
            _make_candidate("customs territory", frequency=5, pmi=15.0),
            _make_candidate("release of goods", frequency=3, pmi=10.0),
        ]
        cross_db_phrases = {"customs territory": "ucc"}
        p = tmp_path / "cands.jsonl"
        _write_jsonl(p, candidates)
        # generate_report prints but also returns tiers — cross-domain is printed internally
        high, medium, low = generate_report(candidates, set(), cross_db_phrases, p)
        # ensure it completes without error and returns correct tiers
        assert len(high) == 1
        assert len(medium) == 1

    def test_ne_overlap_detected(self, tmp_path: Path) -> None:
        candidates = [
            _make_candidate("european union", frequency=8, pmi=20.0),
        ]
        ne_phrases = {"european union"}
        p = tmp_path / "cands.jsonl"
        _write_jsonl(p, candidates)
        high, _, _ = generate_report(candidates, ne_phrases, {}, p)
        assert len(high) == 1


# ---------------------------------------------------------------------------
# auto_approve_high()
# ---------------------------------------------------------------------------


class TestAutoApproveHigh:
    def test_sets_approved_true_on_high_candidates(self, tmp_path: Path) -> None:
        candidates = [
            _make_candidate("customs territory", frequency=5, pmi=15.0),
            _make_candidate("border crossing", frequency=1, pmi=2.0),
        ]
        p = tmp_path / "cands.jsonl"
        _write_jsonl(p, candidates)

        high_records = [candidates[0]]
        n = auto_approve_high(p, high_records)
        assert n == 1

        updated = load_candidates(p)
        by_phrase = {r["phrase"]: r for r in updated}
        assert by_phrase["customs territory"]["approved"] is True
        assert "approved" not in by_phrase["border crossing"]

    def test_does_not_modify_low_records(self, tmp_path: Path) -> None:
        candidates = [
            _make_candidate("low term", frequency=1, pmi=2.0),
        ]
        p = tmp_path / "cands.jsonl"
        _write_jsonl(p, candidates)
        n = auto_approve_high(p, [])
        assert n == 0
        updated = load_candidates(p)
        assert "approved" not in updated[0]

    def test_returns_count_of_approved(self, tmp_path: Path) -> None:
        candidates = [
            _make_candidate("a", frequency=5, pmi=15.0),
            _make_candidate("b", frequency=6, pmi=16.0),
            _make_candidate("c", frequency=1, pmi=2.0),
        ]
        p = tmp_path / "cands.jsonl"
        _write_jsonl(p, candidates)
        n = auto_approve_high(p, candidates[:2])
        assert n == 2

    def test_preserves_all_records(self, tmp_path: Path) -> None:
        candidates = [_make_candidate(f"term{i}", frequency=5, pmi=15.0) for i in range(5)]
        p = tmp_path / "cands.jsonl"
        _write_jsonl(p, candidates)
        auto_approve_high(p, candidates[:2])
        updated = load_candidates(p)
        assert len(updated) == 5


# ---------------------------------------------------------------------------
# _auto_ne_path()
# ---------------------------------------------------------------------------


class TestAutoNePath:
    def test_detects_ne_from_statistical_candidates_name(self, tmp_path: Path) -> None:
        ne = tmp_path / "ucc_ne_candidates.jsonl"
        ne.write_text("{}\n", encoding="utf-8")
        result = _auto_ne_path(tmp_path / "ucc_statistical_candidates.jsonl")
        assert result == ne

    def test_detects_ne_from_mwe_name(self, tmp_path: Path) -> None:
        # 'cbam_mwe_en.jsonl' → 'cbam_ne_en.jsonl' (replaces 'mwe' with 'ne', keeps lang suffix)
        ne = tmp_path / "cbam_ne_en.jsonl"
        ne.write_text("{}\n", encoding="utf-8")
        result = _auto_ne_path(tmp_path / "cbam_mwe_en.jsonl")
        assert result == ne

    def test_returns_none_if_ne_file_missing(self, tmp_path: Path) -> None:
        result = _auto_ne_path(tmp_path / "cbam_mwe_en.jsonl")
        assert result is None

    def test_returns_none_for_unrecognised_pattern(self, tmp_path: Path) -> None:
        result = _auto_ne_path(tmp_path / "random_file.jsonl")
        assert result is None
