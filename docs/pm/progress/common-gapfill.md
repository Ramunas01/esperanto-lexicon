# Progress — common-lexicon gap-fill (initiative: common-gapfill)

**This file is the session-restore record.** If a session is lost, read this
top-to-bottom plus the linked brief to resume exactly where we stopped.

- **Brief:** [`docs/pm/briefs/common-gapfill.md`](../briefs/common-gapfill.md)
- **Branch:** `analysis/common-gapfill` (stacked on PR #5 `analysis/tinystories-coverage`)
- **Status:** ⏸ **Phase 1–2 COMPLETE — STOPPED at the human review gate.**
  No DB writes performed. Awaiting Ramunas's review of the worksheet.
- **Last updated after:** building the authoring worksheet (Phase 2).

---

## Where we are

| Phase | State |
|---|---|
| 1 — consolidate the queue | ✅ done (no DB writes) |
| 2 — propose EO anchors → worksheet | ✅ done (no DB writes) |
| **HUMAN REVIEW GATE (Ramunas)** | ⏳ **pending — we are here** |
| 3 — apply approved changes (gated inserts) | ⛔ not started (needs approved worksheet) |
| 4 — re-measure customs corpus | ⛔ not started (after Phase 3) |

## What was produced (Phase 1–2)

Code (committed on the branch, with tests):
- `src/analyzer/fetch_tinystories.py` — (from PR #5) clean corpus fetch.
- `src/lexicon/build_gapfill_worksheet.py` — Phase 1–2 builder. Pure functions
  unit-tested in `tests/test_build_gapfill_worksheet.py` (19 tests). No DB writes.
- Fetched `data/lexicon_db/espdic.txt` (full ESPDIC, CC-BY-3.0, **gitignored** —
  regenerate: it's downloaded from the ESPDIC mirror; see build_eo_inventory.py URL).

Deliverables (`data/analysis/gapfill/`, `.tsv` committed):
- `consolidated_gap_lemmas.tsv` — lemma, total_freq, origin, has_anchor.
- `authoring_worksheet.tsv` — the review worksheet (12 columns per the brief).
- `british_spellings.tsv` — 12 UK→US variants for the Phase-3b spelling map.

## Headline numbers

- **2,372 consolidated gap lemmas** (from 2,960 `common_gap` surface types +
  256 common words **reclaimed** from the `proper_noun` bucket, − 12 British
  spellings split off).
- Worksheet actions: **NEW 1,535 · LINK 355 · no_match 482.**
- Flags: `ok` 1,797 · `no_match` 482 · `compound` 93.
- ESPDIC anchor recall ≈ 80% of lemmas.

## Corrections to the brief (found during implementation)

1. **`audit_root_consistency.py` does not exist.** Use
   `src/lexicon/eo_root_decomposer.py` as the Phase-3 post-write validator
   (it reports resolution % / truncations). The brief's named script was never
   committed.
2. **LINK is the minority, not the majority.** The brief assumed most fixes are
   LINKs, but `lexicon_v2.db` has only **2,782 concepts** (sparse), so **NEW
   1,535 > LINK 355**. Both are insert-only; Phase 3 just does more `concept`
   authoring than expected.
3. **Reverse EN→EO anchoring is inherently ambiguous** — this is why it's a
   review gate, not an auto-apply. Known limits baked into the tool:
   - Anchor stem = `strip_flexion(headword)` (e.g. `brakum`), *not* the
     over-reduced bare root (`brak` = "arm"). Selection is by sense-quality
     (non-compound, shortest), with **no** link-bias (link-bias made `hop`
     resolve to `danc` "dance").
   - **Polysemy still slips through**: e.g. `bug`→`mis` (software fault) when
     the child sense is insect (`insekto` is in `alt_candidates`); `nod`→
     `balanc`. The reviewer must sense-check using the `eo_gloss` and
     `alt_candidates` columns.
   - ESPDIC **proper-name** headwords (`Benedikto:Ben`) are dropped, so English
     names no longer anchor to garbage. Residual name-or-word items
     (`lily`, `jack`) are marked `reclaimed from proper_noun — confirm not a
     name` in `notes`.

## How Ramunas reviews the worksheet (Phase 2 → Phase 3 input)

Per row in `authoring_worksheet.tsv`, mark **approved / hold / reject** and edit
freely. Focus points:
- **`flag=no_match` (482)** — no single-word EO anchor found (multi-word EO or
  none). Needs a manual EO headword, or reject (many are names / interjections).
- **`notes` mentions "confirm not a name"** — reclaimed from the names bucket;
  decide word vs character name (`lily`, `jack`, `sue`, `daisy` are likely
  names here despite being real words).
- **`flag=compound` (93)** — verify the `component_roots` split before it
  becomes `concept_root` rows.
- **`alt_candidates`** — the sense check. If the chosen `eo_word`/`eo_gloss`
  is the wrong sense, pick from here.
- **`number` Tier-3→Tier-1 demotion** (from PR #5) — rule on it; applied in
  Phase 3c only if approved (the one sanctioned change to an existing entry).

The approved worksheet is the **sole input** to Phase 3.

## To resume

```bash
git checkout analysis/common-gapfill
# Re-run Phase 1–2 (idempotent, no DB writes) if inputs changed:
python3 src/lexicon/build_gapfill_worksheet.py \
  --triaged data/analysis/tinystories_unknown_triaged.tsv \
  --lexicon data/lexicon_db/lexicon_v2.db --espdic data/lexicon_db/espdic.txt \
  --inventory data/lexicon_db/eo_inventory.json --out-dir data/analysis/gapfill
# If espdic.txt is missing (gitignored), refetch from the ESPDIC mirror
# (URL in src/lexicon/build_eo_inventory.py: ESPDIC_URL).
```
**Next action when the approved worksheet returns:** implement Phase 3 (a new
gated writer `src/lexicon/apply_gapfill.py` — back up DB, transaction,
insert-only LINK/NEW, `source='tinystories_gap_v1'`; Phase 3b spelling map;
Phase 3c `number` demotion only if approved; validate with
`eo_root_decomposer.py`). Then Phase 4 re-measure over
`~/projects/esperanto-lexicon-corpus/proficiency_eval/` (strata: control 5 /
novice 7 / expert 17).

## Operating notes (WSL crash lesson)

- Work is run **foreground, sequential** by the PM — no `run_in_background`
  fan-out, no concurrent agents. This initiative is light data (a few MB); it
  does **not** need separate Programmer agents.
- Reserve separate Programmer agents (launched by the human in their own shells,
  one job each) for genuinely heavy/parallel jobs. None in Phases 1–4 here.
