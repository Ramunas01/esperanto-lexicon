# Progress — inventory-vs-tier root coverage (initiative: root-tier-coverage)

**Session-restore record.** Programmer: update this at start and end.

- **Advisor/PM brief:** [`../briefs/root-tier-coverage.md`](../briefs/root-tier-coverage.md)
- **Programmer brief (execute this):** [`../programmer/root-tier-coverage.md`](../programmer/root-tier-coverage.md)
- **Branch:** `analysis/root-tier-coverage` (off `main`, not stacked).
- **Status:** 🔧 **IN PROGRESS (Programmer, 2026-07-11) — read-only diagnostic; PR, no merge.**

## The job
Read-only, corpus-free diagnostic: join `eo_inventory.json` (26,447 ESPDIC roots + glosses)
against `lexicon_v2.db` tiers to find Esperanto roots the language treats as common that our
T1–T3 tiers miss. Author nothing. Deliver `root_tier_coverage.tsv`, `candidate_gaps.tsv`,
`shade_mismatches.tsv`, memo. Settle the Ramunas-vs-Advisor bet on where gaps concentrate.

## PM-verified repo reality (2026-07-11)
- `eo_inventory.json` present; `roots` = 26,447 × `{gloss, prod, tier(core/extended/tail)}`.
- Join clean **100%**: 2,648/2,652 `concept_root.root` are inventory keys. Coverage query =
  concept_root ⋈ concept_lang.tier IN (1,2,3) → **2,652 roots covered**, 23,799 uncovered
  (tail 20,841 / core 994 / extended 1,964). `concept_root` holds only T1–3 roots (T4 in domain DBs).
- `wordfreq` importable (PR #12); use `zipf_frequency(w,'en')` (no `__version__`).
- Shade-mismatch design validated: `lepor`("hare, rabbit") uncovered vs `kunikl`("rabbit") covered.

## THREE traps the Programmer MUST handle (PM-measured)
1. Glosses start with `"to "`/articles → naive head scorer scores `to`(zipf 7.4) for every verb.
   Strip function words, score the content head.
2. Common head word ≠ common concept (`kolĉik`="meadow saffron"). Require short+common gloss, not
   just a common head; long/phrasal → obscure.
3. Derived-form glosses (`abrad`="abrasive") cause false gaps — normalize/lemmatize the gloss word
   and check `inflected_forms`/`uk_to_us` before deciding "not covered".

## Expectation reset (PM preview — record honestly)
Basic filter already gives **~1,117 candidate_gap / ~832 shade_mismatch — NOT a handful.**
candidate_gap is dominated by **Latinate formal vocab** (abolish/absurd/abrupt/adverse/adolescent)
→ supports the **Advisor bet** (gaps large at T3, <5% T1). Report the real, commonness-ranked,
T3-weighted number; don't force a handful. A large T1 gap = red flag (English phrasal lexicalization).

## Out of scope
Author nothing (TSVs are review output). No tier writes, no corpus work, no names. Each hit needs
a later human glance.

## Log
- 2026-07-11 (PM): coverage arc closed (PR #13 merged); branch + briefs set up. Verified join
  (100% aligned), wordfreq available, shade-mismatch example (lepor/kunikl); previewed the buckets
  (~1,117 gap / ~832 shade) and caught the three gloss-scoring traps. Awaiting Programmer.
- 2026-07-11 (Programmer, start): confirmed data — inventory roots=26,447 (core 2,626 / extended
  2,402 / tail 21,414 / modern 5); covered T1–3 roots = 2,652 (by MIN tier: T1=764, T2=1,824,
  T3=64; by ANY tier T3=447). wordfreq OK (to=7.43 — the trap). Validated gloss scorer on trap
  cases: trap#1 `to`-strip works; trap#2 — `incens`="to burn incense" (2-word phrasal) slips a
  min-zipf gate, so candidate_gap requires a **single content word** (phrasal→obscure); trap#3 —
  normalize gloss word via spaCy lemma + `inflected_forms` + `uk_to_us` before the covered check.
  Building `src/analyzer/root_tier_coverage.py` (pure scorer + join + bucket split) + tests.
- 2026-07-11 (Programmer, end): **COMPLETE — PR open, not merged.** Code:
  `src/analyzer/root_tier_coverage.py` (pure, 26 tests) + `build_root_coverage.py` (driver).
  Deliverables in `data/analysis/root_coverage/` (root_tier_coverage.tsv, candidate_gaps.tsv,
  shade_mismatches.tsv) + memo `docs/analysis/root_tier_coverage.md`. Full suite 922 passed.
  **Beyond the 3 briefed traps I added a 4th (proper-noun/demonym exclusion — American/Google/Louis
  dominated a naive run) + hyphen + stopword + tail-prior + a primary-vs-later-sense split for
  shade.** Results: covered 2,648 / obscure 22,653 / **candidate_gap 666 (621 distinct; T3-weighted:
  T1=1, T2=107, T3=558; Latinate-formal cluster)** / **shade_mismatch 480 (lepor-style granularity)**.
  Coverage by ESPDIC tier: core 62.1% / extended 18.2% / tail 2.7%. **THE BET → Advisor decisively
  closer:** T1 gap ~0% (Advisor <5% ✓, Ramunas 20% ✗), T2 5–6% (Advisor single-digit ✓, Ramunas 25%
  ✗), T3 large (both, Advisor's direction). T1 gap = 1 root (damn) → no red flag. Noted residuals:
  derivational adjectives (democratic/agricultural — base noun may be covered) + informal register.
  Read-only; authored nothing.
