"""Unit tests for batch_coverage_report measure-computation functions."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src" / "analyzer"))

from batch_coverage_report import distinct_t4_count, sentence_cooccur_stats
from coverage_report import TokenResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _t4(text: str, matched_phrase: str | None = None) -> TokenResult:
    return TokenResult(
        text=text,
        lemma=text,
        category="TIER4",
        matched_phrase=matched_phrase,
    )


def _t1(text: str) -> TokenResult:
    return TokenResult(text=text, lemma=text, category="TIER1")


def _t2(text: str) -> TokenResult:
    return TokenResult(text=text, lemma=text, category="TIER2")


def _unk(text: str) -> TokenResult:
    return TokenResult(text=text, lemma=text, category="UNKNOWN")


# ---------------------------------------------------------------------------
# distinct_t4_count
# ---------------------------------------------------------------------------


class TestDistinctT4Count:
    def test_empty_returns_zero(self) -> None:
        assert distinct_t4_count([]) == 0

    def test_no_t4_returns_zero(self) -> None:
        results = [_t1("the"), _t2("import"), _unk("flibbertigibbet")]
        assert distinct_t4_count(results) == 0

    def test_single_t4(self) -> None:
        assert distinct_t4_count([_t4("customs duty", "customs duty")]) == 1

    def test_concept_repeated_five_times_counts_as_one(self) -> None:
        # The same matched_phrase repeated 5× must deduplicate to 1.
        results = [_t4("customs duty", "customs duty")] * 5
        assert distinct_t4_count(results) == 1

    def test_two_distinct_phrases(self) -> None:
        results = [
            _t4("customs duty", "customs duty"),
            _t4("customs duty", "customs duty"),
            _t4("export licence", "export licence"),
        ]
        assert distinct_t4_count(results) == 2

    def test_fallback_to_text_lower_when_no_matched_phrase(self) -> None:
        # When matched_phrase is None, text.lower() is used as the key.
        results = [
            _t4("Customs"),   # matched_phrase=None → "customs"
            _t4("customs"),   # matched_phrase=None → "customs"  (same key)
            _t4("tariff"),    # matched_phrase=None → "tariff"
        ]
        assert distinct_t4_count(results) == 2

    def test_mixed_phrase_and_text_dedup(self) -> None:
        # matched_phrase takes priority; two different texts with same matched_phrase → 1
        results = [
            _t4("customs duties", "customs duty"),
            _t4("customs duty", "customs duty"),
        ]
        assert distinct_t4_count(results) == 1

    def test_non_t4_tokens_ignored(self) -> None:
        results = [
            _t1("the"),
            _t4("export licence", "export licence"),
            _t2("national"),
            _t4("tariff", "tariff"),
            _unk("blockchain"),
        ]
        assert distinct_t4_count(results) == 2


# ---------------------------------------------------------------------------
# sentence_cooccur_stats
# ---------------------------------------------------------------------------


class TestSentenceCooccurStats:
    def test_empty_sentences_all_zero(self) -> None:
        cooccur_pairs, n_any, n_multi = sentence_cooccur_stats([])
        assert cooccur_pairs == 0
        assert n_any == 0
        assert n_multi == 0

    def test_sentence_with_no_t4(self) -> None:
        sent = [_t1("the"), _t2("goods")]
        cooccur_pairs, n_any, n_multi = sentence_cooccur_stats([sent])
        assert cooccur_pairs == 0
        assert n_any == 0
        assert n_multi == 0

    def test_sentence_with_one_t4_concept(self) -> None:
        sent = [_t4("customs duty", "customs duty"), _t1("is")]
        cooccur_pairs, n_any, n_multi = sentence_cooccur_stats([sent])
        assert cooccur_pairs == 0
        assert n_any == 1
        assert n_multi == 0

    def test_three_distinct_concepts_give_three_pairs(self) -> None:
        # C(3, 2) = 3
        sent = [
            _t4("customs duty", "customs duty"),
            _t4("export licence", "export licence"),
            _t4("tariff quota", "tariff quota"),
        ]
        cooccur_pairs, n_any, n_multi = sentence_cooccur_stats([sent])
        assert cooccur_pairs == 3
        assert n_any == 1
        assert n_multi == 1

    def test_two_concepts_give_one_pair(self) -> None:
        sent = [
            _t4("customs duty", "customs duty"),
            _t4("tariff", "tariff"),
        ]
        cooccur_pairs, n_any, n_multi = sentence_cooccur_stats([sent])
        assert cooccur_pairs == 1
        assert n_any == 1
        assert n_multi == 1

    def test_repeated_concept_in_sentence_counts_once(self) -> None:
        # Same matched_phrase twice → still only 1 distinct concept → 0 pairs.
        sent = [
            _t4("customs duty", "customs duty"),
            _t4("customs duties", "customs duty"),
        ]
        cooccur_pairs, n_any, n_multi = sentence_cooccur_stats([sent])
        assert cooccur_pairs == 0
        assert n_any == 1
        assert n_multi == 0

    def test_four_concepts_give_six_pairs(self) -> None:
        # C(4, 2) = 6
        sent = [
            _t4("a", "a"),
            _t4("b", "b"),
            _t4("c", "c"),
            _t4("d", "d"),
        ]
        cooccur_pairs, n_any, n_multi = sentence_cooccur_stats([sent])
        assert cooccur_pairs == 6

    def test_multiple_sentences_aggregate(self) -> None:
        # sent1: 0 T4 → 0 pairs, n_any=0, n_multi=0
        # sent2: 1 T4 → 0 pairs, n_any+=1, n_multi+=0
        # sent3: 3 T4 → 3 pairs, n_any+=1, n_multi+=1
        sent1 = [_t1("hello")]
        sent2 = [_t4("customs duty", "customs duty")]
        sent3 = [_t4("a", "a"), _t4("b", "b"), _t4("c", "c")]
        cooccur_pairs, n_any, n_multi = sentence_cooccur_stats([sent1, sent2, sent3])
        assert cooccur_pairs == 3
        assert n_any == 2
        assert n_multi == 1


# ---------------------------------------------------------------------------
# multi_concept_ratio
# ---------------------------------------------------------------------------


class TestMultiConceptRatio:
    """Verify multi_concept_ratio = sentences(k≥2) / sentences(k≥1) on synthetic input."""

    def _ratio(self, per_sentence: list[list[TokenResult]]) -> float:
        _, n_any, n_multi = sentence_cooccur_stats(per_sentence)
        return round(n_multi / max(n_any, 1), 4)

    def test_all_single_concept_sentences(self) -> None:
        # 3 sentences each with 1 T4 concept → ratio = 0/3 = 0.0
        sents = [[_t4("a", "a")], [_t4("b", "b")], [_t4("c", "c")]]
        assert self._ratio(sents) == 0.0

    def test_all_multi_concept_sentences(self) -> None:
        # 2 sentences each with 2 T4 concepts → ratio = 2/2 = 1.0
        sents = [
            [_t4("a", "a"), _t4("b", "b")],
            [_t4("c", "c"), _t4("d", "d")],
        ]
        assert self._ratio(sents) == 1.0

    def test_mixed_sentences(self) -> None:
        # 4 sentences with T4 concepts: 1, 2, 1, 3
        # n_any=4, n_multi=2 (the 2- and 3-concept sentences) → ratio = 2/4 = 0.5
        sents = [
            [_t4("a", "a")],
            [_t4("b", "b"), _t4("c", "c")],
            [_t4("d", "d")],
            [_t4("e", "e"), _t4("f", "f"), _t4("g", "g")],
        ]
        assert self._ratio(sents) == 0.5

    def test_no_t4_sentences_returns_zero(self) -> None:
        sents = [[_t1("the"), _t2("goods")], [_t1("is")]]
        assert self._ratio(sents) == 0.0

    def test_empty_input_returns_zero(self) -> None:
        assert self._ratio([]) == 0.0
