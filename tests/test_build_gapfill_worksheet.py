"""Tests for the gap-fill worksheet builder (Phases 1-2 pure logic).

The spaCy-free pure functions are unit-tested here; the CLI glue (DB / ESPDIC
/ decomposer wiring) is exercised end-to-end in the actual run, not mocked.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "lexicon"))

from build_gapfill_worksheet import (  # noqa: E402
    AnchorProposal,
    consolidate_common_gap,
    normalise_sense,
    parse_espdic,
    propose_anchor,
    reclaim_proper_nouns,
    split_british_spellings,
    uk_to_us,
)


# ---------------------------------------------------------------------------
# A tiny fake decomposer standing in for the real Decomposer. Returns a
# Decomposition-like object with the attributes propose_anchor touches.
# ---------------------------------------------------------------------------


class _Root:
    def __init__(self, root: str) -> None:
        self.root = root
        self.tier = "core"
        self.position = 0


class _Dec:
    def __init__(self, roots: list[str]) -> None:
        self.content_roots = tuple(_Root(r) for r in roots)

    @property
    def is_compound(self) -> bool:
        return len(self.content_roots) >= 2


class _FakeDecomposer:
    """Maps EO headword -> list of root stems via an injected table."""

    def __init__(self, table: dict[str, list[str]]) -> None:
        self.table = table

    def decompose_word(self, word: str) -> _Dec:
        return _Dec(self.table.get(word, []))


# ---------------------------------------------------------------------------
# normalise_sense / parse_espdic
# ---------------------------------------------------------------------------


class TestNormaliseSense:
    def test_strips_infinitive_and_article(self) -> None:
        assert normalise_sense("to hug") == "hug"
        assert normalise_sense("a rainbow") == "rainbow"

    def test_strips_parenthetical_and_punctuation(self) -> None:
        assert normalise_sense("bug (insect)") == "bug"
        assert normalise_sense(" Doll! ") == "doll"


class TestParseEspdic:
    def test_reverse_and_forward(self) -> None:
        text = "brakumi : to hug, to embrace\nĉielarko : rainbow\n-ad- : suffix\n"
        reverse, forward = parse_espdic(text)
        assert reverse["hug"] == ["brakumi"]
        assert reverse["embrace"] == ["brakumi"]
        assert reverse["rainbow"] == ["ĉielarko"]
        assert forward["brakumi"] == "to hug, to embrace"
        # affix entries are skipped
        assert all(not h.startswith("-") for hs in reverse.values() for h in hs)

    def test_multiple_headwords_for_one_sense(self) -> None:
        text = "ĉielarko : rainbow\npluvarko : rainbow\n"
        reverse, _ = parse_espdic(text)
        assert reverse["rainbow"] == ["ĉielarko", "pluvarko"]


# ---------------------------------------------------------------------------
# Phase 1: consolidate / reclaim / british
# ---------------------------------------------------------------------------


def _row(token: str, freq: int, bucket: str, lemma: str = "") -> dict[str, str]:
    return {
        "token": token,
        "frequency": str(freq),
        "bucket": bucket,
        "is_propn": "0",
        "caps_majority": "0",
        "lemma": lemma or token,
    }


class TestConsolidate:
    def test_collapses_surface_forms_by_lemma(self) -> None:
        rows = [
            _row("hugged", 655, "common_gap", lemma="hug"),
            _row("hugging", 45, "common_gap", lemma="hug"),
            _row("doll", 249, "common_gap", lemma="doll"),
            _row("timmy", 999, "proper_noun", lemma="timmy"),  # excluded
        ]
        out = consolidate_common_gap(rows)
        assert out == {"hug": 700, "doll": 249}

    def test_falls_back_to_token_when_lemma_blank(self) -> None:
        rows = [_row("pond", 242, "common_gap", lemma="")]
        assert consolidate_common_gap(rows) == {"pond": 242}


class TestReclaim:
    def test_reclaims_common_word_with_anchor(self) -> None:
        rows = [
            _row("Mommy", 1441, "proper_noun", lemma="mommy"),
            _row("Timmy", 1829, "proper_noun", lemma="timmy"),
        ]
        reverse = {"mommy": ["panjo"]}  # timmy has no anchor
        assert reclaim_proper_nouns(rows, reverse) == {"mommy": 1441}

    def test_ignores_non_proper_noun_rows(self) -> None:
        rows = [_row("hugged", 10, "common_gap", lemma="hug")]
        assert reclaim_proper_nouns(rows, {"hug": ["brakumi"]}) == {}


class TestBritish:
    def test_uk_to_us_folds(self) -> None:
        assert uk_to_us("colour") == "color"
        assert uk_to_us("colourful") == "colorful"
        assert uk_to_us("favourite") == "favorite"
        assert uk_to_us("centre") == "center"
        assert uk_to_us("grey") == "gray"
        assert uk_to_us("dog") == "dog"  # unchanged

    def test_split_routes_variant_and_folds_frequency(self) -> None:
        lemmas = {"colour": 92, "dog": 5}
        # US form not in lexicon but is a real ESPDIC word -> fold onto us form
        remaining, british = split_british_spellings(
            lemmas, en_words=set(), reverse_index={"color": ["kolor"]}
        )
        assert "colour" not in remaining
        assert remaining["color"] == 92
        assert british[0]["uk_form"] == "colour"
        assert british[0]["us_form"] == "color"
        assert british[0]["us_in_lexicon"] is False

    def test_non_british_our_word_kept_as_gap(self) -> None:
        # 'sour' -> 'sor' is not a real word; must stay a normal gap lemma.
        remaining, british = split_british_spellings(
            {"sour": 66}, en_words=set(), reverse_index={}
        )
        assert remaining == {"sour": 66}
        assert british == []

    def test_variant_already_in_lexicon_not_refolded(self) -> None:
        remaining, british = split_british_spellings(
            {"colour": 92}, en_words={"color"}, reverse_index={}
        )
        assert "colour" not in remaining
        assert "color" not in remaining  # already covered; no concept row needed
        assert british[0]["us_in_lexicon"] is True


# ---------------------------------------------------------------------------
# Phase 2: propose_anchor
# ---------------------------------------------------------------------------


class TestProposeAnchor:
    def test_link_when_stem_exists(self) -> None:
        # eo_root is strip_flexion(headword); LINK iff that stem exists.
        reverse = {"good": ["bona"]}
        dec = _FakeDecomposer({"bona": ["bon"]})
        a = propose_anchor("good", reverse, {"bona": "good"}, dec, {"bon"})
        assert a.action == "LINK"
        assert a.eo_root == "bon"  # strip_flexion("bona")
        assert a.flag == "ok"

    def test_new_when_stem_absent(self) -> None:
        reverse = {"hug": ["brakumi"]}
        dec = _FakeDecomposer({"brakumi": ["brak"]})  # decomposer over-reduces
        a = propose_anchor("hug", reverse, {"brakumi": "to hug"}, dec, {"brak"})
        # strip_flexion keeps the meaning-bearing stem, so it is NOT a false LINK
        assert a.action == "NEW"
        assert a.eo_root == "brakum"

    def test_no_link_bias_prefers_shortest_sense(self) -> None:
        # 'hop': anchoring loan 'hopi' must win over existing-root 'danceti'.
        reverse = {"hop": ["danceti", "hopi", "salteti"]}
        dec = _FakeDecomposer(
            {"danceti": ["danc"], "hopi": ["hop"], "salteti": ["salt"]}
        )
        a = propose_anchor("hop", reverse, {"hopi": "to hop"}, dec, {"danc"})
        assert a.eo_word == "hopi"
        assert a.eo_root == "hop"
        assert a.action == "NEW"  # not a false LINK to 'danc'

    def test_compound_flagged_with_components(self) -> None:
        reverse = {"rainbow": ["ĉielarko"]}
        dec = _FakeDecomposer({"ĉielarko": ["ĉiel", "ark"]})
        a = propose_anchor("rainbow", reverse, {"ĉielarko": "rainbow"}, dec, set())
        assert a.action == "NEW"
        assert a.flag == "compound"
        assert a.component_roots == ["ĉiel", "ark"]
        assert a.eo_root == "ĉielark"  # strip_flexion, not the bare head root

    def test_no_match_when_only_multiword(self) -> None:
        reverse = {"butterfly": ["citrona papilio"]}
        dec = _FakeDecomposer({})
        a = propose_anchor("butterfly", reverse, {}, dec, set())
        assert a.action == ""
        assert a.flag == "no_match"
        assert a.alt_candidates == ["citrona papilio"]

    def test_no_match_when_absent(self) -> None:
        a = propose_anchor("zzz", {}, {}, _FakeDecomposer({}), set())
        assert a.flag == "no_match"
        assert isinstance(a, AnchorProposal)

    def test_alternatives_listed_not_flagged(self) -> None:
        # Polysemy/synonymy is surfaced via alt_candidates, not a noisy flag.
        reverse = {"bow": ["banto", "pafarko"]}
        dec = _FakeDecomposer({"banto": ["bant"], "pafarko": ["paf", "ark"]})
        a = propose_anchor("bow", reverse, {"banto": "bow"}, dec, set())
        assert a.eo_word == "banto"  # non-compound preferred
        assert a.eo_root == "bant"
        assert a.flag == "ok"
        assert a.alt_candidates == ["pafarko"]
