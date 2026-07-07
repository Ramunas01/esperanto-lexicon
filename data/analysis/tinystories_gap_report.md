# TinyStories coverage probe — gap report

**Branch:** `analysis/tinystories-coverage`  **Language:** EN  **Lexicon:** `lexicon_v2.db` (read-only)
**Corpus:** 5,000 TinyStories (`roneneldan/TinyStories`, train split, first 5,000 records),
100 chunks × 50 stories, **356,465 classified tokens**.

This is a **common-vocabulary hygiene + metric-calibration** probe, not an expertise study.
TinyStories is written in a deliberately tiny (~1,500-word) child vocabulary with no domain
content and no expertise gradient. Because the vocabulary is known-simple *by construction*,
every token the analyzer cannot classify is — by elimination — a **Tier-1/2 coverage gap** or a
**lemmatisation miss**, nothing else. The probe therefore measures the reliability of the
`T1+T2` denominator that the whole `T4_ratio` expertise metric divides by.

> **Data-quality note (corpus build).** ~7.5 % of TinyStories source records contain
> double-encoded UTF-8 mojibake (a curly quote `“` arrives as the literal string `â€œ`).
> Written verbatim these produce garbage UNKNOWN tokens (`â€œbe`, `better.â€`) that have
> nothing to do with lexicon coverage. The fetch script
> (`src/analyzer/fetch_tinystories.py`) repairs the mojibake and folds Unicode punctuation
> to ASCII, then drops any non-ASCII residue. The corpus used here is verified 0 mojibake /
> 0 non-ASCII. An earlier attempt that skipped this step inflated UNKNOWN with encoding
> artefacts — recorded so the failure class is not repeated.

---

## 1. Headline

| Metric | Value |
|---|---|
| Classified tokens | 356,465 |
| **T1 + T2 coverage** | **80.5 %** |
| Tier 3 | 99 (0.03 %) |
| **UNKNOWN** | **19.5 %** |
| Unique UNKNOWN types | 3,819 |
| **Pooled `T4_ratio` (no domain DBs)** | **0.000000** |
| **Pooled `T4_ratio` (all 6 domain DBs)** | **0.000771** |

The 19.5 % UNKNOWN rate looks high for child vocabulary, but the triage below shows **the
majority of it is proper nouns (character names)**, not lexicon failure. The genuine
common-lexicon gap is **~8 % of running tokens**, and lemmatisation misses are **negligible
(<0.2 %)** — the pipeline's `T1+T2` denominator is structurally sound; it is simply missing a
well-defined, fixable set of common child words.

---

## 2. UNKNOWN triage (three buckets)

Buckets are mutually exclusive, evaluated `inflection_miss → proper_noun → common_gap`.
Full per-token data: `data/analysis/tinystories_unknown_triaged.tsv`
(columns: `token, frequency, bucket, is_propn, caps_majority, lemma`).

| Bucket | Unique types | Occurrences | % of UNKNOWN | % of corpus |
|---|---:|---:|---:|---:|
| `proper_noun` | 706 | 40,142 | **57.8 %** | 11.26 % |
| `common_gap` | 2,960 | 28,708 | **41.3 %** | 8.05 % |
| `inflection_miss` | 153 | 616 | 0.9 % | 0.17 % |
| **Total** | 3,819 | 69,466 | 100 % | 19.49 % |

* **`proper_noun` (57.8 %)** — expected and ignorable. TinyStories is saturated with a small
  cast of character names (`lily` 4354, `timmy` 1829, `ben` 1631, `tom` 1600, …). Names are
  language/geography-dependent and out of scope for the common lexicon (see CLAUDE.md
  "Named entity handling … not yet designed").
* **`common_gap` (41.3 %)** — the genuine, frequency-ranked Tier-1/2 gap-fill queue (§3).
* **`inflection_miss` (0.9 %)** — the token's *isolated* spaCy lemma resolves in the lexicon
  but the analyzer left it UNKNOWN in context (e.g. `playing→play`, `loved→love`,
  `sharing→share`, `grown→grow`). At 616 occurrences (0.17 % of corpus) this is negligible —
  **a direct validation that the analyzer's in-context lemmatisation + `inflected_forms`
  lookup is healthy** and is *not* inflating UNKNOWN.

---

## 3. Common-gap queue (top 50) — the Tier-1/2 gap-fill list

These are genuine gaps: spot-checked against the lexicon, `hug`, `nod`, `hop`, `butterfly`,
`doll`, `pond`, `duck`, `balloon`, `rainbow`, `swing`, `clap` all return **0 rows** in
`concept_lang(en)`. A child lexicon that omits these is materially incomplete.

| # | freq | token | # | freq | token |
|--:|--:|---|--:|--:|---|
| 1 | 655 | hugged | 26 | 106 | tasty |
| 2 | 404 | nodded | 27 | 105 | dolls |
| 3 | 339 | hopped | 28 | 104 | basket |
| 4 | 253 | butterfly | 29 | 104 | shining |
| 5 | 249 | doll | 30 | 103 | sunshine |
| 6 | 242 | pond | 31 | 100 | sack |
| 7 | 202 | bug | 32 | 92 | lovely |
| 8 | 202 | magical | 33 | 92 | rainbow |
| 9 | 163 | swing | 34 | 89 | bugs |
| 10 | 158 | cheered | 35 | 89 | hoped |
| 11 | 156 | clapped | 36 | 87 | cute |
| 12 | 150 | balloon | 37 | 84 | meadow |
| 13 | 143 | nearby | 38 | 81 | bow |
| 14 | 141 | relieved | 39 | 81 | jar |
| 15 | 136 | dragon | 40 | 81 | playground |
| 16 | 134 | cookies | 41 | 79 | colourful |
| 17 | 134 | duck | 42 | 78 | picnic |
| 18 | 131 | bucket | 43 | 78 | swings |
| 19 | 128 | kite | 44 | 75 | gently |
| 20 | 123 | backyard | 45 | 75 | sparkly |
| 21 | 122 | naughty | 46 | 74 | angel |
| 22 | 115 | nap | 47 | 74 | hopping |
| 23 | 114 | swam | 48 | 74 | tightly |
| 24 | 112 | treasure | 49 | 72 | yelled |
| 25 | 109 | blanket | 50 | 71 | nest |

**Two structural observations for whoever works the queue:**

1. **Inflection redundancy.** Many rows are surface inflections of one missing root
   (`hugged`/`hopped`/`hopping`, `doll`/`dolls`, `bug`/`bugs`, `swing`/`swings`/`swam`). The
   queue is surface-form ranked; adding the **lemma** plus letting `inflected_forms` cover the
   rest will clear several rows each. The 2,960 types collapse to substantially fewer roots.
2. **British spellings.** `colourful`, `colour`, `favourite`, `behaviour`, `neighbour(s)`
   surface as UNKNOWN because the lexicon (Oxford/Dolch-seeded) carries US spellings only.
   This is a **spelling-variant coverage gap**, not a vocabulary gap — a candidate for a
   normalisation/variant map rather than new concepts.

---

## 4. Flags for human review (report only — nothing changed)

### 4a. Tier-misassignment flag
One resolved token with corpus frequency ≥ 50 sits at Tier 3:

| freq | token | current tier |
|--:|---|--:|
| 51 | number | 3 (C1) |

`number` is plainly age-5 vocabulary; Tier 3 (C1) looks too high. **Candidate for demotion to
Tier 1/2 — flagged only; no tier was changed** (hard rule, CLAUDE.md).

### 4b. Proper-noun bucket leakage (reclaim to the gap queue)
The `proper_noun` bucket is assigned on capitalisation / spaCy `PROPN`. spaCy tags
capitalised **common** words as `PROPN` too, so a handful of high-frequency common child words
are hiding in `proper_noun` and should be **reclaimed into the gap queue**:

| freq | token | why it leaked |
|--:|---|---|
| 1441 | mommy | address term, almost always capitalised |
| 633 | mum | address term |
| 426 | rabbit | personified animal ("Rabbit") |
| 388 | curious | frequently sentence-initial / titled |
| 384 | hug | PROPN-mistagged |
| 343 | okay | interjection, capitalised |
| 338 | daddy | address term |
| 263 | bunny | personified animal |

≈ 4,700 occurrences. Because these carry `is_propn=1`, they are *not* caught by the
`is_propn=0` audit filter — the reviewer should eyeball the top of the `proper_noun` bucket by
frequency. (The 23 caps-only leaks with `is_propn=0` are mostly interjections — `uh`,
`woah`, `hurray` — and are trivial.) This modestly **understates** `common_gap` and overstates
`proper_noun` in §2.

---

## 5. Calibration-floor check — **PASS**

Requirement: TinyStories pooled `T4_ratio` must sit below the validation report's control-
stratum floor of **0.018**. A value at/above 0.018 would signal spurious Tier-4 hits on child
vocabulary (a tooling bug).

| Configuration | T4 hits | `T4_ratio` | vs floor 0.018 |
|---|--:|--:|:--|
| No domain DBs | 0 | 0.000000 | **PASS** (trivially — no T4 source loaded) |
| **All 6 domain DBs loaded** | 221 | **0.000771** | **PASS — 23× below floor** |

The meaningful test loads the domain DBs (the only source of T4). Even with all six
customs/expert DBs loaded, child vocabulary yields `T4_ratio = 0.000771` — 221 incidental hits
in 356 k tokens (0.06 %), from child words that happen to collide with a domain MWE surface
form (`goods`, `value`, `party`, `office`, …). **No spurious-hit tooling bug; the floor holds
robustly.**

---

## 6. Conclusions

1. **The `T1+T2` denominator is sound but under-covered.** Real coverage gap ≈ 8 % of running
   tokens, concentrated in a fixable, frequency-ranked set of common child words. Lemmatisation
   misses are negligible (<0.2 %) — the pipeline is not inflating UNKNOWN.
2. **Most of the 19.5 % UNKNOWN is character names** (57.8 % of UNKNOWN), i.e. the
   not-yet-designed named-entity layer, not lexicon failure.
3. **Calibration floor holds** (`T4_ratio` 0.000771 ≪ 0.018). The metric does not manufacture
   Tier-4 signal from child text.
4. **Actionable output:** the top-50 gap queue (§3), the British-spelling variant cluster, the
   `number` tier flag (§4a), and the ~8 leaked common words to reclaim from `proper_noun`
   (§4b). All are **for human review** — no lexicon entry, tier, word, cefr_level, or source
   was modified by this task.

### Honest limits
This says nothing about the Tier-4 / expertise end — there is no domain content in TinyStories.
It is common-vocabulary hygiene + metric calibration. The gap queue is a *candidate* list for
human review, not an auto-applied change. Proper-noun/common-word separation is heuristic
(§4b) and imperfect by construction — the named-entity layer remains an open design item.

---

## 7. Reproduce

```bash
# 1. Fetch clean corpus (~1M tokens; repairs mojibake, gitignored raw data)
python3 src/analyzer/fetch_tinystories.py --num-stories 5000 --stories-per-chunk 50 \
    --output-dir ~/projects/esperanto-lexicon-corpus/tinystories/stories

# 2. RUN A — coverage, no domain DBs (the probe)
python3 src/analyzer/batch_coverage_report.py \
    --corpus ~/projects/esperanto-lexicon-corpus/tinystories --lang en \
    --lexicon data/lexicon_db/lexicon_v2.db \
    --output data/analysis/tinystories_run/tinystories_coverage.csv

# 3. Calibration run — all domain DBs (floor check)
python3 src/analyzer/batch_coverage_report.py \
    --corpus ~/projects/esperanto-lexicon-corpus/tinystories --lang en \
    --lexicon data/lexicon_db/lexicon_v2.db \
    --domain-dbs data/domain_db/*.db \
    --output data/analysis/tinystories_run/with_domain/tinystories_coverage_domdb.csv

# 4. Triage the pooled UNKNOWN tokens
python3 src/analyzer/tinystories_gap_triage.py \
    --pooled data/analysis/tinystories_run/unknown_tokens_pooled.txt \
    --corpus ~/projects/esperanto-lexicon-corpus/tinystories \
    --lexicon data/lexicon_db/lexicon_v2.db --lang en \
    --output-tsv data/analysis/tinystories_unknown_triaged.tsv
```

**Deliverables (under `data/analysis/`):**
`tinystories_run/tinystories_coverage.csv` (per-text + pooled metrics),
`tinystories_unknown_triaged.tsv` (every UNKNOWN token + frequency + bucket + diagnostics),
`tinystories_gap_report.md` (this report). CSVs are gitignored (regenerable); the `.tsv` and
this report are committed.
