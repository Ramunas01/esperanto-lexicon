"""Tests for ``src.lexicon.eo_root_decomposer``.

These tests use a deliberately minimal in-memory inventory in the new
``build_eo_inventory.py`` shape (``roots`` is a dict of
``{gloss, prod, tier}`` objects) so each algorithmic rule is isolated
from the contamination of the full 25k-root ESPDIC.
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
    TIER_MODERN,
    TIER_TAIL,
    ContentRoot,
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

    Notable choices:
      * ``konsent`` (core) + ``inter`` (prefix) — for 1a ``interkonsent``.
      * ``long`` (core) + ``laŭ`` (prefix) — for 1a ``laŭlong``.
      * ``interpret`` is seeded as core, prod=6 — Rule 1 must keep it whole
        even though ``inter+pret`` is a valid affix-strip path. Also
        ``pret`` is seeded as a core root to make the over-split path
        attractive but ultimately rejected by the productivity floor.
      * ``klimat`` is core (prod=4) so the 1c test exercises sourcing the
        working stem from ``eo_word="klimato"`` rather than the stored
        truncated ``eo_root="klim"`` (which the inventory cannot resolve).
      * ``maŝin`` (core) for Rule 1 protection against the ``-in`` suffix.
      * ``kun`` is core AND in ``other`` — function-word precedence over
        Rule 1.
      * ``patr`` core — simple SINGLE_ROOT.
      * ``vapor`` + ``ŝip`` (both core) — compound.
      * ``foosin`` is a tail/prod=1 stem that ALSO splits as ``foo+sin``
        where ``foo`` is core — exercises the "low-confidence singleton
        competes" branch of Rule 1.
    """
    return {
        "meta": {"source": "test fixture"},
        "roots": {
            "patr":     _root("father", TIER_CORE, prod=10),
            "vapor":    _root("steam", TIER_CORE, prod=6),
            "ŝip":      _root("ship", TIER_CORE, prod=11),
            "maŝin":    _root("machine", TIER_CORE, prod=4),
            "san":      _root("health", TIER_CORE, prod=20),
            "art":      _root("art", TIER_CORE, prod=8),
            "land":     _root("country", TIER_CORE, prod=8),
            "konsent":  _root("agree", TIER_CORE, prod=8),
            "long":     _root("long", TIER_CORE, prod=15),
            "klimat":   _root("climate", TIER_CORE, prod=4),
            "interpret":_root("interpret", TIER_CORE, prod=6),
            "pret":     _root("ready", TIER_CORE, prod=4),
            "kun":      _root("together", TIER_CORE, prod=21),
            "ili":      _root("they", TIER_EXTENDED, prod=2),
            # Productivity-floor competition fixtures.
            "foo":      _root("foo head", TIER_CORE, prod=3),
            "sin":      _root("sin tail", TIER_CORE, prod=3),
            "foosin":   _root("foosin singleton", TIER_TAIL, prod=1),
            # Modern-tier supplement entry — must be treated like extended
            # (kept whole by Rule 1, never a low-confidence singleton).
            "dvd":      _root("DVD", TIER_MODERN, prod=-1),
        },
        "suffixes": ["ist", "ej", "ul", "in", "et", "ar", "o", "a", "e"],
        "prefixes": ["mal", "re", "ekster", "inter", "laŭ"],
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
# Inventory loading
# ---------------------------------------------------------------------------


def test_new_format_root_set_and_tier_map(tmp_path: Path) -> None:
    """Building the Decomposer from ``{gloss, prod, tier}`` yields a root
    set, a ``tier_of`` map, and a ``prod_of`` map. Number roots fold in
    with tier=core."""
    inv_path = tmp_path / "inv.json"
    inv_path.write_text(json.dumps(_build_inventory()), encoding="utf-8")
    loaded = load_inventory(inv_path)
    d = Decomposer(loaded)
    assert "patr" in d.roots
    assert d.tier_of["patr"] == TIER_CORE
    assert d.prod_of["patr"] == 10
    assert d.tier_of["du"] == TIER_CORE  # number root override


def test_legacy_inventory_format_raises(tmp_path: Path) -> None:
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
# Decomposition shape (Part 1d)
# ---------------------------------------------------------------------------


def test_decomposition_carries_ordered_content_roots(decomposer: Decomposer) -> None:
    """A compound's ``content_roots`` are ordered with explicit positions
    and the head is the last element."""
    d = decomposer.decompose("vaporŝip")
    assert d.kind == KIND_COMPOUND
    assert d.is_compound
    roots = d.content_roots
    assert [cr.root for cr in roots] == ["vapor", "ŝip"]
    assert [cr.position for cr in roots] == [0, 1]
    assert [cr.tier for cr in roots] == [TIER_CORE, TIER_CORE]
    assert d.head == ContentRoot("ŝip", TIER_CORE, 1)


def test_decomposition_single_root_has_one_content_root(decomposer: Decomposer) -> None:
    d = decomposer.decompose("patr")
    assert d.kind == KIND_SINGLE_ROOT
    assert not d.is_compound
    assert len(d.content_roots) == 1
    assert d.head == ContentRoot("patr", TIER_CORE, 0)


# ---------------------------------------------------------------------------
# Part 1a — prepositional prefixes available at decode time
# ---------------------------------------------------------------------------


def test_1a_interkonsent_decomposes_via_prepositional_prefix(decomposer: Decomposer) -> None:
    """``interkonsent`` (no entry in fixture inventory) decomposes as
    prefix ``inter`` + root ``konsent`` (core) once ``inter`` is in the
    decode prefix list."""
    d = decomposer.decompose("interkonsent")
    assert d.kind == KIND_SINGLE_ROOT
    assert d.head.root == "konsent"
    assert d.prefixes == ("inter",)
    assert d.suffixes == ()
    assert len(d.content_roots) == 1


def test_1a_lauxlong_decomposes_via_prepositional_prefix(decomposer: Decomposer) -> None:
    """``laŭlong`` → prefix ``laŭ`` + root ``long`` (core)."""
    d = decomposer.decompose("laŭlong")
    assert d.kind == KIND_SINGLE_ROOT
    assert d.head.root == "long"
    assert d.prefixes == ("laŭ",)


# ---------------------------------------------------------------------------
# Part 1b — productivity floor
# ---------------------------------------------------------------------------


def test_1b_high_prod_root_kept_whole_against_split(decomposer: Decomposer) -> None:
    """``interpret`` is core/prod=6: Rule 1 keeps it whole even though
    ``inter+pret`` is a valid prefix-strip into another core root."""
    d = decomposer.decompose("interpret")
    assert d.kind == KIND_SINGLE_ROOT
    assert d.head.root == "interpret"
    assert d.prefixes == ()
    assert d.suffixes == ()


def test_1b_tail_singleton_does_compete_with_decomposition(decomposer: Decomposer) -> None:
    """``foosin`` is tail/prod=1 — Rule 1 does NOT short-circuit. The core
    compound ``foo+sin`` therefore wins on tier-rank, even though it has
    more morphemes than the whole-stem-as-root candidate."""
    d = decomposer.decompose("foosin")
    assert d.kind == KIND_COMPOUND
    assert [cr.root for cr in d.content_roots] == ["foo", "sin"]


# ---------------------------------------------------------------------------
# Part 1c — working stem from eo_word, not stored eo_root
# ---------------------------------------------------------------------------


def test_1c_uses_eo_word_not_stored_eo_root(decomposer: Decomposer) -> None:
    """``decompose_word`` strips flexion from the word and resolves to the
    true root — exactly the path the DB pass uses for every concept."""
    d = decomposer.decompose_word("klimato")
    assert d.kind == KIND_SINGLE_ROOT
    assert d.head.root == "klimat"


def test_1c_db_pass_sources_working_stem_from_eo_word(tmp_path: Path) -> None:
    """A concept seeded with ``eo_word='klimato'`` but a truncated
    ``eo_root='klim'`` (the v1→v2 migration class of error) resolves to
    ``klimat`` after the pass, because input came from the word."""
    db = tmp_path / "fix.db"
    conn = sqlite3.connect(db)
    create_common_lexicon_schema(conn)
    cur = conn.execute(
        "INSERT INTO concept (eo_root, eo_word, eo_prefix, eo_suffix, eo_status) "
        "VALUES ('klim', 'klimato', '', '', 'complete')"
    )
    cid = cur.lastrowid
    conn.commit()
    conn.close()

    summary, updates, root_rows, _u = process_db(
        db, Decomposer(_build_inventory()),
        dry_run=False, out_dir=tmp_path / "out",
    )

    conn = sqlite3.connect(db)
    eo_root, = conn.execute(
        "SELECT eo_root FROM concept WHERE id = ?", (cid,)
    ).fetchone()
    cr_rows = conn.execute(
        "SELECT root, position, is_head, tier FROM concept_root "
        "WHERE concept_id = ? ORDER BY position",
        (cid,),
    ).fetchall()
    conn.close()

    assert eo_root == "klimat"
    assert cr_rows == [("klimat", 0, 1, TIER_CORE)]
    assert summary.eo_root_changed == 1


# ---------------------------------------------------------------------------
# Existing rule-level checks (carried over)
# ---------------------------------------------------------------------------


def test_prefix_and_suffix_chain_strips_to_true_root(decomposer: Decomposer) -> None:
    d = decomposer.decompose("malsanulej")
    assert d.kind == KIND_SINGLE_ROOT
    assert d.head.root == "san"
    assert d.prefixes == ("mal",)
    assert d.suffixes == ("ul", "ej")


def test_single_suffix_strip(decomposer: Decomposer) -> None:
    d = decomposer.decompose("artist")
    assert d.kind == KIND_SINGLE_ROOT
    assert d.head.root == "art"
    assert d.suffixes == ("ist",)


def test_inventory_root_protects_against_suffix_strip(decomposer: Decomposer) -> None:
    d = decomposer.decompose("maŝin")
    assert d.kind == KIND_SINGLE_ROOT
    assert d.head.root == "maŝin"
    assert d.suffixes == ()


def test_compound_number_roots_recognised(decomposer: Decomposer) -> None:
    d = decomposer.decompose("dudek")
    assert d.kind == KIND_COMPOUND
    assert [cr.root for cr in d.content_roots] == ["du", "dek"]


def test_function_word_classification(decomposer: Decomposer) -> None:
    """Rule 2 precedes Rule 1: ``kun`` is in ``other`` AND in roots →
    FUNCTION_WORD."""
    d = decomposer.decompose("kun")
    assert d.kind == KIND_FUNCTION_WORD


def test_function_word_with_accusative_n(decomposer: Decomposer) -> None:
    d = decomposer.decompose("ilin")
    assert d.kind == KIND_FUNCTION_WORD


def test_unresolved_single_char_artifact(decomposer: Decomposer) -> None:
    d = decomposer.decompose("k")
    assert d.kind == KIND_UNRESOLVED
    cat, _note = classify_unresolved("k", decomposer)
    assert cat == "artifact"


# ---------------------------------------------------------------------------
# Part 2 — concept_root population and head anchoring
# ---------------------------------------------------------------------------


def _seed_fixture_db(path: Path) -> dict[int, dict]:
    conn = sqlite3.connect(path)
    create_common_lexicon_schema(conn)
    seed = [
        # (eo_word, stored_eo_root, eo_prefix, eo_suffix)
        ("patro",         "patr",         "", ""),  # simple, already correct
        ("vaporŝipo",     "vaporŝip",     "", ""),  # compound
        ("malsanulejo",   "malsanulej",   "", ""),  # affix chain
        ("kun",           "kun",          "", ""),  # function word
        ("k",             "k",            "", ""),  # unresolved
        ("klimato",       "klim",         "", ""),  # 1c eo_word source
        ("",              "stale",        "", ""),  # skipped: no eo_word
    ]
    pre_state: dict[int, dict] = {}
    for eo_word, eo_root, pfx, suf in seed:
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
            (cid, eo_word or eo_root),
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


def _read_concept_root_state(path: Path) -> list[tuple]:
    conn = sqlite3.connect(path)
    rows = conn.execute(
        "SELECT concept_id, root, position, is_head, tier FROM concept_root "
        "ORDER BY concept_id, position"
    ).fetchall()
    conn.close()
    return rows


@pytest.fixture
def fixture_db(tmp_path: Path) -> Path:
    db = tmp_path / "fixture.db"
    _seed_fixture_db(db)
    return db


def test_compound_emits_one_concept_root_row_per_component(
    fixture_db: Path, tmp_path: Path
) -> None:
    """``vaporŝip`` → two rows ordered by position, is_head=1 only on
    ``ŝip``, eo_root anchored on ``ŝip``."""
    summary, _u, _r, _x = process_db(
        fixture_db, Decomposer(_build_inventory()),
        dry_run=False, out_dir=tmp_path / "out",
    )

    conn = sqlite3.connect(fixture_db)
    cid, eo_root = conn.execute(
        "SELECT id, eo_root FROM concept WHERE eo_word = 'vaporŝipo'"
    ).fetchone()
    rows = conn.execute(
        "SELECT root, position, is_head, tier FROM concept_root "
        "WHERE concept_id = ? ORDER BY position",
        (cid,),
    ).fetchall()
    conn.close()

    assert rows == [
        ("vapor", 0, 0, TIER_CORE),
        ("ŝip",   1, 1, TIER_CORE),
    ]
    assert eo_root == "ŝip"
    assert summary.compound >= 1


def test_simple_word_emits_single_concept_root_row_is_head(
    fixture_db: Path, tmp_path: Path
) -> None:
    process_db(
        fixture_db, Decomposer(_build_inventory()),
        dry_run=False, out_dir=tmp_path / "out",
    )
    conn = sqlite3.connect(fixture_db)
    cid, = conn.execute(
        "SELECT id FROM concept WHERE eo_word = 'patro'"
    ).fetchone()
    rows = conn.execute(
        "SELECT root, position, is_head, tier FROM concept_root "
        "WHERE concept_id = ?", (cid,),
    ).fetchall()
    conn.close()
    assert rows == [("patr", 0, 1, TIER_CORE)]


def test_root_support_query_credits_both_compound_components(
    fixture_db: Path, tmp_path: Path
) -> None:
    """The root-support query crediting both components of a compound is
    exactly the join the design exists for."""
    process_db(
        fixture_db, Decomposer(_build_inventory()),
        dry_run=False, out_dir=tmp_path / "out",
    )
    conn = sqlite3.connect(fixture_db)
    rows = dict(conn.execute(
        "SELECT root, COUNT(DISTINCT concept_id) "
        "FROM concept_root WHERE root IN ('vapor', 'ŝip') GROUP BY root"
    ).fetchall())
    conn.close()
    # ``ŝip`` is also the head of the ``vaporŝipo`` concept; ``vapor`` is
    # only the leading component of the same concept. Each is supported by
    # exactly one concept in the fixture.
    assert rows == {"vapor": 1, "ŝip": 1}


def test_function_word_and_skipped_concepts_get_no_concept_root_rows(
    fixture_db: Path, tmp_path: Path
) -> None:
    process_db(
        fixture_db, Decomposer(_build_inventory()),
        dry_run=False, out_dir=tmp_path / "out",
    )
    conn = sqlite3.connect(fixture_db)
    # ``kun`` is FUNCTION_WORD, ``k`` is UNRESOLVED, the empty-word row is
    # skipped. None of them should have concept_root rows.
    fn_cid, = conn.execute(
        "SELECT id FROM concept WHERE eo_word = 'kun'"
    ).fetchone()
    skip_cid, = conn.execute(
        "SELECT id FROM concept WHERE eo_word = ''"
    ).fetchone()
    unres_cid, = conn.execute(
        "SELECT id FROM concept WHERE eo_word = 'k'"
    ).fetchone()
    for cid in (fn_cid, skip_cid, unres_cid):
        n, = conn.execute(
            "SELECT COUNT(*) FROM concept_root WHERE concept_id = ?", (cid,),
        ).fetchone()
        assert n == 0, f"concept_id={cid} should have no concept_root rows"
    conn.close()


def test_summary_reports_required_counts(
    fixture_db: Path, tmp_path: Path
) -> None:
    summary, _u, _r, _x = process_db(
        fixture_db, Decomposer(_build_inventory()),
        dry_run=False, out_dir=tmp_path / "out",
    )
    assert summary.processed == 7
    assert summary.skipped_no_word == 1
    assert summary.function_word == 1
    assert summary.unresolved == 1
    # patro, malsanulejo, klimato are simple; vaporŝipo is compound.
    assert summary.simple == 3
    assert summary.compound == 1
    assert summary.concept_root_rows == 3 + 2  # 3 simples + 1 compound (2)
    assert summary.head_tier_distribution[TIER_CORE] == 4


# ---------------------------------------------------------------------------
# Idempotency + constraints
# ---------------------------------------------------------------------------


def test_db_pass_is_idempotent_byte_identical(
    fixture_db: Path, tmp_path: Path
) -> None:
    """Second run reports 0 eo_root changes and produces byte-identical
    ``concept_root`` and ``concept`` column state."""
    process_db(
        fixture_db, Decomposer(_build_inventory()),
        dry_run=False, out_dir=tmp_path / "out",
    )
    state_concept_1 = _read_concept_state(fixture_db)
    state_root_1 = _read_concept_root_state(fixture_db)

    summary_2, _u, _r, _x = process_db(
        fixture_db, Decomposer(_build_inventory()),
        dry_run=False, out_dir=tmp_path / "out",
    )
    state_concept_2 = _read_concept_state(fixture_db)
    state_root_2 = _read_concept_root_state(fixture_db)

    assert summary_2.eo_root_changed == 0
    assert state_concept_1 == state_concept_2
    assert state_root_1 == state_root_2


def test_db_pass_does_not_touch_protected_columns(
    fixture_db: Path, tmp_path: Path
) -> None:
    """``tier``, ``word``, ``cefr_level``, ``source`` and ``eo_word`` are
    byte-identical before vs after."""
    pre_concept = _read_concept_state(fixture_db)
    pre_lang = _read_concept_lang_state(fixture_db)

    process_db(
        fixture_db, Decomposer(_build_inventory()),
        dry_run=False, out_dir=tmp_path / "out",
    )

    post_concept = _read_concept_state(fixture_db)
    post_lang = _read_concept_lang_state(fixture_db)

    for cid in pre_concept:
        assert pre_concept[cid]["eo_word"] == post_concept[cid]["eo_word"]
    assert pre_lang == post_lang


def test_dry_run_does_not_write_to_db_or_jsonl(
    fixture_db: Path, tmp_path: Path
) -> None:
    out_dir = tmp_path / "out"
    pre_concept = _read_concept_state(fixture_db)
    pre_root = _read_concept_root_state(fixture_db)

    summary, _u, _r, _x = process_db(
        fixture_db, Decomposer(_build_inventory()),
        dry_run=True, out_dir=out_dir,
    )

    post_concept = _read_concept_state(fixture_db)
    post_root = _read_concept_root_state(fixture_db)

    assert pre_concept == post_concept
    assert pre_root == post_root  # both empty before & after on a dry-run
    assert not (out_dir / "eo_unresolved_stems.jsonl").exists()
    # Reported diff still describes what would have changed.
    assert summary.eo_root_changed >= 1


def test_no_eo_compounds_jsonl_emitted(
    fixture_db: Path, tmp_path: Path
) -> None:
    """The old compound artifact is gone — compounds live in concept_root."""
    out_dir = tmp_path / "out"
    process_db(
        fixture_db, Decomposer(_build_inventory()),
        dry_run=False, out_dir=out_dir,
    )
    assert not (out_dir / "eo_compounds.jsonl").exists()
    assert (out_dir / "eo_unresolved_stems.jsonl").exists()


# ---------------------------------------------------------------------------
# tier=modern protection (Part A)
# ---------------------------------------------------------------------------


def test_modern_tier_root_is_kept_whole_by_rule_1(decomposer: Decomposer) -> None:
    """A supplement entry (tier=modern, prod=-1) is treated like extended:
    Rule 1 short-circuits and returns SINGLE_ROOT without exploring
    decompositions. This prevents a modern borrowing like ``dvd`` from
    being misanalysed as a suffix-strip just because its productivity
    is unmeasured."""
    d = decomposer.decompose("dvd")
    assert d.kind == KIND_SINGLE_ROOT
    assert d.head.root == "dvd"
    assert d.head.tier == TIER_MODERN
    assert d.prefixes == ()
    assert d.suffixes == ()


def test_modern_tier_in_tier_rank_ties_with_extended() -> None:
    """``TIER_MODERN`` carries the same selection rank as ``TIER_EXTENDED``
    so that a supplement root never loses to a tail singleton in a
    decomposition tie-break."""
    from src.lexicon.eo_root_decomposer import TIER_RANK
    assert TIER_RANK[TIER_MODERN] == TIER_RANK[TIER_EXTENDED]
