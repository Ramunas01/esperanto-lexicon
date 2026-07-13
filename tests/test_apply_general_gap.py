"""Tests for the general-adult gap merge path (source='general_gap_v1').

In-memory SQLite + a fake decomposer; no network, no real lexicon DB.
"""

from __future__ import annotations

import csv
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "lexicon"))

from apply_gapfill_merge import (  # noqa: E402
    GENERAL_GAP_SOURCE,
    _parse_root_detail,
    audit_eo_root_invariant,
    run_general_gap_merge,
)
from schema import create_common_lexicon_schema  # noqa: E402


# --- fake decomposer: strips the final grammatical ending for the head root --


class _CR:
    def __init__(self, root: str) -> None:
        self.root = root


class _Dec:
    def __init__(self, roots):
        self.content_roots = tuple(_CR(r) for r in roots)


class _FakeDecomposer:
    def decompose_word(self, word: str) -> _Dec:
        stem = word[:-1] if word[-1:] in "oaie" else word
        return _Dec([stem])

    def root_tier(self, root: str):
        return None


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    create_common_lexicon_schema(conn)
    return conn


def _worksheet(tmp_path, rows) -> Path:
    base = ["decision", "review_flag", "flag", "fold", "en_word", "anchor_root",
            "all_roots", "root_detail", "eo_word", "eo_pos", "proposed_tier",
            "gloss_zipf", "inv_tier", "prod", "gloss", "note"]
    extra = [k for r in rows for k in r if k not in base]
    cols = base + list(dict.fromkeys(extra))
    p = tmp_path / "ws.tsv"
    with p.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow(cols)
        for r in rows:
            w.writerow([r.get(c, "") for c in cols])
    return p


def _r(**kw):
    return kw


def test_authors_only_approved(db, tmp_path):
    ws = _worksheet(tmp_path, [
        _r(decision="approve", flag="common", en_word="carbon", anchor_root="karbon",
           eo_word="karbono", proposed_tier="2"),
        _r(decision="hold", flag="domain-adjacent", en_word="colonel",
           anchor_root="kolonel", eo_word="kolonelo", proposed_tier=""),
        _r(decision="reject", flag="common", en_word="rugby", anchor_root="rugbe",
           eo_word="rugbeo", proposed_tier="3"),
        _r(decision="", flag="common", en_word="fleet", anchor_root="flot",
           eo_word="floto", proposed_tier="3"),
    ])
    rep = run_general_gap_merge(db, ws, _FakeDecomposer())
    assert rep["authored"] == 1  # only carbon
    words = {w for (w,) in db.execute("SELECT word FROM concept_lang WHERE lang='en'")}
    assert words == {"carbon"}
    assert "colonel" not in words and "rugby" not in words and "fleet" not in words


def test_source_tier_and_invariant(db, tmp_path):
    ws = _worksheet(tmp_path, [
        _r(decision="approve", flag="common", en_word="carbon", anchor_root="karbon",
           eo_word="karbono", proposed_tier="2"),
    ])
    rep = run_general_gap_merge(db, ws, _FakeDecomposer())
    cid = next(iter(rep["new_cids"]))
    src, tier = db.execute(
        "SELECT source, tier FROM concept_lang WHERE concept_id=?", (cid,)).fetchone()
    assert src == GENERAL_GAP_SOURCE and tier == 2
    # invariant: concept.eo_root == concept_root head == decomposition head 'karbon'
    eo_root = db.execute("SELECT eo_root FROM concept WHERE id=?", (cid,)).fetchone()[0]
    head = db.execute(
        "SELECT root FROM concept_root WHERE concept_id=? AND is_head=1", (cid,)).fetchone()[0]
    assert eo_root == head == "karbon"
    audit = audit_eo_root_invariant(db, rep["new_cids"])
    assert audit["head_mismatches_new"] == 0
    assert audit["concept_lang_dupe_rows"] == 0
    assert audit["new_eo_word_collisions"] == 0


def test_verb_and_adjective_endings(db, tmp_path):
    ws = _worksheet(tmp_path, [
        _r(decision="approve", flag="common", en_word="ford", anchor_root="travad",
           eo_word="travadi", proposed_tier="3"),
        _r(decision="approve", flag="common", en_word="democratic", anchor_root="demokrat",
           eo_word="demokrata", proposed_tier="2"),
    ])
    rep = run_general_gap_merge(db, ws, _FakeDecomposer())
    assert rep["authored"] == 2
    roots = {w: r for w, r in db.execute(
        """SELECT cl.word, c.eo_root FROM concept c
           JOIN concept_lang cl ON cl.concept_id=c.id""")}
    assert roots["ford"] == "travad"       # travadi -> travad
    assert roots["democratic"] == "demokrat"  # demokrata -> demokrat


def test_missing_tier_is_skipped(db, tmp_path):
    ws = _worksheet(tmp_path, [
        _r(decision="approve", flag="common", en_word="x", anchor_root="x",
           eo_word="xo", proposed_tier=""),  # approved but no tier -> skip
    ])
    rep = run_general_gap_merge(db, ws, _FakeDecomposer())
    assert rep["authored"] == 0 and rep["skipped"] == 1


def test_reviewer_tier_column_overrides_proposed(db, tmp_path):
    # a reviewer-added 'tier' column takes precedence over proposed_tier
    cols = ["decision", "en_word", "anchor_root", "eo_word", "proposed_tier", "tier"]
    p = tmp_path / "ws2.tsv"
    with p.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow(cols)
        w.writerow(["approve", "carbon", "karbon", "karbono", "3", "2"])
    rep = run_general_gap_merge(db, p, _FakeDecomposer())
    tier = db.execute("SELECT tier FROM concept_lang WHERE lang='en'").fetchone()[0]
    assert tier == 2  # reviewer 'tier' wins


def test_idempotent_rerun(db, tmp_path):
    ws = _worksheet(tmp_path, [
        _r(decision="approve", flag="common", en_word="carbon", anchor_root="karbon",
           eo_word="karbono", proposed_tier="2"),
    ])
    run_general_gap_merge(db, ws, _FakeDecomposer())
    rep2 = run_general_gap_merge(db, ws, _FakeDecomposer())  # already authored
    assert rep2["authored"] == 0
    assert db.execute("SELECT COUNT(*) FROM concept_lang WHERE word='carbon'").fetchone()[0] == 1


# --- split handling ---------------------------------------------------------


def test_parse_root_detail():
    pairs = _parse_root_detail("kancelier=chancellor || rektor=chancellor, rector")
    assert pairs == [("kancelier", "chancellor"), ("rektor", "chancellor, rector")]


def test_split_authors_each_root_as_own_concept(db, tmp_path):
    ws = _worksheet(tmp_path, [
        _r(decision="split", en_word="erect", all_roots="erekt,vertikal",
           root_detail="erekt=to erect || vertikal=erect, vertical, upright",
           proposed_tier="3"),
    ])
    rep = run_general_gap_merge(db, ws, _FakeDecomposer())
    assert rep["split_concepts"] == 2 and rep["authored"] == 2
    rows = dict(db.execute(
        """SELECT c.eo_word, c.eo_root FROM concept c"""))
    # erekt -> 'to erect' -> verb ending i; vertikal -> adj/noun ending
    assert "erekti" in rows and rows["erekti"] == "erekt"
    assert any(w.startswith("vertikal") for w in rows)
    # both concepts carry the shared English head 'erect'
    ens = {w for (w,) in db.execute("SELECT word FROM concept_lang WHERE lang='en'")}
    assert ens == {"erect"}
    audit = audit_eo_root_invariant(db, rep["new_cids"])
    assert audit["head_mismatches_new"] == 0
    assert audit["new_eo_word_collisions"] == 0  # erekti != vertikal* -> distinct


def test_split_uses_proposed_tier(db, tmp_path):
    ws = _worksheet(tmp_path, [
        _r(decision="split", en_word="acute", all_roots="akut,sagac",
           root_detail="akut=acute || sagac=acute, shrewd", proposed_tier="2"),
    ])
    rep = run_general_gap_merge(db, ws, _FakeDecomposer())
    tiers = {t for (t,) in db.execute("SELECT DISTINCT tier FROM concept_lang")}
    assert tiers == {2}
    assert rep["by_tier"] == {2: 2}


def test_review_flag_r9park_approve_is_authored(db, tmp_path):
    # review_flag is metadata: an R9-park *approve* must still be authored.
    ws = _worksheet(tmp_path, [
        _r(decision="approve", review_flag="R9-park (Effort B)", en_word="carbon",
           anchor_root="karbon", eo_word="karbono", proposed_tier="3"),
    ])
    rep = run_general_gap_merge(db, ws, _FakeDecomposer())
    assert rep["authored"] == 1
    assert db.execute("SELECT COUNT(*) FROM concept_lang WHERE word='carbon'").fetchone()[0] == 1


def test_hold_is_skipped_not_authored(db, tmp_path):
    ws = _worksheet(tmp_path, [
        _r(decision="hold", review_flag="R9-park (Effort B)", en_word="agricultural",
           anchor_root="agrikultur", eo_word="agrikultura", proposed_tier=""),
    ])
    rep = run_general_gap_merge(db, ws, _FakeDecomposer())
    assert rep["authored"] == 0 and rep["held"] == 1
    assert db.execute("SELECT COUNT(*) FROM concept").fetchone()[0] == 0
