# esperanto-lexicon
The code, which builds vocabularies for specialist knowledge area.

## eolex-relevance

`eolex-relevance` is a standalone, pip-installable package that scores a text's
relevance to up to ~10 domain ("Tier-4") dictionaries and returns a vector of
per-domain relevance scores. It reuses this repo's Esperanto root-decomposition
framework but is usable from any project: it has **no runtime dependency** on
the lexicon database — a single portable `*.bundle` is all a consumer needs.

It is a transparent **TF-IDF over Esperanto roots** scorer (no embeddings, no
training); `explain()` shows exactly which roots drove each score.

### Install

From this repo:

```bash
pip install -e ".[spacy]"
```

From another project (e.g. `the-essence`):

```bash
pip install -e "../esperanto-lexicon[spacy]"
```

spaCy is optional. Without it, en/lt resolution falls back to lowercase surface
forms (lower recall but fully functional); Esperanto is always decomposed
morphologically and needs no spaCy. With spaCy, install the models you use:

```bash
python -m spacy download en_core_web_sm
python -m spacy download lt_core_news_sm
```

### Build once / score many

A **builder** compiles a bundle (run inside this repo, where the lexicon assets
live); a **runtime scorer** loads only the bundle.

```bash
eolex-relevance build \
    --domains domains.json \
    --lexicon data/lexicon_db/lexicon_v2.db \
    --inventory data/lexicon_db/eo_inventory.json \
    --out model.bundle

eolex-relevance score --model model.bundle --lang eo \
    --text "La importinstanco kontrolis la deklaron." --json
```

`domains.json` is a list of domain specs; each is one of:

```jsonc
{"name": "customs", "source": "terms",  "lang": "eo", "terms": ["importi", "deklaro"]}
{"name": "cooking", "source": "corpus", "lang": "eo", "path": "cooking_eo.txt"}
{"name": "law",     "source": "db",     "lang": "eo", "query": "SELECT word FROM ..."}
```

`terms` and `corpus` are the primary, fully-specified paths. `db` is a
documented hook with a sensible default query — adapt it to your domain-tagging
schema.

### Usage (downstream project)

```python
from eolex_relevance import RelevanceScorer

scorer = RelevanceScorer.load("model.bundle")          # loads only the bundle
res = scorer.score("La importinstanco kontrolis la deklaron.", lang="eo")

res.vector        # [0.81, 0.05, 0.14]  (floats, in domain order)
res.domains       # ["customs", "cooking", "law"]
res.as_dict()     # {"customs": 0.81, "cooking": 0.05, "law": 0.14}
res.coverage      # 0.80  — fraction of content tokens whose root is known
res.explain("customs")   # top contributing roots, with weights and glosses
```

The output vector can be normalized: `normalize="none"` (raw cosines, default),
`"l1"` (components sum to 1 — a domain profile), or `"max"`.

### Scoring math

Given `N` domains with root-frequency maps `f_i`:

- `df(r)` = number of domains containing `r`;  `idf(r) = log((N+1)/(df(r)+1)) + 1`
- domain vector `w_i(r) = (f_i(r) / Σ f_i) · idf(r)`, then **L2-normalized**

For an input text with content-root multiset `c(r)`:

- `tf(r) = c(r) / Σ c`;  `u(r) = tf(r) · idf(r)` over bundle-vocabulary roots,
  then L2-normalized
- `relevance_i = cosine(u, w_i) ∈ [0, 1]`
- `coverage = (content tokens whose root ∈ vocab) / (total content tokens)`

Esperanto compounds decompose to multiple roots and **credit each** (so a word
spanning two domains lifts both). Identical input → identical vector
(deterministic). Bundles record their provenance (inventory/DB version, domain
list, scoring config) so any vector is reproducible from a known bundle.

### Examples

Runnable, and double as docs:

```bash
python examples/build_demo.py            # build demo.bundle from 3 toy domains
python examples/score_demo.py            # score sample texts, print vectors
cat   examples/use_from_other_project.py # the minimal downstream snippet
```

### Tests

```bash
pytest tests/eolex_relevance/                 # fast, offline, toy fixtures
pytest -m slow tests/eolex_relevance/         # integration on the real bundle
```
