# Gap-fill review session — operating protocol

Hand this to a Claude Code **review agent** at the start of a live review session.
It turns the 2,372-row gap-fill worksheet into a spoken dialogue: the agent pulls
the evidence and recommends; **Ramunas makes every call.** Nothing here writes the
lexicon or the open Excel file.

## Setup (once, with Excel closed)

```bash
python3 src/analyzer/review/export_snapshot.py     # snapshot + seed prior decisions
python3 src/analyzer/review/set_completeness.py    # closed-set gap audit (optional, recommended)
```

This writes `data/analysis/gapfill/worksheet_export.tsv` (the snapshot the agent
reads) and seeds `review_decisions.tsv` with the ~1,646 rows already decided in the
workbook (293 accept / 18 reject / 1,335 postpone). Then reopen the workbook in
Excel for viewing on your second screen — **the agent never touches it.**

## Standing policy for the review agent

1. **Order & resume.** Work *pending* rows (not already in `review_decisions.tsv`)
   in priority order **P1_name → P2_hot → P3_compound → P4_nomatch → P5_mid →
   P6_tail**, frequency-descending within a band. ~726 rows are pending.
2. **Per row, call the context tool** and read its evidence:
   ```bash
   python3 src/analyzer/review/review_context.py <en_lemma>
   ```
   It prints: the row, corpus example sentences (sense-diverse) + match count, the
   Esperanto anchor round-trip (does `eo_word`'s gloss actually mean the lemma?),
   the alternatives with their glosses, a name signal, and a one-line
   **RECOMMENDATION** (`ACCEPT` / `REJECT(name)` / `ASK(reason)`).
3. **Auto-policy (Ramunas opts in; revocable per band).** When Ramunas has said
   "auto," apply `ACCEPT` and `REJECT(name)` recommendations automatically and
   record them `--source auto` with the reason. Surface only `ASK` rows as
   questions. Every auto decision is logged with its reason — this is delegating
   the obvious bulk, not bypassing the gate. (Estimated split on the pending set:
   ~57% auto-handleable, ~43% ASK.)
4. **Spot-check.** After each batch of ~25 autos, show Ramunas 3–4 auto-accepted
   and 1–2 auto-rejected rows *with their evidence* to confirm. If he overturns
   >~10%, tighten the policy (ask more, auto less).
5. **Never auto-decide P1_name.** Name-or-word rows (`lily`, `jack`, `rose`,
   `bill`) carry the most weight and error — always present them as `ASK` with the
   actual name/common-noun split, even if the tool says `REJECT(name)`.
6. **Questions are compact.** For an `ASK` row present: word · freq · 2–4 sentences ·
   the proposed anchor's round-trip gloss · the alternative senses. Wait for a terse
   reply.
7. **Record every decision** via `review_record.py`; run `review_merge.py` when
   Ramunas wants a refreshed viewable copy (`gapfill_review.reviewed.xlsx`).

## Ramunas's terse reply grammar (for `ASK` rows)

| reply | meaning |
|---|---|
| `1` | accept (as proposed) |
| `0` | reject |
| `h` | hold (follow-up queue) |
| `p` | postpone |
| `k <n>` | accept, but use alternative candidate **n** as the anchor (agent records the override) |
| `<free text>` | a note or a corrected Esperanto word; agent proposes the root/word, confirms, records the override |
| `auto N` | apply the agent's recommendations for the next **N** rows, then resume asking |
| `show autos` | dump the recent auto decisions for audit |

## Recording (what the agent runs)

```bash
# straight decision
python3 src/analyzer/review/review_record.py <lemma> accept --source auto  --reason "..."
python3 src/analyzer/review/review_record.py <lemma> reject --source human --reason "name"
# decision with a corrected anchor (Ramunas picked an alternative / gave an EO word)
python3 src/analyzer/review/review_record.py lily reject --note "character name"
python3 src/analyzer/review/review_record.py bug  accept --eo-root insekt --eo-word insekto \
    --source human --reason "child sense = insect, not software"
```

`review_record.py` is idempotent: the last write for a lemma wins, so re-deciding is
just another append.

## Anchor correction in the loop

When the round-trip doesn't match (e.g. `bug`→`miso` is the *software* sense; the
child sense is `insekto`), the tool flags it `ASK — polysemy` and lists the better
alternative. On `k <n>` or a typed Esperanto word, the agent records the decision
**with `--eo-root/--eo-word` override**. Ramunas never edits the workbook's K/L
columns by hand.

## Output → Phase 3

The approved set for the Phase-3 gated writer is `review_decisions.tsv` filtered to
`decision=accept` (with any anchor overrides applied). `hold` = follow-up queue;
`reject`/`postpone` are dropped. Same insert-only writer, same
`source='tinystories_gap_v1'`. Also feed `set_gaps.tsv` (missing closed-set members)
into the same queue.

## Hard rules

- Never read or write the live `gapfill_review.xlsx` (Excel holds it open) — only
  the `worksheet_export.tsv` snapshot in, `review_decisions.tsv` out.
- Never write `lexicon_v2.db`. The human is the gate; autos are a logged,
  spot-checked, revocable delegation.
