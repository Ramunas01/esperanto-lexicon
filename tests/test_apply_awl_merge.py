"""Tests for the Tier-3 AWL family merge (Phase 4) in apply_gapfill_merge.

Pure logic + an in-memory SQLite carrying the common-lexicon schema. No network,
no spaCy (POS is an injected fake), no real lexicon DB.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "lexicon"))

from apply_gapfill_merge import (  # noqa: E402
    AWL_ROOT_OVERRIDES,
    AWL_SOURCE_TAG,
    AWL_TIER,
    audit_eo_root_invariant,
    author_awl_family,
    awl_final_eo_word,
    awl_roots_for,
    resolve_awl_family,
)
from eo_root_decomposer import strip_flexion  # noqa: E402
from schema import create_common_lexicon_schema  # noqa: E402


# --- fakes ------------------------------------------------------------------


class _CR:
    def __init__(self, root: str) -> None:
        self.root = root


class _Dec:
    def __init__(self, roots: list[str]) -> None:
        self.content_roots = tuple(_CR(r) for r in roots)


class _FakeDecomposer:
    """decompose_word returns controlled roots; root_tier is irrelevant here."""

    def __init__(self, mapping: dict[str, list[str]] | None = None) -> None:
        self._m = mapping or {}

    def decompose_word(self, word: str) -> _Dec:
        return _Dec(self._m.get(word, [strip_flexion(word)]))

    def root_tier(self, root: str):
        return None


def _pos(_word: str) -> str:
    return "NOUN"  # deterministic fake tagger


@pytest.fixture
def db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    create_common_lexicon_schema(conn)
    return conn


def _add_concept(conn, eo_word, eo_root, en_words=(), tier=None, head_pos="NOUN"):
    cur = conn.execute(
        "INSERT INTO concept (eo_root, eo_word, eo_pos, eo_status) VALUES (?,?,?,'complete')",
        (eo_root, eo_word, head_pos),
    )
    cid = cur.lastrowid
    conn.execute(
        "INSERT INTO concept_root (concept_id, root, position, is_head, tier) VALUES (?,?,0,1,NULL)",
        (cid, eo_root),
    )
    for w in en_words:
        conn.execute(
            "INSERT INTO concept_lang (concept_id, lang, word, pos, tier, source) "
            "VALUES (?, 'en', ?, 'NOUN', ?, 'seed')",
            (cid, w, tier),
        )
    return cid


# --- awl_final_eo_word ------------------------------------------------------


def test_final_eo_word_fix_uses_corrected():
    row = {"decision": "fix", "corrected_eo_word": "per", "current_eo_word": ""}
    assert awl_final_eo_word(row) == "per"


def test_final_eo_word_approve_uses_current():
    row = {"decision": "approve", "corrected_eo_word": "", "current_eo_word": "nocio"}
    assert awl_final_eo_word(row) == "nocio"


def test_final_eo_word_fix_without_correction_falls_back():
    row = {"decision": "fix", "corrected_eo_word": "  ", "current_eo_word": "areo"}
    assert awl_final_eo_word(row) == "areo"


# --- awl_roots_for ----------------------------------------------------------


def test_roots_override_dinamika():
    assert "dinamika" in AWL_ROOT_OVERRIDES
    roots, method = awl_roots_for("dinamika", _FakeDecomposer())
    assert method == "override"
    assert [r for r, _ in roots] == ["dinamik"]  # NOT the din+amik split


def test_roots_decomposed_compound():
    dec = _FakeDecomposer({"leĝdoni": ["leĝ", "don"]})
    roots, method = awl_roots_for("leĝdoni", dec)
    assert method == "decomposed"
    assert [r for r, _ in roots] == ["leĝ", "don"]  # head 'don' last


def test_roots_single_letter_split_falls_back_to_stem():
    dec = _FakeDecomposer({"apuda": ["x"]})  # bad single-letter split
    roots, method = awl_roots_for("apuda", dec)
    assert method == "single-fallback"
    assert [r for r, _ in roots] == ["apud"]  # strip_flexion('apuda')


def test_roots_never_degenerate():
    # 'ajn' strips to 'a' (1 char) -> must fall through to the whole word.
    dec = _FakeDecomposer({"ajn": ["j"]})
    roots, method = awl_roots_for("ajn", dec)
    assert method == "whole-word"
    assert [r for r, _ in roots] == ["ajn"]
    assert all(len(r) >= 2 for r, _ in roots)


# --- resolve_awl_family -----------------------------------------------------


def test_resolve_link_by_eo_word(db):
    _add_concept(db, "per", "per", en_words=["via"])
    kind, cid, why = resolve_awl_family(db, "via", ["via"], "per")
    assert kind == "LINK" and why == "eo_word"


def test_resolve_link_by_head_form(db):
    cid0 = _add_concept(db, "areo", "are", en_words=["area"])
    kind, cid, why = resolve_awl_family(db, "area", ["area", "areas"], "cXX")
    assert kind == "LINK" and cid == cid0 and why == "head_form"


def test_resolve_new_when_absent(db):
    kind, cid, why = resolve_awl_family(db, "constitute", ["constitute"], "konstitui")
    assert kind == "NEW" and cid is None


def test_resolve_ambiguous_multi_concept(db):
    # The head form itself sits on two concepts (like 'plus'/'percent' in the
    # real data) -> genuinely ambiguous; LINK to the lowest, flagged AMBIG.
    c1 = _add_concept(db, "plus1", "plusa", en_words=["plus"])
    _add_concept(db, "plus2", "plusb", en_words=["plus"])
    kind, cid, why = resolve_awl_family(db, "plus", ["plus"], "novXX")
    assert kind == "LINK" and why.startswith("AMBIG")
    assert cid == c1  # lowest head-concept id


# --- author_awl_family ------------------------------------------------------


def test_author_new_family_holds_invariant(db):
    row = {"decision": "approve", "current_eo_word": "konstitui", "family_head": "constitute"}
    forms = ["constitute", "constitution", "constitutes"]
    out = author_awl_family(db, row, forms, set(), _FakeDecomposer(), _pos)
    assert out["kind"] == "NEW" and out["new_concept"] == 1
    assert out["rows"] == 3
    cid = out["concept_id"]
    eo_root, = db.execute("SELECT eo_root FROM concept WHERE id=?", (cid,)).fetchone()
    head_root, = db.execute(
        "SELECT root FROM concept_root WHERE concept_id=? AND is_head=1", (cid,)
    ).fetchone()
    assert eo_root == head_root  # the invariant
    tiers = {t for (t,) in db.execute(
        "SELECT DISTINCT tier FROM concept_lang WHERE concept_id=?", (cid,))}
    assert tiers == {AWL_TIER}
    src = {s for (s,) in db.execute(
        "SELECT DISTINCT source FROM concept_lang WHERE concept_id=?", (cid,))}
    assert src == {AWL_SOURCE_TAG}


def test_author_via_links_to_per_not_new(db):
    per = _add_concept(db, "per", "per", en_words=["via"])
    row = {"decision": "fix", "corrected_eo_word": "per", "current_eo_word": "",
           "family_head": "via"}
    out = author_awl_family(db, row, ["via"], {"via"}, _FakeDecomposer(), _pos)
    assert out["kind"] == "LINK" and out["concept_id"] == per
    assert out["new_concept"] == 0
    # 'via' already present -> skipped, and NO concept with eo_word='via' created
    assert db.execute("SELECT COUNT(*) FROM concept WHERE eo_word='via'").fetchone()[0] == 0
    assert out["skipped"] == 1 and out["rows"] == 0


def test_author_dynamic_uses_single_root(db):
    row = {"decision": "fix", "corrected_eo_word": "dinamika", "current_eo_word": "",
           "family_head": "dynamic"}
    out = author_awl_family(
        db, row, ["dynamic", "dynamics"], set(),
        _FakeDecomposer({"dinamika": ["din", "amik"]}), _pos,
    )
    assert out["kind"] == "NEW" and out["root_method"] == "override"
    eo_root, = db.execute(
        "SELECT eo_root FROM concept WHERE id=?", (out["concept_id"],)
    ).fetchone()
    assert eo_root == "dinamik"  # NOT 'amik'


def test_author_multiword_deferred(db):
    row = {"decision": "fix", "corrected_eo_word": "per kio", "current_eo_word": "",
           "family_head": "whereby"}
    out = author_awl_family(db, row, ["whereby"], set(), _FakeDecomposer(), _pos)
    assert out["deferred"] == "multiword"
    assert out["new_concept"] == 0 and out["rows"] == 0


def test_author_skips_already_present_members(db):
    row = {"decision": "approve", "current_eo_word": "taksi", "family_head": "assess"}
    forms = ["assess", "assessment"]
    out = author_awl_family(db, row, forms, {"assessment"}, _FakeDecomposer(), _pos)
    assert out["skipped"] == 1  # assessment already present
    assert out["rows"] == 1  # only 'assess' inserted


def test_author_idempotent_second_run(db):
    row = {"decision": "approve", "current_eo_word": "difini", "family_head": "define"}
    forms = ["define", "definition"]
    existing: set = set()
    author_awl_family(db, row, forms, existing, _FakeDecomposer(), _pos)
    # simulate a re-run: existing_en now carries the inserted forms
    out2 = author_awl_family(db, row, forms, {"define", "definition"}, _FakeDecomposer(), _pos)
    assert out2["rows"] == 0  # nothing re-inserted
    total = db.execute(
        "SELECT COUNT(*) FROM concept_lang WHERE lang='en' AND word IN ('define','definition')"
    ).fetchone()[0]
    assert total == 2  # no duplicates


# --- audit ------------------------------------------------------------------


def test_audit_clean_new_concept(db):
    row = {"decision": "approve", "current_eo_word": "difini", "family_head": "define"}
    out = author_awl_family(db, row, ["define"], set(), _FakeDecomposer(), _pos)
    audit = audit_eo_root_invariant(db, {out["concept_id"]})
    assert audit["head_mismatches_new"] == 0
    assert audit["new_without_head_root"] == []
    assert audit["degenerate_head_roots_new"] == []
    assert audit["new_eo_word_collisions"] == 0
    assert audit["concept_lang_dupe_rows"] == 0


def test_audit_detects_head_mismatch(db):
    # Author a concept whose stored eo_root disagrees with its head root.
    cur = db.execute(
        "INSERT INTO concept (eo_root, eo_word, eo_pos, eo_status) VALUES ('WRONG','x','NOUN','complete')"
    )
    cid = cur.lastrowid
    db.execute(
        "INSERT INTO concept_root (concept_id, root, position, is_head, tier) VALUES (?,?,0,1,NULL)",
        (cid, "right"),
    )
    audit = audit_eo_root_invariant(db, {cid})
    assert audit["head_mismatches_new"] == 1
