#!/usr/bin/env python3
"""Score a few sample texts against examples/demo.bundle and print the vectors.

    python examples/build_demo.py      # produces demo.bundle
    python examples/score_demo.py
"""

from __future__ import annotations

from pathlib import Path

from eolex_relevance import RelevanceScorer

BUNDLE = Path(__file__).resolve().parent / "demo.bundle"

SAMPLES = [
    ("eo", "La importinstanco kontrolis la doganan deklaron kaj la tarifon."),
    ("eo", "Mi bakis pomtorton kaj boligis legomojn laŭ nova recepto."),
    ("eo", "La juĝisto legis la verdikton pri la kontrakto en la tribunalo."),
]


def main() -> None:
    if not BUNDLE.exists():
        raise SystemExit("Run examples/build_demo.py first to create demo.bundle")
    scorer = RelevanceScorer.load(BUNDLE, use_spacy=False)
    print(f"domains: {scorer.domains}\n")
    for lang, text in SAMPLES:
        res = scorer.score(text, lang=lang, normalize="l1")
        print(f"[{lang}] {text}")
        for name, score in res.as_dict().items():
            print(f"     {name:<10} {score:.3f}")
        print(f"     coverage={res.coverage:.2f}  "
              f"top={res.top(1)[0][0]!r}\n")

    # explain() shows which roots drove the top domain of the first sample.
    res = scorer.score(SAMPLES[0][1], lang="eo")
    top_domain = res.top(1)[0][0]
    print(f"Why sample 1 scored {top_domain!r}:")
    for c in res.explain(top_domain, top_k=5):
        print(f"     {c['root']:<10} contribution={c['contribution']:.3f} "
              f"({c['gloss']})")


if __name__ == "__main__":
    main()
