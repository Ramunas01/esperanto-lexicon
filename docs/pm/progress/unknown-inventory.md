# Progress — cross-corpus UNKNOWN inventory + D1 accounting (initiative: unknown-inventory)

**Session-restore record.** Programmer: update this at start and end.

- **Advisor/PM brief:** [`../briefs/unknown-inventory.md`](../briefs/unknown-inventory.md)
- **Programmer brief (execute this):** [`../programmer/unknown-inventory.md`](../programmer/unknown-inventory.md)
- **Branch:** `analysis/unknown-inventory` (off `main`; not stacked).
- **Status:** 🔧 **IN PROGRESS (Programmer, 2026-07-11) — read-only diagnostic; PR, no merge.**

## The job
Turn UNKNOWN from a scalar into a **classified cross-corpus taxonomy** and isolate the
**true residual** (non-junk, non-name, non-domain, non-inflection tokens UNKNOWN across ≥2
corpora). **Read-only diagnostic + accounting — NO lexicon writes.** Deliverables = review
files (classified pool, true residual, name candidates) + reusable `unknown_classifier.py` +
memo with the **true residual UNKNOWN %**.

## PM-verified repo reality (2026-07-11)
- **`wordfreq` NOT installed; pip PEP 668-blocked** (Py 3.14, no venv). The zipf junk gate is
  mandatory → resolve first (install / `! pip install --user wordfreq` by Ramunas / documented
  fallback + loud flag). spaCy `en_core_web_sm` present.
- UNKNOWN pools from `batch_coverage_report.py` `write_unknown_pool()`, format `count\ttoken`.
  Keep pools **per-corpus** (universality = # corpora a token is UNKNOWN in). Corpora:
  TinyStories (`data/analysis/tinystories_run/…`, ~3,819 tokens), customs domain + general
  controls in `../esperanto-lexicon-corpus/proficiency_eval/` (control 5 / novice 7 / expert 17,
  + corpus-1..7 domain-area texts).
- Name store: `src.lexicon.query_named_entities.resolve` (272 entities, on `main`). Lemma/surface
  resolution: `src/analyzer/coverage_report.py` (`classify_tokens`/`load_inflected_forms`).

## Classifier order (first match wins)
junk → named_entity → inflection_miss → domain_term → common_gap → **true_residual**.
D1 coupling: suppress named_entity+junk from the gap tally → report **true residual UNKNOWN %**
= raw − names − junk − known-gaps; add optional `--classify-unknown` to batch_coverage_report
(never change its default output).

## Out of scope
No lexicon/tier writes, no full names layer, no tier-derivation (R8 future). Author nothing —
name candidates are emitted for future curation, not written to the store.

## Log
- 2026-07-11 (PM): PR #11 (Tier-3 AWL) merged to `main`; branch + briefs set up; assumptions
  verified (pool source + format, name store + resolve API, corpora present; **wordfreq missing
  + PEP-668 blocked — flagged as the one dependency to resolve at dispatch**). Awaiting Programmer.
- 2026-07-11 (Programmer, start): **wordfreq RESOLVED** — installed 3.1.1 via
  `pip install --user --break-system-packages wordfreq` (the brief's permitted route; no fallback
  needed). Corpora confirmed: tinystories/stories (100), proficiency_eval/{control 5, novice 7,
  expert 17}. The `corpus-1..7` domain dirs in the brief don't exist; using the strata as corpora
  (child / general-control / customs-novice / customs-expert) — 4 diverse corpora for universality.
  Plan: regenerate per-corpus UNKNOWN pools with the CURRENT (post-AWL) lexicon, common-lexicon
  only (no domain DBs, so domain terms surface as UNKNOWN → `domain_term` bucket via concentration);
  capture PROPN/casing/lemma features during a spaCy pass for the name gate. Building
  `unknown_classifier.py` (pure `classify_token` + tests) + a driver.
- 2026-07-11 (Programmer, end): **COMPLETE — PR open, not merged.** Deliverables in
  `data/analysis/unknown_inventory/` (pooled_unknown_classified.tsv, true_residual.tsv,
  name_candidates.tsv) + memo `docs/analysis/unknown_inventory.md`. Code:
  `src/analyzer/unknown_classifier.py` (reusable, 35 tests) + `build_unknown_inventory.py` (driver)
  + optional `batch_coverage_report.py --classify-unknown` (default output unchanged). Full suite
  850 passed. **Result:** raw UNKNOWN 9.01% of 378k content tokens → **true-residual UNKNOWN 0.006%
  (2 types / 21 tokens)**. named_entity = 89% of UNKNOWN (the elephant). **Honest shape-read:** the
  non-name tail is a single coherent class — **British spellings** (17 types / 1,097 tokens whose US
  form is already in the lexicon; `mum`→mom, `colourful`→colorful…), scattered into `local` because
  they cluster in the British-authored TinyStories (universality-1). That's the one real leak — cheap
  to close via an extended `uk_to_us` fold. Secondary: `inflection_miss` (945, spaCy lemmatizer gaps),
  `domain_term` (1,360, customs → Tier-4). 936 name candidates emitted for the names layer; **authored
  nothing**. wordfreq gate used (no fallback needed).
