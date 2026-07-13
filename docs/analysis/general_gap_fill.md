# Effort A — place the 666 candidate_gaps into T1–T3 (general-adult layer)

Effort A of the "place-the-666 + lifecycle" plan. Turns the 666 per-root
`candidate_gaps` (PR #14 — the general-adult vocabulary the AWL/academic seed
skipped) into a **distinct-concept, R9-flagged review worksheet**, then stops at the
human gate. **A1 is done and this session STOPS; no DB writes.** The A3 merge path is
built and dry-run-validated, ready to run the moment the reviewed worksheet returns.
(Effort B — the R9 lifecycle scaffold — is a separate branch, not built here.)

## A1 — consolidation (done, no DB writes)
`src/analyzer/consolidate_general_gaps.py` turns 666 rows into
`data/analysis/tier3_general/general_gap_worksheet.tsv`:

- **Dedupe by concept:** 44 English words are glossed by more than one root; they
  collapse (`demokrat`+`demokrati`→democratic; `suĉ`+`mamsuĉ`→suck;
  `agrikultur`+`agrokultur`+`agronomi`→agricultural; `kopirajt`+`aŭtorrajt`→copyright).
  **666 raw rows → 621 distinct concepts.** All collapsed roots are shown for review.
- **Fold derived forms (flagged for the gate):** **168** concepts are `-ic/-al/...`
  adjectives (`democratic`, `presidential`, `naval`, `mechanical`) whose noun is the
  natural anchor. Each is tagged `derived_adj` with a *"confirm noun anchor / eo_word"*
  note. The *derivational* fold (which noun, LINK-vs-NEW) is an irregular,
  case-by-case linguistic call — exactly the PR #14 residual — so it is **surfaced for
  the human**, not auto-merged (auto-deriving `agricultural`→`agriculture` is
  unreliable; `toxic`/`chronic` are standalone adjectives with no noun to fold onto).
- **Flag by R9 direction** (roadmap R9 — *direction of travel*, not raw commonness):

  | flag | n | disposition |
  | --- | ---: | --- |
  | `common` | 597 | everyday general-adult → place into T1–T3 |
  | `domain-adjacent` | 17 | recognised but leans T4 (military ranks, `naval`, `genetic`, `agriculture`) → **hold for domain review** |
  | `register-marked` | 6 | frequent but not neutral (`damn`, `gay`, `bastard`, `homosexual`, `fart`, `prostitute`) → **hold** |
  | `archaic` | 1 | backward-facing (`archaic`) → **philology-T4 when Effort B builds it** |

  Flags are **heuristic proposals** (curated whole-word lists + gloss cues); the human
  confirms. Whole-word matching avoids the substring trap (`suck`→"suckle" stays
  `common`; `prefix` is not flagged for containing "fik").
- **Tier proposal** for the `common` bulk: T2 when gloss zipf ≥ 4.5 (**7** concepts),
  else **T3-general** (**590**). Held rows carry no tier — they are *parked with
  reasons*, not placed.

### Worksheet columns
`decision · flag · fold · en_word · anchor_root · all_roots · eo_word · eo_pos ·
proposed_tier · gloss_zipf · inv_tier · prod · gloss · note`. `decision` is blank for
the reviewer (approve / hold / reject); `common` is the near-auto-approve bulk, so the
real review is the ~24 held + the 168 derived-adjective anchors — not all 621.

## A2 — human review gate [RAMUNAS / ADVISOR] (not this session)
Approve/hold/reject, fix anchors, confirm tier, and decide the derived-adjective folds.
**This is where the session stops.** Resume at A3 on the edited worksheet.

## A3 — gated merge (built + dry-run-validated; runs after review)
`apply_gapfill_merge.py --general-gap-triaged <worksheet>` — a new
`source='general_gap_v1'` path that **reuses `author_concept`** (no forked writer): one
concept per approved row, insert-only, `eo_root` derived from the eo_word decomposition
head (the PR #8 invariant — never a stale stem), backup + single transaction + the
standard `audit_eo_root_invariant`, auto-rollback if the audit regresses. Rows not
marked `approve` are skipped (held). A reviewer-added `tier` column overrides
`proposed_tier`.

**Dry-run validation (5 sample common rows, rolled back — DB untouched):** 5 concepts
authored, tiers {2:1, 3:4}, **audit PASS** (0 `eo_root↔head` mismatches, 0 dupes, 0
collisions), `eo_root` correctly = decomposition head (`karbono`→`karbon`,
`cirkvito`→`cirkvit`). After the real merge, `root_tier_coverage.py` is re-run to
confirm the placed concepts leave `candidate_gap`; counts reported then.

## Held subsets — parked with reasons for Effort B
- **domain-adjacent (17):** `colonel`, `lieutenant`, `admiral`, `artillery`, `cavalry`,
  `infantry`, `regiment`, `naval`, `genetic`, `magnetic`, `atomic`, `anatomical`,
  `imperial`, `parliamentary`, `diplomatic`, `agriculture`, `agricultural`. A general
  adult recognises these, but they lean Tier-4 (military/hard-science/institutional) —
  hold for a domain-vs-common review rather than auto-placing into the general core.
- **register-marked (6):** `damn`, `gay`, `bastard`, `homosexual`, `fart`, `prostitute`.
  Common by frequency but not register-neutral — a placement/register call, not an
  automatic T1–T3 add.
- **archaic (1):** `archaic` — backward-facing; belongs in the Effort-B philology-T4
  archive, not the common band.
No held/archaic root is authored; none leaves the inventory. (R9: movement is a
status/domain assignment, reversible — the sorting is Effort B's job.)

## Honest notes
- The **168 derived adjectives** are the substance of the A2 review: whether each is a
  separate concept (`toxic`→`toksika`) or a fold onto an existing/covered noun
  (`presidential`→`prezidento`) is a per-item judgment. The worksheet proposes an
  adjective eo_word (`root`+`a`) and flags every one for anchor confirmation.
- Anchor auto-selection (core > extended, higher productivity, shorter) is imperfect for
  all-equal groups (`agricultural` picks `agronomi`, semantically "agronomy") — hence
  `all_roots` is shown so the reviewer re-anchors.

## Deliverables
- `data/analysis/tier3_general/general_gap_worksheet.tsv` — the A1 review worksheet (621 rows).
- `src/analyzer/consolidate_general_gaps.py` (+ `tests/test_consolidate_general_gaps.py`, 29 tests).
- `apply_gapfill_merge.py` `--general-gap-triaged` path (+ `tests/test_apply_general_gap.py`, 11 tests).
- This memo. Full suite: **962 passed.**

---

## A3 — gated merge (COMMITTED 2026-07-14)
Reviewed worksheet: `general_gap_triaged.xlsx` (621 rows) → `general_gap_triaged.tsv`.
Decisions: **616 approve · 4 split · 1 hold**. The merge acts on the `decision` column:
`approve` → 1 concept at its reviewed `eo_word`/tier; `split` → **each root in
`all_roots`** authored as its own concept (eo_word = root + POS ending from its
`root_detail` gloss; single root → `eo_root` = decomposition head); `hold` → skipped.
`review_flag` (incl. `R9-park`) is metadata — the **23 R9-park approves were authored**;
only the 1 R9-park `hold` (`agricultural`) was skipped.

Backup + single transaction + insert-only + mandatory post-write invariant audit
(auto-rollback). **Committed:**

| | value |
| --- | --- |
| concepts authored | **624** (616 approve + **8** from 4 splits) |
| by tier | **T2 = 301 · T3 = 323** |
| source | `general_gap_v1` |
| row deltas | concept 5101→5725, concept_lang +624, concept_root +624 |
| **audit** | **PASS** — 0 `eo_root↔head` mismatches (whole DB), 0 dupes, 0 eo_word collisions, 0 degenerate roots |

**Splits → 8 distinct concepts** (one English word, distinct EO roots): `chancellor` →
`kanceliero`/`rektoro`; `acute` → `akuta`/`sagaca` (ADJ); `accessory` →
`anekso`/`kunkulpo`; `erect` → `erekti` (VERB)/`vertikala` (ADJ). (Reviewer correction
applied: the three adjective senses `akut`/`sagac`/`vertikal` use their `-a` form with
`eo_pos=ADJ`.)

### Post-merge coverage re-run (`root_tier_coverage.py`)
The placed concepts left `candidate_gap`:

| bucket | before (PR #14) | after |
| --- | ---: | ---: |
| `covered_T1_3` | 2,648 | **3,272** (+624) |
| **`candidate_gap`** | **666** | **3** |
| `shade_mismatch` | 480 | 451 |

Covered roots by tier now: T1 764 · T2 (any) 2,639 · T3 (any) **770** (was 447). The
**3 residual `candidate_gap`** are exactly the three roots of the one **held** concept —
`agrikultur` / `agrokultur` / `agronomi` (`agricultural`, R9-parked for Effort B) —
correctly not authored. Evidence: `data/analysis/root_coverage/after_general_gap/`.

**Status: A3 COMMITTED, audit clean, candidate_gap 666→3. PR #15 stays open — not merged.**
