"""Unit tests for the Tier-3 AWL worksheet builder (pure bits only).

Covers the AWL parser + junk gate, form normalisation, the morphological POS
tagger + injected-fallback tagger, the US-spelling variant generator, the
family LINK/NEW classifier + member split, the worksheet writer, and the
read-only tier loader (via an in-memory DB). No network, no spaCy, no real
lexicon DB — the spaCy fallback is exercised through an injected fake.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "lexicon"))

from build_awl_worksheet import (  # noqa: E402
    DEFAULT_CEFR,
    DEFAULT_TIER,
    WORKSHEET_COLUMNS,
    Family,
    build_rows,
    classify_family,
    load_awl_families,
    load_en_word_tiers,
    make_pos_tagger,
    morphological_pos,
    normalize_form,
    row_to_cells,
    summarise,
    us_spelling_variants,
    write_worksheet,
)
from eo_root_decomposer import strip_flexion  # noqa: E402


# ---------------------------------------------------------------------------
# Fake decomposer (propose_anchor needs .decompose_word -> .is_compound /
# .content_roots[].root). Single root by default; multi root = compound.
# ---------------------------------------------------------------------------


class _CR:
    def __init__(self, root: str) -> None:
        self.root = root


class _Decomp:
    def __init__(self, roots: list[str]) -> None:
        self.content_roots = tuple(_CR(r) for r in roots)

    @property
    def is_compound(self) -> bool:
        return len(self.content_roots) >= 2


class _FakeDecomposer:
    def __init__(self, compounds: dict[str, list[str]] | None = None) -> None:
        self._c = compounds or {}

    def decompose_word(self, word: str) -> _Decomp:
        return _Decomp(self._c.get(word, [strip_flexion(word)]))


# ---------------------------------------------------------------------------
# normalize_form / junk gate
# ---------------------------------------------------------------------------


def test_normalize_form_lowercases_and_folds_unicode_hyphen():
    assert normalize_form("  Co‑ordinate ") == "co-ordinate"  # U+2011
    assert normalize_form("re–assess") == "re-assess"  # en dash
    assert normalize_form("ANALYSE") == "analyse"


# ---------------------------------------------------------------------------
# morphological_pos
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "word,expected",
    [
        ("analytically", "ADV"),
        ("significantly", "ADV"),
        ("availability", "NOUN"),
        ("assessment", "NOUN"),
        ("consistency", "NOUN"),
        ("analyse", "VERB"),  # -yse
        ("maximize", "VERB"),
        ("identify", "VERB"),
        ("analytical", "ADJ"),  # -ical
        ("hazardous", "ADJ"),
        ("accessible", "ADJ"),
    ],
)
def test_morphological_pos_hits(word, expected):
    assert morphological_pos(word) == expected


@pytest.mark.parametrize("word", ["derive", "perspective", "process", "area", "concept", "supply"])
def test_morphological_pos_leaves_ambiguous_to_fallback(word):
    # -ive verbs/nouns, bare roots, and non-adverb -ly words must NOT be forced.
    assert morphological_pos(word) is None


def test_morphological_pos_short_word_none():
    assert morphological_pos("go") is None


# ---------------------------------------------------------------------------
# make_pos_tagger (morphology -> injected spaCy -> NOUN)
# ---------------------------------------------------------------------------


class _FakeSpacyDoc:
    def __init__(self, pos: str) -> None:
        self._pos = pos

    def __getitem__(self, i):
        tok = type("T", (), {"pos_": self._pos})()
        return tok

    def __bool__(self) -> bool:
        return True


def _fake_spacy(mapping):
    return lambda w: _FakeSpacyDoc(mapping.get(w, "PROPN"))


def test_tagger_morphology_wins_over_spacy():
    tagger = make_pos_tagger(_fake_spacy({"analytical": "NOUN"}))
    assert tagger("analytical") == "ADJ"  # morphology (-ical) beats spaCy's NOUN


def test_tagger_uses_spacy_for_ambiguous():
    tagger = make_pos_tagger(_fake_spacy({"derive": "VERB", "perspective": "NOUN"}))
    assert tagger("derive") == "VERB"
    assert tagger("perspective") == "NOUN"


def test_tagger_propn_falls_back_to_noun():
    tagger = make_pos_tagger(_fake_spacy({"foobar": "PROPN"}))
    assert tagger("foobar") == "NOUN"


def test_tagger_no_spacy_defaults_noun():
    tagger = make_pos_tagger(None)
    assert tagger("area") == "NOUN"  # no morphology, no spaCy -> NOUN
    assert tagger("analytical") == "ADJ"  # morphology still applies


# ---------------------------------------------------------------------------
# us_spelling_variants
# ---------------------------------------------------------------------------


def test_us_spelling_variants():
    assert us_spelling_variants("analyse")[0] == "analyse"
    assert "analyze" in us_spelling_variants("analyse")
    assert "maximize" in us_spelling_variants("maximise")
    assert "labor" in us_spelling_variants("labour")
    assert "license" in us_spelling_variants("licence")
    assert us_spelling_variants("concept") == ["concept"]  # nothing to fold


# ---------------------------------------------------------------------------
# load_awl_families
# ---------------------------------------------------------------------------


@pytest.fixture
def awl_fixture(tmp_path) -> Path:
    data = {
        "sublist_1": {
            "analyse": {"subwords": ["analysis", "analyst", "analyse", "Analytical"]},
            "area": {"subwords": ["areas"]},
            "despite": {"subwords": None},  # single-form family
        },
        "sublist_2": {
            "co‑ordinate": {"subwords": ["co‑ordinated"]},  # U+2011 hyphen
            "x": {"subwords": ["ok"]},  # junk head (single char) -> dropped
        },
    }
    p = tmp_path / "awl.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def test_load_awl_families_structure(awl_fixture):
    families, dropped = load_awl_families(awl_fixture)
    heads = {f.head for f in families}
    assert "analyse" in heads and "area" in heads and "despite" in heads
    assert "co-ordinate" in heads  # U+2011 folded, family survives
    assert "x" not in heads and "x" in dropped  # junk head dropped


def test_load_awl_families_head_removed_from_members_and_deduped(awl_fixture):
    families, _ = load_awl_families(awl_fixture)
    analyse = next(f for f in families if f.head == "analyse")
    # head 'analyse' removed from members; 'Analytical' lowercased; sorted
    assert "analyse" not in analyse.members
    assert "analytical" in analyse.members
    assert list(analyse.members) == sorted(set(analyse.members))


def test_load_awl_families_null_subwords_is_headonly(awl_fixture):
    families, _ = load_awl_families(awl_fixture)
    despite = next(f for f in families if f.head == "despite")
    assert despite.members == ()
    assert despite.forms == ("despite",)


def test_load_awl_families_sorted_by_sublist(awl_fixture):
    families, _ = load_awl_families(awl_fixture)
    sublists = [f.sublist for f in families]
    assert sublists == sorted(sublists)


# ---------------------------------------------------------------------------
# classify_family — LINK / NEW / manual + member split + spelling fallback
# ---------------------------------------------------------------------------


def _tagger():
    return make_pos_tagger(None)  # morphology + NOUN fallback, deterministic


def test_classify_new_family():
    fam = Family("constitute", 1, ("constitutes", "constitution"))
    rev = {"constitute": ["konstitui"]}
    fwd = {"konstitui": "to constitute"}
    row = classify_family(
        fam, rev, fwd, _FakeDecomposer(), existing_roots=set(),
        en_tiers={}, pos_tagger=_tagger(),
    )
    assert row.action == "NEW"
    assert row.eo_root == strip_flexion("konstitui")  # 'konstitu'
    assert row.flag == "ok"
    assert {w for w, _ in row.forms_new} == {"constitute", "constitutes", "constitution"}
    assert row.forms_present == []


def test_classify_link_by_existing_root():
    fam = Family("concept", 1, ("concepts",))
    rev = {"concept": ["nocio"]}
    fwd = {"nocio": "notion, concept"}
    root = strip_flexion("nocio")  # 'noci'
    row = classify_family(
        fam, rev, fwd, _FakeDecomposer(), existing_roots={root},
        en_tiers={}, pos_tagger=_tagger(),
    )
    assert row.action == "LINK"


def test_classify_link_by_existing_en_head():
    fam = Family("area", 1, ("areas",))
    rev = {"area": ["areo"]}
    fwd = {"areo": "area"}
    row = classify_family(
        fam, rev, fwd, _FakeDecomposer(), existing_roots=set(),
        en_tiers={"area": [1]}, pos_tagger=_tagger(),
    )
    assert row.action == "LINK"  # head already in lexicon
    assert ("area", [1]) in row.forms_present  # present member skipped
    assert all(w != "area" for w, _ in row.forms_new)


def test_classify_manual_when_no_anchor_and_absent():
    fam = Family("thereby", 8, ())
    row = classify_family(
        fam, {}, {}, _FakeDecomposer(), existing_roots=set(),
        en_tiers={}, pos_tagger=_tagger(),
    )
    assert row.action == ""  # no ESPDIC anchor, not in lexicon -> manual
    assert row.flag == "no_match"


def test_classify_spelling_fallback_anchors_british_head():
    fam = Family("analyse", 1, ("analysis",))
    rev = {"analyze": ["analizi"]}  # only the US spelling is in ESPDIC
    fwd = {"analizi": "to analyze"}
    row = classify_family(
        fam, rev, fwd, _FakeDecomposer(), existing_roots=set(),
        en_tiers={}, pos_tagger=_tagger(),
    )
    assert row.flag == "ok"
    assert row.eo_root == strip_flexion("analizi")
    assert any("US spelling" in n for n in row.notes)


def test_classify_member_tier_split():
    fam = Family("assess", 1, ("assessment", "assessed"))
    rev = {"assess": ["taksi"]}
    fwd = {"taksi": "to assess"}
    row = classify_family(
        fam, rev, fwd, _FakeDecomposer(), existing_roots=set(),
        en_tiers={"assessment": [2]}, pos_tagger=_tagger(),
    )
    present = dict(row.forms_present)
    assert present.get("assessment") == [2]  # already present -> skipped
    assert "assessment" not in {w for w, _ in row.forms_new}


# ---------------------------------------------------------------------------
# row_to_cells / write_worksheet
# ---------------------------------------------------------------------------


def test_row_to_cells_column_order():
    fam = Family("area", 1, ("areas",))
    rev = {"area": ["areo"]}
    row = classify_family(
        fam, rev, {"areo": "area"}, _FakeDecomposer(), set(), {}, _tagger()
    )
    cells = row_to_cells(row)
    assert len(cells) == len(WORKSHEET_COLUMNS)
    assert cells[0] == 1  # sublist
    assert cells[1] == "area"  # family_head
    assert cells[WORKSHEET_COLUMNS.index("proposed_tier")] == DEFAULT_TIER
    assert cells[WORKSHEET_COLUMNS.index("cefr")] == DEFAULT_CEFR
    assert cells[WORKSHEET_COLUMNS.index("decision")] == ""  # blank for reviewer


def test_write_worksheet_roundtrip(tmp_path):
    fams = [Family("area", 1, ("areas",)), Family("concept", 1, ("concepts",))]
    rev = {"area": ["areo"], "concept": ["nocio"]}
    fwd = {"areo": "area", "nocio": "concept"}
    rows = build_rows(fams, rev, fwd, _FakeDecomposer(), set(), {}, _tagger())
    out = tmp_path / "ws.tsv"
    write_worksheet(rows, out)
    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines[0].split("\t") == WORKSHEET_COLUMNS
    assert len(lines) == 3  # header + 2 families


def test_summarise_counts():
    fams = [Family("area", 1, ("areas",)), Family("thereby", 8, ())]
    rev = {"area": ["areo"]}
    rows = build_rows(fams, rev, {"areo": "area"}, _FakeDecomposer(), set(), {}, _tagger())
    s = summarise(rows)
    assert s["families"] == 2
    assert s["flags"]["no_match"] == 1  # thereby unanchored
    assert 0.0 <= s["espdic_recall_pct"] <= 100.0


# ---------------------------------------------------------------------------
# load_en_word_tiers (read-only DB helper) — in-memory sqlite, no file
# ---------------------------------------------------------------------------


def test_load_en_word_tiers(tmp_path):
    db = tmp_path / "mini.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE concept_lang (
            id INTEGER PRIMARY KEY, concept_id INTEGER, lang TEXT,
            word TEXT, pos TEXT, cefr_level TEXT, tier INTEGER, source TEXT
        );
        INSERT INTO concept_lang (concept_id, lang, word, tier) VALUES
            (1,'en','Area',1), (1,'en','region',NULL), (2,'lt','sritis',2);
        """
    )
    conn.commit()
    conn.close()
    tiers = load_en_word_tiers(db)
    assert tiers["area"] == [1]  # lowercased
    assert tiers["region"] == [-1]  # NULL tier -> -1 sentinel
    assert "sritis" not in tiers  # non-en excluded
