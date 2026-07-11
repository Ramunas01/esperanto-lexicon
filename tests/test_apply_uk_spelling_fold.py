"""Tests for the British-spelling fold generator + insert-only writer.

Pure logic + an in-memory SQLite carrying the common-lexicon schema. No network,
no real lexicon DB.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "lexicon"))

from apply_uk_spelling_fold import (  # noqa: E402
    FORM_DESCRIPTION,
    apply_folds,
    audit,
    deinflect_candidates,
    generate_folds,
    resolve_us_lemma,
)
from schema import create_common_lexicon_schema  # noqa: E402

# A tiny lexicon: US concept words with their tiers.
EN_TIERS = {
    "color": [1], "colorful": [1], "favorite": [1], "neighbor": [1],
    "center": [1, 2], "theater": [1], "behavior": [2], "airplane": [2],
    "organized": [2], "organizer": [2], "recognize": [2], "pajama": [2],
    "per": [2],  # the dangerous real-word target for the 'pre' false fold
}


# --- resolve_us_lemma (the guard) ------------------------------------------


def test_lemma_direct_concept():
    assert resolve_us_lemma("color", EN_TIERS) == "color"
    assert resolve_us_lemma("colorful", EN_TIERS) == "colorful"


def test_lemma_via_deinflection():
    # plural/past US surface not stored; its base concept is.
    assert resolve_us_lemma("colors", EN_TIERS) == "color"    # colors -> color
    assert resolve_us_lemma("colored", EN_TIERS) == "color"   # colored -> color
    assert resolve_us_lemma("neighbors", EN_TIERS) == "neighbor"


def test_lemma_absent_returns_none():
    assert resolve_us_lemma("fertilizer", EN_TIERS) is None
    assert resolve_us_lemma("suprized", EN_TIERS) is None  # typo junk


def test_deinflect_candidates():
    assert "color" in deinflect_candidates("colors")
    assert "color" in deinflect_candidates("colored")
    assert deinflect_candidates("ox") == []  # too short to strip


# --- generate_folds (data-driven, guarded) ---------------------------------


def _toks(*pairs):
    # (token, count) with a default bucket
    return [(t, c, "local") for t, c in pairs]


def test_generate_folds_basic():
    folds, absent = generate_folds(
        _toks(("colour", 17), ("colours", 35), ("neighbour", 20)), EN_TIERS
    )
    by = {d["uk_form"]: d for d in folds}
    assert by["colour"]["us_form"] == "color" and by["colour"]["tier"] == 1
    assert by["colours"]["us_form"] == "color"  # de-inflected to the concept
    assert by["neighbour"]["us_form"] == "neighbor"
    assert absent == []


def test_generate_folds_rejects_us_absent_and_junk():
    folds, absent = generate_folds(
        _toks(("fertiliser", 10), ("suprised", 1)), EN_TIERS
    )
    assert folds == []
    absent_forms = {d["uk_form"] for d in absent}
    assert "fertiliser" in absent_forms  # genuine US-absent gap
    assert "suprised" in absent_forms    # typo, correctly not folded


def test_generate_folds_skips_non_british():
    folds, absent = generate_folds(_toks(("stratum", 11), ("dog", 5)), EN_TIERS)
    assert folds == [] and absent == []  # neither folds (no rule applies)


def test_generate_folds_pre_not_mistaken_for_per():
    # 'pre' must NOT fold to the real word 'per' (min_stem guard in uk_to_us).
    folds, absent = generate_folds(_toks(("pre", 5)), EN_TIERS)
    assert folds == [] and absent == []


def test_generate_folds_tier_is_lowest():
    folds, _ = generate_folds(_toks(("centre", 1)), EN_TIERS)
    assert folds[0]["us_form"] == "center"
    assert folds[0]["tier"] == 1  # center is [1,2] -> lowest


# --- writer + audit (in-memory DB) -----------------------------------------


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    create_common_lexicon_schema(conn)
    # one real US concept + row so counts are non-trivial
    conn.execute("INSERT INTO concept (id, eo_root, eo_word, eo_status) VALUES (1,'kolor','koloro','complete')")
    conn.execute("INSERT INTO concept_lang (concept_id, lang, word, pos, tier, source) VALUES (1,'en','color','NOUN',1,'seed')")
    conn.commit()
    return conn


def test_apply_folds_inserts_and_is_idempotent(db):
    folds = [
        {"uk_form": "colour", "us_form": "color", "total_freq": 17, "tier": 1},
        {"uk_form": "colours", "us_form": "color", "total_freq": 35, "tier": 1},
    ]
    s1 = apply_folds(db, folds)
    assert s1["inserted"] == 2
    rows = db.execute(
        "SELECT inflected_word, lemma, form_description, tier FROM inflected_forms ORDER BY inflected_word"
    ).fetchall()
    assert rows == [("colour", "color", FORM_DESCRIPTION, 1),
                    ("colours", "color", FORM_DESCRIPTION, 1)]
    # re-run: UNIQUE(inflected_word,lemma,lang) makes it a no-op
    s2 = apply_folds(db, folds)
    assert s2["inserted"] == 0 and s2["skipped"] == 2
    assert db.execute("SELECT COUNT(*) FROM inflected_forms").fetchone()[0] == 2


def test_audit_concept_untouched(db):
    before = {t: db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t in ("concept", "concept_lang", "inflected_forms")}
    apply_folds(db, [{"uk_form": "colour", "us_form": "color", "total_freq": 1, "tier": 1}])
    rep = audit(db, before)
    assert rep["concept_unchanged"] is True
    assert rep["concept_lang_unchanged"] is True
    assert rep["dupe_rows"] == 0
    assert rep["inflected_after"] == rep["inflected_before"] + 1
