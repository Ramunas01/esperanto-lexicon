# Progress — Tier-3 AWL seed (initiative: tier3-awl-seed)

**Session-restore record.** Programmer: update this at start and end.

- **Advisor/PM brief:** [`../briefs/tier3-awl-seed.md`](../briefs/tier3-awl-seed.md)
- **Programmer brief (execute this):** [`../programmer/tier3-awl-seed.md`](../programmer/tier3-awl-seed.md)
- **Branch:** `analysis/tier3-awl-seed` (off `main`; the #5→#10 stack is now merged, so this
  branches directly from `main`, not stacked).
- **Status:** 🟡 **SET UP — briefs filed, awaiting Programmer dispatch.**

## The job
Grow Tier 3 from **96** EN words to a domain-general formal core by translate-and-merge
**assembly** of the Academic Word List (AWL, Coxhead 2000, ~570 families / ~3,000 forms).
Reuse the gap-fill anchor→review→merge pipeline. No mining, no UNKNOWN loop.

## PM-verified repo reality (2026-07-07)
- Tier 3 today = 96 `concept_lang` rows (EN, `source='tier3_unknown_pool_2026_05_29'`).
- `concept_lang` UNIQUE = `(concept_id, lang, word, pos)` → a concept can hold many EN words
  (precedent: one concept has 11). LOCKED design: **family = 1 concept + N EN rows @ tier=3**,
  not N concepts. Insert-only idempotency comes free from the UNIQUE key.
- Pipeline present: `build_gapfill_worksheet.py`, `gapfill_prep.py`, `apply_gapfill_merge.py`
  (writer), audit = `eo_root_decomposer.py`, `batch_coverage_report.py` (has `t3_anchor_density`).
- **Invariant (must hold):** `concept.eo_root` == `concept_root` head root — set from the
  decomposition head, never a stale stem (this broke the last merge and forced a restore+redo).

## Phase gate
P1 acquire+normalize [PROG] → P2 anchor worksheet `data/analysis/tier3/awl_worksheet.tsv`
[PROG, no DB] → **P3 human review [RAMUNAS] — STOP here** → P4 gated insert-only merge
(`source='awl_t3'`) + audit [PROG] → P5 one-time `batch_coverage_report` validation, honest
null-result reporting, `data/analysis/tier3/t3_validation.md` [PROG + RAMUNAS].

## Out of scope
Names (Wikidata rail / `named_entity` store, not AWL); discovery/UNKNOWN loop; R8 commonness-
derivation machinery. Never modify existing `tier`/`word`/`cefr_level`/`source`.

## Log
- 2026-07-07 (PM): #5→#10 stack merged to `main`; branch + briefs set up; brief assumptions
  verified (T3=96, pipeline present, schema supports family model, `t3_anchor_density` present);
  family→one-concept design locked. Awaiting Programmer dispatch.
