# Gap-fill merge — post-merge audit (Phases D + E)

**Date:** 2026-07-06 · **Branch:** `analysis/merge-and-audit` · **Writer:**
`src/lexicon/apply_gapfill_merge.py` (insert-only + the one approved `number` change).
**Backup:** `data/lexicon_db/lexicon_v2.db.bak-20260706-003928` (retained).

## What was merged (Phase D)

| | count |
|---|--:|
| Plan rows (reconciled) | 2,193 |
| **Authored (new concepts)** | **2,192** |
| — from `tinystories_gap_v1` | 2,113 |
| — from `set_completeness_v1` | 79 |
| Skipped (already resolved — idempotent) | 1 |
| Tier split of new concepts | 201 T1 / 1,991 T2 |
| `number` | tier 3→1, anchored `nombr`/`nombro`, cefr left C1 |

Row deltas: `concept` 2,782 → 4,974 (+2,192); `concept_lang` 4,786 → 6,978 (+2,192);
`concept_root` 2,634 → 5,072 (+2,438, compounds add component rows).

Reconciliation applied: dropped `beachs` (tail triage); set-gaps authoritative for the 56
words shared with the accepts (seed tier wins); 8 sense-split lemmas
(`trunk`/`spoil`/`beam`/`flap`/`tuck`/`scoop`/`palm`/`perch`) each authored as their own
concept; glosses re-derived from `final_eo_word`; `concept.eo_root` set from the
decomposition **head root** to preserve the lexicon invariant.

## Integrity (Phase E1) — PASS

| check | result |
|---|---|
| `eo_root` == `concept_root` head root | **0 / 4,713 mismatches** (invariant preserved) |
| `eo_root_decomposer` dry-run — `eo_root` changed | **0** (writer agrees with the decomposer) |
| Resolution | 15 unresolved / 4,974 ≈ **99.7%** (1 artifact, 14 unknown — same character as before) |
| Orphan `concept_lang` (bad FK) | 0 |
| NULL/empty `concept_lang.word` | 0 |
| New duplicate concepts introduced | **0** (693 `(en word+eo_word)` duplicates are **pre-existing** in the base lexicon — identical pre/post; e.g. `about`/`pri` doubled at concept 5 `oxford_3000` — a base data-quality item, out of scope) |

## Coverage re-probe (Phase E2) — the payoff

TinyStories (356,465 tokens), no domain DBs, before vs after the merge:

| metric | before | after |
|---|--:|--:|
| **UNKNOWN** | 19.49% | **8.33%** |
| T1 + T2 coverage | 80.48% | **91.66%** |

**UNKNOWN fell 11.2 points — 57% fewer.** The remaining 8.33% is dominated by character
names (the not-yet-designed named-entity layer), i.e. below the original common-gap share —
the common-vocabulary hole this project set out to close is now largely closed.

## Notes / out of scope
- 693 pre-existing duplicate concepts in the base lexicon (e.g. `about`/`pri`) were **not**
  touched (insert-only discipline; existing rows are never modified). Worth a separate
  dedup pass someday.
- `number` keeps `cefr_level=C1` by Ramunas's ruling (from a source); only the internal
  tier was demoted.
