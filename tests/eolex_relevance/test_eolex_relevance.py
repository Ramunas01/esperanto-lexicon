"""Unit tests for eolex_relevance — fast, offline, on toy fixtures."""

from __future__ import annotations

import json
import math
import subprocess
import sys

import numpy as np
import pytest

from eolex_relevance import Bundle, RelevanceScorer
from eolex_relevance.build import build_word_root_map, compile_vectors
from eolex_relevance.eo_decomposer import Decomposer
from eolex_relevance.resolver import Resolver


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------


def _toy_inventory():
    return {
        "roots": {
            "kat": {"gloss": "cat", "prod": 5, "tier": "core"},
            "hund": {"gloss": "dog", "prod": 5, "tier": "core"},
            "import": {"gloss": "import", "prod": 5, "tier": "core"},
            "instanc": {"gloss": "authority", "prod": 5, "tier": "core"},
        },
        "suffixes": ["ej", "ad"],
        "prefixes": ["mal"],
        "correlatives": ["kio"],
        "other": ["la", "kaj", "de"],
        "number_roots": ["du"],
        "verb_endings": ["as", "is", "os", "us", "u", "i"],
        "nominal_endings": ["o", "a", "e"],
    }


def test_resolver_eo_plural_to_root():
    """Esperanto ``katoj`` (cats) → root ``kat``."""
    r = Resolver(_toy_inventory(), {}, ["eo"], use_spacy=False)
    res = r.resolve("katoj", "eo")
    assert [t.roots for t in res] == [("kat",)]


def test_resolver_eo_drops_function_words():
    r = Resolver(_toy_inventory(), {}, ["eo"], use_spacy=False)
    res = r.resolve("la kato kaj la hundo", "eo")
    # "la"/"kaj" dropped; only kato, hundo remain.
    assert [t.roots for t in res] == [("kat",), ("hund",)]


def test_resolver_eo_compound_two_roots():
    r = Resolver(_toy_inventory(), {}, ["eo"], use_spacy=False)
    res = r.resolve("importinstanco", "eo")
    assert len(res) == 1
    assert set(res[0].roots) == {"import", "instanc"}


def test_resolver_en_surface_fallback():
    """Without spaCy, the lowercase surface form is looked up directly."""
    wm = {("en", "cat"): ["kat"]}
    r = Resolver(_toy_inventory(), wm, ["en"], use_spacy=False)
    assert r.resolve("cat", "en")[0].roots == ("kat",)
    # "cats" surface is not a map key → unresolved (reduced recall, no spaCy).
    assert r.resolve("cats", "en")[0].roots == ()


def test_resolver_en_spacy_lemma():
    """With spaCy, ``cats`` lemmatizes to ``cat`` and resolves."""
    wm = {("en", "cat"): ["kat"]}
    r = Resolver(_toy_inventory(), wm, ["en"], use_spacy=True)
    if not r.spacy_available:
        pytest.skip("spaCy en_core_web_sm not installed")
    res = r.resolve("cats", "en")
    content = [t for t in res if t.surface == "cats"]
    assert content and content[0].roots == ("kat",)


# ---------------------------------------------------------------------------
# Domain compile / IDF
# ---------------------------------------------------------------------------


def test_idf_shared_root_lower_than_unique():
    """A root in every domain gets lower IDF than a domain-unique root."""
    from collections import Counter

    freqs = [
        Counter({"shared": 1, "a": 1}),
        Counter({"shared": 1, "b": 1}),
        Counter({"shared": 1, "c": 1}),
    ]
    vocab, idf, vectors = compile_vectors(freqs)
    idx = {r: i for i, r in enumerate(vocab)}
    assert idf[idx["shared"]] < idf[idx["a"]]
    # df=N=3 → idf = log(4/4)+1 = 1.0 exactly for the shared root.
    assert idf[idx["shared"]] == pytest.approx(1.0)


def test_domain_vectors_are_l2_normalized():
    from collections import Counter

    freqs = [Counter({"a": 2, "b": 1}), Counter({"c": 1})]
    _vocab, _idf, vectors = compile_vectors(freqs)
    for row in vectors:
        norm = float(np.linalg.norm(row))
        assert norm == pytest.approx(1.0) or norm == pytest.approx(0.0)


def test_word_root_map_includes_compound(lexicon_db_path):
    wm = build_word_root_map(lexicon_db_path, ["en"])
    assert wm[("en", "cat")] == ["kat"]
    assert set(wm[("en", "import authority")]) == {"import", "instanc"}


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def test_customs_text_scores_customs_over_cooking(scorer):
    res = scorer.score("importi deklaro importi", lang="eo")
    d = res.as_dict()
    assert d["customs"] > d["cooking"]
    assert d["customs"] > d["animals"]


def test_idf_shared_root_low_discrimination(scorer):
    """Text of only the universally-shared root barely distinguishes domains."""
    res = scorer.score("oficejo", lang="eo")
    spread = max(res.vector) - min(res.vector)
    # Compare against a domain-unique text, which should discriminate strongly.
    res_unique = scorer.score("kato", lang="eo")
    spread_unique = max(res_unique.vector) - min(res_unique.vector)
    assert spread < spread_unique


def test_compound_raises_two_domains(scorer):
    """A compound resolving to two roots in two domains lifts both."""
    # katfabriko-style compound: kat (animals) + import (customs)? build a
    # compound of two domain-unique roots. "katimport" → kat + import.
    res = scorer.score("katimporto", lang="eo")
    d = res.as_dict()
    assert d["animals"] > 0
    assert d["customs"] > 0
    # cooking has neither root.
    assert d["cooking"] == pytest.approx(0.0)


def test_coverage_partial_with_oov(scorer):
    # "kato" resolves (in vocab); "fluganta"/"xyzzy" do not.
    res = scorer.score("kato zzzqqq", lang="eo")
    assert 0.0 < res.coverage < 1.0


def test_all_oov_zero_vector_no_crash(scorer):
    res = scorer.score("zzzqqq wwwvvv", lang="eo")
    assert res.coverage == pytest.approx(0.0)
    assert all(v == pytest.approx(0.0) for v in res.vector)
    # does not raise.


def test_empty_text(scorer):
    res = scorer.score("", lang="eo")
    assert res.coverage == 0.0
    assert res.n_content_tokens == 0
    assert all(v == 0.0 for v in res.vector)


def test_determinism(scorer):
    a = scorer.score("importi deklaro oficejo kato", lang="eo").vector
    b = scorer.score("importi deklaro oficejo kato", lang="eo").vector
    assert a == b


# ---------------------------------------------------------------------------
# Shape / order / normalize
# ---------------------------------------------------------------------------


def test_vector_shape_and_order(scorer):
    res = scorer.score("importi", lang="eo")
    assert len(res.vector) == len(res.domains)
    assert res.domains == ["animals", "cooking", "customs"]
    assert list(res.as_dict().keys()) == res.domains


def test_normalize_l1_sums_to_one(scorer):
    res = scorer.score("importi kato kuiri", lang="eo", normalize="l1")
    assert sum(res.vector) == pytest.approx(1.0)


def test_normalize_max(scorer):
    res = scorer.score("importi kato kuiri", lang="eo", normalize="max")
    assert max(res.vector) == pytest.approx(1.0)


def test_normalize_invalid(scorer):
    with pytest.raises(ValueError):
        scorer.score("importi", lang="eo", normalize="bogus")


# ---------------------------------------------------------------------------
# explain()
# ---------------------------------------------------------------------------


def test_explain_returns_contributing_roots(scorer):
    res = scorer.score("importi deklaro", lang="eo")
    contribs = res.explain("customs")
    roots = {c["root"] for c in contribs}
    assert "import" in roots and "deklar" in roots
    # contributions sum to the raw cosine for the domain.
    total = sum(c["contribution"] for c in contribs)
    di = res.domains.index("customs")
    assert total == pytest.approx(res.raw_vector[di])


def test_explain_unknown_domain_raises(scorer):
    res = scorer.score("importi", lang="eo")
    with pytest.raises(KeyError):
        res.explain("nonexistent")


# ---------------------------------------------------------------------------
# Bundle round-trip + provenance
# ---------------------------------------------------------------------------


def test_bundle_roundtrip(toy_bundle_path):
    b = Bundle.load(toy_bundle_path)
    assert b.domains == ["animals", "cooking", "customs"]
    assert b.meta["schema_version"] == 1
    assert "build_date" in b.meta
    assert b.meta["langs"] == ["eo", "en"]
    assert "ofic" in b.vocab
    # provenance: scoring config recorded.
    assert b.meta["scoring"]["vector_norm"] == "l2"


def test_bundle_bytes_deterministic(tmp_path, toy_specs, lexicon_db_path, inventory_path):
    from eolex_relevance.build import build_bundle

    p1 = tmp_path / "a.bundle"
    p2 = tmp_path / "b.bundle"
    build_bundle(toy_specs, lexicon_db_path, inventory_path, p1,
                 langs=["eo", "en"], use_spacy=False, build_date="2026-01-01")
    build_bundle(toy_specs, lexicon_db_path, inventory_path, p2,
                 langs=["eo", "en"], use_spacy=False, build_date="2026-01-01")
    assert p1.read_bytes() == p2.read_bytes()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_score_emits_json(tmp_path, toy_bundle_path):
    out = subprocess.run(
        [sys.executable, "-m", "eolex_relevance", "score",
         "--model", str(toy_bundle_path), "--lang", "eo",
         "--text", "importi deklaro", "--no-spacy", "--json"],
        capture_output=True, text=True, check=True,
    )
    payload = json.loads(out.stdout)
    assert "domains" in payload
    assert "vector" in payload
    assert "coverage" in payload
    assert len(payload["vector"]) == len(payload["domains"])


def test_cli_build_and_score(tmp_path, toy_specs, lexicon_db_path, inventory_path):
    specs_path = tmp_path / "domains.json"
    specs_path.write_text(json.dumps(toy_specs), encoding="utf-8")
    bundle_path = tmp_path / "cli.bundle"
    build = subprocess.run(
        [sys.executable, "-m", "eolex_relevance", "build",
         "--domains", str(specs_path), "--lexicon", str(lexicon_db_path),
         "--inventory", str(inventory_path), "--out", str(bundle_path),
         "--langs", "eo,en", "--no-spacy"],
        capture_output=True, text=True, check=True,
    )
    info = json.loads(build.stdout)
    assert info["domains"] == ["animals", "cooking", "customs"]
    assert bundle_path.exists()
