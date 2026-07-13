"""Unit tests for the A1 general-gap consolidation (pure logic, no network/DB)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "analyzer"))

from consolidate_general_gaps import (  # noqa: E402
    consolidate,
    flag_direction,
    gloss_tokens,
    is_derived_adjective,
    pos_and_ending,
    propose_tier,
    select_anchor,
)


# --- flag_direction (whole-word, not substring) -----------------------------


def test_flag_register_marked():
    assert flag_direction("damn", "damn") == "register-marked"
    assert flag_direction("gay", "gay, homosexual, queer") == "register-marked"


def test_flag_substring_trap_avoided():
    # 'prefix' contains 'fik'/'fuck'? no — must not misfire on substrings.
    assert flag_direction("prefix", "to prefix") == "common"
    # 'suck' -> 'suckle' is the ordinary verb, NOT register.
    assert flag_direction("suck", "to suck, suckle") == "common"


def test_flag_domain_adjacent():
    assert flag_direction("colonel", "colonel") == "domain-adjacent"
    assert flag_direction("genetic", "genetic") == "domain-adjacent"
    assert flag_direction("naval", "naval") == "domain-adjacent"


def test_flag_archaic():
    assert flag_direction("foo", "archaic, obsolete") == "archaic"


def test_flag_common_default():
    assert flag_direction("carbon", "carbon") == "common"
    assert flag_direction("circuit", "circuit") == "common"


def test_register_precedence_over_domain():
    # order in flag_direction: archaic > register > domain > common
    assert flag_direction("gay", "gay") == "register-marked"


# --- is_derived_adjective ---------------------------------------------------


@pytest.mark.parametrize("w", ["democratic", "presidential", "naval", "mechanical", "toxic", "collective"])
def test_derived_adjective_true(w):
    assert is_derived_adjective(w) is True


@pytest.mark.parametrize("w", ["carbon", "circuit", "fleet", "damn", "poll", "gap"])
def test_derived_adjective_false(w):
    assert is_derived_adjective(w) is False


# --- pos_and_ending ---------------------------------------------------------


def test_pos_verb_from_to_gloss():
    assert pos_and_ending("ford", "to ford") == ("VERB", "i")


def test_pos_adjective():
    assert pos_and_ending("democratic", "democratic") == ("ADJ", "a")


def test_pos_noun_default():
    assert pos_and_ending("carbon", "carbon") == ("NOUN", "o")


# --- select_anchor (core > extended, prod desc, shorter) --------------------


def test_select_anchor_prefers_core_then_prod_then_short():
    rows = [
        {"root": "demokrat", "inv_tier": "extended", "prod": "2"},
        {"root": "demokrati", "inv_tier": "core", "prod": "4"},
    ]
    anchor, all_roots = select_anchor(rows)
    assert anchor == "demokrati"  # core beats extended
    assert set(all_roots) == {"demokrat", "demokrati"}


def test_select_anchor_shorter_breaks_tie():
    rows = [
        {"root": "aaaa", "inv_tier": "core", "prod": "3"},
        {"root": "bb", "inv_tier": "core", "prod": "3"},
    ]
    assert select_anchor(rows)[0] == "bb"


# --- propose_tier -----------------------------------------------------------


def test_propose_tier_common_bands():
    assert propose_tier(4.6, "common") == "2"
    assert propose_tier(4.4, "common") == "3"
    assert propose_tier(3.2, "common") == "3"


def test_propose_tier_held_blank():
    assert propose_tier(5.0, "domain-adjacent") == ""
    assert propose_tier(5.0, "register-marked") == ""


# --- consolidate (dedupe + fold flag + ordering) ----------------------------


def _row(root, head, zipf, inv="core", prod="3", gloss=None):
    return {"root": root, "gloss_head": head, "gloss_zipf": str(zipf),
            "suggested_tier": "3", "inv_tier": inv, "prod": prod,
            "gloss": gloss or head}


def test_consolidate_dedupes_by_head():
    rows = [
        _row("demokrat", "democratic", 4.7, "extended", "2"),
        _row("demokrati", "democratic", 4.7, "core", "4"),
        _row("karbon", "carbon", 4.55),
    ]
    concepts = consolidate(rows)
    assert len(concepts) == 2  # democratic collapses
    dem = next(c for c in concepts if c.en_word == "democratic")
    assert dem.anchor_root == "demokrati"
    assert set(dem.all_roots) == {"demokrat", "demokrati"}
    assert dem.fold == "derived_adj"


def test_consolidate_flags_and_tiers():
    rows = [
        _row("karbon", "carbon", 4.6),          # common, T2
        _row("cirkvit", "circuit", 4.2),        # common, T3
        _row("kolonel", "colonel", 4.4),        # domain-adjacent, held
        _row("x", "damn", 5.1, gloss="damn"),   # register, held
    ]
    concepts = {c.en_word: c for c in consolidate(rows)}
    assert concepts["carbon"].flag == "common" and concepts["carbon"].proposed_tier == "2"
    assert concepts["circuit"].proposed_tier == "3"
    assert concepts["colonel"].flag == "domain-adjacent" and concepts["colonel"].proposed_tier == ""
    assert concepts["damn"].flag == "register-marked"


def test_consolidate_common_first_ordering():
    rows = [
        _row("kolonel", "colonel", 4.9),   # domain-adjacent
        _row("karbon", "carbon", 4.5),     # common
    ]
    concepts = consolidate(rows)
    assert concepts[0].flag == "common"  # common bulk sorts first


def test_gloss_tokens_whole_words():
    assert gloss_tokens("gay, homosexual/queer") == ["gay", "homosexual", "queer"]
