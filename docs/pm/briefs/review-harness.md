# PM brief — set up an interactive review dialogue for the gap-fill worksheet

*Advisor brief as received. Implementation status and deviations are tracked in
[`../progress/review-harness.md`](../progress/review-harness.md).*

Goal: turn the slow manual review of `data/analysis/gapfill/gapfill_review.xlsx` into a
spoken dialogue between Ramunas and a Claude Code "review agent." The agent does the
mechanical work (pull corpus usage, round-trip the Esperanto anchor, look up
alternatives, recommend) so Ramunas only makes the call. Ramunas has done ~300 rows
already; resume from there. **The human stays the gate.** This task writes NOTHING to the
lexicon — its output is an approved-decisions file that the existing Phase-3 gated writer
(from the common-gapfill brief) consumes.

Your job: build the small harness (Parts A, C, D), then hand Ramunas the operating
protocol (Part B) to run the live session with a review agent. Open a PR for the scripts;
the review session itself is interactive and not a PR artifact.

## Hard concurrency rule
Ramunas keeps the `.xlsx` OPEN in Excel on a second screen for viewing. Excel locks it.
**The agent must never read or write the live `.xlsx`.** At setup, export a snapshot
`worksheet_export.tsv` (all columns incl. existing decisions). The agent reads the
snapshot and writes decisions to a sidecar TSV. A merge script produces a *separate*
viewable copy on request. Never write `gapfill_review.xlsx` itself.

## Part A — the review harness (three scripts, `src/analyzer/review/`)

**`review_context.py <en_lemma>`** — the one call that assembles everything for a row:
- From `worksheet_export.tsv`: `total_freq`, `flag`, `priority`, `eo_gloss` (D),
  `eo_root`/`eo_word` (K/L), `alt_candidates`, existing note.
- **Corpus usage:** `grep -iw` the lemma across
  `~/projects/esperanto-lexicon-corpus/tinystories/stories/chunk*.txt`; dedupe; select up
  to ~6 sense-diverse example sentences (prefer sentences that differ lexically around the
  target word, to surface polysemy). Show the match count.
- **Anchor round-trip (replaces Google Translate):** look up `eo_word` in ESPDIC →
  its English gloss(es); print whether that gloss matches the corpus sense. Also print the
  `alt_candidates` with their ESPDIC glosses so a better sense can be picked.
- **Name signal:** report caps-majority and whether the token also appears lowercased as a
  common noun in the sentences (a word used as BOTH a name and a common noun → flag).
- **Recommendation:** one line — `ACCEPT` (valid root + round-trip matches + single sense),
  `REJECT(name)`, or `ASK(reason)` (polysemy / gloss-mismatch / no_match / borderline),
  with a one-sentence reason.
Be verbose here — Ramunas wants to see the evidence; token cost is not a concern.

**`review_record.py <en_lemma> <decision> [--note ...] [--eo-root R --eo-word W] [--source human|auto] [--reason ...]`**
- Appends to `data/analysis/gapfill/review_decisions.tsv`
  (`en_lemma, decision, note, eo_root_override, eo_word_override, source, reason, ts`).
- Idempotent: last write per lemma wins. `decision ∈ {accept, reject, hold, postpone}`.
- `eo_root_override`/`eo_word_override` carry a corrected anchor (Ramunas never edits K/L
  by hand; the agent proposes, he confirms, it lands here for the Phase-3 writer).

**`review_merge.py`** — folds `review_decisions.tsv` into a *new* copy
`gapfill_review.reviewed.xlsx` (col I = decision, col J = note, a `corrected_anchor`
column for overrides). For viewing only; never overwrites the open original.

## Part B — the operating protocol (hand this to Ramunas for the live session)

See [`../review-session-protocol.md`](../review-session-protocol.md) — built from the
seven-point standing policy: order & resume P1→P5 freq-desc skipping decided rows;
opt-in auto-policy for clear ACCEPT/REJECT(name) recorded `--source auto`; spot-check
every ~25 autos; compact ASK questions; terse reply grammar (`1`/`0`/`h`/`k n`/free
text/`auto N`/`show autos`); in-loop anchor correction via overrides; name-ambiguous
high-freq words always ASK; record via `review_record.py`, never touch lexicon or the
open xlsx.

## Part C — semantic-set completeness audit (`set_completeness.py` → `set_gaps.tsv`)

Closed sets must be checked as *wholes*, not just the members TinyStories used. For a
curated set of closed categories — family/kinship, body parts (incl. all five fingers),
colours, numbers 1–20 + tens, days, months, weather, common animals, basic motion verbs,
basic emotions — enumerate the canonical English members, check presence in
`concept_lang(en)` at Tier 1/2, and emit `data/analysis/gapfill/set_gaps.tsv` (`set,
member, in_lexicon(Y/N), proposed_eo_anchor, eo_gloss`). The review agent cross-references
this during the session ("siblings X, Y of this set are also missing — add them too?").

## Part D — reconcile existing work + wiring
- Import Ramunas's ~300 existing decisions from the live xlsx's column I (`1`=accept,
  `0`=reject) into `review_decisions.tsv` with `source=human`, so the agent skips them.
  (One-time read of the file while Excel is closed, or from the snapshot he exports.)
- The **approved set** for Phase-3 is `review_decisions.tsv` filtered to `decision=accept`
  (with any anchor overrides); `hold` rows are the follow-up queue; `reject`/`postpone`
  are dropped. Same gated, insert-only writer, same `source='tinystories_gap_v1'`.

## Files
**Read:** `worksheet_export.tsv` (snapshot), TinyStories chunks, ESPDIC, `lexicon_v2.db`
(read-only), `eo_inventory.json`. **Write:** the four scripts; `review_decisions.tsv`;
`set_gaps.tsv`; `gapfill_review.reviewed.xlsx` (copy). Branch `analysis/review-harness`.

## Constraints
No writes to `lexicon_v2.db` or the open `.xlsx`. Human is the gate; auto-decisions are a
logged, spot-checked delegation, revocable per band. The agent proposes Esperanto anchors
but Ramunas confirms. Every decision traceable (`source`, `reason`, `ts`).

## Success criteria
Per-row human effort drops to a terse reply on `ASK` rows only; the obvious majority is
auto-handled and spot-checked; `set_gaps.tsv` surfaces missing set members; the approved
`review_decisions.tsv` flows straight into the existing Phase-3 writer with no re-keying.
