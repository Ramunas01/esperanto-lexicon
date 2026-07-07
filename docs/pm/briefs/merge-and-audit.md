# PM brief — merge the gap-fill inventory into the lexicon (with audit)

Objective: take the reviewed TinyStories gap inventory and the systematic-set gaps all the
way to a **fully merged, audited lexicon DB**, then close the loop by re-measuring customs.
Owners are tagged **[PROG]** (Claude Code), **[RAMUNAS]** (human reviewer/approver), **[PM]**
(you: orchestrate, produce Claude Code prompts, keep the progress log).

**The gate is absolute:** no row reaches `lexicon_v2.db` without Ramunas's approval. Writes
are insert-only; the one sanctioned change to an existing row (the `number` tier demotion)
is applied only on his explicit ruling. Back up the DB and use a transaction for the write
phase. Follow the session-restore convention (`docs/pm/progress/`).

## Inputs (verify exact paths/filenames in the repo)
- `data/analysis/gapfill/gapfill_review.reviewed.xlsx` — the reviewed inventory (sheet
  `reviewed`; cols: `review_priority, batch, decision, band, en_lemma, base_word,
  total_freq, final_eo_root, final_eo_word, anchor_source, eo_gloss, note, source, reason`).
  2,389 rows: **accept 2,171 / reject 218**.
- `data/analysis/gapfill/gapfill_review.xlsx` — the pre-review workbook (reference).
- `data/analysis/gapfill/systematic_sets_seed.tsv` — 39 closed/semi-open/names-straddle sets,
  387 members with proposed tiers (place it here if not already).
- `docs/coverage_report_examples.md` — coverage-metric reference (T4_ratio definition, the
  0.018 control floor).
- ESPDIC, `eo_inventory.json`, `lexicon_v2.db` (read-only until the write phase).

## Three risks to carry (from the QA of the reviewed file)
1. **Tier pollution (the #1 risk).** 1,152 accepts are freq<5; TinyStories' generator drifts
   into adult vocabulary (`courtier`, `lavish`, `obstinate` at freq 1–2). The reviewed file
   has **no tier column** — so tier assignment is happening off-sheet. The tail must be
   tier-triaged, not authored blanket-Tier-1, or it corrupts the very axis the expertise
   metric divides on.
2. **Gloss integrity.** ~295 accepts have a blank `eo_gloss`, and the gloss column has
   desynced from corrected anchors (`bug`→root `insekt` but gloss still reads the rejected
   `mis`/"software bug"). Fix by re-deriving every gloss from `final_eo_word` via ESPDIC.
3. **Insert-only discipline + names-straddle.** Never touch existing `tier`/`word`/
   `cefr_level`/`source`. Do NOT author the names-straddle sets (planets, continents) — route
   them to the future names layer.

---

## Task list

### Phase A — Prep & QA fixes  [PROG] (no DB writes)
- **A1** Load the `reviewed` sheet; confirm the accept/reject split; **drop the 1 accept with
  a blank `final_eo_root`** (defective). Emit the clean accept set.
- **A2 Gloss re-derivation.** For every accept, re-derive `eo_gloss` from `final_eo_word` via
  ESPDIC. Flag any `final_eo_word` **not found in ESPDIC** (suspect anchor) → to [RAMUNAS].
- **A3 Tier proposal + triage worksheet.** Assign a proposed tier by band/frequency
  (`P1_name`,`P2_hot`, high-freq → Tier 1/2). Everything **freq<5** → mark
  `tier-triage-needed`. Emit `data/analysis/gapfill/tier_triage.tsv` (en_lemma, freq,
  final_eo_root, final_eo_word, re-derived gloss, proposed_tier) for Ramunas.
- Output: `accepts_clean.tsv`, `anchor_flags.tsv`, `tier_triage.tsv`.

### Phase B — Systematic-set completeness audit  [PROG] (no DB writes)
- **B1** Run the set-completeness check against **the lexicon DB** (not TinyStories) using
  `systematic_sets_seed.tsv`. For each `closed`/`semi-open` member, test presence in
  `concept_lang(en)`; for the missing, propose an EO anchor via ESPDIC and carry the seed's
  proposed tier. Emit `data/analysis/gapfill/set_gaps.tsv`.
- **B2** Exclude the `names-straddle` rows (planets, continents) from authoring; list them
  separately as a note for the names layer.
- Output: `set_gaps.tsv` (higher-confidence than the frequency tail) + names-straddle note.

### Phase C — Human review gate  [RAMUNAS]
- **C1** Tier-triage `tier_triage.tsv`: mark each tail row **Tier 1 / Tier 2 / drop** (drop =
  too advanced for the child lexicon).
- **C2** Approve `set_gaps.tsv` (confirm anchors + tiers for the systematic gaps).
- **C3** Resolve `anchor_flags.tsv` (ESPDIC-missing anchors) and any gloss corrections.
- **C4** Rule on the **`number` Tier-3→Tier-1 demotion**.
- Output: approved Wave-1 set, approved Wave-2 (tail) set, approved set-gaps, `number` ruling.

### Phase D — Gated merge  [PROG] (the one write phase)
- **D0** Back up `lexicon_v2.db` (timestamped); open a single transaction.
- **D1 Wave 1** — insert the high-confidence set: accepts with **freq≥5** OR `source=human`/
  `anchor_source=curated`, **plus** the approved `set_gaps`. For each: **LINK** (concept
  exists → add one `concept_lang` en row) or **NEW** (create `concept` + `concept_lang` +
  `concept_root`). Re-derived gloss; `source='tinystories_gap_v1'` (or `'set_completeness_v1'`);
  human-approved tier. Insert-only; skip if the en word already resolves.
- **D2 Wave 2** — insert the tier-triaged tail (Ramunas's Tier 1/2; dropped rows excluded).
- **D3** Apply the `number` demotion **only if approved** — a separate, clearly-logged
  single-row `tier` update (the sole sanctioned exception).
- Never modify any other existing row. Report inserted/linked counts by wave/source/tier.

### Phase E — Post-merge audit  [PROG]
- **E1 Integrity.** Run the consistency validator (`eo_root_decomposer.py` /
  `audit_root_consistency.py` — verify the actual tool name in the repo) → assert **0
  truncations, 0 mismatches**, resolution stays ≈99.7%, no duplicate concepts.
- **E2 Coverage re-probe.** Re-run `batch_coverage_report.py` on the TinyStories sample →
  confirm the `common_gap`/UNKNOWN rate dropped; report the new number vs the prior 19.5%.
- **E3** Emit `data/analysis/gapfill/merge_audit.md` (counts, integrity result, coverage
  before/after). → [RAMUNAS] sign-off.

### Phase F — Loop closure  [PROG] + [RAMUNAS]  (the validation payoff)
- **F1** Re-run the 29-text customs corpus before/after the merge; report per-stratum
  `T4_ratio`, `UNKNOWN%`, and expert/novice separation.
- **F2** `data/analysis/gapfill/loop_closure_report.md` — plainly state whether a cleaner
  denominator sharpened the metric. A null result is a valid finding. May inform `CLAUDE.md`/
  roadmap **only** with Ramunas's approval.

---

## Definition of done
The approved Wave-1 + Wave-2 + set-completeness gaps are merged insert-only into
`lexicon_v2.db` with re-derived glosses and human-approved tiers; the post-merge audit shows
0 truncations / 0 mismatches and resolution ≈99.7%; the TinyStories re-probe shows a reduced
UNKNOWN/common-gap rate; and the customs loop-closure report is filed for review. Names-
straddle sets are recorded for the names layer, not authored. All writes traceable by
`source` tag; the pre-merge DB backup is retained.

## Constraints
Insert-only except the approved `number` demotion; never change existing
`tier`/`word`/`cefr_level`/`source`; human-gated; concurrency-safe (don't write any file
Ramunas has open in Excel — work from snapshots); PRs with tests, no merge without review.
