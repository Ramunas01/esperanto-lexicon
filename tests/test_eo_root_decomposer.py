"""Tests for ``src.lexicon.eo_root_decomposer``.

These tests use a deliberately minimal in-memory inventory in the new
``build_eo_inventory.py`` shape (``roots`` is a dict of
``{gloss, prod, tier}`` objects). A controlled inventory lets each test case
isolate exactly one algorithmic rule without contamination from the full
25k-root ESPDIC.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from src.lexicon.eo_root_decomposer import (
    KIND_COMPOUND,
    KIND_FUNCTION_WORD,
    KIND_SINGLE_ROOT,
    KIND_UNRESOLVED,
    TIER_CORE,
    TIER_EXTENDED,
    TIER_TAIL,
    Decomposer,
    classify_unresolved,
    load_inventory,
    process_db,
)
from src.lexicon.schema import create_common_lexicon_schema


# ---------------------------------------------------------------------------
# Controlled inventory
# ---------------------------------------------------------------------------


def _root(gloss: str, tier: str, prod: int = 5) -> dict:
    return {"gloss": gloss, "prod": prod, "tier": tier}


def _build_inventory() -> dict:
    """Minimal tiered inventory covering every spec test case.

    Key choices:
      * ``maŝin`` is seeded as a *core* root so Rule 1 protects it from the
        ``-in`` suffix-strip that would otherwise apply (and that's exactly
        the kind of error Rule 1 exists to prevent).
      * ``kun`` is seeded as a core root AND placed in ``other`` so Rule 2
        precedence over Rule 1 is exercised.
      * ``ili`` is seeded as an extended root AND in ``other`` so the
        accusative-``n`` function-word path works (``ilin`` → ``ili``).
      * For the core-preference test, stem ``patdek`` has two valid
        analyses: SINGLE_ROOT (whole-stem-as-root, tier=tail) vs COMPOUND
        ``[patr-without-r? no — we use distinct roots]``. We pick the two
        primitives ``pat`` (core) and ``dek`` (core, from number_roots) so
        the compound's worst tier is ``core`` while the whole-stem
        ``patdek`` (tail) is rank ``tail``.
    """
    return {
        "meta": {"source": "test fixture"},
        "roots": {
            "san": _root("health", TIER_CORE),
            "art": _root("art", TIER_CORE),
            "patr": _root("father", TIER_CORE),
            "vapor": _root("steam", TIER_CORE),
            "ŝip": _root("ship", TIER_CORE),
            "maŝin": _root("machine", TIER_CORE),
            "land": _root("country", TIER_CORE),
            "labor": _root("labour", TIER_CORE),
            "kun": _root("together", TIER_CORE),
            "ili": _root("they", TIER_EXTENDED),
            # Core-preference fixture: two ways to read ``patdek``.
            "pat": _root("pat (core)", TIER_CORE),
            "patdek": _root("patdek (tail)", TIER_TAIL),
        },
        "suffixes": ["ist", "ej", "ul", "in", "et", "ar"],
        "prefixes": ["mal", "re", "ekster"],
        "number_roots": ["du", "dek"],
        "correlatives": ["iu"],
        "other": ["kun", "ili", "kaj"],
        "verb_endings": ["as", "is", "os", "us", "u", "i"],
        "nominal_endings": ["o", "a", "e"],
    }


@pytest.fixture
def decomposer() -> Decomposer:
    return Decomposer(_build_inventory())


# ---------------------------------------------------------------------------
# Inventory loading / tier map
# ---------------------------------------------------------------------------


def test_new_format_root_set_and_tier_map(tmp_path: Path) -> None:
    """Building the Decomposer from the new ``{gloss, prod, tier}`` shape
    yields a root set keyed on the root strings and a ``tier_of`` map that
    reports the correct tier."""
    inv_path = tmp_path / "inv.json"
    inv_path.write_text(
        json.dumps(_build_inventory()), encoding="utf-8"
    )
    loaded = load_inventory(inv_path)
    d = Decomposer(loaded)
    assert "patr" in d.roots
    assert "patr" in d.tier_of
    assert d.tier_of["patr"] == TIER_CORE
    # Number roots are folded in with tier override to core.
    assert "du" in d.roots
    assert d.tier_of["du"] == TIER_CORE


def test_legacy_inventory_format_raises(tmp_path: Path) -> None:
    """An inventory using the old list-of-glosses shape must fail loudly
    rather than silently produce nonsense decompositions."""
    legacy = {
        "roots": {"san": ["health"]},
        "suffixes": [],
        "prefixes": [],
        "correlatives": [],
        "other": [],
        "number_roots": [],
    }
    p = tmp_path / "legacy.json"
    p.write_text(json.dumps(legacy), encoding="utf-8")
    with pytest.raises(ValueError, match="legacy list-of-glosses format"):
        load_inventory(p)


# ---------------------------------------------------------------------------
# Algorithmic property tests
# ---------------------------------------------------------------------------


def test_inventory_root_returns_single_root_unchanged(decomposer: Decomposer) -> None:
    """Rule 1: ``patr`` is a core root → SINGLE_ROOT with no affixes."""
    d = decomposer.decompose("patr")
    assert d.kind == KIND_SINGLE_ROOT
    assert d.root == "patr"
    assert d.prefixes == ()
    assert d.suffixes == ()


def test_prefix_and_suffix_chain_strips_to_true_root(decomposer: Decomposer) -> None:
    """``malsanulej`` → root ``san``, prefix ``mal``, suffix ``ul+ej``."""
    d = decomposer.decompose("malsanulej")
    assert d.kind == KIND_SINGLE_ROOT
    assert d.root == "san"
    assert d.prefixes == ("mal",)
    assert d.suffixes == ("ul", "ej")


def test_single_suffix_strip(decomposer: Decomposer) -> None:
    """``artist`` → root ``art`` (core) + suffix ``ist``. The affix analysis
    wins because ``art`` is core and ``artist`` is not in the inventory."""
    d = decomposer.decompose("artist")
    assert d.kind == KIND_SINGLE_ROOT
    assert d.root == "art"
    assert d.suffixes == ("ist",)


def test_compound_number_roots_recognised(decomposer: Decomposer) -> None:
    """``dudek`` → COMPOUND of number roots ``du`` + ``dek``."""
    d = decomposer.decompose("dudek")
    assert d.kind == KIND_COMPOUND
    assert d.components == ("du", "dek")


def test_inventory_root_protects_against_suffix_strip(decomposer: Decomposer) -> None:
    """Rule 1 beats suffix-strip: ``maŝin`` (core) stays whole, not ``maŝ+in``."""
    d = decomposer.decompose("maŝin")
    assert d.kind == KIND_SINGLE_ROOT
    assert d.root == "maŝin"
    assert d.suffixes == ()


def test_core_preference_beats_tail_whole_root(decomposer: Decomposer) -> None:
    """Selection key prefers a core-only decomposition over a tail
    whole-stem root.

    The fixture inventory deliberately makes ``patdek`` a *tail* root AND
    splittable as ``pat`` (core) + ``dek`` (core). The decomposer must pick
    the compound because its worst tier rank (``core=0``) beats the tail
    whole-stem rank (``tail=2``), even though the compound has more
    morphemes.
    """
    d = decomposer.decompose("patdek")
    assert d.kind == KIND_COMPOUND
    assert d.components == ("pat", "dek")


def test_function_word_classification(decomposer: Decomposer) -> None:
    """Rule 2 takes precedence over Rule 1: ``kun`` is in ``other`` (and
    also a core root in the fixture) → FUNCTION_WORD."""
    d = decomposer.decompose("kun")
    assert d.kind == KIND_FUNCTION_WORD


def test_function_word_with_accusative_n(decomposer: Decomposer) -> None:
    """``ilin`` → strip the accusative ``-n`` → ``ili`` ∈ other → FUNCTION_WORD."""
    d = decomposer.decompose("ilin")
    assert d.kind == KIND_FUNCTION_WORD


def test_two_root_compound(decomposer: Decomposer) -> None:
    """``vaporŝip`` → COMPOUND, components ``[vapor, ŝip]``."""
    d = decomposer.decompose("vaporŝip")
    assert d.kind == KIND_COMPOUND
    assert d.components == ("vapor", "ŝip")


def test_unresolved_single_char_artifact(decomposer: Decomposer) -> None:
    """Single character ``k`` → UNRESOLVED, category ``artifact``."""
    d = decomposer.decompose("k")
    assert d.kind == KIND_UNRESOLVED
    cat, _note = classify_unresolved("k", decomposer)
    assert cat == "artifact"


def test_unresolved_bare_affix_artifact(decomposer: Decomposer) -> None:
    """A stem that is itself a bare affix (e.g. ``ebl``) → artifact."""
    cat, _note = classify_unresolved("ebl", decomposer)
    assert cat == "artifact"


# ---------------------------------------------------------------------------
# DB-pass tests
# ---------------------------------------------------------------------------


def _seed_fixture_db(path: Path) -> dict[int, dict]:
    """Create a tiny v2 lexicon DB with seed concepts spanning each outcome.

    Returns the pre-run state keyed by concept id so the constraint-check
    test can verify unchanged columns.
    """
    conn = sqlite3.connect(path)
    create_common_lexicon_schema(conn)

    seed = [
        # (eo_root, eo_word, eo_prefix, eo_suffix) — covers each outcome.
        ("patr",        "patro",        "", ""),  # already correct
        ("malsanulej",  "malsanulejo",  "", ""),  # strip prefix+suffixes
        ("artist",      "artisto",      "", ""),  # strip suffix
        ("vaporŝip",    "vaporŝipo",    "", ""),  # compound
        ("kun",         "kun",          "", ""),  # function word
        ("k",           "k",            "", ""),  # unresolved (artifact)
    ]
    pre_state: dict[int, dict] = {}
    for eo_root, eo_word, pfx, suf in seed:
        cur = conn.execute(
            "INSERT INTO concept "
            "(eo_root, eo_word, eo_prefix, eo_suffix, eo_status) "
            "VALUES (?, ?, ?, ?, 'complete')",
            (eo_root, eo_word, pfx, suf),
        )
        cid = cur.lastrowid
        conn.execute(
            "INSERT INTO concept_lang "
            "(concept_id, lang, word, pos, cefr_level, tier, source) "
            "VALUES (?, 'en', ?, 'NOUN', 'B1', 2, 'fixture')",
            (cid, eo_word),
        )
        pre_state[cid] = {
            "eo_root": eo_root,
            "eo_word": eo_word,
            "eo_prefix": pfx,
            "eo_suffix": suf,
        }
    conn.commit()
    conn.close()
    return pre_state


def _read_concept_state(path: Path) -> dict[int, dict]:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, eo_root, eo_word, eo_prefix, eo_suffix FROM concept"
    ).fetchall()
    conn.close()
    return {r["id"]: dict(r) for r in rows}


def _read_concept_lang_state(path: Path) -> list[tuple]:
    conn = sqlite3.connect(path)
    rows = conn.execute(
        "SELECT concept_id, lang, word, pos, cefr_level, tier, source "
        "FROM concept_lang ORDER BY id"
    ).fetchall()
    conn.close()
    return rows


@pytest.fixture
def fixture_db(tmp_path: Path) -> Path:
    db = tmp_path / "fixture.db"
    _seed_fixture_db(db)
    return db


def test_db_pass_emits_compound_with_component_tiers(
    fixture_db: Path, tmp_path: Path
) -> None:
    """Compound jsonl records carry the per-component tier list."""
    out_dir = tmp_path / "out"
    summary, _updates, compounds, unresolved = process_db(
        fixture_db,
        Decomposer(_build_inventory()),
        out_dir,
        dry_run=False,
    )
    assert summary.processed == 6
    assert summary.compounds == 1
    assert summary.function_word == 1
    assert summary.unresolved == 1

    comp_path = out_dir / "eo_compounds.jsonl"
    rec = json.loads(comp_path.read_text(encoding="utf-8").strip())
    assert rec["component_roots"] == ["vapor", "ŝip"]
    assert rec["component_tiers"] == [TIER_CORE, TIER_CORE]
    assert rec["eo_root_stem"] == "vaporŝip"

    unres_path = out_dir / "eo_unresolved_stems.jsonl"
    rec = json.loads(unres_path.read_text(encoding="utf-8").strip())
    assert rec["category"] == "artifact"
    assert rec["eo_root_stem"] == "k"


def test_db_pass_reports_tier_breakdown(
    fixture_db: Path, tmp_path: Path
) -> None:
    """Summary tracks how many concepts resolved to each root tier."""
    out_dir = tmp_path / "out"
    summary, _u, _c, _r = process_db(
        fixture_db,
        Decomposer(_build_inventory()),
        out_dir,
        dry_run=False,
    )
    # patr / san (via malsanulej) / art (via artist) are all core roots.
    # The compound and function-word and unresolved rows don't count.
    assert summary.decomposed_by_tier[TIER_CORE] == 3


def test_db_pass_is_idempotent(
    fixture_db: Path, tmp_path: Path
) -> None:
    """Second run reports 0 updated and leaves columns byte-identical."""
    out_dir = tmp_path / "out"
    process_db(
        fixture_db,
        Decomposer(_build_inventory()),
        out_dir,
        dry_run=False,
    )
    state_after_first = _read_concept_state(fixture_db)

    summary_2, updates_2, _c, _r = process_db(
        fixture_db,
        Decomposer(_build_inventory()),
        out_dir,
        dry_run=False,
    )
    state_after_second = _read_concept_state(fixture_db)

    assert summary_2.updated == 0
    assert updates_2 == []
    assert state_after_first == state_after_second


def test_db_pass_does_not_touch_tier_word_cefr_source_columns(
    fixture_db: Path, tmp_path: Path
) -> None:
    """``tier``, ``word``, ``cefr_level``, ``source`` (and ``eo_word``)
    must be byte-identical before and after the pass."""
    out_dir = tmp_path / "out"
    pre_concept = _read_concept_state(fixture_db)
    pre_lang = _read_concept_lang_state(fixture_db)

    process_db(
        fixture_db,
        Decomposer(_build_inventory()),
        out_dir,
        dry_run=False,
    )

    post_concept = _read_concept_state(fixture_db)
    post_lang = _read_concept_lang_state(fixture_db)

    for cid in pre_concept:
        assert pre_concept[cid]["eo_word"] == post_concept[cid]["eo_word"]
    assert pre_lang == post_lang


def test_dry_run_does_not_write_to_db_or_jsonl(
    fixture_db: Path, tmp_path: Path
) -> None:
    """``--dry-run`` must leave the DB and jsonl outputs untouched."""
    out_dir = tmp_path / "out"
    pre_concept = _read_concept_state(fixture_db)

    summary, updates, _c, _r = process_db(
        fixture_db,
        Decomposer(_build_inventory()),
        out_dir,
        dry_run=True,
    )

    post_concept = _read_concept_state(fixture_db)
    assert pre_concept == post_concept
    assert not (out_dir / "eo_compounds.jsonl").exists()
    assert not (out_dir / "eo_unresolved_stems.jsonl").exists()
    # The would-be diff is still reported.
    assert summary.updated == 2
    assert len(updates) == 2
