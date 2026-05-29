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
    load_inflected_forms,
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
        assert summary["counts"] == {"TIER1": 2, "TIER2": 0, "TIER3": 0, "TIER4": 1, "UNKNOWN": 1, "SKIP": 1}


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


# ---------------------------------------------------------------------------
# load_inflected_forms
# ---------------------------------------------------------------------------


class TestLoadInflectedForms:
    def _make_db(self, tmp_path: Path, rows: list[tuple]) -> Path:
        """Create a minimal lexicon DB with inflected_forms table."""
        import sqlite3
        db = tmp_path / "lex.db"
        conn = sqlite3.connect(db)
        conn.execute(
            "CREATE TABLE inflected_forms "
            "(inflected_word TEXT, lemma TEXT, lang TEXT, form_description TEXT, tier INTEGER)"
        )
        conn.executemany("INSERT INTO inflected_forms VALUES (?,?,?,?,?)", rows)
        conn.commit()
        conn.close()
        return db

    def test_absent_db_returns_empty(self, tmp_path: Path) -> None:
        result = load_inflected_forms(tmp_path / "none.db", "en")
        assert result == {}

    def test_only_meaningful_mappings_loaded(self, tmp_path: Path) -> None:
        db = self._make_db(tmp_path, [
            ("is", "be", "en", "3sg present", 1),
            ("is", "is", "en", "self", 1),   # self-referential — must be excluded
            ("are", "be", "en", "plural present", 1),
            ("are", "are", "en", "self", 1),  # self-referential — must be excluded
        ])
        result = load_inflected_forms(db, "en")
        assert result == {"is": "be", "are": "be"}

    def test_self_referential_only_returns_nothing(self, tmp_path: Path) -> None:
        db = self._make_db(tmp_path, [
            ("have", "have", "en", "self", 1),
        ])
        result = load_inflected_forms(db, "en")
        assert result == {}

    def test_lang_filter_applied(self, tmp_path: Path) -> None:
        db = self._make_db(tmp_path, [
            ("yra", "būti", "lt", "3sg present", 1),
            ("is", "be", "en", "3sg present", 1),
        ])
        lt_result = load_inflected_forms(db, "lt")
        en_result = load_inflected_forms(db, "en")
        assert lt_result == {"yra": "būti"}
        assert en_result == {"is": "be"}

    def test_keys_lowercased(self, tmp_path: Path) -> None:
        db = self._make_db(tmp_path, [
            ("Were", "be", "en", "past plural", 1),
        ])
        result = load_inflected_forms(db, "en")
        assert "were" in result
        assert result["were"] == "be"


# ---------------------------------------------------------------------------
# classify_tokens — inflected_forms lookup (steps 3-4)
# ---------------------------------------------------------------------------


class TestInflectedFormsClassification:
    """Tests for the inflected_forms lookup path in classify_tokens."""

    def _classify(
        self,
        tokens: list[SimpleToken],
        *,
        tier1: set[str] | None = None,
        tier2: set[str] | None = None,
        inflected: dict[str, str] | None = None,
    ) -> list[TokenResult]:
        return classify_tokens(
            tokens,
            mwe_phrases=set(),
            tier1_words=tier1 or set(),
            tier2_words=tier2 or set(),
            inflected_forms=inflected,
        )

    def test_inflected_to_tier1_via_text(self) -> None:
        # 'is' not in tier1 directly; inflected_forms maps 'is' → 'be'; 'be' in tier1
        tokens = [_tok("is", "is")]
        result = self._classify(
            tokens,
            tier1={"be"},
            inflected={"is": "be"},
        )
        assert result[0].category == "TIER1"

    def test_inflected_to_tier1_via_spacy_lemma(self) -> None:
        # spaCy gives lemma 'be' for 'are', but 'are' not in tier1; 'are' in inflected
        # This tests step 4: tok.lemma_ in inflected_forms
        tokens = [_tok("are", "be")]  # spaCy lemma is already 'be'
        # Step 2 (lemma 'be' in tier1) wins here — test step 4 with a different lemma
        tokens = [_tok("were", "be_wrong")]  # spaCy gives wrong lemma; text 'were' in inflected
        result = self._classify(
            tokens,
            tier1={"be"},
            inflected={"were": "be"},
        )
        assert result[0].category == "TIER1"

    def test_inflected_to_tier2(self) -> None:
        tokens = [_tok("was", "was")]
        result = self._classify(
            tokens,
            tier2={"be"},
            inflected={"was": "be"},
        )
        assert result[0].category == "TIER2"

    def test_inflected_lemma_path_step4(self) -> None:
        # tok.text 'xyz' not in inflected; tok.lemma 'had' is in inflected → 'have' → tier1
        tokens = [_tok("xyz", "had")]
        result = self._classify(
            tokens,
            tier1={"have"},
            inflected={"had": "have"},
        )
        assert result[0].category == "TIER1"

    def test_direct_match_wins_over_inflected(self) -> None:
        # 'is' is directly in tier1 — inflected_forms should not be needed
        tokens = [_tok("is", "is")]
        result = self._classify(
            tokens,
            tier1={"is"},
            inflected={"is": "be"},  # 'be' is NOT in tier1, but 'is' is
        )
        assert result[0].category == "TIER1"

    def test_unknown_when_inflected_canon_not_in_tiers(self) -> None:
        # inflected maps 'are' → 'be', but 'be' not in tier1 or tier2
        tokens = [_tok("are", "are")]
        result = self._classify(
            tokens,
            tier1={"cat"},
            inflected={"are": "be"},
        )
        assert result[0].category == "UNKNOWN"

    def test_no_inflected_forms_still_unknown(self) -> None:
        tokens = [_tok("is", "is")]
        result = self._classify(tokens, tier1={"be"}, inflected=None)
        assert result[0].category == "UNKNOWN"

    def test_inflected_forms_does_not_affect_mwe(self) -> None:
        # MWE matching should be unaffected by inflected_forms
        tokens = [_tok("customs", "customs"), _tok("duty", "duty")]
        result = classify_tokens(
            tokens,
            mwe_phrases={"customs duty"},
            tier1_words=set(),
            tier2_words=set(),
            inflected_forms={"customs": "custom"},
        )
        assert result[0].category == "TIER4"
        assert result[0].n_tokens == 2
