# Progress — merge gap-fill into lexicon, with audit (initiative: merge-and-audit)

**Session-restore record + Ramunas's Phase-C review guide.**

- **Brief:** [`../briefs/merge-and-audit.md`](../briefs/merge-and-audit.md)
- **Branch:** `analysis/merge-and-audit` (stacked on PR #7 `analysis/review-harness`)
- **Status:** ✅ **Phase C COMPLETE (2026-07-06). ⏳ Ready for Phase D (gated write) on Ramunas's go.**
- **Depends on:** the reviewed inventory (`gapfill_review.reviewed.xlsx`, local/gitignored)
  and `docs/systematic_sets_seed.tsv` (Advisor tier authority).

## What was produced (`data/analysis/gapfill/`, all TSV, no DB writes)

| File | Rows | What it is |
|---|--:|---|
| `accepts_clean.tsv` | 2,170 | clean accepts (dropped 1 blank-root); ESPDIC-re-derived glosses; `proposed_tier` + `review_flag` |
| `anchor_flags.tsv` | 150 | accepts whose `final_eo_word` isn't in ESPDIC — **all `curated`** hand-coined compounds to verify |
| `tier_triage.tsv` | 1,152 | the freq<5 tail, all default **Tier 2**; 196 `rare-anchor` flagged for close review |
| `set_gaps.tsv` | 371 | systematic-set members vs lexicon; **80 missing** with proposed anchor + seed tier |
| `names_straddle_note.txt` | 16 | planets/continents — **not authored**, routed to the names layer |

### QA-risk status (from the brief)
- **Risk #2 gloss integrity — largely fixed:** 2,020/2,170 glosses re-derived from
  `final_eo_word` via ESPDIC (fixes the `bug`→`insekt`/gloss-says-`mis` desync). The 150
  that couldn't re-derive == the `curated`-coinage `anchor_flags`.
- **Risk #1 tier pollution — contained:** tiering priority = **Advisor seed** (authoritative
  for set members; cardinals→T1, tens/ordinals→T2, per-set tiers) → frequency (freq≥20 T1,
  else T2) → freq<5 tail **defaults to Tier 2, never blanket Tier 1**. The `rare-anchor`
  flag surfaces likely adult-drift/junk (`inevitably`, `beachs`) mixed with fine compounds.
- **Risk #3 insert-only / names-straddle:** the 1 defective row dropped; 16 names-straddle
  excluded. No existing rows touched.

## Phase C — what Ramunas does (your long session)

Everything is a TSV you can edit (the `.xlsx` is never touched by the harness). Priorities,
smallest/highest-leverage first:

1. **`anchor_flags.tsv` (150)** — confirm each curated coinage is valid Esperanto
   (`sunkremo`=sunscreen, `mielabelo`=honeybee). Mark bad ones for re-anchor.
2. **`set_gaps.tsv` — the 80 `in_lexicon=N`** — approve the proposed EO anchor + the seed
   tier for each missing set member (fingers, ordinals, wild/sea animals, body detail…).
3. **`tier_triage.tsv` — the 196 `review_flag=rare-anchor`** — the real triage: mark
   `drop` (junk/adult like `beachs`, `inevitably`) vs keep (set `proposed_tier` 1/2). The
   other ~956 default Tier 2 — **spot-check only**.
4. **`number` — RESOLVED (2026-07-05).** Phase D3, concept_id=2694 (en `number`):
   - **tier 3 → 1** (approved demotion; sole sanctioned existing-row change, logged).
   - **`cefr_level` left `C1`** (Ramunas: from a source, don't touch).
   - **Anchor to `nombr`/`nombro`** (approved): fill the NULL `concept.eo_root='nombr'`,
     `eo_word='nombro'`, `eo_pos='NOUN'`, and insert a `concept_root` row (root `nombr`,
     is_head). Round-trips: ESPDIC `nombro` = "amount, number, quantity". Root `nombr`
     already exists on concept 1649 (`numerous`/`multnombra`, ADJ) — shared root is fine
     (like `kapablo`/`kapabla`), **not a duplicate**. Enrichment of NULL fields, not a
     change to existing values.

Hand back the edited TSVs (or a note of the changes) and I run Phase D.

## Phase C results (2026-07-06) — review COMPLETE

Ramunas's triaged files in `data/analysis/gapfill/`:
- `anchor_flags_triaged.tsv` (150) — all **ok** (122 well-formed, 28 attested), 0 corrections.
- `set_gaps_triaged.tsv` (80) — 57 ok + **23 fix** (corrected_eo_word); tiers 43 T1 / 37 T2.
- `tier_triage_rare_triaged.tsv` (196) — 195 keep (T2), **1 drop** (`beachs`).
- Tier-1 rule tightened to **seed + freq≥50** (`T1_FREQ_THRESHOLD=50`) → accepts now
  195 T1 / 1,975 T2 (was 541/1,629). T1-vs-T2 does not affect T4_ratio; this is tier-model
  correctness. Non-rare tail (956) and freq≥5 non-seed accepts accepted as auto-proposed.
- `number`: tier 3→1 + anchor `nombr`/`nombro` (see item 4 above).

### Reconciled Phase-D plan (dry preview; no writes yet)
- Accepts to author: 2,170 − 1 drop (`beachs`) = **2,169**  (Wave 1 freq≥5/curated 1,312;
  Wave 2 freq<5 tail 857). None already resolve in the current lexicon.
- Set-gaps to author: **80** (43 T1 / 37 T2; 23 corrected anchors).
- **Reconciliation rules Phase D must apply (owner: PROG):**
  1. **56 words appear in BOTH the accepts and the set-gaps** (`giraffe`, `duck`, `butterfly`,
     `fox`, `rabbit`, `thumb`, `elbow`, …) — author once; **the Advisor seed tier wins**
     (systematic-set authority), prefer the corrected/curated anchor.
  2. **8 sense-split base lemmas** (`trunk`×3, `spoil`/`beam`/`flap`/`tuck`/`scoop`/`palm`/
     `perch`×2) — author each `lemma#sense` as its **own** concept with its own anchor (the
     `#` contract). Not accidental duplicates.
- `number`: 1 tier UPDATE + anchor enrichment.
- Net new concepts ≈ 2,169 + 80 − 56 (dedup) ≈ **2,193**.

## Phase D–F — after approval (Claude Code)

- **D (the one write phase):** back up `lexicon_v2.db` (timestamped) + single transaction.
  Wave 1 = high-confidence (freq≥5 or curated/human) + approved set-gaps; Wave 2 = the
  tier-triaged tail (dropped rows excluded). Insert-only LINK/NEW; re-derived gloss;
  `source='tinystories_gap_v1'` / `'set_completeness_v1'`; approved tiers. `number` demotion
  only if approved (sole existing-row change, logged).
- **E:** integrity via `eo_root_decomposer.py` (NB: brief's `audit_root_consistency.py`
  does **not** exist) → 0 truncations/mismatches, resolution ≈99.7%; TinyStories re-probe
  UNKNOWN% vs prior 19.5%; write `merge_audit.md`.
- **F:** re-run the 29-text customs corpus before/after → `loop_closure_report.md` (T4_ratio,
  UNKNOWN%, expert/novice separation; a null result is a valid finding).

## To resume / regenerate

```bash
git checkout analysis/merge-and-audit
python3 src/analyzer/gapfill_prep.py        # idempotent, no DB writes; rebuilds all 5 outputs
```
Inputs: `gapfill_review.reviewed.xlsx` (local, gitignored), `docs/systematic_sets_seed.tsv`,
`espdic.txt`, `eo_inventory.json`, `lexicon_v2.db` (read-only). 9 tests in
`tests/test_gapfill_prep.py`.

## Decisions on record
- Tier-triage approach: **auto-propose + review flags** (Ramunas, this session).
- Tier authority: **the Advisor seed** (`systematic_sets_seed.tsv`).
- `number` demotion: **APPROVED (2026-07-05)** — tier 3→1 for concept_lang concept_id=2694,
  applied in Phase D3 (backed-up transaction, logged). cefr/anchor sub-questions still open.

## Operating notes
- All prep is foreground, single script, no DB writes. Phase D is the only write phase and
  is fully human-gated with a pre-write backup.
