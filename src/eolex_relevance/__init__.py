"""eolex_relevance — score text relevance to domain ("Tier-4") dictionaries.

Build-once / score-many. A :func:`eolex_relevance.build.build_bundle` call
compiles a portable ``.bundle`` from the Esperanto-lexicon assets; downstream
projects then load only that bundle::

    from eolex_relevance import RelevanceScorer
    scorer = RelevanceScorer.load("customs_law_med.bundle")
    res = scorer.score("La importinstanco kontrolis la deklaron.", lang="eo")
    res.as_dict()   # {"customs": 0.81, "law": 0.12, "medicine": 0.03}

The scorer is a transparent TF-IDF-over-Esperanto-roots cosine — no embeddings,
no training; ``res.explain(domain)`` shows which roots drove each score.
"""

from __future__ import annotations

from .bundle import Bundle
from .scorer import RelevanceScorer, ScoreResult

__all__ = ["RelevanceScorer", "ScoreResult", "Bundle", "__version__"]

__version__ = "0.1.0"
