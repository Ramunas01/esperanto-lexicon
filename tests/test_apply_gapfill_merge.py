"""Tests for the Phase-D gap-fill merge writer."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "lexicon"))

from apply_gapfill_merge import (  # noqa: E402
    apply_number,
    author_concept,
    derive_pos,
    reconcile,
    tier_to_cefr,
)


class _Root:
    def __init__(self, r): self.root = r


class _Dec:
    def __init__(self, roots): self.content_roots = tuple(_Root(r) for r in roots)


class _FakeDecomposer:
    def __init__(self, roots, tiers): self._r, self._t = roots, tiers
    def decompose_word(self, w): return _Dec(self._r.get(w, []))
    def root_tier(self, r): return self._t.get(r)


DEC = _FakeDecomposer(
    roots={"brakumi": ["brak"], "ĉielarko": ["ĉiel", "ark"], "nombro": ["nombr"],
           "palmo": ["palm"], "manplato": ["man", "plat"]},
    tiers={"brak": "core", "ĉiel": "core", "ark": "core", "nombr": "core",
           "palm": "tail", "man": "core", "plat": "core"},
)


def test_derive_pos_and_cefr():
    assert derive_pos("brakumi") == "VERB"
    assert derive_pos("nombro") == "NOUN"
    assert derive_pos("bona") == "ADJ"
    assert derive_pos("rapide") == "ADV"
    assert tier_to_cefr(1) == "A1" and tier_to_cefr(2) == "A2"


def _acc(lemma, word, root, tier="2"):
    return {"en_lemma": lemma, "final_eo_word": word, "final_eo_root": root,
            "proposed_tier": tier}


class TestReconcile:
    def test_drop_and_setgap_wins_and_splits(self):
        accepts = [
            _acc("giraffe", "ĝirafo", "ĝiraf", "1"),   # overlaps set-gap → skipped
            _acc("beachs", "strando", "strand"),        # dropped
            _acc("palm#tree", "palmo", "palm"),          # sense-split → kept
            _acc("palm#hand", "manplato", "man"),        # sense-split → kept
            _acc("hug", "brakumi", "brak", "1"),         # plain, not in set-gap → kept
        ]
        rare = [{"en_lemma": "beachs", "decision": "drop", "final_tier": ""}]
        set_gaps = [{"member_en": "giraffe", "decision": "ok", "proposed_eo_anchor": "ĝiraf/ĝirafo",
                     "corrected_eo_word": "", "proposed_tier": "1"}]
        out = reconcile(accepts, rare, set_gaps, existing_en=set())
        words = {r["key"] for r in out}
        assert "giraffe" in words          # authored from set-gap
        assert "beachs" not in words       # dropped
        assert "palm#tree" in words and "palm#hand" in words  # both splits kept
        assert "hug" in words
        # giraffe authored once, tier from seed (1)
        g = [r for r in out if r["key"] == "giraffe"][0]
        assert g["source"] == "set_completeness_v1" and g["tier"] == 1

    def test_existing_word_skipped(self):
        accepts = [_acc("hug", "brakumi", "brak")]
        out = reconcile(accepts, [], [], existing_en={"hug"})
        assert out == []

    def test_setgap_fix_uses_corrected_word(self):
        set_gaps = [{"member_en": "rainbow", "decision": "fix",
                     "proposed_eo_anchor": "pluvark/pluvarko",
                     "corrected_eo_word": "ĉielarko", "proposed_tier": "1"}]
        out = reconcile([], [], set_gaps, existing_en=set())
        assert out[0]["eo_word"] == "ĉielarko"


# ---------------------------------------------------------------------------
# Writing against an in-memory DB
# ---------------------------------------------------------------------------

_DDL = """
CREATE TABLE concept (id INTEGER PRIMARY KEY AUTOINCREMENT, eo_root TEXT, eo_word TEXT,
  eo_pos TEXT, eo_prefix TEXT, eo_suffix TEXT, eo_status TEXT DEFAULT 'pending',
  wordnet_synset TEXT, wordnet_definition TEXT, hypernym_chain TEXT, immediate_hypernym TEXT);
CREATE TABLE concept_lang (id INTEGER PRIMARY KEY AUTOINCREMENT, concept_id INTEGER NOT NULL,
  lang TEXT NOT NULL, word TEXT NOT NULL, pos TEXT, cefr_level TEXT, tier INTEGER, source TEXT);
CREATE TABLE concept_root (concept_id INTEGER NOT NULL, root TEXT NOT NULL, position INTEGER NOT NULL,
  is_head INTEGER NOT NULL DEFAULT 0, tier TEXT, PRIMARY KEY (concept_id, position));
"""


def _db():
    c = sqlite3.connect(":memory:")
    c.executescript(_DDL)
    return c


class TestAuthor:
    def test_eo_root_is_head_and_compound_rows(self):
        c = _db()
        # compound: ĉielarko -> ĉiel + ark ; eo_root must equal head 'ark'
        author_concept(c, {"en_word": "rainbow", "eo_word": "ĉielarko", "eo_root": "pluvark",
                           "tier": 1, "source": "set_completeness_v1", "key": "rainbow"}, DEC)
        cid, root, word = c.execute("SELECT id,eo_root,eo_word FROM concept").fetchone()
        assert root == "ark" and word == "ĉielarko"   # head, not the stale 'pluvark'
        roots = c.execute("SELECT root,position,is_head FROM concept_root ORDER BY position").fetchall()
        assert roots == [("ĉiel", 0, 0), ("ark", 1, 1)]
        cl = c.execute("SELECT word,pos,cefr_level,tier,source FROM concept_lang").fetchone()
        assert cl == ("rainbow", "NOUN", "A1", 1, "set_completeness_v1")

    def test_idempotent_skip(self):
        c = _db()
        row = {"en_word": "hug", "eo_word": "brakumi", "eo_root": "brak", "tier": 1,
               "source": "tinystories_gap_v1", "key": "hug"}
        assert author_concept(c, row, DEC) is True
        assert author_concept(c, row, DEC) is False   # second time skipped
        assert c.execute("SELECT COUNT(*) FROM concept").fetchone()[0] == 1

    def test_apply_number(self):
        c = _db()
        c.execute("INSERT INTO concept (id,eo_root,eo_word,eo_status) VALUES (2694,NULL,NULL,'pending')")
        c.execute("INSERT INTO concept_lang (concept_id,lang,word,pos,cefr_level,tier,source)"
                  " VALUES (2694,'en','number','NOUN','C1',3,'tier3_unknown_pool')")
        apply_number(c, DEC)
        con = c.execute("SELECT eo_root,eo_word,eo_pos FROM concept WHERE id=2694").fetchone()
        assert con == ("nombr", "nombro", "NOUN")
        cl = c.execute("SELECT tier,cefr_level FROM concept_lang WHERE concept_id=2694").fetchone()
        assert cl == (1, "C1")   # tier demoted, cefr untouched
        assert c.execute("SELECT root,is_head FROM concept_root WHERE concept_id=2694").fetchone() == ("nombr", 1)
