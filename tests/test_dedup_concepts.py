"""Tests for concept dedup (one concept per Esperanto word).

Hermetic: a tiny in-file lexicon and a dict-backed lemmatizer, no spaCy model.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from lexicon.dedup_concepts import (  # noqa: E402
    classify_groups,
    find_inflected_rows,
    fold_row,
    foldable,
    load_espdic_senses,
    load_groups,
    merge_group,
    resolved_tier,
    structural_audit,
    word_tier_triples,
)
from lexicon.schema import (  # noqa: E402
    create_common_lexicon_schema,
    create_concept_merge_schema,
    create_lifecycle_schema,
)

LEMMAS = {
    "achieving": ("achieve", "VBG"),
    "achieved": ("achieve", "VBD"),
    "methodologies": ("methodology", "NNS"),
    "pecked": ("peck", "VBD"),
}


def lemmatize(word: str) -> tuple[str, str]:
    return LEMMAS.get(word, (word, "VB"))


ESPDIC = """\
atingi : to accomplish, achieve, attain, reach
brili : to glisten, glow, shine, sparkle
beki : to peck
"""


def _concept(conn, cid, eo_word, root, *, pos="VERB", prefix="", suffix="",
             synset=None, roots=True):
    conn.execute(
        "INSERT INTO concept (id, eo_root, eo_word, eo_pos, eo_prefix, eo_suffix, "
        "eo_status, wordnet_synset) VALUES (?,?,?,?,?,?,'complete',?)",
        (cid, root, eo_word, pos, prefix, suffix, synset),
    )
    if roots:
        conn.execute(
            "INSERT INTO concept_root (concept_id, root, position, is_head, tier) "
            "VALUES (?, ?, 0, 1, 'core')",
            (cid, root),
        )


def _lang(conn, cid, word, tier, *, lang="en", pos="VERB", source="oxford_3000"):
    conn.execute(
        "INSERT INTO concept_lang (concept_id, lang, word, pos, tier, source) "
        "VALUES (?,?,?,?,?,?)",
        (cid, lang, word, pos, tier, source),
    )


@pytest.fixture()
def lex(tmp_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(tmp_path / "lex.db", isolation_level=None)
    create_common_lexicon_schema(conn)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS concept_root (concept_id INTEGER NOT NULL, "
        "root TEXT NOT NULL, position INTEGER NOT NULL, is_head INTEGER NOT NULL "
        "DEFAULT 0, tier TEXT, PRIMARY KEY (concept_id, position))"
    )
    create_concept_merge_schema(conn)
    # safe synonyms: achieve (Oxford, has synset) / accomplish (gap-fill: NULL
    # affixes, unknown POS, no concept_root rows) -> atingi
    _concept(conn, 20, "atingi", "ating", synset="achieve.v.01")
    _lang(conn, 20, "achieve", 2)
    _lang(conn, 20, "pasiekti", 2, lang="lt")
    _concept(conn, 21, "atingi", "ating", pos="X", prefix=None, suffix=None,
             roots=False)
    _lang(conn, 21, "accomplish", 2, source="general_gap_v1")
    _lang(conn, 21, "pasiekti", 2, lang="lt")  # identical LT row -> dropped
    # suspect anchor: shine / shin -> brili ("shin" is not a sense of brili)
    _concept(conn, 30, "brili", "bril")
    _lang(conn, 30, "shine", 1)
    _concept(conn, 31, "brili", "bril")
    _lang(conn, 31, "shin", 2, source="tinystories_gap_v1")
    # inflections on the same concept as the lemma
    _lang(conn, 20, "achieving", 3, source="awl_t3")
    _lang(conn, 20, "achieved", 2, source="awl_t3")
    _concept(conn, 40, "metodologio", "metodologi", pos="NOUN")
    _lang(conn, 40, "methodology", 3, pos="NOUN", source="awl_t3")
    _lang(conn, 40, "methodologies", 3, pos="NOUN", source="awl_t3")
    # inflection on a DIFFERENT concept than its lemma
    _concept(conn, 50, "beki", "bek")
    _lang(conn, 50, "peck", 2)
    _concept(conn, 51, "bekado", "bek", pos="NOUN")
    _lang(conn, 51, "pecked", 2, source="tinystories_gap_v1")
    return conn


@pytest.fixture()
def senses(tmp_path: Path) -> dict[str, set[str]]:
    path = tmp_path / "espdic.txt"
    path.write_text(ESPDIC, encoding="utf-8")
    return load_espdic_senses(path)


def _groups(conn, senses):
    groups = load_groups(conn)
    classify_groups(conn, groups, senses, lemmatize)
    return {g.eo_word: g for g in groups}


class TestEspdicSenses:
    def test_strips_to_and_splits_commas(self, senses) -> None:
        assert senses["atingi"] == {"accomplish", "achieve", "attain", "reach"}


class TestClassify:
    def test_true_synonyms_are_safe_and_empty_fields_compatible(
        self, lex, senses
    ) -> None:
        # NULL vs '' affixes, 'X' vs VERB, missing concept_root: all compatible
        g = _groups(lex, senses)["atingi"]
        assert g.verdict == "safe_synonyms"
        assert g.survivor == 20  # has the WordNet synset

    def test_off_gloss_member_is_suspect(self, lex, senses) -> None:
        g = _groups(lex, senses)["brili"]
        assert g.verdict == "suspect_anchor"
        assert g.survivor is None
        assert {m.cid: m.in_gloss for m in g.members} == {30: True, 31: False}

    def test_two_real_values_conflict(self, lex, senses) -> None:
        lex.execute("UPDATE concept SET eo_suffix = 'eg' WHERE id = 21")
        lex.execute("UPDATE concept SET eo_suffix = 'et' WHERE id = 20")
        assert _groups(lex, senses)["atingi"].verdict == "identity_conflict"

    def test_staged_lifecycle_member_blocks_merge(self, lex, senses) -> None:
        create_lifecycle_schema(lex)
        lex.execute("INSERT INTO concept_lifecycle (concept_id) VALUES (21)")
        assert _groups(lex, senses)["atingi"].verdict == "identity_conflict"

    def test_unknown_eo_word(self, lex, senses) -> None:
        _concept(lex, 60, "zzzo", "zzz")
        _concept(lex, 61, "zzzo", "zzz")
        assert _groups(lex, senses)["zzzo"].verdict == "no_espdic"


class TestMerge:
    def test_merge_repoints_rows_and_keeps_word_tiers(self, lex, senses) -> None:
        g = _groups(lex, senses)["atingi"]
        triples = word_tier_triples(lex)
        lex.execute("BEGIN")
        stats = merge_group(lex, g, "2026-10-14")
        lex.execute("COMMIT")

        assert stats == {"moved": 1, "dropped": 1}
        assert lex.execute("SELECT COUNT(*) FROM concept WHERE eo_word='atingi'"
                           ).fetchone()[0] == 1
        words = {w for (w,) in lex.execute(
            "SELECT word FROM concept_lang WHERE concept_id = 20 AND lang='en'")}
        assert {"achieve", "accomplish"} <= words
        assert word_tier_triples(lex) == triples  # no tier changed
        assert structural_audit(lex) == {
            "orphan_concept_lang": 0, "orphan_concept_root": 0, "head_mismatches": 0
        }

    def test_merge_is_recorded_for_reversal(self, lex, senses) -> None:
        g = _groups(lex, senses)["atingi"]
        lex.execute("BEGIN")
        merge_group(lex, g, "2026-10-14")
        lex.execute("COMMIT")
        retired, survivor, snap = lex.execute(
            "SELECT retired_id, survivor_id, snapshot FROM concept_merge"
        ).fetchone()
        snap = json.loads(snap)
        assert (retired, survivor) == (21, 20)
        assert snap["concept"]["eo_word"] == "atingi"
        assert len(snap["moved_concept_lang_ids"]) == 1
        assert snap["dropped_concept_lang"][0][2] == "pasiekti"
        assert snap["survivor_before"]["identity"]["eo_pos"] == "VERB"

    def test_survivor_empty_fields_are_filled(self, lex, senses) -> None:
        # survivor lacks affix/POS/roots; the retired member has them
        lex.execute("UPDATE concept SET eo_pos='X', eo_suffix=NULL WHERE id=20")
        lex.execute("DELETE FROM concept_root WHERE concept_id = 20")
        lex.execute("UPDATE concept SET eo_pos='VERB', eo_suffix='' WHERE id=21")
        lex.execute("INSERT INTO concept_root VALUES (21, 'ating', 0, 1, 'core')")
        g = _groups(lex, senses)["atingi"]
        lex.execute("BEGIN")
        merge_group(lex, g, "2026-10-14")
        lex.execute("COMMIT")
        assert lex.execute("SELECT eo_pos FROM concept WHERE id=20").fetchone() == (
            "VERB",
        )
        assert lex.execute(
            "SELECT root, is_head FROM concept_root WHERE concept_id=20"
        ).fetchall() == [("ating", 1)]

    def test_differing_tier_on_identical_row_refuses(self, lex, senses) -> None:
        lex.execute("UPDATE concept_lang SET tier = 1 WHERE concept_id = 21 "
                    "AND lang = 'lt'")
        g = _groups(lex, senses)["atingi"]
        lex.execute("BEGIN")
        with pytest.raises(ValueError, match="tier"):
            merge_group(lex, g, "2026-10-14")
        lex.execute("ROLLBACK")


class TestFold:
    def test_same_concept_inflections_are_foldable(self, lex) -> None:
        rows = {r.word: r for r in find_inflected_rows(lex, lemmatize)}
        assert foldable(rows["methodologies"])
        assert foldable(rows["achieving"])  # T3 row, lemma T2: no tier gain
        assert foldable(rows["achieved"])  # same tier as lemma
        assert not foldable(rows["pecked"])  # lemma on another concept

    def test_row_with_better_tier_than_lemma_is_not_foldable(self, lex) -> None:
        lex.execute("UPDATE concept_lang SET tier = 1 WHERE word = 'achieved'")
        rows = {r.word: r for r in find_inflected_rows(lex, lemmatize)}
        assert not foldable(rows["achieved"])  # folding would demote it

    def test_fold_moves_row_and_keeps_resolved_tier(self, lex) -> None:
        r = {r.word: r for r in find_inflected_rows(lex, lemmatize)}["methodologies"]
        before = resolved_tier(lex, r.word, r.lemma)
        lex.execute("BEGIN")
        assert fold_row(lex, r)
        lex.execute("COMMIT")
        assert lex.execute(
            "SELECT 1 FROM concept_lang WHERE word = 'methodologies'"
        ).fetchone() is None
        assert lex.execute(
            "SELECT lemma, form_description, tier FROM inflected_forms "
            "WHERE inflected_word = 'methodologies'"
        ).fetchone() == ("methodology", "concept_row_fold", 3)
        assert resolved_tier(lex, r.word, r.lemma) == before
