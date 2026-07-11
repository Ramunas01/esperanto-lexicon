# British-spelling fold — closing the T1–T3 coverage arc

Resolves the one real leak the cross-corpus UNKNOWN inventory (PR #12) found: the
British/Commonwealth spelling cluster whose **US form already exists as a concept**.
Pure normalization — no new vocabulary, no Esperanto anchoring, no sense review, no
human gate. Insert-only; the existing US `concept`/`concept_lang` rows are never
touched.

## Mechanism
Each British surface form gets an insert-only `inflected_forms` row
`(inflected_word=<british>, lemma=<us concept word>, lang='en',
form_description='british_spelling', tier=<us concept's tier>)`. The resolver
(`coverage_report.classify_tokens` via `load_inflected_forms`) already maps
surface→lemma→tier before UNKNOWN, so the British surface resolves to the existing US
concept — **no resolver-code change, no new `concept_lang` rows** (which would have
inflated coverage as "new" vocabulary).

Generation is **data-driven and guarded** (no hand-listed pairs): iterate the
committed inventory `pooled_unknown_classified.tsv` (buckets `local`, `common_gap`,
`true_residual`), fold each token with the extended `uk_to_us`, reduce the folded US
form to its **concept lemma** (the lexicon stores base forms: `colours`→`colors`→
`color`), and emit a row **only when that lemma is an existing en concept word**. The
guard covers British inflections directly and rejects junk/typos.

Two refinements were needed versus the naive map (both regression-tested):
- **`-re→-er` needs a min-stem guard** — else `pre`→`per` (a real word the US-present
  guard can't catch) and `tore`→`toer`. Requiring ≥3 chars before `-re` blocks them.
- **British plurals/inflections must target the concept lemma** — `colours`/`neighbours`/
  `centres` fold to `color`/`neighbor`/`center` via de-inflection, since the lexicon
  stores base forms, not `colors`.

## The 18 folds (270 tokens)
| british | → US lemma | tier | n | | british | → US lemma | tier | n |
| --- | --- | :-: | --: | --- | --- | --- | :-: | --: |
| colourful | colorful | 1 | 79 | | theatre | theater | 1 | 4 |
| favourite | favorite | 1 | 54 | | rumour | rumor | 2 | 3 |
| colours | color | 1 | 35 | | flavour | flavor | 2 | 2 |
| coloured | colored | 2 | 20 | | organised | organized | 2 | 2 |
| neighbour | neighbor | 1 | 20 | | organiser | organizer | 2 | 2 |
| colour | color | 1 | 17 | | centres | center | 1 | 1 |
| neighbours | neighbor | 1 | 15 | | flavours | flavor | 2 | 1 |
| aeroplane | airplane | 2 | 9 | | pyjamas | pajama | 2 | 1 |
| behaviour | behavior | 2 | 4 | | recognise | recognize | 2 | 1 |

All US lemmas are Tier-1/2 — which matters: the resolver's `inflected_forms` path only
checks T1/T2 for the canonical lemma, so a T3 target would not resolve. (None here do.)
Full list committed at `data/analysis/uk_spelling/british_folds.tsv`.

## Before / after (UNKNOWN classifier re-run with `inflected_forms` loaded)
| measure | before | after | Δ |
| --- | --: | --: | --: |
| **TinyStories UNKNOWN** | 28,944 (8.12%) | 28,676 (8.04%) | −268 tokens |
| pooled UNKNOWN | 34,077 | 33,805 | −272 tokens |
| pooled `local` bucket | 560 | 311 | −249 |
| pooled `common_gap` bucket | 47 | 25 | −22 |
| pooled `true_residual` | 21 (2 types) | 21 (2 types) | unchanged |

All 18 folded tokens now resolve (0 remain UNKNOWN); no British `-our`/`-ise`/`-re`
token remains in `local`/`common_gap`. The absolute UNKNOWN drop is modest because
names dominate UNKNOWN (~89%) — but the British cluster was the *only coherent
non-name systematic class*, and it is now gone. The residual is no longer a pattern.

## The true residual: genuine single words, not a systematic hole
Post-fold cross-corpus `true_residual` = **2 tokens**, both correctly non-foldable:
- **`stratum`** — a Latin-origin word, US spelling = UK spelling; nothing to fold.
  (It appears at all only because the `control` corpus texts carry metadata headers
  `# stratum: control` — a corpus-hygiene artifact, not vocabulary.)
- **`fertiliser`** — its US form `fertilizer` is **not in the lexicon**, so it cannot
  fold: a genuine one-word common gap, not a spelling miss.

### `us_form_absent` — British tokens whose US form is genuinely absent (out of scope)
These fold in spelling but their US form is not a concept, so they were **not** written
(candidates for a trivial future 1-word add, not this task):

| british | US form (absent) | n | note |
| --- | --- | --: | --- |
| fertiliser | fertilizer | 10 | genuine gap |
| apologised | apologized | 4 | genuine gap |
| centimetres | centimeters | 2 | genuine gap |
| capitalising | capitalizing | 1 | genuine gap |
| equaliser | equalizer | 1 | genuine gap |
| mesmerised | mesmerized | 1 | genuine gap |
| suprised | suprized | 1 | **typo** for "surprised" — correctly rejected, not a gap |

## Deliberately deferred (per the brief, to the next initiative)
`mum`/`mummy`/`organisation` are British spellings the inventory **misrouted into the
`named_entity` bucket** (they appear proper-cased — "Mum", "Mummy"). The generator
scans only `local`/`common_gap`/`true_residual`, so they were **not** folded here.
Clearing that contamination is the **name-candidate regeneration** initiative (Part B
of the source brief), not this one. `uk_to_us` now knows these folds (`mum→mom`, …), so
that task can extend the fold to the `named_entity` bucket cleanly.

## Also fixed: a schema drift
`schema.py`'s `inflected_forms` definition was missing the `UNIQUE (inflected_word,
lemma, lang)` constraint that the live DB already carries (the fold's idempotency
guard). Added it to the source of truth so a fresh regeneration matches production. The
live `lexicon_v2.db` already had it — no migration needed; the `--commit` fold was
idempotent (`INSERT OR IGNORE`).

## Audit
Backup + single transaction + post-write audit: **18 rows inserted (inflected_forms
49→67), `concept` and `concept_lang` unchanged, 0 duplicate rows — PASS.** Read-only on
existing US entries throughout.

## Closing
**T1–T3 common-vocabulary coverage is complete.** After gap-fill, the AWL seed, and this
British-spelling fold, the cross-corpus true residual is a handful of **genuine single
words** — `stratum` (US=UK) and a short `us_form_absent` list led by `fertiliser` — not a
systematic hole. This formally ends the common-vocabulary coverage line of work; what
remains for UNKNOWN is the names layer (the ~89% elephant), a different kind of problem.

## Artifacts
- `data/analysis/uk_spelling/british_folds.tsv` — the folded pairs + `us_form_absent` gaps.
- `data/analysis/uk_spelling/after/` — the post-fold regenerated inventory (evidence).
- `src/lexicon/apply_uk_spelling_fold.py` (generator + insert-only writer);
  extended `src/lexicon/build_gapfill_worksheet.py:uk_to_us`.
- Tests: `tests/test_apply_uk_spelling_fold.py`, `tests/test_build_gapfill_worksheet.py::TestBritish`
  (every fold class + guards; no network).
