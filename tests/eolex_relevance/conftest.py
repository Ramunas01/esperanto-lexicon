"""Shared fixtures for the eolex_relevance test-suite.

A tiny offline inventory, a tiny lexicon DB, and a bundle built from three toy
domains (animals / cooking / customs) — so the whole suite is fast and needs
no network, no real lexicon assets, and no spaCy models.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from eolex_relevance import RelevanceScorer
from eolex_relevance.build import build_bundle

# Core roots used by the toy domains. ``ofic`` is deliberately shared by all
# three domains (low IDF); the rest are domain-unique (high IDF).
TOY_ROOTS = {
    "kat": "cat",
    "hund": "dog",
    "kuir": "cook",
    "pom": "apple",
    "import": "import",
    "deklar": "declaration",
    "instanc": "authority",
    "ofic": "office",
}


@pytest.fixture(scope="session")
def inventory_path(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("eolex_assets")
    inv = {
        "meta": {"source": "toy-test-fixture", "built": "2026-01-01"},
        "roots": {
            r: {"gloss": g, "prod": 5, "tier": "core"}
            for r, g in TOY_ROOTS.items()
        },
        "suffixes": ["ad", "ej", "il", "ist", "an", "ec"],
        "prefixes": ["mal", "re"],
        "correlatives": ["kio", "kiu"],
        "other": ["la", "kaj", "de", "pri", "en", "kun"],
        "number_roots": ["du"],
        "verb_endings": ["as", "is", "os", "us", "u", "i"],
        "nominal_endings": ["o", "a", "e"],
    }
    p = d / "eo_inventory.json"
    p.write_text(json.dumps(inv, ensure_ascii=False), encoding="utf-8")
    return p


@pytest.fixture(scope="session")
def lexicon_db_path(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("eolex_db")
    p = d / "lexicon_toy.db"
    conn = sqlite3.connect(p)
    conn.executescript(
        """
        CREATE TABLE concept(
            id INTEGER PRIMARY KEY, eo_root TEXT, eo_word TEXT,
            eo_prefix TEXT, eo_suffix TEXT, eo_status TEXT);
        CREATE TABLE concept_lang(
            id INTEGER PRIMARY KEY, concept_id INTEGER, lang TEXT, word TEXT,
            pos TEXT, cefr_level TEXT, tier INTEGER, source TEXT);
        CREATE TABLE concept_root(
            concept_id INTEGER, root TEXT, position INTEGER,
            is_head INTEGER, tier TEXT);
        """
    )
    # (concept_id, head_root, eo_word, en_word)
    rows = [
        (1, "kat", "kato", "cat"),
        (2, "hund", "hundo", "dog"),
        (3, "kuir", "kuiri", "cook"),
        (4, "pom", "pomo", "apple"),
        (5, "import", "importi", "import"),
        (6, "deklar", "deklaro", "declaration"),
        (7, "instanc", "instanco", "authority"),
        (8, "ofic", "oficejo", "office"),
    ]
    for cid, root, eo_word, en_word in rows:
        conn.execute(
            "INSERT INTO concept(id, eo_root, eo_word) VALUES (?, ?, ?)",
            (cid, root, eo_word),
        )
        conn.execute(
            "INSERT INTO concept_root(concept_id, root, position, is_head, tier)"
            " VALUES (?, ?, 0, 1, 'core')",
            (cid, root),
        )
        conn.execute(
            "INSERT INTO concept_lang(concept_id, lang, word) VALUES (?, 'en', ?)",
            (cid, en_word),
        )
    # A compound concept: "importinstanco" -> import + instanc (two roots).
    conn.execute(
        "INSERT INTO concept(id, eo_root, eo_word) VALUES (9, 'instanc', 'importinstanco')"
    )
    conn.executemany(
        "INSERT INTO concept_root(concept_id, root, position, is_head, tier) VALUES (?,?,?,?,'core')",
        [(9, "import", 0, 0), (9, "instanc", 1, 1)],
    )
    conn.execute(
        "INSERT INTO concept_lang(concept_id, lang, word) VALUES (9, 'en', 'import authority')"
    )
    conn.commit()
    conn.close()
    return p


@pytest.fixture(scope="session")
def toy_specs() -> list[dict]:
    # Esperanto term lists keep the build deterministic without spaCy.
    # Each domain has two unique roots + the shared root ``ofic`` (oficejo).
    return [
        {"name": "animals", "source": "terms",
         "terms": ["kato", "hundo", "oficejo"], "lang": "eo"},
        {"name": "cooking", "source": "terms",
         "terms": ["kuiri", "pomo", "oficejo"], "lang": "eo"},
        {"name": "customs", "source": "terms",
         "terms": ["importi", "deklaro", "oficejo"], "lang": "eo"},
    ]


@pytest.fixture(scope="session")
def toy_bundle_path(tmp_path_factory, toy_specs, lexicon_db_path, inventory_path) -> Path:
    out = tmp_path_factory.mktemp("eolex_bundle") / "toy.bundle"
    build_bundle(
        toy_specs,
        lexicon_db=lexicon_db_path,
        inventory=inventory_path,
        out_path=out,
        langs=["eo", "en"],
        use_spacy=False,
    )
    return out


@pytest.fixture()
def scorer(toy_bundle_path) -> RelevanceScorer:
    # use_spacy=False everywhere so scoring is deterministic regardless of
    # which spaCy models happen to be installed on the test machine.
    return RelevanceScorer.load(toy_bundle_path, use_spacy=False)
