"""Tests for ``src.lexicon.audit_root_consistency`` — the read-only
diagnostic introduced in Part C.

The audit must:
  * classify a ``klimato``/``klim`` row as ``truncation``;
  * count a consistent row as ``ok`` and NOT write it to the jsonl;
  * never modify the database (row counts and column values unchanged).
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
    looks_unrelated,
)
from src.lexicon.schema import create_common_lexicon_schema


# ---------------------------------------------------------------------------
# Minimal inventory fixture
# ---------------------------------------------------------------------------


def _root(gloss: str, tier: str, prod: int = 5) -> dict:
    return {"gloss": gloss, "prod": prod, "tier": tier}


def _build_inventory() -> dict:
    return {
        "meta": {"source": "test fixture"},
        "roots": {
            "klimat": _root("climate", "core", prod=4),
            "patr":   _root("father", "core", prod=10),
            # For the over-reduced detection check:
            "prez":   _root("price", "core", prod=9),
            # Note: prezid intentionally NOT in this fixture inventory —
            # it's the analogue of pre-Part-B state where prezid was
            # collapsed into prez. The audit should detect that
            # ``prezido`` decomposes into prez+id with an unrelated gloss
            # (en_word="to preside" vs head_gloss="price").
        },
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


# ---------------------------------------------------------------------------
# Issue classification
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
    The head gloss ('price') and concept's en_word ('to preside') share
    no meaningful overlap → ``over_reduced_candidate``."""
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
    """The audit must not mutate any column of any concept row."""
    db = tmp_path / "fix.db"
    _seed_db(db, [
        ("klim", "klimato", "climate"),
        ("patr", "patro", "father"),
        ("prez", "prezido", "to preside"),
    ])
    pre = _read_concept_state(db)

    audit(db, inventory_path, tmp_path / "audit.jsonl")

    post = _read_concept_state(db)
    assert pre == post


# ---------------------------------------------------------------------------
# The relatedness heuristic
# ---------------------------------------------------------------------------


def test_looks_unrelated_treats_substring_as_related() -> None:
    """``active`` is a substring of ``activity`` — they should not be
    flagged as unrelated (otherwise every simple-suffix derivation would
    be a false positive)."""
    assert not looks_unrelated("activity", "active, in action")


def test_looks_unrelated_catches_genuine_gloss_drift() -> None:
    """``turnip`` and ``rapid`` share nothing — this is exactly the
    false-merge signature the audit exists to find."""
    assert looks_unrelated("rapid", "turnip")


def test_looks_unrelated_missing_side_is_not_flagged() -> None:
    """Without both sides, we have no evidence — return ``False`` rather
    than overreport."""
    assert not looks_unrelated(None, "anything")
    assert not looks_unrelated("anything", None)
    assert not looks_unrelated("", "anything")
