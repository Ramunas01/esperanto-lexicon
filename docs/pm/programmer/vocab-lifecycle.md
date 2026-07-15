# Programmer brief — Effort B: vocabulary-lifecycle homes + sorting scaffold (R9)

Self-contained hand-off for a single Programmer agent. Source PM brief:
`docs/pm/briefs/666-and-lifecycle.md` (Effort B); governing model: **R9** in `docs/ROADMAP.md`
(read it). Branch `design/vocab-lifecycle` (already created off `main`); **PR, no merge**. This is
**Effort B only** — Effort A (placing the 666) is a separate branch. **Design + scaffold, NOT the
full sort.**

**One-line goal:** stand up the two out-of-band lifecycle homes and a *validated sorting rule*
that can eventually route the ~22,653 `obscure_root` remainder by **direction of travel** —
**without ever dropping a root from the inventory.** Prove the rule + the no-loss guarantee first;
the full 22k run is explicitly deferred.

## The R9 model (get the scoring treatment exactly right)
Sort by *direction of travel*, not raw commonness:
- **`unplaced`** (rising/new: coinages, fresh borrowings) — a **staging status, EXCLUDED from the
  expertise metric** (neither common denominator nor specialist numerator). A rising word must not
  yet count as specialist. Transient; graduates up to T1–T3 or fades to philology.
- **T1–T3** (common) — the general-adult layer (Effort A's 666) lives here once placed.
- **philology / historical-linguistic T4** (fading/archaic) — obsolete/dialectal/scholarly roots;
  a real Tier-4 specialist domain, **COUNTED as expertise** like any T4.
- **`unplaced` and philology-T4 must NEVER merge** — both hold "uncommon" words but get OPPOSITE
  scoring treatment. Collapsing them would either let rising everyday words inflate expertise (the
  `ampermetro` trap) or erase scholarly vocabulary from the signal.

## Repo reality (PM-verified 2026-07-13)
- `concept` has `eo_status` (complete/pending) — NOT a lifecycle field; do not overload it.
- The metric reads tiers via `coverage_report.load_tier_words` (`concept_lang.tier IN (1,2)`) and
  `load_tier3_words` (`tier=3`); T4 comes from the per-domain DBs under `data/domain_db/`.
- Inventory = `eo_inventory.json` `roots` (26,447); covered-T1–3 roots = 2,652; obscure = 22,653
  (per PR #14 `root_tier_coverage.tsv`). These are the numbers the no-loss invariant reconciles to.

## B1 — Schema for the two homes [PROG] (design + minimal DDL, human-reviewed before build)
- **`unplaced` status:** design where it lives (a lifecycle column/table on `concept`, or a
  status value) such that a concept marked `unplaced` is **excluded from scoring**. Wire the metric
  to skip it — **additive flag, do NOT change existing scoring defaults** (existing analyses must
  not shift). Show the exclusion works with a test (an `unplaced` concept counts in neither the
  common nor the specialist side).
- **philology-T4 domain:** a genuine Tier-4 domain DB (same shape as existing `data/domain_db/*.db`
  domains) for obsolete/archaic/dialectal/scholarly roots, **counted as expertise** like any T4.
- Both: **no root leaves the inventory** when it moves into a home; movement is a status/domain
  assignment — reversible, provenance-stamped (R8 derived-not-fixed). Minimal DDL only; human-
  reviewed before any build-out.

## B2 — The sorting design (NOT the full run) [PROG + ADVISOR]
A written method for routing an obscure root by direction of travel: what evidence sends a root to
`unplaced` (recent coinage / rising frequency / new borrowing) vs philology-T4 (attested-historical
/ archaic-marked / absent from modern frequency lists) vs "leave unclassified-inventory for now."
Deliver a **memo + a small labelled sample (~200 obscure roots hand-routed)** to validate the rule.
**Explicitly do NOT run the full 22k sort** — prove the routing rule + the no-loss guarantee first.

## B3 — The no-loss invariant [PROG] (make it a test, not a hope)
Assert + test that **every ESPDIC root is always in exactly one state**: covered-tier / `unplaced`
/ a T4 domain (incl. philology) / unclassified-obscure. Counts must **reconcile to the full
inventory** (26,447) before and after any move; **nothing is ever deleted, only re-labelled**. This
partition test is the whole point of "don't lose inventory."

## Deliverables
- `src/lexicon/schema.py` additions (minimal DDL for `unplaced` + the philology-T4 domain
  registration) + idempotent migration — **human-reviewed before applied**; the metric-exclusion
  wiring (additive flag) in the analyzer.
- `docs/design/vocab_lifecycle.md` — the B1 schema rationale + B2 sorting method + the R9 scoring
  table (unplaced EXCLUDED vs philology-T4 COUNTED).
- `data/analysis/lifecycle/obscure_route_sample.tsv` — the ~200 hand-routed obscure roots.
- The **no-loss invariant test** (B3) + the metric-exclusion test.

## Scope / constraints
Design + scaffold + the invariant test — **do NOT run the full 22k sort**; do NOT author lexicon
content; status-relabel-only, reversible, provenance-stamped; never delete a root; human-review
the DDL before applying. `wordfreq` available for commonness signals. Update
`docs/pm/progress/vocab-lifecycle.md` at session start and end.

## Success criteria
The `unplaced` status and philology-T4 domain exist and are correctly wired into (EXCLUDED from /
COUNTED by) the metric — proven by tests; a validated sorting rule + the ~200-root labelled sample;
and a passing **no-loss invariant test** proving the full inventory count (26,447) is conserved
across every state. The full sort is deferred — this lands the homes, the rule, and the guarantee.
