"""Tests for the eolex public API — fast (toy fixtures) + slow (real bundle)."""

from __future__ import annotations

import pytest

from eolex import Bundle, Decomposer, Lexicon, Resolver
from eolex.eo_decomposer import KIND_COMPOUND, KIND_SINGLE_ROOT, KIND_FUNCTION_WORD


# ---------------------------------------------------------------------------
# Decomposer (via Lexicon.decompose)
# ---------------------------------------------------------------------------


def test_decompose_simple_word(toy_lexicon):
    d = toy_lexicon.decompose("akvo", lang="eo")
    assert d.kind == KIND_SINGLE_ROOT
    assert d.roots == ("akv",)
    assert not d.is_compound


def test_decompose_compound(toy_lexicon):
    d = toy_lexicon.decompose("akvobirdo", lang="eo")
    assert d.is_compound
    assert "akv" in d.roots
    assert "bird" in d.roots
    assert d.head is not None and d.head.root == "bird"


def test_decompose_requires_eo_lang(toy_lexicon):
    with pytest.raises(ValueError, match="lang='eo'"):
        toy_lexicon.decompose("cat", lang="en")


# ---------------------------------------------------------------------------
# roots()
# ---------------------------------------------------------------------------


def test_roots_eo_simple(toy_lexicon):
    assert toy_lexicon.roots("akvo", lang="eo") == ["akv"]


def test_roots_eo_compound(toy_lexicon):
    roots = toy_lexicon.roots("akvobirdo", lang="eo")
    assert set(roots) == {"akv", "bird"}


def test_roots_en_lookup(toy_lexicon):
    assert toy_lexicon.roots("cat", lang="en") == ["kat"]


def test_roots_en_unknown(toy_lexicon):
    assert toy_lexicon.roots("xyzzy", lang="en") == []


# ---------------------------------------------------------------------------
# inventory_tier()
# ---------------------------------------------------------------------------


def test_inventory_tier_core(toy_lexicon):
    assert toy_lexicon.inventory_tier("akv") == "core"


def test_inventory_tier_extended(toy_lexicon):
    assert toy_lexicon.inventory_tier("san") == "extended"


def test_inventory_tier_unknown(toy_lexicon):
    assert toy_lexicon.inventory_tier("zzzz") is None


def test_inventory_tier_case_insensitive(toy_lexicon):
    assert toy_lexicon.inventory_tier("AKV") == "core"


# ---------------------------------------------------------------------------
# gloss()
# ---------------------------------------------------------------------------


def test_gloss_known_root(toy_lexicon):
    g = toy_lexicon.gloss("akv")
    assert g is not None and "water" in g


def test_gloss_unknown_root(toy_lexicon):
    assert toy_lexicon.gloss("zzzz") is None


# ---------------------------------------------------------------------------
# pedagogical_tier()
# ---------------------------------------------------------------------------


def test_pedagogical_tier_t1_eo(toy_lexicon):
    assert toy_lexicon.pedagogical_tier("akvo", lang="eo") == 1


def test_pedagogical_tier_t1_en(toy_lexicon):
    assert toy_lexicon.pedagogical_tier("cat", lang="en") == 1


def test_pedagogical_tier_t3_en(toy_lexicon):
    assert toy_lexicon.pedagogical_tier("framework", lang="en") == 3


def test_pedagogical_tier_unknown(toy_lexicon):
    assert toy_lexicon.pedagogical_tier("xyzzy", lang="en") is None


def test_pedagogical_tier_case_insensitive(toy_lexicon):
    assert toy_lexicon.pedagogical_tier("AKVO", lang="eo") == 1


# ---------------------------------------------------------------------------
# cefr()
# ---------------------------------------------------------------------------


def test_cefr_known(toy_lexicon):
    assert toy_lexicon.cefr("akvo", lang="eo") == "A1"


def test_cefr_none_when_no_cefr(toy_lexicon):
    # framework has tier=3 but no cefr_level in our toy fixture
    assert toy_lexicon.cefr("framework", lang="en") is None


def test_cefr_unknown(toy_lexicon):
    assert toy_lexicon.cefr("zzzz", lang="en") is None


# ---------------------------------------------------------------------------
# Bundle round-trip (concept_lang_map survives save/load)
# ---------------------------------------------------------------------------


def test_bundle_concept_lang_roundtrip(toy_bundle):
    assert toy_bundle.concept_lang_map[("eo", "akvo")] == (1, "A1")
    assert toy_bundle.concept_lang_map[("en", "framework")] == (3, None)


def test_bundle_without_concept_lang_loads_empty(tmp_path, toy_lexicon):
    """Older bundles without the concept_lang table load with empty map."""
    # Build a bundle without concept_lang by using a bundle that has no map
    import numpy as np
    from eolex.bundle import Bundle

    b = Bundle(
        domains=[], vocab=[], idf=np.array([]), vectors=np.zeros((0, 0)),
        word_root_map={}, inventory=toy_lexicon._bundle.inventory,
        concept_lang_map={},  # empty → table NOT written
        meta={"build_date": "2026-01-01", "langs": ["eo"]},
    )
    path = tmp_path / "no_clang.bundle"
    b.save(path)
    loaded = Bundle.load(path)
    assert loaded.concept_lang_map == {}


# ---------------------------------------------------------------------------
# Low-level public re-exports from eolex
# ---------------------------------------------------------------------------


def test_decomposer_importable_from_eolex():
    """Decomposer, Resolver, Bundle re-exported from eolex."""
    from eolex import Decomposer, Resolver, Bundle
    assert callable(Decomposer)
    assert callable(Resolver)
    assert callable(Bundle.load)


# ---------------------------------------------------------------------------
# Real packaged bundle — marked slow, require built bundle
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_real_inventory_tier_core(real_lexicon):
    assert real_lexicon.inventory_tier("akv") == "core"


@pytest.mark.slow
def test_real_gloss_nonempty(real_lexicon):
    g = real_lexicon.gloss("akv")
    assert g and len(g) > 0


@pytest.mark.slow
def test_real_pedagogical_tier_t1_eo(real_lexicon):
    assert real_lexicon.pedagogical_tier("akvo", lang="eo") == 1


@pytest.mark.slow
def test_real_pedagogical_tier_t1_en(real_lexicon):
    assert real_lexicon.pedagogical_tier("cat", lang="en") == 1


@pytest.mark.slow
def test_real_pedagogical_tier_t3_en(real_lexicon):
    # "framework" was seeded as T3 by seed_tier3
    assert real_lexicon.pedagogical_tier("framework", lang="en") == 3


@pytest.mark.slow
def test_real_cefr_a1(real_lexicon):
    assert real_lexicon.cefr("akvo", lang="eo") == "A1"


@pytest.mark.slow
def test_real_decompose_compound(real_lexicon):
    d = real_lexicon.decompose("akvobirdo", lang="eo")
    assert d.is_compound
    assert "akv" in d.roots


@pytest.mark.slow
def test_real_concept_lang_counts(real_lexicon):
    """Tier counts reconcile with known lexicon_v2.db state (1080/2713/97 EN)."""
    m = real_lexicon._bundle.concept_lang_map
    en_t1 = sum(1 for (lang, _), (t, _) in m.items() if lang == "en" and t == 1)
    en_t2 = sum(1 for (lang, _), (t, _) in m.items() if lang == "en" and t == 2)
    en_t3 = sum(1 for (lang, _), (t, _) in m.items() if lang == "en" and t == 3)
    # Counts come from MIN-dedup of concept_lang; raw DB has 1080/2713/97 but
    # dedup by word collapses some duplicates → expect close but not exact.
    assert en_t1 >= 900, f"T1 EN: {en_t1}"
    assert en_t2 >= 2000, f"T2 EN: {en_t2}"
    assert en_t3 >= 80, f"T3 EN: {en_t3}"


@pytest.mark.slow
def test_real_eo_tier_count(real_lexicon):
    """All 2660 eo_word concepts should be in the map."""
    eo_entries = [(w, t) for (lang, w), (t, _) in real_lexicon._bundle.concept_lang_map.items() if lang == "eo"]
    assert len(eo_entries) >= 2600, f"EO entries: {len(eo_entries)}"


@pytest.mark.slow
def test_real_lexicon_load_default():
    """Lexicon.load() with no arg loads from package data (self-contained)."""
    lex = Lexicon.load()
    assert lex.inventory_tier("akv") == "core"
    assert lex.pedagogical_tier("akvo", lang="eo") == 1
