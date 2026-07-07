# Progress — gap-fill review harness (initiative: review-harness)

**Session-restore record.** Read this + the brief to resume.

- **Brief:** [`docs/pm/briefs/review-harness.md`](../briefs/review-harness.md)
- **Protocol (for the live session):** [`docs/pm/review-session-protocol.md`](../review-session-protocol.md)
- **Branch:** `analysis/review-harness` (stacked on PR #6 `analysis/common-gapfill`)
- **Status:** ✅ **Harness built and validated. Ready for Ramunas's live review session.**
  No lexicon writes; the live `.xlsx` is never touched.
- **Depends on:** the common-gapfill worksheet (PR #6). Precedes common-gapfill Phase 3.

## What was built (`src/analyzer/review/`)

| Script | Role |
|---|---|
| `xlsx_lite.py` | dependency-free XLSX read + fresh-file write (openpyxl won't install; never patch the live file) |
| `_common.py` | shared pure logic: decisions I/O, corpus grep, name signal, anchor round-trip, recommendation |
| `export_snapshot.py` | **setup (Part D):** snapshot the workbook + seed decisions from col I; refuses to run if Excel lock present |
| `review_context.py` | **Part A:** all evidence for one lemma + ACCEPT/REJECT(name)/ASK recommendation |
| `review_record.py` | **Part A:** append a decision (idempotent, last-write-wins) |
| `review_merge.py` | **Part C:** fold decisions into a fresh `gapfill_review.reviewed.xlsx` (view-only copy) |
| `set_completeness.py` | **Part C:** closed-set completeness audit → `set_gaps.tsv` |

`tests/test_review_harness.py` — 19 tests. Full suite green.

## State of the data (after setup was run once)

- `worksheet_export.tsv` — snapshot of the 2,372-row `worksheet` tab (gitignored, regenerable).
- `review_decisions.tsv` — **committed durable decision log.** Seeded with Ramunas's
  1,646 prior decisions (293 accept / 18 reject / 1,335 postpone). **726 rows pending.**
- `set_gaps.tsv` — 226 closed-set members, **51 gaps** (19 animals, 10 body incl. finger
  names, 8 weather, 7 family, …) the frequency queue never surfaced.
- `gapfill_review.xlsx` / `.reviewed.xlsx` — gitignored (Ramunas's working file / generated copy).

## Validated behaviour

- **Polysemy guard works:** `bug`→`miso` (software) is caught as `ASK` because `insekto`
  carries "bug" as its *primary* sense; `pond`→`lageto`, `duck`→`anasa` are clean ACCEPTs.
- **Estimated pending split:** ~57% auto-handleable (414 ACCEPT), ~43% ASK (312) — all
  `P3_compound` and `P4_nomatch` correctly route to ASK. No `P1_name` pending (Ramunas did
  them). Cuts the human's remaining work to ~312 terse replies.
- **Setup safety:** `export_snapshot.py` refuses to read the xlsx if the `~$` Excel lock
  exists; existing decisions are never clobbered.

## Design decisions / deviations from the brief

- **No openpyxl** (PEP 668 blocks install; also unwanted dependency). XLSX read/write is
  pure-stdlib `zipfile`+XML in `xlsx_lite.py`. The merge output is a *fresh* minimal xlsx
  (inline strings, no styling) rather than a patched copy — simpler and safer.
- **Recommendation is conservative** and sense-aware: it only ACCEPTs when the lemma is the
  anchor's *primary* ESPDIC sense and no better-fitting alternative exists; everything else
  (polysemy, secondary sense, compound, no_match, name-ambiguous) → ASK.
- `review_decisions.tsv` is committed as the durable, crash-recoverable work product;
  the snapshot and Excel files are gitignored.

## To resume / run a session

1. Close Excel. `python3 src/analyzer/review/export_snapshot.py` (idempotent; won't
   re-seed already-recorded lemmas). Optionally `set_completeness.py`.
2. Open a Claude Code **review agent**, give it `docs/pm/review-session-protocol.md`
   as standing policy, and start at the first pending P1/P2 row.
3. Agent loop: `review_context.py <lemma>` → recommend → (auto or ASK) →
   `review_record.py …`. `review_merge.py` for a refreshed viewable copy.

**Next after review:** common-gapfill **Phase 3** consumes
`review_decisions.tsv` (decision=accept, with overrides) + `set_gaps.tsv` via the
gated insert-only writer (`source='tinystories_gap_v1'`), then **Phase 4** re-measures.

## Operating notes

- All harness scripts are light and foreground; no background fan-out, no concurrent
  agents. The live session is one interactive review agent (Ramunas-driven).
