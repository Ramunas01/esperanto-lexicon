# Progress — Effort A: general-adult gap-fill (initiative: general-gap-fill)

**Session-restore record.** Programmer: update this at start and end.

- **Advisor/PM brief:** [`../briefs/666-and-lifecycle.md`](../briefs/666-and-lifecycle.md) (Effort A)
- **Programmer brief (execute this):** [`../programmer/general-gap-fill.md`](../programmer/general-gap-fill.md)
- **Branch:** `analysis/general-gap-fill` (off `main`, not stacked). Sibling: `design/vocab-lifecycle` (Effort B).
- **Status:** 🟡 **SET UP — briefs filed, awaiting Programmer dispatch.**

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
