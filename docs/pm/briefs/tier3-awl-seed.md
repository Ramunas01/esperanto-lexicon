# PM brief — Tier-3 seed from the Academic Word List (assembly, not discovery)

Goal: populate the near-empty Tier 3 (currently ~99 words) with a principled, domain-neutral
core of formal adult vocabulary, fast. The key insight that makes it fast: **Tier 3 does not
need discovery.** A linguist already enumerated exactly this category — formal words common
*across* domains but absent from everyday speech. So this is a **translate-and-merge assembly
job**, reusing the gap-fill anchor→review→merge pipeline, with **no corpus mining and no
UNKNOWN-inspection loop** in the iteration.

## Source
- **v1 seed: the Academic Word List (AWL, Coxhead 2000)** — ~570 word families (~3,000 word
  forms). Domain-general *by construction*, which is precisely why it fits Tier 3 and why we
  do NOT seed T3 from legal/domain texts (those smuggle Tier-4 domain terms into T3). Source a
  published machine-readable AWL; attribute Coxhead.
- **v2 (optional, later): Academic Vocabulary List (AVL, Gardner & Davies)** — ~3,000 modern
  lemmas, for depth once v1 lands. Not in scope now.

## The efficiency structure (570 decisions → ~3,000 words)
Anchor at the **family/root level, not per word.** For each AWL family head (`analyse`),
the reviewer approves ONE Esperanto anchor (`analiz`); the pipeline then auto-generates
`concept_lang(en)` rows at Tier 3 for **all member lemmas of that family** (`analysis`,
`analytical`, `analyst`, `analytically`…), all pointing at the approved root. So Ramunas
reviews ~570 anchors, but ~3,000 English lemmas gain Tier-3 coverage. (Member lemmas each need
their own `concept_lang` row because the analyzer resolves by English lemma — `analytical`
won't lemmatize to `analyse`.)

**Expect unusually clean anchoring.** AWL vocabulary is Latinate/international (`concept`,
`function`, `structure`, `hypothesis`, `significant`), and Esperanto drew from the same stock
(`koncepto`, `funkcio`, `strukturo`, `hipotezo`, `signifa`). ESPDIC recall should be far higher
than the Germanic child-vocabulary gap-fill — lighter review, smaller hold bucket.

## Phases (reuse the gap-fill pipeline)

**Phase 1 — Acquire & normalize [PROG].** Fetch the AWL; produce a clean list of family heads
+ their member lemmas. De-dupe against existing lexicon (many may already be present as
concepts needing only a Tier-3 `en` link).

**Phase 2 — Build the anchor worksheet [PROG] (no DB writes).** For each ~570 family head:
reverse-ESPDIC-lookup → proposed `eo_root`/`eo_word`/`eo_gloss`; mark **LINK** (concept exists,
add T3 en rows) vs **NEW**; flag `ambiguous`/`no_match`/`compound`; list the family members that
will attach. Emit `data/analysis/tier3/awl_worksheet.tsv`. Run the frequency/junk gate we added
so no artifacts enter.

**Phase 3 — Human review gate [RAMUNAS].** Per family: approve/hold/reject; fix the anchor where
wrong (same terse flow as the gap-fill). Default tier = **3** (cefr B2/C1); flag the rare family
that's really T2-common or T4-concentrated. STOP here for the edited worksheet.

**Phase 4 — Gated merge [PROG].** Back up DB; transaction; insert-only. For each approved family:
LINK or NEW the root, then generate `concept_lang(en)` rows at `tier=3`, `source='awl_t3'` for the
head + members. Never modify existing rows. Run the integrity audit (`eo_root_decomposer.py` /
verify the real tool name): 0 truncations/mismatches, resolution holds, no dupes. Report counts.

**Phase 5 — One-time end validation [PROG] + [RAMUNAS].** This is the payoff check, run ONCE at
the end (not per-iteration): re-run `batch_coverage_report.py` on the 29-text customs corpus and
report whether **`t3_anchor_density`** (the Tier-3-in-domain-context signal — a strong complementary
measure in the validation report) improved, and whether expert/novice separation moved. Honest
reporting: a null result is a valid finding.

## Explicitly OUT of scope
- **No names.** Named entities come from the Wikidata rail (inventory-v0), never the AWL. The
  group-invariant names (`Moon`, oceans, continents) become derived-T3 later by **query against
  the `named_entity` store** — not collected here.
- **No discovery loop / no UNKNOWN inspection during iteration.** The AWL *is* the list.
- **No R8 machinery.** AWL words are the group-invariant formal core, so a stored Tier-3 on
  `concept_lang` is consistent with R8's stable-core carve-out. The commonness/reference-group
  derivation is a separate future track; do not build it here.
- If a *later* task mines additional formal vocabulary from documents, apply cross-domain IDF
  (keep only words spread across ≥2 domain corpora) to avoid smuggling T4 terms into T3. Not
  needed for the AWL seed (already curated domain-general).

## Files
Read: `CLAUDE.md`, the AWL source, ESPDIC, `eo_inventory.json`, `lexicon_v2.db` (schema),
`batch_coverage_report.py`. Write (Phase 2, no DB): `awl_worksheet.tsv`. Write (Phase 4, gated):
`lexicon_v2.db` inserts + tests. Write (Phase 5): `data/analysis/tier3/t3_validation.md`.
Branch `analysis/tier3-awl-seed`; PR; no merge without review.

## Constraints
Insert-only; human-gated; back up + transaction + post-write audit (mandatory — recall the
merge's silent invariant break). Never touch existing `tier`/`word`/`cefr_level`/`source`.
Concurrency-safe (don't write files Ramunas has open).

## Success criteria
~570 families reviewed → ~3,000 English lemmas linked at Tier 3, source-tagged, insert-only;
audit clean; resolution ≈99.7%; Tier 3 grows from ~99 to a usefully-populated core; and the
one-time validation reports the effect on `t3_anchor_density` plainly. Fast because it is
assembly (a known list) — not the open-ended discovery loop you feared.
