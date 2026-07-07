"""Tests for the gap-fill merge prep (Phase A + B pure logic)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "analyzer"))

from gapfill_prep import phase_a, phase_b, propose_tier, review_flag  # noqa: E402


class _Root:
    def __init__(self, root: str) -> None:
        self.root = root


class _Dec:
    def __init__(self, roots: list[str]) -> None:
        self.content_roots = tuple(_Root(r) for r in roots)


class _FakeDecomposer:
    """word -> roots, and root -> inventory tier, via injected tables."""

    def __init__(self, roots: dict[str, list[str]], tiers: dict[str, str]) -> None:
        self._roots = roots
        self._tiers = tiers

    def decompose_word(self, word: str) -> _Dec:
        return _Dec(self._roots.get(word, []))

    def root_tier(self, root: str) -> str | None:
        return self._tiers.get(root)


DEC = _FakeDecomposer(
    roots={"pupo": ["pup"], "bubblegumo": ["maĉ", "gum"], "eviti": ["evit"]},
    tiers={"pup": "core", "gum": "tail", "evit": "core"},
)


class TestProposeTier:
    def test_seed_wins(self) -> None:
        seed = {"one": "1", "thirty": "2"}
        assert propose_tier("one", "one", 3, "unu", seed, DEC, 5) == "1"
        assert propose_tier("thirty", "thirty", 2, "tridek", seed, DEC, 5) == "2"

    def test_sense_split_key_uses_base(self) -> None:
        seed = {"spoil": "1"}
        assert propose_tier("spoil#pamper", "spoil", 47, "dorloti", seed, DEC, 5) == "1"

    def test_freq_head_tiering(self) -> None:
        assert propose_tier("hug", "hug", 1116, "brakumi", {}, DEC, 5) == "1"
        assert propose_tier("x", "x", 7, "io", {}, DEC, 5) == "2"

    def test_tail_defaults_tier2_never_tier1(self) -> None:
        # freq<threshold always Tier 2, regardless of anchor rarity.
        assert propose_tier("gator", "gator", 4, "bubblegumo", {}, DEC, 5) == "2"
        assert propose_tier("dodge", "dodge", 4, "eviti", {}, DEC, 5) == "2"


class TestReviewFlag:
    def test_rare_anchor_flagged(self) -> None:
        # tail root 'gum' -> rare-anchor
        assert review_flag(2, "bubblegumo", DEC, 5) == "rare-anchor"

    def test_common_anchor_not_flagged(self) -> None:
        assert review_flag(4, "eviti", DEC, 5) == ""  # 'evit' is core

    def test_above_threshold_never_flagged(self) -> None:
        assert review_flag(50, "bubblegumo", DEC, 5) == ""


class TestPhaseA:
    def _rows(self):
        return [
            {"decision": "accept", "en_lemma": "pond", "base_word": "pond",
             "total_freq": "242", "final_eo_root": "laget", "final_eo_word": "pupo",
             "band": "P2_hot", "eo_gloss": "old", "anchor_source": "curated", "note": ""},
            {"decision": "accept", "en_lemma": "bad", "base_word": "bad",
             "total_freq": "0", "final_eo_root": "", "final_eo_word": "",
             "band": "P5", "eo_gloss": "", "anchor_source": "", "note": ""},  # dropped
            {"decision": "accept", "en_lemma": "gator", "base_word": "gator",
             "total_freq": "4", "final_eo_root": "aligator", "final_eo_word": "bubblegumo",
             "band": "P6_tail", "eo_gloss": "x", "anchor_source": "curated", "note": ""},
            {"decision": "reject", "en_lemma": "no", "base_word": "no",
             "total_freq": "1", "final_eo_root": "r", "final_eo_word": "w",
             "band": "P5", "eo_gloss": "", "anchor_source": "", "note": ""},
        ]

    def test_drop_glossderive_triage(self) -> None:
        forward = {"pupo": "chrysalis, pupa, doll", "bubblegumo": ""}
        out = phase_a(self._rows(), forward, {}, DEC, threshold=5)
        assert len(out["dropped"]) == 1  # blank final_eo_root
        accepts = {a["en_lemma"]: a for a in out["accepts"]}
        # gloss re-derived from ESPDIC via final_eo_word
        assert accepts["pond"]["eo_gloss"] == "chrysalis, pupa, doll"
        assert accepts["pond"]["gloss_source"] == "espdic"
        # bubblegumo not in ESPDIC -> anchor flag + kept original gloss
        assert any(f["en_lemma"] == "gator" for f in out["anchor_flags"])
        assert accepts["gator"]["gloss_source"] == "kept_original"
        # freq<5 -> tier_triage, default T2, rare-anchor flagged
        tri = {t["en_lemma"]: t for t in out["tier_triage"]}
        assert tri["gator"]["proposed_tier"] == "2"
        assert tri["gator"]["review_flag"] == "rare-anchor"
        assert "pond" not in tri  # freq 242 not in tail


class TestPhaseB:
    def test_presence_proposal_and_straddle_exclusion(self) -> None:
        seed = [
            {"set_name": "colors", "member_en": "red", "category": "closed", "proposed_tier": "1"},
            {"set_name": "colors", "member_en": "teal", "category": "closed", "proposed_tier": "1"},
            {"set_name": "planets", "member_en": "mars", "category": "names-straddle", "proposed_tier": "Tnames"},
        ]
        gaps, straddle = phase_b(seed, covered={"red"}, propose=lambda m: (f"{m}o", f"{m} gloss"))
        by = {g["member_en"]: g for g in gaps}
        assert by["red"]["in_lexicon"] == "Y" and by["red"]["proposed_eo_anchor"] == ""
        assert by["teal"]["in_lexicon"] == "N" and by["teal"]["proposed_eo_anchor"] == "tealo"
        assert by["teal"]["proposed_tier"] == "1"  # carried from seed
        assert len(straddle) == 1 and straddle[0]["member_en"] == "mars"
        assert "mars" not in by  # excluded from authoring
