# Tier-3 AWL seed — Phases 1–2 memo (worksheet ready for review)

**Status: STOPPED at the Phase-3 human gate, as briefed.** Phases 1–2 (acquire →
normalise → anchor worksheet) are done and produce
`data/analysis/tier3/awl_worksheet.tsv` (570 rows). **No DB writes.** Phase 4 (the
gated insert-only merge) runs only after Ramunas returns the reviewed worksheet.

Goal: grow the near-empty Tier 3 (currently **96** EN `concept_lang` rows) into a
domain-general formal core by *assembly* of the **Academic Word List** (AWL,
Coxhead 2000) — reusing the gap-fill anchor→review→merge pipeline, no corpus mining.

## Source & provenance (recorded per the ESPDIC/Wikidata discipline)
- **AWL:** Averil Coxhead (2000), *A New Academic Word List*, TESOL Quarterly 34(2).
- **Machine-readable rendering:** `github.com/lpmi-13/machine_readable_wordlists`
  (`Academic/AWL/AWL.json`), stated upstream = Victoria University of Wellington's
  canonical AWL. **License CC0-1.0.** Retrieved **2026-07-08**. Vendored to
  `data/awl/awl_coxhead.json`; provenance in `data/awl/SOURCE.md`.
- **Validated against the published AWL invariants before use** (a source that
  fails these is corrupted/abridged and was to be rejected):

  | invariant | expected | observed |
  | --- | --- | --- |
  | word families | 570 | **570** ✓ |
  | sublists | 10 | **10** (60×9 + 30) ✓ |
  | Sublist-1 families | 60 | **60** ✓ |
  | distinct word forms | ~3,000 | **3,107** ✓ |

  Structure preserved: family head → member forms, tagged with **sublist (1–10)** —
  carried through the worksheet as a frequency-priority signal (Sublist 1 = most
  frequent), not acted on. `subwords: null` families (`despite`, `hence`, `overall`…)
  are legitimate single-form families, not corruption.

## Phase 1 — acquire & normalise
`load_awl_families` parses the vendored JSON into 570 families, lowercasing and
folding Unicode hyphens (U+2011 in `co‑ordinate`/`co‑operate`) to ASCII so those
families survive, removing the head from its own member list, and de-duping members.
A junk gate keeps only real alphabetic lemmas (≥2 letters, internal hyphen allowed);
**0 real forms were dropped** from the vetted AWL.

## Phase 2 — anchor worksheet (`awl_worksheet.tsv`, one row per family)
Each family head is reverse-ESPDIC-anchored via the shared
`build_gapfill_worksheet.propose_anchor` (sense-quality ranked, `strip_flexion`
stem), marked **LINK** vs **NEW**, and flagged `ok` / `compound` / `no_match`. Member
forms are split into new (will be inserted) vs already-present (skipped, with their
tier). POS per form: a high-precision morphological suffix tagger for the derived
forms spaCy mislabels (`analytical`→ADJ, `analyse`→VERB, `significantly`→ADV), with
`en_core_web_sm` as the fallback for bare roots (`derive`→VERB, `perspective`→NOUN)
and NOUN as last resort.

### Headline numbers
- **570 families → 3,107 forms** (2,606 new / **501 already present** in the lexicon).
- **ESPDIC recall 97.5%** (556/570 families auto-anchored) — as predicted, far above
  the Germanic child-vocab gap-fill, because the AWL is Latinate/international and
  Esperanto drew from the same stock (`koncepto`, `funkcio`, `strukturo`).
- **Actions:** LINK 448 · NEW 111 · manual (needs hand-anchor) 11.
- **Flags:** ok 550 · compound 6 · no_match 14.
- **British-spelling fold** recovered 8 heads that otherwise missed ESPDIC
  (`analyse→analyze`, `labour→labor`, `maximise→maximize`, `licence→license`,
  `utilise→utilize`, `minimise→minimize`), each noted for the reviewer.

### What needs the reviewer's attention (the point of the gate)
- **11 manual families** with no ESPDIC anchor and not yet in the lexicon:
  `administrate, constrain, hence, incidence, innovate, thereby, qualitative,
  forthcoming, nonetheless, ongoing, whereby`. Mostly function words and rare
  derivations — anchor by hand or hold.
- **6 compound-flagged** heads to verify — the decomposer over-splits some single
  roots: `legislate→leĝ+don` (ok), but `dynamic→din+amik`, `parameter→par+metr`,
  `fee→honor+ari` are dubious splits flagged for a look.
- **~30 families** carry a "multiple EO senses — verify anchor" note (the ESPDIC head
  had several single-word candidates); `alt_candidates` lists them for a quick check.
- **501 already-present forms** (e.g. `analysis`/`analyze` already at tier 2) will be
  left untouched; only the missing family members get `tier=3` rows. A concept
  spanning tiers across its EN rows is allowed (tier is per `concept_lang` row).

### Worksheet columns
`sublist · family_head · action · eo_root · eo_word · eo_gloss · flag · head_pos ·
head_in_lexicon · n_forms · n_new · n_present · forms_new · forms_present ·
component_roots · alt_candidates · proposed_tier(3) · cefr(C1) · decision · notes`.
The **`decision`** column is blank for Ramunas: `approve` / `hold` / `reject`, and
fix the anchor in-place where wrong (same terse flow as the gap-fill review).

## Phase 4 plan (NOT run this session — after review)
Reuse `apply_gapfill_merge` (do not fork the writer). Per approved family, insert-only,
inside one transaction with a DB backup:
- **NEW:** author one `concept` via the existing `author_concept` logic on the head —
  which already derives `concept.eo_root` from the decomposition head, holding the
  **`eo_root` == `concept_root` head invariant** automatically — then add member
  `concept_lang(en, tier=3, source='awl_t3')` rows to that same `concept_id`.
- **LINK:** resolve the family `concept_id` (existing EN head word, else the concept
  carrying the approved `eo_root`) and add only the missing members at `tier=3`.
- The `(concept_id, lang, word, pos)` UNIQUE key makes the merge idempotent.
- **Mandatory post-write audit** (`eo_root_decomposer.py`): 0 truncations, 0
  `eo_root`↔head mismatches, resolution ≈99.7% holds, no new dupes. Report inserted
  counts (families, new concepts, T3 EN rows, LINK vs NEW, skipped-already-present).

## Phase 5 (one-time, after merge)
Run `batch_coverage_report.py` once on the 29-text customs corpus; report whether
`t3_anchor_density` moved and whether expert/novice separation changed. **A null
result is a valid finding** — report honestly. Write `data/analysis/tier3/t3_validation.md`.

## Scope / constraints honoured
Insert-only; human-gated; no `.db` writes this session; never modify an existing
`tier`/`word`/`cefr_level`/`source`. No names (Wikidata rail), no discovery loop, no
R8 commonness-derivation machinery — a stored `tier=3` on `concept_lang` is consistent
with R8's stable-core carve-out for the group-invariant formal core. Tests cover the
pure bits (parser, family expansion, POS tagger, LINK/NEW classifier, worksheet
writer) with fixtures — no network. Branch `analysis/tier3-awl-seed`; PR, no merge.
