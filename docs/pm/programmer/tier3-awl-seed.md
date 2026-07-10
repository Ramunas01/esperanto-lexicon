# Programmer brief — Tier-3 seed from the Academic Word List (assembly, not discovery)

Self-contained hand-off for a single Programmer agent. Source PM brief:
`docs/pm/briefs/tier3-awl-seed.md` (read it first — this brief is the execution plan for it).
Branch `analysis/tier3-awl-seed` (already created off `main`); **PR, no merge**.

**One-line goal:** grow Tier 3 from ~96 EN words to a domain-general formal core by
translate-and-merge assembly of the **Academic Word List (AWL, Coxhead 2000)** — reusing the
existing gap-fill anchor→review→merge pipeline. **No corpus mining, no UNKNOWN-inspection loop.**

## Repo reality (PM-verified 2026-07-07, use these — don't rediscover)
- Current Tier 3: **96 `concept_lang` rows** (all `lang='en'`, all `source='tier3_unknown_pool_2026_05_29'`).
- **`concept_lang` UNIQUE key = `(concept_id, lang, word, pos)`.** A single concept legally
  carries many EN words (existing concepts already hold up to 11). This is the house pattern
  and the UNIQUE key is your insert-only idempotency guard.
- Reusable pipeline (all present): `src/lexicon/build_gapfill_worksheet.py` (ESPDIC reverse
  lookup / `parse_espdic` / `propose_anchor` / `strip_flexion` / junk+frequency gate),
  `src/analyzer/gapfill_prep.py` (reconcile a reviewed worksheet), `src/lexicon/apply_gapfill_merge.py`
  (insert-only merge writer: backup + transaction + `--dry-run`), audit tool =
  **`src/lexicon/eo_root_decomposer.py`** (the brief's `audit_root_consistency.py` does NOT
  exist — use the decomposer), `src/analyzer/batch_coverage_report.py` (has `t3_anchor_density`).
- ESPDIC at `data/lexicon_db/espdic.txt` (fetched by build/gapfill tools; CC-BY-3.0).
  Inventory at `data/lexicon_db/eo_inventory.json` (gitignored, regenerate if absent).
- **Named entities are the Wikidata rail** (`named_entity` tables, `src/lexicon/load_named_entities.py`)
  — never seed names from the AWL. Out of scope here.

## LOCKED design decision (PM ruling — implement this unless the human overrides)
**A family = ONE concept carrying N EN `concept_lang` rows at `tier=3`**, NOT N concepts.
- Head lemma (`analyse`): **LINK** if a concept with that EN word already exists → reuse its
  `concept_id`; else **NEW** concept with `eo_root`=approved root (head of a `concept_root` row),
  `eo_word`=approved EO word, `eo_pos`, `eo_status='complete'`.
- Members (`analysis`/NOUN, `analytical`/ADJ, `analyst`/NOUN, `analytically`/ADV): each an
  insert-only `concept_lang(concept_id=<family concept>, lang='en', word, pos, cefr_level, tier=3,
  source='awl_t3')` row. Distinct on `(word,pos)` → UNIQUE key prevents dupes on re-run.
- **INVARIANT (do not break — it cost a full redo on the last merge):** for every NEW concept,
  `concept.eo_root` MUST equal the `concept_root` head root. Set `eo_root` from the decomposition
  head, never from a curated/stale stem. Post-write audit must show 0 mismatches.
- If the head LINKs to a concept that already has a tier on its existing EN rows, **leave those
  rows untouched**; only add the missing members at `tier=3`. A concept spanning tiers across its
  EN rows is allowed (tier is per `concept_lang` row).

## Phase 1 — Acquire & normalize (no DB writes)
Source a machine-readable AWL (Coxhead 2000, 570 families / ~3,000 forms; attribute Coxhead in
a header comment + the memo). Emit a clean structure: family head → member lemmas (+ POS where
the source gives it; else tag POS at Phase 2 via spaCy `en_core_web_sm`). De-dupe every lemma
against the current lexicon (`concept_lang` EN words): mark which already exist (and at what tier)
so Phase 2 can classify LINK vs NEW and skip already-T3 members.

## Phase 2 — Anchor worksheet (no DB writes)
For each ~570 family head: reverse-ESPDIC-lookup → proposed `eo_root`/`eo_word`/`eo_gloss`;
mark **LINK** vs **NEW**; flag `ambiguous` / `no_match` / `compound`; list the member lemmas that
will attach (with POS) and which are already present. Run the frequency/junk gate so no artifacts
enter. Emit `data/analysis/tier3/awl_worksheet.tsv`. **Expect high ESPDIC recall** — AWL is
Latinate/international (`koncepto`, `funkcio`, `strukturo`, `hipotezo`, `signifa`); the hold/no_match
bucket should be far smaller than the Germanic child-vocab gap-fill. Report recall vs that baseline.
**STOP after Phase 2** — the worksheet is the human gate. (Don't write files Ramunas may have open;
emit a fresh TSV he copies to `.xlsx`.)

## Phase 3 — Human review [RAMUNAS] (not you)
Per family: approve / hold / reject; fix the anchor where wrong. Default `tier=3` (cefr B2/C1);
flag the rare family that's really T2-common or T4-concentrated. Resume at Phase 4 on the edited
worksheet.

## Phase 4 — Gated merge (the only write phase)
Extend/reuse `apply_gapfill_merge.py` (do NOT fork a second divergent writer): backup DB +
single transaction + `--dry-run` first. For each approved family: LINK or NEW the concept per the
LOCKED design; generate `concept_lang(en)` rows at `tier=3`, `source='awl_t3'` for head + members;
insert-only (never UPDATE existing rows). Then run the audit (`eo_root_decomposer.py`): 0 truncations,
0 `eo_root`↔head mismatches, resolution ≈99.7% holds, no new dupes. Report inserted counts
(families, new concepts, T3 EN rows, LINK vs NEW, skipped-already-present).

## Phase 5 — One-time end validation [PROG + RAMUNAS]
Run ONCE (not per-iteration): `batch_coverage_report.py` on the 29-text customs corpus. Report
whether **`t3_anchor_density`** moved and whether expert/novice separation changed. **A null result
is a valid finding — report honestly.** Write `data/analysis/tier3/t3_validation.md`.

## Scope bounds & constraints
Insert-only; human-gated; backup + transaction + mandatory post-write audit. **Never modify an
existing `tier`/`word`/`cefr_level`/`source`.** No names, no discovery loop, no R8 commonness-
derivation machinery (a stored `tier=3` on `concept_lang` is consistent with R8's stable-core
carve-out for the group-invariant formal core). No `.db` commits (gitignored). Tests for the pure
bits (AWL parser, family expansion, LINK/NEW classifier, worksheet writer) with fixtures — no
network in tests. Update `docs/pm/progress/tier3-awl-seed.md` at session start and end.

## Success criteria
~570 families reviewed → ~3,000 EN lemmas linked at Tier 3, `source='awl_t3'`, insert-only;
audit clean; resolution ≈99.7%; Tier 3 grows from ~96 to a usefully-populated core; Phase-5
validation reports the `t3_anchor_density` effect plainly. Fast because it is assembly of a known
list, not discovery.
