# Progress — Effort A: general-adult gap-fill (initiative: general-gap-fill)

**Session-restore record.** Programmer: update this at start and end.

- **Advisor/PM brief:** [`../briefs/666-and-lifecycle.md`](../briefs/666-and-lifecycle.md) (Effort A)
- **Programmer brief (execute this):** [`../programmer/general-gap-fill.md`](../programmer/general-gap-fill.md)
- **Branch:** `analysis/general-gap-fill` (off `main`, not stacked). Sibling: `design/vocab-lifecycle` (Effort B).
- **Status:** 🔧 **IN PROGRESS (Programmer, 2026-07-13) — A1 consolidate + worksheet; STOP at human gate.**

## The job
Place the clearly-common subset of the 666 `candidate_gaps` (PR #14) — the missing **general-adult
vocabulary layer** the AWL/academic seed skipped — into T1–T3 via the human-gated gap-fill pipeline.
Insert-only, reviewed, audited. Hold domain-adjacent/register/archaic for Effort B.

## PM-verified repo reality (2026-07-13)
- Input `data/analysis/root_coverage/candidate_gaps.tsv` (on main): cols `root, gloss_head,
  gloss_zipf, suggested_tier, inv_tier, prod, gloss`; 666 rows (T1=1 `damn` / T2=107 / T3=558).
- **Reuse `apply_gapfill_merge.py:author_concept()`** — insert-only, sets `concept.eo_root` from the
  decomposition head (the PR #8 invariant fix — don't regress). New `source='general_gap_v1'` path.
- Re-run `src/analyzer/root_tier_coverage.py` post-merge to confirm placed concepts leave the gap.
- Metric tier-loaders: `coverage_report.load_tier_words` / `load_tier3_words`.

## Phase gate
A1 consolidate (dedupe-by-concept + fold derived `-ic/-al` adjectives onto the noun anchor + flag
by R9 direction) → worksheet `data/analysis/tier3_general/general_gap_worksheet.tsv` [PROG, no DB]
→ **A2 human review [RAMUNAS/ADVISOR], STOP** → A3 gated insert-only merge (`general_gap_v1`) +
mandatory invariant audit + re-run join [PROG].

## Known nuance (from PR #14 residuals)
Many gaps are **derivational adjectives** (`democratic`, `agricultural`) whose base noun may
already be covered — the fold in A1 must handle *derivational* forms (PR #14's normalization was
only inflectional). And **register-marked** items (`damn`, `gay`) are frequent-not-neutral → hold,
don't auto-place. So the distinct-concept count after dedupe/fold is expected well below 666.

## Out of scope
Names; the R9 lifecycle scaffold (Effort B: `design/vocab-lifecycle`); the ~22,653 obscure sort.
Held/archaic roots are parked with reasons, not authored.

## Log
- 2026-07-13 (PM): PR #14 merged to `main` (candidate_gaps.tsv now on main); branch + briefs set
  up. Verified input columns, the reusable insert-only writer (invariant-safe), and the join
  re-run tool. Awaiting Programmer.
- 2026-07-13 (Programmer): **A1 COMPLETE + A3 writer built & dry-run-validated — STOPPED at the A2
  human gate; no DB writes. PR open, not merged.**
  - `src/analyzer/consolidate_general_gaps.py`: **666 raw rows → 621 distinct concepts** (44 heads
    deduped). R9 flags: common 597 / domain-adjacent 17 / register-marked 6 / archaic 1. common by
    tier: T2=7 / T3=590. 168 derived-adjective concepts flagged for anchor confirmation. Whole-word
    flag matching (avoids the `suck`→suckle / `prefix`→"fik" substring traps). Worksheet:
    `data/analysis/tier3_general/general_gap_worksheet.tsv`. 29 tests.
  - `apply_gapfill_merge.py --general-gap-triaged`: new `source='general_gap_v1'` path reusing
    `author_concept` (eo_root from decomposition head — invariant held) + `audit_eo_root_invariant`
    + backup/txn/auto-rollback. 6 tests. **Dry-run (5 common rows, rolled back): 5 authored, audit
    PASS (0 mismatches/dupes/collisions), DB untouched.**
  - Full suite 957 passed. Memo `docs/analysis/general_gap_fill.md`. Held subsets parked with
    reasons for Effort B. → **[RAMUNAS/ADVISOR] review the worksheet (approve/hold/reject, fix
    anchors incl. the 168 derived adjectives, confirm tiers); then resume A3: run the gated merge,
    audit, re-run `root_tier_coverage.py`, report placed counts + residual candidate_gap.**
