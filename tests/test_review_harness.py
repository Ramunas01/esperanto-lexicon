"""Tests for the gap-fill review harness pure logic + xlsx round-trip."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "analyzer" / "review"))

import export_snapshot  # noqa: E402
from _common import (  # noqa: E402
    append_decision,
    load_decisions,
    matching_sentences,
    name_signal,
    recommend,
    roundtrip_glosses,
    roundtrip_matches,
    select_diverse,
)
from set_completeness import audit  # noqa: E402
from xlsx_lite import _col_index, _index_to_col, read_sheet, write_xlsx  # noqa: E402


# ---------------------------------------------------------------------------
# xlsx_lite
# ---------------------------------------------------------------------------


class TestXlsxLite:
    def test_col_index_roundtrip(self) -> None:
        for letters in ("A", "B", "Z", "AA", "AB", "AZ", "BA"):
            assert _index_to_col(_col_index(letters)) == letters

    def test_write_read_roundtrip(self, tmp_path: Path) -> None:
        out = tmp_path / "x.xlsx"
        write_xlsx(out, ["a", "b"], [["1", "x & <y>"], ["2", "ĉielarko"]])
        header, rows = read_sheet(out)
        assert header == ["a", "b"]
        assert rows == [{"a": "1", "b": "x & <y>"}, {"a": "2", "b": "ĉielarko"}]


# ---------------------------------------------------------------------------
# decisions sidecar
# ---------------------------------------------------------------------------


class TestDecisions:
    def test_last_write_wins(self, tmp_path: Path) -> None:
        d = tmp_path / "dec.tsv"
        append_decision(d, {"en_lemma": "pond", "decision": "accept", "source": "auto"})
        append_decision(d, {"en_lemma": "pond", "decision": "reject", "source": "human"})
        append_decision(d, {"en_lemma": "hug", "decision": "hold"})
        loaded = load_decisions(d)
        assert loaded["pond"]["decision"] == "reject"
        assert loaded["pond"]["source"] == "human"
        assert loaded["hug"]["decision"] == "hold"


# ---------------------------------------------------------------------------
# corpus usage
# ---------------------------------------------------------------------------


class TestCorpus:
    def test_matching_sentences_whole_word_and_dedupe(self) -> None:
        text = "The bug flew. A debugger is not a bug. The bug flew."
        got = matching_sentences(text, ["bug"])
        assert got == ["The bug flew.", "A debugger is not a bug."]

    def test_select_diverse_picks_varied(self) -> None:
        sents = [
            "the cat sat on the mat",
            "the cat sat on the mat again",  # near dup
            "a dog barked loudly outside",
            "rockets orbit distant planets",
        ]
        got = select_diverse(sents, ["cat"], k=2)
        assert got[0] == sents[0]
        assert got[1] in (sents[2], sents[3])  # a lexically distant one, not the dup


class TestNameSignal:
    def test_caps_and_lowercase_freq(self) -> None:
        surfaces = [
            {"token": "Lily", "freq": 90, "is_propn": True, "caps_majority": True},
            {"token": "lily", "freq": 10, "is_propn": False, "caps_majority": False},
        ]
        sig = name_signal(surfaces)
        assert sig["caps_majority"] == 0.9
        assert sig["lowercase_common_freq"] == 10
        assert sig["ever_propn"] is True


# ---------------------------------------------------------------------------
# round-trip + recommendation
# ---------------------------------------------------------------------------


class TestRoundtrip:
    def test_glosses_normalised(self) -> None:
        fwd = {"brakumi": "to embrace, hug (warmly)"}
        assert roundtrip_glosses("brakumi", fwd) == ["embrace", "hug"]

    def test_matches_with_limit(self) -> None:
        g = ["evil", "fault", "foul", "bug"]
        assert roundtrip_matches("bug", g) is True
        assert roundtrip_matches("bug", g, limit=2) is False  # buried secondary sense


def _row(**kw) -> dict[str, str]:
    base = {
        "en_lemma": "pond", "priority": "P2_hot", "flag": "ok",
        "action": "NEW", "eo_root": "laget", "eo_word": "lageto",
        "alt_candidates": "",
    }
    base.update(kw)
    return base


_CLEAN_SIG = {"caps_majority": 0.0, "ever_propn": False, "lowercase_common_freq": 200}


class TestRecommend:
    def test_clean_accept(self) -> None:
        v, _ = recommend(_row(), _CLEAN_SIG, ["pond"], {}, 200)
        assert v == "ACCEPT"

    def test_no_match_ask(self) -> None:
        v, r = recommend(_row(flag="no_match", eo_root="", action=""), _CLEAN_SIG, [], {}, 5)
        assert v == "ASK" and "no_match" in r

    def test_compound_ask(self) -> None:
        v, r = recommend(
            _row(flag="compound", eo_word="ĉielarko"), _CLEAN_SIG, ["rainbow"], {}, 5
        )
        # lemma mismatch on 'pond' row reused — use a matching gloss
        v2, r2 = recommend(
            _row(en_lemma="rainbow", flag="compound", eo_word="ĉielarko"),
            _CLEAN_SIG, ["rainbow"], {}, 5,
        )
        assert v2 == "ASK" and "compound" in r2

    def test_polysemy_ask_when_better_alt(self) -> None:
        row = _row(en_lemma="bug", eo_word="miso", alt_candidates="insekto")
        v, r = recommend(
            row, _CLEAN_SIG, ["evil", "fault", "foul", "bug"],
            {"insekto": ["bug", "insect"]}, 200,
        )
        assert v == "ASK" and "polysemy" in r

    def test_secondary_sense_ask_without_alt(self) -> None:
        row = _row(en_lemma="bug", eo_word="miso")
        v, r = recommend(row, _CLEAN_SIG, ["evil", "fault", "foul", "bug"], {}, 200)
        assert v == "ASK" and "secondary" in r

    def test_roundtrip_mismatch_ask(self) -> None:
        v, r = recommend(_row(), _CLEAN_SIG, ["lake"], {}, 200)
        assert v == "ASK" and "doesn't contain" in r

    def test_strong_name_reject(self) -> None:
        sig = {"caps_majority": 1.0, "ever_propn": True, "lowercase_common_freq": 0}
        v, r = recommend(
            _row(en_lemma="lily", priority="P1_name", eo_word="lilo"),
            sig, ["lily"], {}, 100,
        )
        assert v == "REJECT(name)"

    def test_name_ambiguous_ask(self) -> None:
        sig = {"caps_majority": 0.6, "ever_propn": True, "lowercase_common_freq": 5}
        v, r = recommend(
            _row(en_lemma="rose", priority="P1_name", eo_word="rozo"),
            sig, ["rose"], {}, 100,
        )
        assert v == "ASK" and "name-or-word" in r


# ---------------------------------------------------------------------------
# export_snapshot mapping + set audit
# ---------------------------------------------------------------------------


class TestExportSnapshot:
    def test_col_i_seeds_decisions(self, tmp_path: Path) -> None:
        xlsx = tmp_path / "wb.xlsx"
        write_xlsx(
            xlsx,
            ["en_lemma", "decision", "reviewer_note"],
            [["pond", "1", "ok"], ["lily", "0", "name"],
             ["hug", "postpone", ""], ["dragon", "", ""]],
        )
        snap = tmp_path / "snap.tsv"
        dec = tmp_path / "dec.tsv"
        summary = export_snapshot.export(xlsx, snap, dec, sheet="reviewed")
        assert summary["by_decision"] == {"accept": 1, "reject": 1, "postpone": 1}
        loaded = load_decisions(dec)
        assert loaded["pond"]["decision"] == "accept"
        assert loaded["lily"]["decision"] == "reject"
        assert "dragon" not in loaded  # blank stays pending

    def test_export_skips_already_decided(self, tmp_path: Path) -> None:
        xlsx = tmp_path / "wb.xlsx"
        write_xlsx(xlsx, ["en_lemma", "decision", "reviewer_note"], [["pond", "1", ""]])
        snap, dec = tmp_path / "s.tsv", tmp_path / "d.tsv"
        append_decision(dec, {"en_lemma": "pond", "decision": "reject", "source": "human"})
        summary = export_snapshot.export(xlsx, snap, dec, sheet="reviewed")
        assert summary["seeded"] == 0
        assert load_decisions(dec)["pond"]["decision"] == "reject"  # not clobbered


class TestSetAudit:
    def test_audit_marks_presence_and_proposes(self) -> None:
        sets = {"colours": ["red", "teal"]}
        covered = {"red"}
        rows = audit(sets, covered, lambda m: (f"{m}-root/{m}o", f"{m} gloss"))
        by = {r["member"]: r for r in rows}
        assert by["red"]["in_lexicon"] == "Y"
        assert by["red"]["proposed_eo_anchor"] == ""  # present → no proposal
        assert by["teal"]["in_lexicon"] == "N"
        assert by["teal"]["proposed_eo_anchor"] == "teal-root/tealo"
