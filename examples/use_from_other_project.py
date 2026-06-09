#!/usr/bin/env python3
"""The minimal import → load → score snippet a downstream project copies.

A consumer (e.g. the-essence) installs the package and ships a prebuilt
bundle::

    pip install -e "../esperanto-lexicon[spacy]"

then needs only the bundle file at runtime — no lexicon DB, no network:
"""

from eolex_relevance import RelevanceScorer

# Path to a bundle produced by `eolex-relevance build` (ship it with your app).
scorer = RelevanceScorer.load("demo.bundle")

result = scorer.score(
    "La importinstanco kontrolis la doganan deklaron.", lang="eo"
)

print(result.vector)        # [0.81, 0.05, 0.14]  — in scorer.domains order
print(result.domains)       # ['customs', 'cooking', 'law']
print(result.as_dict())     # {'customs': 0.81, 'cooking': 0.05, 'law': 0.14}
print(result.coverage)      # fraction of content tokens whose root is known
