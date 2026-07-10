# Cross-corpus UNKNOWN inventory + D1 accounting

Read-only diagnostic. Turns UNKNOWN from a scalar (~8–9%) into a **classified,
cross-corpus taxonomy** and isolates the one diagnostic cell — the **true residual**
(non-junk, non-name, non-domain, non-inflection tokens UNKNOWN across ≥2 corpora).
No lexicon writes; authors nothing.

## Headline
**True-residual UNKNOWN = 0.006% (21 tokens, 2 distinct types) pooled across 4 corpora.**
After subtracting the known elephant (names = **89%** of all UNKNOWN), junk, domain
terms, inflection misses, and plain common-gaps, essentially nothing structural is
left. The two residual tokens are `fertiliser` (a British spelling) and `stratum` (a
corpus-header artifact). **On the strict cross-corpus definition, the common
foundation is complete** — the reassuring result the brief anticipated.

**But the honest read of the tail is more interesting than "just names":** the
leftover non-name vocabulary is dominated by ONE coherent, addressable class —
**British/Commonwealth spellings** — that the universality bar hid (see below). That
is the one place the foundation still leaks, and it is cheap to close.

## Method
- **wordfreq** (the mandatory junk gate) installed 3.1.1 via
  `pip install --user --break-system-packages wordfreq` — the brief's permitted route;
  **no fallback junk gate was needed.** zipf < 1.5 ≈ "essentially not an English word".
- **4 corpora, kept separate** (universality = # corpora a token is UNKNOWN in):
  `tinystories` (child, 100 texts), `control` (general topics, 5), `novice` (customs, 7),
  `expert` (customs, 17). The brief's `corpus-1..7` domain dirs don't exist; the customs
  strata stand in. `novice`/`expert` are tagged **domain**; `tinystories`/`control` are
  non-domain.
- **Pools regenerated with the current (post-AWL) lexicon, common-lexicon only** (no
  domain DBs), so domain vocabulary surfaces as UNKNOWN and is sorted by the
  classifier's `domain_term` bucket via cross-corpus concentration.
- **Classifier** (`src/analyzer/unknown_classifier.py`, reusable + tested), first match
  wins: `junk → named_entity → inflection_miss → domain_term → common_gap → true_residual`
  (+ `local` for single-corpus non-domain leftovers). Name bucket matched against the v0
  `named_entity` store (272 entities) via `query_named_entities.resolve` — store hit =
  `confirmed`, name-cased/PROPN but absent = `candidate`.

## Classified breakdown (pooled)

| bucket | types | tokens | note |
| --- | ---: | ---: | --- |
| `junk` | 270 | 710 | OCR/symbols/abbrev (`e.g.`, `u.s.`, `&`), volume is not signal |
| `named_entity` | 1,008 | 30,434 | **the elephant — 89% of UNKNOWN** (lily/timmy/ben…) |
| `inflection_miss` | 229 | 945 | lemma resolves, surface didn't → a pipeline issue |
| `domain_term` | 625 | 1,360 | customs jargon (classification, dumping, resale…) → Tier-4 |
| `common_gap` | 11 | 47 | plain common words still missing (mostly British spellings) |
| **`true_residual`** | **2** | **21** | **the deliverable** |
| `local` | 232 | 560 | single-corpus, non-domain leftovers |
| **raw UNKNOWN** | **2,377** | **34,077** | **9.01% of 378,313 content tokens** |

Raw UNKNOWN % by corpus: `tinystories` 8.1% · `control` 15.1% · `novice` 22.9% ·
`expert` 24.1% (higher in the domain corpora, as expected — they carry Tier-4 vocab
that a common-lexicon-only pass cannot cover). True-residual % by corpus:
`tinystories` 0.000 · `control` 1.051 · `novice` 0.000 · `expert` 0.055.

## The shape of what remains — the real finding: British spellings
The strict true-residual is ~empty, but the classification's *tail* (`local` +
`common_gap` + a few mis-cased into `named_entity`) is not random noise. It is a single
coherent regime the lexicon structurally misses: **British/Commonwealth spelling
variants of words it already holds in American form.** Quantified with the gap-fill's
own `uk_to_us` fold, restricted to variants whose US form is *already in the lexicon*:

> **17 UNKNOWN types / 1,097 tokens** are British spellings the lexicon could already
> resolve: `mum`→mom (633), `mummy`→mommy (236), `colourful`→colorful (79),
> `favourite`→favorite (54), `coloured`→colored, `neighbour`→neighbor, `colour`→color,
> `aeroplane`→airplane, `centre`→center, `behaviour`, `theatre`, `organisation`,
> `flavour`, `favour`, `honour`, … (a fuller fold list — `-iser`, `-gement`, plurals —
> would catch more: `fertiliser`, `judgement`, `colours`, `neighbours`).

**Why universality hid it:** British spellings concentrate in the British-authored
`tinystories`, so most are UNKNOWN in only *one* corpus → bucketed `local`, not
`true_residual`. With a second British corpus they would jump straight into the true
residual. So the "0.006%" is real for *this* corpus set but slightly flatters the
foundation — the spelling-regime hole is genuine, just under-exposed by corpus mix.

## Secondary observations
- **`inflection_miss` (945 tokens, 229 types)** — surfaces where spaCy's lemmatizer
  fails in context (e.g. an occurrence of `playing` not lemmatized to `play`) so a known
  base word falls to UNKNOWN. A pipeline fix (stemmer fallback / better lemmatization),
  not a lexicon gap. Small but free to reclaim.
- **`named_entity` = 89%** — confirms the names layer is the right home for the bulk of
  UNKNOWN; nothing to do here beyond feeding candidates to it (D1).
- **`domain_term` (1,360)** — customs vocabulary correctly isolated to the domain corpora;
  belongs in the Tier-4 domain DBs, not the common lexicon.

## D1 accounting — name candidates
`data/analysis/unknown_inventory/name_candidates.tsv`: **936** name-bucket tokens absent
from the v0 store, salience-ranked (lily 4,354 · timmy 1,829 · ben 1,631 · tom · tim ·
jack · sam · john …). These are TinyStories given-names — future curation for the names
layer; **authored nothing**. (A handful of capitalized address terms — `mum`/`mummy` —
land here too; they are really British spellings and should route to the spelling fold,
not the store.)

## Honest caveats
- Only **4 corpora**, and the non-tinystories ones are small (5/7/17 texts), so the
  ≥2-corpus universality bar is demanding — part of why the strict residual is tiny.
- **Corpus hygiene:** `control` texts carry metadata headers (`# stratum: control`),
  which is why `stratum` appears in the residual — an artifact, not vocabulary. Stripping
  headers before analysis would remove it.
- The name gate on lowercased pooled tokens leans on spaCy PROPN / observed proper-noun
  casing; it is deliberately conservative (a token whose base form is a known word is
  treated as an inflection, not a name) to avoid mis-routing `loved`/`customs`.

## Go-forward
1. **Close the British-spelling regime** — the one real leak. Extend the gap-fill's
   `uk_to_us` fold (add `-ise/-iser`, `-gement`, plural `-ours`/`-res`) and apply it at
   lookup or as `inflected_forms`/aliases. Reclaims ~1,100+ UNKNOWN tokens for near-zero
   effort. (Read-only here; this is a follow-up authoring task.)
2. **Feed `name_candidates.tsv` to the names layer** (future curation), not the common
   lexicon.
3. **Optional lemmatizer hardening** to drain `inflection_miss`.
4. The reusable classifier is wired into `batch_coverage_report.py` via the optional
   `--classify-unknown` flag (default output unchanged) so future coverage runs can show
   classified-UNKNOWN, not just the scalar.

**Bottom line:** after names + gap-fill + AWL, the common foundation is structurally
sound — the only coherent class it still misses is British spelling, which is a cheap,
well-understood fold rather than a surprise. A reassuring result, with one concrete,
low-cost action.

## Artifacts
- `data/analysis/unknown_inventory/pooled_unknown_classified.tsv` — every token: per-corpus
  UNKNOWN counts, universality, bucket, zipf, is_propn, lemma, store-match.
- `data/analysis/unknown_inventory/true_residual.tsv` — the isolated cell, universality-ranked.
- `data/analysis/unknown_inventory/name_candidates.tsv` — name-bucket tokens absent from the store.
- Code: `src/analyzer/unknown_classifier.py`, `src/analyzer/build_unknown_inventory.py`;
  `batch_coverage_report.py --classify-unknown`. Tests: `tests/test_unknown_classifier.py`
  (35, fixtures, no network).
