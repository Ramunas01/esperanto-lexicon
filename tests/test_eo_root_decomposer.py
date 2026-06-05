"""Tests for ``src.lexicon.eo_root_decomposer``.

These tests use a deliberately minimal in-memory inventory rather than the
real BRO ``eo_inventory.json``. The real BRO contains entries (``log`` as a
root, ``bo`` as a prefix) that would let ``blog`` decompose as ``bo + log``,
which is correct against BRO but not the algorithmic property the spec wants
to exercise. A controlled inventory lets each test case isolate exactly one
algorithmic rule.
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
    Decomposer,
    classify_unresolved,
    process_db,
)
from src.lexicon.schema import create_common_lexicon_schema


# ---------------------------------------------------------------------------
# Controlled inventory
# ---------------------------------------------------------------------------


def _build_inventory() -> dict:
    """Return a minimal inventory covering every spec test case.

    The contents are chosen so that:
      * ``maŝin`` stays whole via rule 1 (root listed; suffix ``-in`` is also
        listed and would otherwise wrongly strip).
      * ``kun`` is FUNCTION_WORD (listed in ``other``; not in roots).
      * ``vaporŝip`` is a clean two-root compound.
      * ``blog`` is UNRESOLVED — ``log`` is intentionally NOT listed as a
        root and ``bo`` is intentionally NOT listed as a prefix.
    """
    return {
        # gloss values irrelevant to the algorithm — only the keys matter.
        "roots": {
            "san": ["health"],
            "art": ["art"],
            "patr": ["father"],
            "vapor": ["steam"],
            "ŝip": ["ship"],
            "maŝin": ["machine"],
            "magazen": ["magazine"],
            "centr": ["centre"],
            "land": ["land"],
            "labor": ["labour"],
        },
        "suffixes": ["ist", "ej", "ul", "in", "et", "ar"],
        "prefixes": ["mal", "re", "ekster", "kun"],
        "correlatives": ["iu", "ili"],
        "other": ["kun", "kaj"],
    }


@pytest.fixture
def decomposer() -> Decomposer:
    return Decomposer(_build_inventory())


# ---------------------------------------------------------------------------
# Algorithmic property tests
# ---------------------------------------------------------------------------


def test_inventory_root_returns_single_root_unchanged(decomposer: Decomposer) -> None:
    """Rule 1: ``patr`` is in roots → SINGLE_ROOT with no affixes."""
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
    """``artist`` → root ``art``, suffix ``ist``."""
    d = decomposer.decompose("artist")
    assert d.kind == KIND_SINGLE_ROOT
    assert d.root == "art"
    assert d.prefixes == ()
    assert d.suffixes == ("ist",)


def test_compound_number_roots_recognised(decomposer: Decomposer) -> None:
    """``dudek`` → COMPOUND of number roots ``du`` + ``dek``."""
    d = decomposer.decompose("dudek")
    assert d.kind == KIND_COMPOUND
    assert d.components == ("du", "dek")


def test_inventory_root_protects_against_suffix_strip(decomposer: Decomposer) -> None:
    """Rule 1 must beat suffix-strip: ``maŝin`` stays whole, not ``maŝ+in``."""
    d = decomposer.decompose("maŝin")
    assert d.kind == KIND_SINGLE_ROOT
    assert d.root == "maŝin"
    assert d.prefixes == ()
    assert d.suffixes == ()


def test_function_word_classification(decomposer: Decomposer) -> None:
    """``kun`` is in ``other`` → FUNCTION_WORD, eo_root unchanged."""
    d = decomposer.decompose("kun")
    assert d.kind == KIND_FUNCTION_WORD


def test_function_word_with_accusative_n(decomposer: Decomposer) -> None:
    """``ilin`` → ``ili`` is a correlative → FUNCTION_WORD."""
    d = decomposer.decompose("ilin")
    assert d.kind == KIND_FUNCTION_WORD


def test_two_root_compound(decomposer: Decomposer) -> None:
    """``vaporŝip`` → COMPOUND, components [vapor, ŝip]."""
    d = decomposer.decompose("vaporŝip")
    assert d.kind == KIND_COMPOUND
    assert d.components == ("vapor", "ŝip")


def test_unresolved_loanword(decomposer: Decomposer) -> None:
    """``blog`` has no inventory match → UNRESOLVED, category ``loanword``."""
    d = decomposer.decompose("blog")
    assert d.kind == KIND_UNRESOLVED
    cat, _note = classify_unresolved("blog", decomposer)
    assert cat == "loanword"


def test_unresolved_single_char_artifact(decomposer: Decomposer) -> None:
    """Single character ``k`` → UNRESOLVED, category ``artifact``."""
    d = decomposer.decompose("k")
    assert d.kind == KIND_UNRESOLVED
    cat, _note = classify_unresolved("k", decomposer)
    assert cat == "artifact"


# ---------------------------------------------------------------------------
# DB-pass tests — idempotency and column-constraint check
# ---------------------------------------------------------------------------


def _seed_fixture_db(path: Path) -> dict[int, dict]:
    """Create a tiny v2 lexicon DB with a handful of concepts spanning each
    decomposer outcome. Returns the pre-run state keyed by concept id so the
    constraint-check test can verify unchanged columns.
    """
    conn = sqlite3.connect(path)
    create_common_lexicon_schema(conn)

    seed = [
        # (eo_root, eo_word, eo_prefix, eo_suffix) — covers each outcome.
        ("patr",        "patro",        "", ""),    # already correct
        ("malsanulej",  "malsanulejo",  "", ""),    # strip prefix+suffixes
        ("artist",      "artisto",      "", ""),    # strip suffix
        ("vaporŝip",    "vaporŝipo",    "", ""),    # compound
        ("kun",         "kun",          "", ""),    # function word
        ("blog",        "blogo",        "", ""),    # unresolved (loanword)
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
        # Attach an EN concept_lang row so we can prove the script doesn't
        # mutate non-target columns.
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


@pytest.fixture
def inventory_path(tmp_path: Path) -> Path:
    p = tmp_path / "inv.json"
    p.write_text(json.dumps(_build_inventory()), encoding="utf-8")
    return p


def test_db_pass_emits_compound_and_unresolved_jsonl(
    fixture_db: Path, inventory_path: Path, tmp_path: Path
) -> None:
    """One full pass produces the two jsonl artefacts with the right rows."""
    out_dir = tmp_path / "out"
    summary, _updates, compounds, unresolved = process_db(
        fixture_db,
        Decomposer(_build_inventory()),
        out_dir,
        dry_run=False,
    )
    # Counts add up.
    assert summary.processed == 6
    assert summary.compounds == 1
    assert summary.function_word == 1
    assert summary.unresolved == 1
    assert summary.updated == 2  # malsanulej + artist (compound row unchanged
    # because vaporŝip has no outer affixes, so no DB write needed for it).
    # Compound jsonl contents.
    comp_path = out_dir / "eo_compounds.jsonl"
    assert comp_path.exists()
    lines = comp_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["component_roots"] == ["vapor", "ŝip"]
    assert rec["eo_root_stem"] == "vaporŝip"
    # Unresolved jsonl contents.
    unres_path = out_dir / "eo_unresolved_stems.jsonl"
    assert unres_path.exists()
    lines = unres_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["category"] == "loanword"
    assert rec["eo_root_stem"] == "blog"


def test_db_pass_is_idempotent(
    fixture_db: Path, inventory_path: Path, tmp_path: Path
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

    summary_2, updates_2, _c2, _u2 = process_db(
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
    fixture_db: Path, inventory_path: Path, tmp_path: Path
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

    # eo_word never touched.
    for cid in pre_concept:
        assert pre_concept[cid]["eo_word"] == post_concept[cid]["eo_word"]
    # concept_lang completely untouched (tier, word, pos, cefr_level, source).
    assert pre_lang == post_lang


def test_dry_run_does_not_write_to_db_or_jsonl(
    fixture_db: Path, inventory_path: Path, tmp_path: Path
) -> None:
    """``--dry-run`` must leave the DB and jsonl outputs untouched."""
    out_dir = tmp_path / "out"
    pre_concept = _read_concept_state(fixture_db)

    summary, updates, _c, _u = process_db(
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
