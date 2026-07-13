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
