"""Tests for ``src.lexicon.audit_root_consistency`` — the read-only
diagnostic with the SV-based over-reduction detector.

Covers the spec's expected behaviours:
  * classify a ``klimato``/``klim`` row as ``truncation``;
  * count a consistent row as ``ok`` and NOT write it;
  * SV detector: ``over_reduced("rapid","rap")`` and ``("koler","kol")``
    → True; ``("kampad","kamp")``, ``("artist","art")``, ``("flugil","flug")``
    → False;
  * audit never modifies the database (row counts and column values
    unchanged before vs after).
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from src.lexicon.audit_root_consistency import (
    ISSUE_OK,
    ISSUE_OVER_REDUCED,
    ISSUE_TRUNCATION,
    audit,
    build_successor_index,
    over_reduced,
)
from src.lexicon.schema import create_common_lexicon_schema


# ---------------------------------------------------------------------------
# Minimal inventory fixture (now with the ``headwords`` field the audit
# expects, since the SV detector needs the HEADS set)
# ---------------------------------------------------------------------------


def _root(gloss: str, tier: str, prod: int = 5) -> dict:
    return {"gloss": gloss, "prod": prod, "tier": tier}


def _build_inventory() -> dict:
    return {
        "meta": {"source": "test fixture"},
        "roots": {
            "klimat": _root("climate", "core", prod=4),
            "patr":   _root("father", "core", prod=10),
            "prez":   _root("price", "core", prod=9),
            # prezid NOT in this fixture — the pre-Part-B state.
        },
        "headwords": sorted({
            "klimato", "klimata", "klimate", "klimati",
            "patro", "patra", "patre", "patri",
            "prezo", "preza", "preze",
            # Five prezid+ending forms — needed so SV(prezid) >= 5 (the
            # default over_reduced threshold) and the detector fires.
            "prezido", "prezida", "prezide", "prezidi", "prezidu",
        }),
        "suffixes": ["ist", "ej", "ul", "in", "et", "ar", "id", "o", "a", "e"],
        "prefixes": ["mal", "re", "inter"],
        "number_roots": [],
        "correlatives": [],
        "other": [],
        "verb_endings": ["as", "is", "os", "us", "u", "i"],
        "nominal_endings": ["o", "a", "e"],
    }


@pytest.fixture
def inventory_path(tmp_path: Path) -> Path:
    p = tmp_path / "inv.json"
    p.write_text(json.dumps(_build_inventory()), encoding="utf-8")
    return p


def _seed_db(path: Path, seed: list[tuple]) -> None:
    """seed: list of (eo_root, eo_word, en_word) tuples."""
    conn = sqlite3.connect(path)
    create_common_lexicon_schema(conn)
    for eo_root, eo_word, en_word in seed:
        cur = conn.execute(
            "INSERT INTO concept "
            "(eo_root, eo_word, eo_prefix, eo_suffix, eo_status) "
            "VALUES (?, ?, '', '', 'complete')",
            (eo_root, eo_word),
        )
        cid = cur.lastrowid
        if en_word is not None:
            conn.execute(
                "INSERT INTO concept_lang "
                "(concept_id, lang, word, pos, cefr_level, tier, source) "
                "VALUES (?, 'en', ?, 'NOUN', 'B1', 2, 'fixture')",
                (cid, en_word),
            )
    conn.commit()
    conn.close()


def _read_concept_state(path: Path) -> list[tuple]:
    conn = sqlite3.connect(path)
    rows = conn.execute(
        "SELECT id, eo_root, eo_word, eo_prefix, eo_suffix FROM concept "
        "ORDER BY id"
    ).fetchall()
    conn.close()
    return rows


def _read_concept_lang_state(path: Path) -> list[tuple]:
    conn = sqlite3.connect(path)
    rows = conn.execute(
        "SELECT concept_id, lang, word, pos, cefr_level, tier, source "
        "FROM concept_lang ORDER BY id"
    ).fetchall()
    conn.close()
    return rows


# ---------------------------------------------------------------------------
# SV-based over_reduced detector (pure function, no DB)
# ---------------------------------------------------------------------------


def test_over_reduced_flags_rapid_over_rap() -> None:
    """`rapid` is a real root that the greedy reducer wrongly collapsed
    into `rap`. The SV detector sees that `rapid` itself is an attested
    basic word (rapida/i/o/e in HEADS) with high SV → True."""
    heads = {
        "rapida", "rapide", "rapidi", "rapido", "rapidu",
        "rapo", "rapi", "rapa",
    }
    succ = build_successor_index(heads)
    assert over_reduced("rapid", "rap", heads, succ, sv_threshold=5) is True


def test_over_reduced_flags_koler_over_kol() -> None:
    """`koler` (anger) is the residual short-collision the spec calls out."""
    heads = {
        "kolero", "kolera", "kolere", "koleri", "koleru",
        "kolo", "kola", "kole", "koli",
    }
    succ = build_successor_index(heads)
    assert over_reduced("koler", "kol", heads, succ, sv_threshold=5) is True


def test_over_reduced_skips_correct_kampad_reduction() -> None:
    """`kampad` is a legitimate `kamp + ad` derivation — not over-reduced.
    The SV detector should NOT flag it."""
    heads = {
        "kampo", "kampa", "kampe", "kampi",
        "kampado", "kampada",
    }
    succ = build_successor_index(heads)
    assert over_reduced("kampad", "kamp", heads, succ, sv_threshold=5) is False


def test_over_reduced_skips_correct_artist_reduction() -> None:
    heads = {
        "arto", "arta", "arte", "arti",
        "artisto", "artista",
    }
    succ = build_successor_index(heads)
    assert over_reduced("artist", "art", heads, succ, sv_threshold=5) is False


def test_over_reduced_skips_correct_flugil_reduction() -> None:
    """`flugilo` = wing = `flug + il` (instrument). Correct derivation,
    NOT over-reduced."""
    heads = {
        "flugi", "fluga", "fluge", "flugo",
        "flugilo", "flugila",
    }
    succ = build_successor_index(heads)
    assert over_reduced("flugil", "flug", heads, succ, sv_threshold=5) is False


def test_over_reduced_returns_false_when_head_is_not_a_prefix() -> None:
    """A precondition of the SV detector: ``head_root`` must be a strict
    prefix of ``word_stem``. Otherwise return False without searching."""
    heads = {"hundo", "hunda"}
    succ = build_successor_index(heads)
    assert over_reduced("hund", "kat", heads, succ) is False


def test_over_reduced_returns_false_when_head_equals_stem() -> None:
    """No suffix was stripped → nothing was discarded → not over-reduced."""
    heads = {"hundo", "hunda", "hundi"}
    succ = build_successor_index(heads)
    assert over_reduced("hund", "hund", heads, succ) is False


# ---------------------------------------------------------------------------
# Audit-level issue classification (end-to-end on a fixture DB)
# ---------------------------------------------------------------------------


def test_truncation_flagged_for_klim_vs_klimato(
    tmp_path: Path, inventory_path: Path
) -> None:
    """``eo_word='klimato'`` with stored ``eo_root='klim'`` is a strict
    prefix of the computed stem ``klimat`` → ``truncation``."""
    db = tmp_path / "fix.db"
    _seed_db(db, [("klim", "klimato", "climate")])
    out = tmp_path / "audit.jsonl"

    issue_counts, _heads, total = audit(db, inventory_path, out)

    assert total == 1
    assert issue_counts[ISSUE_TRUNCATION] == 1
    assert issue_counts[ISSUE_OK] == 0
    records = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 1
    rec = records[0]
    assert rec["issue"] == "truncation"
    assert rec["stored_eo_root"] == "klim"
    assert rec["computed_head_root"] == "klimat"


def test_consistent_row_is_ok_and_not_written(
    tmp_path: Path, inventory_path: Path
) -> None:
    """A row where the stored root equals the computed head is counted as
    ``ok`` and produces NO output line."""
    db = tmp_path / "fix.db"
    _seed_db(db, [("patr", "patro", "father")])
    out = tmp_path / "audit.jsonl"

    issue_counts, _heads, total = audit(db, inventory_path, out)

    assert total == 1
    assert issue_counts[ISSUE_OK] == 1
    assert out.read_text(encoding="utf-8") == ""


def test_over_reduced_candidate_flagged_for_prezido_vs_prez(
    tmp_path: Path, inventory_path: Path
) -> None:
    """In a fixture inventory where ``prezid`` is missing (the pre-Part-B
    state), the decomposer over-reduces ``prezido`` → ``prez`` + ``id``.
    The SV detector sees ``prezid+o/a/e/i`` in HEADS with high SV →
    ``over_reduced_candidate``."""
    db = tmp_path / "fix.db"
    _seed_db(db, [("prez", "prezido", "to preside")])
    out = tmp_path / "audit.jsonl"

    issue_counts, heads, total = audit(db, inventory_path, out)

    assert total == 1
    assert issue_counts[ISSUE_OVER_REDUCED] == 1
    assert heads["prez"] == 1


# ---------------------------------------------------------------------------
# DB-write safety (the audit is read-only)
# ---------------------------------------------------------------------------


def test_audit_makes_no_db_writes(
    tmp_path: Path, inventory_path: Path
) -> None:
    """The audit must not mutate any column of any concept row, nor touch
    concept_lang."""
    db = tmp_path / "fix.db"
    _seed_db(db, [
        ("klim", "klimato", "climate"),
        ("patr", "patro", "father"),
        ("prez", "prezido", "to preside"),
    ])
    pre_concept = _read_concept_state(db)
    pre_lang = _read_concept_lang_state(db)

    audit(db, inventory_path, tmp_path / "audit.jsonl")

    post_concept = _read_concept_state(db)
    post_lang = _read_concept_lang_state(db)
    assert pre_concept == post_concept
    assert pre_lang == post_lang


def test_audit_writes_no_records_when_jsonl_empty(
    tmp_path: Path, inventory_path: Path
) -> None:
    """When every row is ``ok``, the jsonl exists but is empty."""
    db = tmp_path / "fix.db"
    _seed_db(db, [("patr", "patro", "father")])
    out = tmp_path / "audit.jsonl"
    audit(db, inventory_path, out)
    assert out.exists()
    assert out.read_text(encoding="utf-8") == ""
