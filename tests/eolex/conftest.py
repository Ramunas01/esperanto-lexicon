"""Shared fixtures for the eolex test suite.

Two fixture tiers:
- ``toy_lexicon`` — fast, built from a tiny in-memory inventory, no real DB.
- ``real_lexicon`` — loads the packaged ``lexicon.bundle``; marked ``slow``.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from eolex import Bundle, Lexicon
from eolex_relevance.build import build_lexicon_bundle

LEXICON_DB = Path(__file__).parents[2] / "data" / "lexicon_db" / "lexicon_v2.db"
INVENTORY = Path(__file__).parents[2] / "data" / "lexicon_db" / "eo_inventory.json"
PACKAGED_BUNDLE = (
    Path(__file__).parents[2] / "eolex" / "eolex" / "data" / "lexicon.bundle"
)

TOY_ROOTS = {
    "akv": {"gloss": "aquatic, of water", "prod": 5, "tier": "core"},
    "kat": {"gloss": "cat", "prod": 5, "tier": "core"},
    "bird": {"gloss": "bird", "prod": 5, "tier": "core"},
    "mal": {"gloss": "bad (prefix)", "prod": 10, "tier": "core"},
    "san": {"gloss": "healthy", "prod": 5, "tier": "extended"},
}


@pytest.fixture(scope="session")
def toy_inventory() -> dict:
    return {
        "meta": {"source": "toy-eolex-fixture"},
        "roots": TOY_ROOTS,
        "suffixes": ["ad", "ej", "il", "ist"],
        "prefixes": ["mal", "re"],
        "correlatives": ["kio", "kiu"],
        "other": ["la", "kaj", "de"],
        "number_roots": ["du"],
        "verb_endings": ["as", "is", "os", "us", "u", "i"],
        "nominal_endings": ["o", "a", "e"],
    }


@pytest.fixture(scope="session")
def toy_bundle(tmp_path_factory, toy_inventory) -> Bundle:
    """Minimal Bundle with toy inventory + concept_lang entries."""
    concept_lang_map = {
        ("eo", "akvo"): (1, "A1"),
        ("eo", "kato"): (1, "A1"),
        ("en", "water"): (1, "A1"),
        ("en", "cat"): (1, "A1"),
        ("en", "framework"): (3, None),
    }
    import numpy as np

    bundle = Bundle(
        domains=[],
        vocab=[],
        idf=np.array([]),
        vectors=np.zeros((0, 0)),
        word_root_map={("en", "cat"): ["kat"], ("en", "water"): ["akv"]},
        inventory=toy_inventory,
        concept_lang_map=concept_lang_map,
        meta={
            "build_date": "2026-01-01",
            "langs": ["eo", "en"],
            "bundle_type": "lexicon",
        },
    )
    path = tmp_path_factory.mktemp("eolex_bundle") / "toy.bundle"
    bundle.save(path)
    return Bundle.load(path)


@pytest.fixture(scope="session")
def toy_lexicon(toy_bundle) -> Lexicon:
    return Lexicon(toy_bundle)


@pytest.fixture(scope="session")
def real_lexicon() -> Lexicon:
    """Load the packaged lexicon bundle (requires built bundle in repo)."""
    if not PACKAGED_BUNDLE.exists():
        pytest.skip("Packaged lexicon.bundle not found; run build_lexicon_bundle first.")
    return Lexicon.load(PACKAGED_BUNDLE)
