# Programmer brief — Effort A: place the 666 candidate_gaps into T1–T3

Self-contained hand-off for a single Programmer agent. Source PM brief:
`docs/pm/briefs/666-and-lifecycle.md` (Effort A). Branch `analysis/general-gap-fill`
(already created off `main`); **PR, no merge**. This is **Effort A only** — Effort B (the R9
lifecycle scaffold) is a separate branch/brief; do not build it here.

**One-line goal:** place the *clearly-common* subset of the 666 `candidate_gaps` (the missing
**general-adult vocabulary layer** the AWL/academic seed skipped) into T1–T3 via the normal
human-gated gap-fill pipeline. Insert-only, human-reviewed, audited.

## Repo reality (PM-verified 2026-07-13 — use these)
- Input: `data/analysis/root_coverage/candidate_gaps.tsv` (on `main`, from PR #14). Columns:
  `root, gloss_head, gloss_zipf, suggested_tier, inv_tier, prod, gloss`. 666 rows (621 distinct
  words); T3-weighted (T1=1 `damn`, T2=107, T3=558); Latinate-formal cluster.
- **Reuse the gap-fill writer** `src/lexicon/apply_gapfill_merge.py` — `author_concept()` already
  authors a single concept insert-only AND **sets `concept.eo_root` from the decomposition head**
  (the invariant that broke in PR #8 and was fixed — do NOT reintroduce a stale-stem write). Add a
  `source='general_gap_v1'` path modeled on the existing `accepts_clean`/`set_gaps` flows; do NOT
  fork a second divergent writer.
- Re-run the join with `src/analyzer/root_tier_coverage.py` after the merge to confirm placed
  concepts leave `candidate_gap`.
- `wordfreq` importable (PR #12); metric tier-loaders are `coverage_report.load_tier_words`
  (tier IN 1,2) / `load_tier3_words` (tier 3).

## A1 — Consolidate [PROG, NO DB writes]
Turn the 666 raw roots into a *distinct-concept* worksheet:
- **Dedupe by concept:** multiple roots glossing one English word collapse
  (`demokrat`/`demokrati`→democratic; `agrikultur`/`agrokultur`/`agronomi`→agricultural;
  `aŭtorrajt`/`kopirajt`→copyright). Report the distinct-concept count (expected well under 666).
- **Fold derived forms:** many gaps are `-ic/-al` adjectives (`democratic`, `presidential`,
  `naval`) whose **noun** is the anchor — attach as forms of one concept, don't author each
  separately. (This is the residual PR #14 flagged: its normalization was inflectional, not
  derivational — handle the derivational fold here, e.g. recognize the EO `-a` adjective as the
  productive form of a covered/anchor noun root.)
- **Flag by direction (R9 — see `docs/ROADMAP.md`):** tag each surviving concept:
  `common` (everyday → T1–T3), `domain-adjacent` (`colonel`, `naval`, `agriculture` — recognised
  but leans T4 → hold for domain review), `register-marked` (`damn`, `fik`, `gay` — frequent but
  not neutral → hold), `archaic` (→ philology-T4 when Effort B builds it). Use `wordfreq` on the
  gloss as the commonness signal.
- Propose a tier per `common` concept: default **T3-general**; very common (gloss zipf ≥ ~4.5)
  may be T2. Emit `data/analysis/tier3_general/general_gap_worksheet.tsv` with columns mirroring
  the prior worksheets (decision, band/flag, root/anchor, eo_word, tier, gloss, note). **STOP —
  this worksheet is the human gate.**

## A2 — Human review gate [RAMUNAS / ADVISOR] (not you)
Approve/hold/reject, fix anchors, confirm tier — same terse flow as `set_gaps`/`anchor_flags`.
Expect the real review to be the domain-adjacent + register-marked + ambiguous subset, not all
distinct concepts. Resume at A3 on the edited worksheet.

## A3 — Gated merge [PROG] (the only write phase)
Reuse `apply_gapfill_merge.py`: **back up DB + single transaction + insert-only**,
`source='general_gap_v1'`, approved tiers. **Never modify existing rows** (no tier/word/cefr/
source edits). **Mandatory post-write audit** (`eo_root_decomposer.py`): 0 `eo_root == concept_root
head` mismatches, resolution holds, no new dupes — the invariant gate stays on (PR #8 lesson). Then
re-run `root_tier_coverage.py` and confirm the placed concepts have left `candidate_gap`; report
counts by tier + the residual candidate_gap.

## Deliverables
- `data/analysis/tier3_general/general_gap_worksheet.tsv` (A1 output, pre-review).
- The `source='general_gap_v1'` writer path + tests.
- Post-merge: audit report + before/after `candidate_gap` counts by tier.
- `docs/analysis/general_gap_fill.md` — memo: distinct-concept count after dedupe/fold, the
  held subsets (domain-adjacent / register / archaic) parked with reasons for Effort B, the
  placed counts by tier, audit result.

## Scope / constraints
Insert-only; human-gated; backup + transaction + mandatory post-write audit; never delete a root
or edit existing `tier`/`word`/`cefr`/`source`. This is the general-adult layer — NOT names, NOT
the R9 lifecycle scaffold (Effort B). Held/archaic roots are *parked with reasons*, not authored.
Update `docs/pm/progress/general-gap-fill.md` at session start and end.

## Success criteria
The clearly-common subset of the 666 (deduped, derived forms folded) placed into T1–T3, audit
clean (0 invariant mismatches), those concepts gone from `candidate_gap`; the held subset parked
with reasons for Effort B; distinct-concept count and per-tier placements reported honestly.
