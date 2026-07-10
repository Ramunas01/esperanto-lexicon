# Progress — Tier-3 AWL seed (initiative: tier3-awl-seed)

**Session-restore record.** Programmer: update this at start and end.

- **Advisor/PM brief:** [`../briefs/tier3-awl-seed.md`](../briefs/tier3-awl-seed.md)
- **Programmer brief (execute this):** [`../programmer/tier3-awl-seed.md`](../programmer/tier3-awl-seed.md)
- **Branch:** `analysis/tier3-awl-seed` (off `main`; the #5→#10 stack is now merged, so this
  branches directly from `main`, not stacked).
- **Status:** 🔧 **IN PROGRESS (Programmer, 2026-07-08) — Phases 1–2. STOP after P2 for Ramunas review.**

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
- 2026-07-08 (Programmer): **Phases 1–2 COMPLETE — STOPPED at the human gate.** PR open, no merge.
  - **AWL source** (Coxhead 2000) vendored to `data/awl/awl_coxhead.json` from
    `github.com/lpmi-13/machine_readable_wordlists` (CC0; upstream = Victoria Univ. Wellington),
    retrieved 2026-07-08; provenance `data/awl/SOURCE.md`. **Validated all published invariants
    before use:** 570 families / 10 sublists / SL1=60 / 3,107 forms — all PASS (per Ramunas's
    source-vetting instruction; structure-preserving with sublist carried through).
  - **New code:** `src/lexicon/build_awl_worksheet.py` — reuses gap-fill `parse_espdic` /
    `propose_anchor` / `load_existing_roots` + shared decomposer (no forked anchor pipeline).
    Adds: AWL parser + junk gate, Unicode-hyphen normalisation, morphological POS tagger with
    spaCy fallback (injectable), US-spelling anchor fallback, LINK/NEW+manual classifier,
    worksheet writer. 38 tests (`tests/test_build_awl_worksheet.py`, no network/spaCy/real DB).
    Full suite 796 passed.
  - **Worksheet** `data/analysis/tier3/awl_worksheet.tsv` (570 rows, one per family):
    3,107 forms (2,606 new / 501 already present). **ESPDIC recall 97.5%** (LINK 448 / NEW 111 /
    manual 11; flags ok 550 / compound 6 / no_match 14). Memo: `docs/tier3/awl_seed_memo.md`.
  - **NO DB writes.** Phase 4 (gated merge via `apply_gapfill_merge`, invariant audit) + Phase 5
    (`t3_anchor_density` validation) deferred until the reviewed worksheet returns. → **[RAMUNAS]
    review `awl_worksheet.tsv`: approve/hold/reject per family; fix anchors; then resume at P4.**
- 2026-07-11 (Programmer): **Phase 4 DRY-RUN complete — STOPPED before the gated commit** (PM
  instruction). Reviewed worksheet `awl_worksheet_triaged.tsv` returned (555 approve / 15 fix /
  0 reject) and committed for the audit trail. Extended `apply_gapfill_merge.py` (not forked) with
  the AWL family merge (`--awl-triaged … --dry-run`): family = 1 concept + N EN rows @ tier=3,
  source='awl_t3', insert-only. 19 new tests; full suite 815 passed. **Dry-run preview (nothing
  written):** 569 families (LINK 442 / NEW 127), 127 new concepts, **2,605 T3 EN rows** (Tier-3
  96 → 2,701), 501 skipped-present, 1 deferred (`whereby` = multiword `per kio`). **Special cases
  handled:** `via`→LINK existing `per` concept 2578 (no NEW eo_word='via'); `dynamic`→NEW single
  root `dinamik` (override, not din+amik). Single-letter-root guard also fixed `incidenco` and 6
  fallbacks. **Post-write audit PASS:** 0 eo_root↔head mismatches (new), 0 degenerate new roots
  (17 pre-existing untouched), 0 dupe rows, 0 new eo_word collisions. 8 ambiguous multi-concept
  families flagged for review. → **[RAMUNAS] sign off on the dry-run to run the gated `--commit`;
  then Phase 5 `t3_anchor_density` validation.**
