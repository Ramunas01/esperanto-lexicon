"""Slow integration tests against the real lexicon assets.

Skipped automatically when ``lexicon_v2.db`` / ``eo_inventory.json`` are not
present (e.g. in a checkout that has not regenerated them). Run with::

    pytest -m slow tests/eolex_relevance/test_slow_integration.py
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eolex_relevance import RelevanceScorer
from eolex_relevance.build import build_bundle
from eolex_relevance.eo_decomposer import Decomposer as VendoredDecomposer

REPO_ROOT = Path(__file__).resolve().parents[2]
LEXICON_DB = REPO_ROOT / "data" / "lexicon_db" / "lexicon_v2.db"
INVENTORY = REPO_ROOT / "data" / "lexicon_db" / "eo_inventory.json"

pytestmark = pytest.mark.slow

requires_assets = pytest.mark.skipif(
    not (LEXICON_DB.exists() and INVENTORY.exists()),
    reason="real lexicon assets not present",
)


@requires_assets
def test_build_and_score_real_bundle(tmp_path):
    specs = [
        {"name": "customs", "source": "terms", "lang": "eo",
         "terms": ["importi", "deklaro", "imposto", "doganaĵo"]},
        {"name": "cooking", "source": "terms", "lang": "eo",
         "terms": ["kuiri", "pomo", "boli", "rostita"]},
        {"name": "law", "source": "terms", "lang": "eo",
         "terms": ["leĝo", "juĝisto", "kontrakto", "verdikto"]},
    ]
    out = tmp_path / "real.bundle"
    build_bundle(specs, LEXICON_DB, INVENTORY, out, langs=["eo", "en", "lt"],
                 use_spacy=False)
    scorer = RelevanceScorer.load(out, use_spacy=False)
    res = scorer.score("La importinstanco kontrolis la doganan deklaron.",
                       lang="eo")
    assert len(res.vector) == 3
    # customs should be the strongest signal for a customs sentence.
    assert res.as_dict()["customs"] == max(res.vector)
    assert 0.0 <= res.coverage <= 1.0


@requires_assets
def test_vendored_decomposer_matches_canonical():
    """The vendored decomposer must not diverge from the lexicon repo's."""
    import sys

    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from src.lexicon.eo_root_decomposer import Decomposer as CanonicalDecomposer

    inv = json.loads(INVENTORY.read_text(encoding="utf-8"))
    vendored = VendoredDecomposer(inv)
    canonical = CanonicalDecomposer(inv)

    # Sample a spread of real headwords.
    sample = inv.get("headwords", [])[:2000]
    mismatches = []
    for word in sample:
        v = vendored.decompose_word(word)
        c = canonical.decompose_word(word)
        if v.kind != c.kind or v.roots != tuple(cr.root for cr in c.content_roots):
            mismatches.append((word, v.kind, c.kind, v.roots))
    assert not mismatches, f"{len(mismatches)} divergences, e.g. {mismatches[:5]}"
