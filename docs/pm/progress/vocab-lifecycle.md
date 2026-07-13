# Progress — Effort B: vocabulary-lifecycle scaffold (initiative: vocab-lifecycle)

**Session-restore record.** Programmer: update this at start and end.

- **Advisor/PM brief:** [`../briefs/666-and-lifecycle.md`](../briefs/666-and-lifecycle.md) (Effort B); model = **R9** in `docs/ROADMAP.md`.
- **Programmer brief (execute this):** [`../programmer/vocab-lifecycle.md`](../programmer/vocab-lifecycle.md)
- **Branch:** `design/vocab-lifecycle` (off `main`, not stacked). Sibling: `analysis/general-gap-fill` (Effort A).
- **Status:** 🟡 **SET UP — briefs filed, awaiting Programmer dispatch.**

## The job
Design + scaffold the two R9 lifecycle homes and a validated sorting rule, **without dropping any
root from inventory**. Design/scaffold + the no-loss test — **NOT the full 22,653-root sort**.

## The R9 rule (scoring treatment is the crux)
- `unplaced` (rising/new) = staging status, **EXCLUDED from scoring** (mustn't count as specialist yet).
- T1–T3 (common) = where the placed general-adult layer lives (Effort A).
- philology-T4 (fading/archaic) = a real T4 specialist domain, **COUNTED as expertise**.
- `unplaced` and philology-T4 **never merge** — opposite scoring (the `ampermetro` trap).

## PM-verified repo reality (2026-07-13)
- `concept.eo_status` is complete/pending — NOT a lifecycle field; don't overload it.
- Metric reads tiers via `coverage_report.load_tier_words` (tier IN 1,2) / `load_tier3_words`
  (tier 3); T4 from `data/domain_db/*.db`. The `unplaced` exclusion wires here (additive flag).
- No-loss reconciles to inventory=26,447 (covered-T1–3 = 2,652; obscure = 22,653 per PR #14).

## Phase gate
B1 schema (unplaced status wired to EXCLUDE from metric; philology-T4 domain COUNTED) — minimal
DDL, human-reviewed before applied → B2 sorting-rule memo + ~200-root labelled sample (do NOT run
the 22k sort) → B3 no-loss invariant test (every root in exactly one state; counts reconcile to
26,447; relabel-only, never delete).

## Out of scope
The full 22k sort; authoring lexicon content; Effort A (placing the 666). Status-relabel-only,
reversible, provenance-stamped; human-review the DDL before applying.

## Log
- 2026-07-13 (PM): PR #14 merged; ROADMAP.md (R9) tracked on main; branch + briefs set up.
  Verified the metric wiring point (tier-loaders), that `eo_status` must not be overloaded, and
  the inventory reconciliation numbers (26,447 / 2,652 / 22,653). Awaiting Programmer.
- 2026-07-13 (Programmer, session start): picked up Effort B. **Branch hazard:** an external
  `git reset --hard origin/analysis/general-gap-fill` had repointed local `design/vocab-lifecycle`
  to Effort A's commit (2f21317); realigned via `git checkout -B design/vocab-lifecycle
  origin/design/vocab-lifecycle` (4c61a53) — tracked tree was clean, no work lost.
  Verified repo reality: `root_tier_coverage.tsv` buckets reconcile EXACTLY to 26,447
  (covered_T1_3 2,648 + obscure_root 22,653 + candidate_gap 666 + shade_mismatch 480). Metric:
  common = `concept_lang.tier IN (1,2)` / `=3`; specialist = `mwe_lang.phrase_normalized` over
  `data/domain_db/*.db`. Signal probe: the 5 `inv_tier=modern` roots are all ALREADY covered
  (dvd/kd/stres…); explicit archaic markers in obscure glosses sparse (~23); obscure gloss_zipf
  ≈10.9k at z=0 vs ≈5.5k at z≥3. **Design:** `unplaced` = additive `concept_lifecycle` table
  (not a concept column, not overloading eo_status) + guarded anti-join in tier-loaders (no-op
  while empty); philology-T4 = scaffolded `data/domain_db/philology.db` via existing
  `create_domain_schema` (counted by existing T4 loader). Sorting rule routes CONSERVATIVELY.
  DDL + migration written but NOT applied to real DBs (human-review gate).
- 2026-07-13 (Programmer, session end): 🟢 **DELIVERED — design + scaffold complete, PR opened, no
  merge.** All deliverables landed:
  - `schema.py:create_lifecycle_schema` — `concept_lifecycle` (unplaced status; CHECK-guarded).
  - `migrate_vocab_lifecycle.py` — idempotent, additive; `--dry-run` proven to touch nothing;
    applied to a **copy** of the real lexicon (concept rows untouched @5,101; 2nd run = no-op);
    scaffolds `philology.db` with full domain shape. **NOT applied to the real DBs** (review gate).
  - `coverage_report.py:_unplaced_exclusion` — additive anti-join in `load_tier_words`/
    `load_tier3_words`; strict no-op on pre-migration DBs and while empty (existing analyses do
    not shift; proven by tests).
  - `vocab_lifecycle.py` — no-loss partition (`partition_roots`/`reconcile`/`check_disjointness`)
    + conservative routing rule.
  - `obscure_route_sample.tsv` — 200 roots (14 philology_t4 / 21 unplaced / 165 unclassified),
    reproducible via `build_obscure_route_sample.py`.
  - `tests/test_vocab_lifecycle.py` — 17 tests: no-loss (total, reconcile-to-26,447 on real data,
    relabel-only conservation, precedence, disjointness/ampermetro), metric-exclusion (both sides
    + pre-migration no-op), routing (incl. `app`/`apple` regression). **Full suite: 939 passed,
    9 skipped, 0 regressions.**
  - Routing bug found+fixed: substring `app` false-matched approach/apple/appeal → word-boundary
    matching. Open question for Advisor: productive-affix false positives (e.g. `pra-` "ancient"
    routed philology but is a live prefix) — routing is a PROPOSER; human confirms before any real
    assignment. **Deferred as scoped:** the full 22,653-root sort.
