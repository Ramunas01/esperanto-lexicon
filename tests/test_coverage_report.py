"""Tests for src/analyzer/coverage_report.py.

All tests bypass spaCy by constructing SimpleToken lists directly and calling
classify_tokens / compute_summary.  No external files or models required.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from analyzer.coverage_report import (
    SimpleToken,
    TokenResult,
    classify_tokens,
    compute_summary,
    load_mwe_phrases,
    load_tier_words,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tok(text: str, lemma: str | None = None, skip: bool = False) -> SimpleToken:
    return SimpleToken(text=text, lemma=lemma or text, is_skip=skip)


def _skip(text: str) -> SimpleToken:
    return _tok(text, skip=True)


# ---------------------------------------------------------------------------
# classify_tokens — basic categories
# ---------------------------------------------------------------------------


class TestBasicClassification:
    def test_tier1_matched_by_text(self) -> None:
        tokens = [_tok("kuris")]
        results = classify_tokens(tokens, set(), {"kuris"}, set())
        assert results[0].category == "TIER1"

    def test_tier1_matched_by_lemma(self) -> None:
        # Text is inflected but lemma matches the tier1 word
        tokens = [_tok("einantys", lemma="eiti")]
        results = classify_tokens(tokens, set(), {"eiti"}, set())
        assert results[0].category == "TIER1"

    def test_tier2_matched(self) -> None:
        tokens = [_tok("gyventojas")]
        results = classify_tokens(tokens, set(), set(), {"gyventojas"})
        assert results[0].category == "TIER2"

    def test_unknown_token(self) -> None:
        tokens = [_tok("xyzunknownword")]
        results = classify_tokens(tokens, set(), set(), set())
        assert results[0].category == "UNKNOWN"

    def test_skip_token_passed_through(self) -> None:
        tokens = [_skip(",")]
        results = classify_tokens(tokens, set(), set(), set())
        assert results[0].category == "SKIP"
        assert results[0].text == ","

    def test_skip_does_not_count_as_mwe_component(self) -> None:
        # A skip token between two content words must not form a bigram
        tokens = [_tok("individuali"), _skip(","), _tok("veikla")]
        mwe = {"individuali veikla"}
        results = classify_tokens(tokens, mwe, set(), set())
        # Comma is SKIP; "individuali" and "veikla" cannot form a bigram across it
        categories = [r.category for r in results]
        assert "TIER4" not in categories or results[0].n_tokens < 2


# ---------------------------------------------------------------------------
# classify_tokens — greedy MWE matching
# ---------------------------------------------------------------------------


class TestGreedyMweMatching:
    def test_bigram_beats_two_unknowns(self) -> None:
        tokens = [_tok("individuali"), _tok("veikla")]
        mwe = {"individuali veikla"}
        results = classify_tokens(tokens, mwe, set(), set())
        assert len(results) == 1
        assert results[0].category == "TIER4"
        assert results[0].n_tokens == 2
        assert results[0].text == "individuali veikla"

    def test_trigram_beats_bigram(self) -> None:
        tokens = [_tok("pajamos"), _tok("natūra"), _tok("lietuvoje")]
        mwe = {"pajamos natūra lietuvoje", "pajamos natūra"}
        results = classify_tokens(tokens, mwe, set(), set())
        # Trigram should win over bigram
        assert len(results) == 1
        assert results[0].category == "TIER4"
        assert results[0].n_tokens == 3

    def test_bigram_preferred_over_two_tier2(self) -> None:
        tokens = [_tok("pajamos"), _tok("natūra")]
        mwe = {"pajamos natūra"}
        tier2 = {"pajamos", "natūra"}
        results = classify_tokens(tokens, mwe, set(), tier2)
        # MWE window tried first → TIER4
        assert len(results) == 1
        assert results[0].category == "TIER4"

    def test_unigram_mwe_match(self) -> None:
        tokens = [_tok("gyventojas")]
        mwe = {"gyventojas"}
        results = classify_tokens(tokens, mwe, set(), set())
        assert results[0].category == "TIER4"
        assert results[0].n_tokens == 1

    def test_lemma_based_mwe_match(self) -> None:
        # Phrase stored as lemma forms; input uses inflected text
        tokens = [_tok("individualia", lemma="individuali"), _tok("veikla", lemma="veikla")]
        mwe = {"individuali veikla"}
        results = classify_tokens(tokens, mwe, set(), set())
        assert len(results) == 1
        assert results[0].category == "TIER4"

    def test_remaining_tokens_after_mwe_classified(self) -> None:
        tokens = [_tok("pajamos"), _tok("natūra"), _tok("yra"), _tok("xyzunknown")]
        mwe = {"pajamos natūra"}
        tier1 = {"yra"}
        results = classify_tokens(tokens, mwe, tier1, set())
        assert results[0].category == "TIER4"
        assert results[0].n_tokens == 2
        assert results[1].category == "TIER1"
        assert results[2].category == "UNKNOWN"

    def test_mwe_not_matched_across_skip_tokens(self) -> None:
        tokens = [_tok("pajamos"), _skip("–"), _tok("natūra")]
        mwe = {"pajamos natūra"}
        results = classify_tokens(tokens, mwe, set(), set())
        # Skip token prevents window formation
        assert results[1].category == "SKIP"
        assert results[0].category != "TIER4" or results[0].n_tokens < 2

    def test_empty_token_list(self) -> None:
        assert classify_tokens([], set(), set(), set()) == []

    def test_all_skip_tokens(self) -> None:
        tokens = [_skip("."), _skip(","), _skip("!")]
        results = classify_tokens(tokens, set(), set(), set())
        assert all(r.category == "SKIP" for r in results)


# ---------------------------------------------------------------------------
# compute_summary — ratio and interpretation
# ---------------------------------------------------------------------------


class TestComputeSummary:
    def _results(self, *categories: str) -> list[TokenResult]:
        return [TokenResult(text=f"w{i}", lemma="w", category=c) for i, c in enumerate(categories)]

    def test_general_audience_interpretation(self) -> None:
        # Many TIER1/2, zero TIER4 → ratio = 0.0 < 0.05
        results = self._results("TIER1", "TIER1", "TIER2", "TIER2", "UNKNOWN")
        summary = compute_summary(results)
        assert summary["expertise_signal"]["interpretation"] == "general audience"

    def test_specialist_interpretation(self) -> None:
        # 4 TIER4 vs 4 common → ratio = 0.5 > 0.20
        results = self._results("TIER1", "TIER1", "TIER2", "TIER2",
                                "TIER4", "TIER4", "TIER4", "TIER4")
        summary = compute_summary(results)
        assert summary["expertise_signal"]["interpretation"] == "specialist"

    def test_mixed_audience_interpretation(self) -> None:
        # 1 TIER4 among 8 → ratio = 0.125 (0.05–0.20)
        results = self._results("TIER1", "TIER1", "TIER2", "TIER2",
                                "TIER2", "TIER2", "TIER2", "TIER4")
        summary = compute_summary(results)
        assert summary["expertise_signal"]["interpretation"] == "mixed audience"

    def test_skip_not_counted_in_total(self) -> None:
        results = self._results("TIER1", "SKIP", "SKIP", "SKIP")
        summary = compute_summary(results)
        # Total classified = 1, skip = 3 → common_pct = 1.0
        assert summary["expertise_signal"]["common_pct"] == 1.0
        assert summary["counts"]["SKIP"] == 3

    def test_ratio_calculation(self) -> None:
        # 2 common, 1 domain → ratio = 0.5
        results = self._results("TIER1", "TIER2", "TIER4")
        summary = compute_summary(results)
        assert abs(summary["expertise_signal"]["ratio"] - 0.5) < 1e-4

    def test_zero_common_words(self) -> None:
        # All TIER4 or UNKNOWN — ratio defaults to 0.0 (no common words)
        results = self._results("TIER4", "UNKNOWN")
        summary = compute_summary(results)
        assert summary["expertise_signal"]["ratio"] == 0.0

    def test_empty_results(self) -> None:
        summary = compute_summary([])
        assert summary["expertise_signal"]["ratio"] == 0.0
        assert summary["counts"]["TIER1"] == 0

    def test_counts_correct(self) -> None:
        results = self._results("TIER1", "TIER1", "TIER4", "UNKNOWN", "SKIP")
        summary = compute_summary(results)
        assert summary["counts"] == {"TIER1": 2, "TIER2": 0, "TIER4": 1, "UNKNOWN": 1, "SKIP": 1}


# ---------------------------------------------------------------------------
# load helpers — require no external files when DB absent
# ---------------------------------------------------------------------------


class TestLoadHelpers:
    def test_tier_words_absent_db(self, tmp_path: Path) -> None:
        t1, t2 = load_tier_words(tmp_path / "none.db", "lt")
        assert t1 == set()
        assert t2 == set()

    def test_mwe_phrases_absent_db(self, tmp_path: Path) -> None:
        phrases = load_mwe_phrases(tmp_path / "none.db", "lt")
        assert phrases == set()

    def test_mwe_phrases_none_db(self) -> None:
        phrases = load_mwe_phrases(None, "lt")
        assert phrases == set()
