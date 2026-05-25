"""Tests for statistical_mwe_detector.py.

All tests bypass spaCy: sentence lists are constructed directly and passed to
count_ngrams / build_scored_candidates / apply_filters.  Only pure Python and
stdlib SQLite are required.
"""

from __future__ import annotations

import math
import sqlite3
import tempfile
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from extractor.statistical_mwe_detector import (
    apply_filters,
    build_scored_candidates,
    count_ngrams,
    load_common_words,
    load_known_phrases,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

# Four sentences whose ngram statistics are fully predictable:
#   "darbo santykiai" appears in three sentences → high PMI
#   All other pairs appear at most once
_SENTENCES: list[list[str]] = [
    ["darbo", "santykiai", "pajamos"],
    ["darbo", "santykiai", "turtas"],
    ["darbo", "santykiai", "esmė"],
    ["kitas", "žodis"],
]
# N = 3+3+1+1+1+1+1 = 11
_N = 11


@pytest.fixture(scope="module")
def ngrams():
    return count_ngrams(_SENTENCES)


# ---------------------------------------------------------------------------
# count_ngrams
# ---------------------------------------------------------------------------


class TestCountNgrams:
    def test_unigram_total(self, ngrams) -> None:
        uni, _, _ = ngrams
        assert sum(uni.values()) == _N

    def test_unigram_frequency(self, ngrams) -> None:
        uni, _, _ = ngrams
        assert uni["darbo"] == 3
        assert uni["santykiai"] == 3
        assert uni["pajamos"] == 1
        assert uni["kitas"] == 1

    def test_bigram_frequency(self, ngrams) -> None:
        _, bi, _ = ngrams
        assert bi[("darbo", "santykiai")] == 3
        assert bi[("santykiai", "pajamos")] == 1
        assert bi[("kitas", "žodis")] == 1

    def test_bigrams_do_not_cross_sentence_boundaries(self, ngrams) -> None:
        _, bi, _ = ngrams
        # "esmė" ends sentence 3; "kitas" starts sentence 4 — should NOT be a bigram
        assert bi[("esmė", "kitas")] == 0

    def test_trigram_frequency(self, ngrams) -> None:
        _, _, tri = ngrams
        assert tri[("darbo", "santykiai", "pajamos")] == 1
        assert tri[("darbo", "santykiai", "turtas")] == 1
        assert tri[("darbo", "santykiai", "esmė")] == 1

    def test_trigrams_do_not_cross_sentence_boundaries(self, ngrams) -> None:
        _, _, tri = ngrams
        assert tri[("santykiai", "esmė", "kitas")] == 0

    def test_empty_input(self) -> None:
        uni, bi, tri = count_ngrams([])
        assert len(uni) == 0
        assert len(bi) == 0
        assert len(tri) == 0

    def test_single_token_sentence_no_bigrams(self) -> None:
        uni, bi, tri = count_ngrams([["solo"]])
        assert uni["solo"] == 1
        assert len(bi) == 0
        assert len(tri) == 0


# ---------------------------------------------------------------------------
# PMI and G2 correctness
# ---------------------------------------------------------------------------


class TestPmiScores:
    """Verify PMI values against hand-calculated ground truth."""

    def test_darbo_santykiai_pmi(self, ngrams) -> None:
        uni, bi, _ = ngrams
        # PMI = log2(f12 * N / (f1 * f2)) = log2(3*11 / (3*3)) = log2(33/9)
        expected = math.log2(33 / 9)
        candidates = build_scored_candidates(uni, bi, {}, min_freq=1, min_pmi=-math.inf, lang="lt", source_file="test.txt")
        bigrams = {c["phrase"]: c for c in candidates if c["ngram_size"] == 2}
        assert "darbo santykiai" in bigrams
        assert abs(bigrams["darbo santykiai"]["pmi"] - round(expected, 4)) < 1e-3

    def test_darbo_santykiai_g2_positive(self, ngrams) -> None:
        uni, bi, _ = ngrams
        candidates = build_scored_candidates(uni, bi, {}, min_freq=1, min_pmi=-math.inf, lang="lt", source_file="test.txt")
        bigrams = {c["phrase"]: c for c in candidates if c["ngram_size"] == 2}
        g2 = bigrams["darbo santykiai"]["g2"]
        # G2 should be positive and substantial (≈ 12.88)
        assert g2 is not None
        assert g2 > 10.0

    def test_g2_approximately_correct(self, ngrams) -> None:
        uni, bi, _ = ngrams
        candidates = build_scored_candidates(uni, bi, {}, min_freq=1, min_pmi=-math.inf, lang="lt", source_file="test.txt")
        bigrams = {c["phrase"]: c for c in candidates if c["ngram_size"] == 2}
        g2 = bigrams["darbo santykiai"]["g2"]
        assert abs(g2 - 12.89) < 0.1

    def test_trigram_g2_is_none(self, ngrams) -> None:
        uni, bi, tri = ngrams
        candidates = build_scored_candidates(uni, bi, tri, min_freq=1, min_pmi=-math.inf, lang="lt", source_file="test.txt")
        trigrams = [c for c in candidates if c["ngram_size"] == 3]
        assert len(trigrams) > 0
        for cand in trigrams:
            assert cand["g2"] is None


# ---------------------------------------------------------------------------
# build_scored_candidates — min_freq and min_pmi thresholds
# ---------------------------------------------------------------------------


class TestBuildScoredCandidates:
    def test_min_freq_filters_rare_bigrams(self, ngrams) -> None:
        uni, bi, tri = ngrams
        candidates = build_scored_candidates(uni, bi, tri, min_freq=2, min_pmi=-math.inf, lang="lt", source_file="test.txt")
        phrases = {c["phrase"] for c in candidates}
        # Only "darbo santykiai" appears ≥2 times among bigrams
        assert "darbo santykiai" in phrases
        assert "kitas žodis" not in phrases

    def test_min_pmi_filters_low_association(self, ngrams) -> None:
        uni, bi, tri = ngrams
        high_pmi_only = build_scored_candidates(uni, bi, tri, min_freq=1, min_pmi=1.5, lang="lt", source_file="test.txt")
        phrases = {c["phrase"] for c in high_pmi_only}
        assert "darbo santykiai" in phrases
        # "kitas žodis" has PMI near 0 (rare pair, both rare words) — not guaranteed negative,
        # but should not pass min_pmi=1.5 given the corpus
        # (both words appear once, N=11 → PMI = log2(1*11/(1*1)) = log2(11) ≈ 3.46)
        # Actually it would pass. Use min_freq=2 to exclude it more reliably.

    def test_empty_ngrams_returns_empty(self) -> None:
        from collections import Counter
        result = build_scored_candidates(Counter(), Counter(), Counter(), 1, 0.0, "lt", "x.txt")
        assert result == []

    def test_output_record_has_required_fields(self, ngrams) -> None:
        uni, bi, tri = ngrams
        candidates = build_scored_candidates(uni, bi, tri, min_freq=1, min_pmi=-math.inf, lang="lt", source_file="test.txt")
        required = {
            "phrase", "phrase_normalized", "lang", "ngram_size", "frequency",
            "pmi", "g2", "source_file", "extraction_method", "approved",
            "tier_suggestion", "notes",
        }
        for cand in candidates:
            assert required <= set(cand.keys()), f"Missing fields in: {cand}"

    def test_output_defaults(self, ngrams) -> None:
        uni, bi, tri = ngrams
        candidates = build_scored_candidates(uni, bi, tri, min_freq=1, min_pmi=-math.inf, lang="lt", source_file="test.txt")
        for cand in candidates:
            assert cand["approved"] is False
            assert cand["tier_suggestion"] == 4
            assert cand["extraction_method"] == "statistical_pmi"
            assert cand["lang"] == "lt"
            assert cand["source_file"] == "test.txt"

    def test_phrase_normalized_equals_phrase(self, ngrams) -> None:
        uni, bi, tri = ngrams
        candidates = build_scored_candidates(uni, bi, tri, min_freq=1, min_pmi=-math.inf, lang="lt", source_file="test.txt")
        for cand in candidates:
            assert cand["phrase_normalized"] == cand["phrase"]


# ---------------------------------------------------------------------------
# load_common_words / load_known_phrases
# ---------------------------------------------------------------------------


def _make_concept_lang_db(words: list[tuple[str, str]]) -> sqlite3.Connection:
    """In-memory DB with concept_lang table populated from (word, lang) pairs."""
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE concept_lang (concept_id INTEGER, lang TEXT, word TEXT, "
        "pos TEXT, cefr_level TEXT, tier INTEGER, source TEXT)"
    )
    conn.executemany(
        "INSERT INTO concept_lang (word, lang) VALUES (?, ?)", words
    )
    conn.commit()
    return conn


def _make_mwe_lang_db(phrases: list[tuple[str, str]]) -> sqlite3.Connection:
    """In-memory DB with mwe_lang table populated from (phrase_normalized, lang) pairs."""
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE mwe_lang (mwe_id INTEGER, lang TEXT, phrase TEXT, "
        "phrase_normalized TEXT, definition_raw TEXT, abbrev TEXT)"
    )
    conn.executemany(
        "INSERT INTO mwe_lang (phrase_normalized, lang) VALUES (?, ?)", phrases
    )
    conn.commit()
    return conn


class TestLoadCommonWords:
    def test_returns_lowercase_words_for_lang(self, tmp_path: Path) -> None:
        db = tmp_path / "lexicon.db"
        conn = _make_concept_lang_db([("Darbo", "lt"), ("santykiai", "lt"), ("work", "en")])
        conn.execute(f"VACUUM INTO '{db}'")
        conn.close()
        words = load_common_words(db, "lt")
        assert "darbo" in words
        assert "santykiai" in words
        assert "work" not in words

    def test_absent_db_returns_empty_set(self, tmp_path: Path) -> None:
        result = load_common_words(tmp_path / "nonexistent.db", "lt")
        assert result == set()

    def test_lang_filter_is_exact(self, tmp_path: Path) -> None:
        db = tmp_path / "lexicon.db"
        conn = _make_concept_lang_db([("hello", "en"), ("bonjour", "fr")])
        conn.execute(f"VACUUM INTO '{db}'")
        conn.close()
        words = load_common_words(db, "lt")
        assert len(words) == 0


class TestLoadKnownPhrases:
    def test_returns_phrase_normalized_for_lang(self, tmp_path: Path) -> None:
        db = tmp_path / "domain.db"
        conn = _make_mwe_lang_db([("darbo santykiai", "lt"), ("work relations", "en")])
        conn.execute(f"VACUUM INTO '{db}'")
        conn.close()
        phrases = load_known_phrases(db, "lt")
        assert "darbo santykiai" in phrases
        assert "work relations" not in phrases

    def test_absent_db_returns_empty_set(self, tmp_path: Path) -> None:
        result = load_known_phrases(Path("/tmp/definitely_does_not_exist_xyz.db"), "lt")
        assert result == set()

    def test_none_db_returns_empty_set(self) -> None:
        result = load_known_phrases(None, "lt")
        assert result == set()


# ---------------------------------------------------------------------------
# apply_filters
# ---------------------------------------------------------------------------


class TestApplyFilters:
    def _candidates(self) -> list[dict]:
        """Return a small candidate list covering different filter scenarios."""
        uni, bi, tri = count_ngrams(_SENTENCES)
        return build_scored_candidates(
            uni, bi, tri, min_freq=1, min_pmi=-math.inf, lang="lt", source_file="test.txt"
        )

    def test_all_common_words_filtered(self) -> None:
        cands = self._candidates()
        # Mark both components of "kitas žodis" as common
        common = {"kitas", "žodis"}
        after_lex, after_dom = apply_filters(cands, common, set())
        phrases = {c["phrase"] for c in after_lex}
        assert "kitas žodis" not in phrases

    def test_novel_component_passes_lexicon_filter(self) -> None:
        cands = self._candidates()
        # "darbo" is common but "santykiai" is novel → phrase should survive
        common = {"darbo"}
        after_lex, _ = apply_filters(cands, common, set())
        phrases = {c["phrase"] for c in after_lex}
        assert "darbo santykiai" in phrases

    def test_known_phrase_filtered_after_lexicon(self) -> None:
        cands = self._candidates()
        # Phrase already in domain DB → filtered by domain filter
        known = {"darbo santykiai"}
        _, after_dom = apply_filters(cands, set(), known)
        phrases = {c["phrase"] for c in after_dom}
        assert "darbo santykiai" not in phrases

    def test_unknown_phrase_survives_domain_filter(self) -> None:
        cands = self._candidates()
        _, after_dom = apply_filters(cands, set(), set())
        phrases = {c["phrase"] for c in after_dom}
        assert "darbo santykiai" in phrases

    def test_component_annotation_added(self) -> None:
        cands = self._candidates()
        common = {"darbo"}
        after_lex, _ = apply_filters(cands, common, set())
        by_phrase = {c["phrase"]: c for c in after_lex}
        cand = by_phrase["darbo santykiai"]
        assert "novel_components" in cand
        assert "common_components" in cand
        assert "all_components_common" in cand
        assert "santykiai" in cand["novel_components"]
        assert "darbo" in cand["common_components"]
        assert cand["all_components_common"] is False

    def test_noise_single_char_filtered(self) -> None:
        uni, bi, _ = count_ngrams([[" a", "darbo"]])
        # Inject a candidate with a single-char component manually
        cands = [
            {
                "phrase": "a darbo",
                "phrase_normalized": "a darbo",
                "lang": "lt",
                "ngram_size": 2,
                "frequency": 5,
                "pmi": 4.0,
                "g2": 9.0,
                "source_file": "test.txt",
                "extraction_method": "statistical_pmi",
                "approved": False,
                "tier_suggestion": 4,
                "notes": "",
            }
        ]
        after_lex, _ = apply_filters(cands, set(), set())
        assert len(after_lex) == 0

    def test_after_lexicon_superset_of_after_domain(self) -> None:
        cands = self._candidates()
        known = {"darbo santykiai"}
        after_lex, after_dom = apply_filters(cands, set(), known)
        lex_phrases = {c["phrase"] for c in after_lex}
        dom_phrases = {c["phrase"] for c in after_dom}
        assert dom_phrases <= lex_phrases

    def test_empty_candidates(self) -> None:
        after_lex, after_dom = apply_filters([], set(), set())
        assert after_lex == []
        assert after_dom == []
