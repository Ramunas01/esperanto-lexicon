"""Unit tests for the inventory-vs-tier root coverage classifier (pure logic).

No network, no spaCy model, no DB — wordfreq/lemmatizer/coverage are injected as
fakes. Includes the required fixture proving the ``"to "``-stripping trap (#1).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "analyzer"))

from root_tier_coverage import (  # noqa: E402
    classify_root,
    content_words,
    first_sense,
    gloss_words_all,
    normalized_forms,
    score_gloss,
    suggest_tier,
    word_is_covered,
)

# Deterministic fake zipf: a small hand-set frequency table.
_ZIPF = {
    "to": 7.4, "the": 7.7, "abolish": 3.5, "hare": 3.7, "rabbit": 4.1,
    "burn": 4.5, "incense": 2.9, "meadow": 3.4, "saffron": 2.4, "absurd": 3.9,
    "relinquish": 3.1, "water": 5.5, "abstract": 3.8, "additive": 3.3,
    "time": 6.3, "use": 5.6,
}


def zipf(w: str) -> float:
    return _ZIPF.get(w, 0.0)


def ident(w: str) -> str:  # identity lemmatizer
    return w


def uk(w: str) -> str:  # trivial uk_to_us stub
    return {"colour": "color"}.get(w, w)


# --- first_sense / content_words --------------------------------------------


def test_first_sense_keeps_original_case():
    assert first_sense("American, of the USA") == "American"
    assert first_sense("hare, rabbit") == "hare"


def test_content_words_strips_function_words():
    assert content_words("to burn incense") == ["burn", "incense"]
    assert content_words("of use") == ["use"]


# --- score_gloss: THE "to " trap (#1) ---------------------------------------


def test_to_trap_scores_content_head_not_to():
    # The whole point: a verb gloss must score 'abolish', never 'to' (zipf 7.4).
    s = score_gloss("to abolish, abrogate", zipf)
    assert s.head == "abolish" and s.zipf == pytest.approx(3.5)
    assert s.common_short is True


def test_article_noun_gloss_scores_head():
    assert score_gloss("a rabbit", zipf).head == "rabbit"


# --- score_gloss: trap #2 (common head != common concept) -------------------


def test_multiword_phrasal_is_obscure():
    s = score_gloss("to burn incense", zipf)  # 'burn' is common; concept isn't
    assert s.common_short is False and s.reason == "multiword"


def test_parenthetical_is_obscure():
    assert score_gloss("top deck (of a vehicle)", zipf).reason == "paren"


def test_low_zipf_is_obscure():
    assert score_gloss("saffron", zipf).reason == "low_zipf"


# --- score_gloss: proper nouns / hyphens / stopwords ------------------------


def test_proper_noun_is_obscure():
    s = score_gloss("American", zipf)
    assert s.common_short is False and s.reason == "proper_noun"


def test_hyphenated_is_obscure():
    assert score_gloss("e-book", zipf).reason == "hyphenated"


def test_stopword_head_is_obscure():
    # 'but'/'my' are grammatical morpheme glosses, not lexical gaps.
    assert score_gloss("but", zipf).reason == "stopword"


def test_common_single_word_passes():
    s = score_gloss("hare, rabbit", zipf)
    assert s.head == "hare" and s.common_short is True


# --- suggest_tier -----------------------------------------------------------


@pytest.mark.parametrize("z,t", [(5.5, 1), (5.0, 1), (4.9, 2), (4.0, 2), (3.9, 3), (3.0, 3)])
def test_suggest_tier(z, t):
    assert suggest_tier(z) == t


# --- normalization (trap #3) ------------------------------------------------


def test_normalized_forms_includes_inflected_and_fold():
    forms = normalized_forms("colours", ident, {"colours": "color"}, uk)
    assert "color" in forms  # via inflected map
    forms2 = normalized_forms("colour", ident, {}, uk)
    assert "color" in forms2  # via uk_to_us


def test_word_is_covered():
    en = frozenset({"color", "rabbit"})
    assert word_is_covered("colour", en, ident, {}, uk) is True   # fold
    assert word_is_covered("rabbit", en, ident, {}, uk) is True
    assert word_is_covered("abolish", en, ident, {}, uk) is False


# --- gloss_words_all --------------------------------------------------------


def test_gloss_words_all_across_senses():
    assert gloss_words_all("hare, rabbit") == ["hare", "rabbit"]
    assert gloss_words_all("to abolish, abrogate") == ["abolish", "abrogate"]


# --- classify_root: the buckets ---------------------------------------------


EN = frozenset({"rabbit", "color", "time", "use", "abstract"})


def _classify(root, gloss, covered_tiers, inv_tier="core", en=EN):
    entry = {"gloss": gloss, "tier": inv_tier, "prod": 1}
    return classify_root(root, entry, covered_tiers, en, zipf, ident, {}, uk)


def test_bucket_covered():
    assert _classify("kunikl", "rabbit", [2]).bucket == "covered_T1_3"


def test_bucket_candidate_gap():
    r = _classify("abol", "to abolish, abrogate", [])
    assert r.bucket == "candidate_gap"
    assert r.suggested_tier == 3  # zipf 3.5 -> T3


def test_bucket_shade_mismatch_lepor_pattern():
    # hare (primary) uncovered, rabbit (later) covered -> granularity split
    r = _classify("lepor", "hare, rabbit", [], inv_tier="tail")
    assert r.bucket == "shade_mismatch" and r.matched_word == "rabbit"


def test_bucket_primary_covered_is_obscure():
    # 'time' (primary head) already covered -> derivative/compound, not a shade
    r = _classify("kronometr", "to time", [], inv_tier="extended")
    assert r.bucket == "obscure_root" and r.reason == "primary_covered"


def test_bucket_tail_prior_obscure():
    # common, uncovered, no covered sense, but tail confidence -> obscure prior
    r = _classify("xyz", "absurd", [], inv_tier="tail")
    assert r.bucket == "obscure_root" and r.reason == "tail_prior"


def test_bucket_multiword_gloss_obscure():
    assert _classify("incens", "to burn incense", []).bucket == "obscure_root"
