# eolex

Thin read-side API over the Esperanto lexicon — morphology, multilingual word resolution, and pedagogical tiers.

Ships a pre-built bundle as package data; no lexicon database or network access needed at runtime.

## Install

```
pip install "eolex @ git+https://github.com/Ramunas01/esperanto-lexicon.git#subdirectory=eolex"
```

## Quick start

```python
from eolex import Lexicon

lex = Lexicon.load()                         # packaged bundle
lex.roots("akvobirdo", lang="eo")            # ["akv", "bird"]
lex.inventory_tier("akv")                    # "core"
lex.gloss("akv")                             # "aquatic, of water, ..."
lex.pedagogical_tier("akvo", lang="eo")      # 1   (Tier 1 = child / A1)
lex.cefr("akvo", lang="eo")                  # "A1"
```

## Two tier systems — do not confuse

| Method | Values | Meaning |
|---|---|---|
| `inventory_tier(root)` | core / extended / tail | ESPDIC morphological productivity |
| `pedagogical_tier(word, lang)` | 1 / 2 / 3 / 4 | Expertise ladder (1 = child) |

## Development

This package lives in `esperanto-lexicon/eolex/` as a git subdirectory with its own `pyproject.toml`.

```bash
pip install -e ./eolex          # editable install
pytest tests/eolex/             # run tests (from repo root)
```

The packaged bundle (`eolex/data/lexicon.bundle`) is committed to the repository and rebuilt by running `build_lexicon_bundle()` from `eolex_relevance.build` against `lexicon_v2.db`.
