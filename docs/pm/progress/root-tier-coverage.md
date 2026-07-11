# Progress — inventory-vs-tier root coverage (initiative: root-tier-coverage)

**Session-restore record.** Programmer: update this at start and end.

- **Advisor/PM brief:** [`../briefs/root-tier-coverage.md`](../briefs/root-tier-coverage.md)
- **Programmer brief (execute this):** [`../programmer/root-tier-coverage.md`](../programmer/root-tier-coverage.md)
- **Branch:** `analysis/root-tier-coverage` (off `main`, not stacked).
- **Status:** 🟡 **SET UP — briefs filed, awaiting Programmer dispatch.**

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
