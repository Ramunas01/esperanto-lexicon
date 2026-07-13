# Programmer brief — inventory-vs-tier coverage (which Esperanto roots do our Tiers miss?)

Self-contained hand-off for a single Programmer agent. Source PM brief:
`docs/pm/briefs/root-tier-coverage.md` (read it first). Branch `analysis/root-tier-coverage`
(already created off `main`); **PR, no merge**.

**One-line goal:** flip from corpus-driven to **inventory-driven** coverage — join
`eo_inventory.json` (ESPDIC roots + glosses) against `lexicon_v2.db` (concept tiers) and surface
the Esperanto roots the language treats as common that our T1–T3 tiers never picked up.
**Read-only, corpus-free. Author nothing.** Produces review TSVs + a memo.

## Repo reality (PM-verified 2026-07-11 — use these, don't rediscover)
- **`eo_inventory.json`** (`data/lexicon_db/`, gitignored, present ~2.4 MB) → `roots` = dict of
  **26,447** entries `{root: {gloss, prod, tier}}` where `tier` ∈ core/extended/tail (ESPDIC
  confidence, NOT pedagogical), `gloss` = English gloss, `prod` = productivity. (Regenerate via
  `build_eo_inventory.py` if absent.)
- **The join is clean (100%):** 2,648 of the 2,652 distinct `concept_root.root` values are
  inventory `roots` keys. Coverage query:
  `SELECT DISTINCT cr.root FROM concept_root cr JOIN concept_lang cl ON cl.concept_id=cr.concept_id
   WHERE cl.lang='en' AND cl.tier IN (1,2,3)` → **2,652 roots covered T1–3**. Everything else in
  the inventory (23,799 roots; tail 20,841 / core 994 / extended 1,964) is uncovered.
- **`concept_root` only holds T1–T3 roots** (T4 lives in domain DBs) — so "T4_or_none" per the
  brief = simply "root not in `concept_root`". Ignore per Ramunas.
- **`wordfreq` IS importable here** (from PR #12; no `__version__` attr — use
  `wordfreq.zipf_frequency(word,'en')`). No install blocker this time; confirm import at start.

## THREE implementation traps (PM-measured — get these right or the list is noise)
1. **ESPDIC verb glosses start with `"to "`; noun glosses with `a/the`.** A naive head-word
   scorer scores **`to`** (zipf 7.4) for *every* verb → the filter passes everything. **Strip
   leading function words** (`to/a/an/the/be/of/with/in/on`) and score the first *content* word.
2. **A common head word ≠ a common concept.** `kolĉik`="meadow saffron", `incens`="burn incense",
   `imperial`="top deck of vehicle" all have a common head (`meadow`/`burn`/`top`) but are
   obscure concepts. Defend with: require the gloss's **first sense to be short** (≤ ~2–3 words)
   AND common, not just a common head; treat long/parenthetical/phrasal glosses as `obscure_root`
   or low-confidence.
3. **Derived-form glosses cause false gaps.** Many glosses are the *adjective/derived* sense
   (`abrad`→"abrasive", `adici`→"additive", `abon`→"subscription-related"); the base concept may
   exist under a different surface (`abrade`/`add`). Before deciding "not covered", normalize the
   gloss word (lemmatize; also check `inflected_forms` and the British `uk_to_us` fold) against
   the concept `en` words — else you over-report gaps.

## The buckets (per root, evaluated with the traps handled)
- **covered_T1_3** — a T1/T2/T3 en concept anchors this root.
- **T4_or_none / obscure_root** — not in `concept_root`, or gloss fails the commonness gate
  (inventory `tier=tail` is a strong prior for obscure). **Counted, not listed.**
- **candidate_gap** — uncovered, gloss is common+short (content-head `zipf ≥ ~3.0`), AND the
  gloss's English word is **NOT** already an existing concept. The prize.
- **shade_mismatch** — uncovered, gloss common, but the English word **IS** already covered by a
  concept → Esperanto splits a sense English blurs (verified example: `lepor`="hare, rabbit"
  uncovered while `kunikl`="rabbit" covered). Own file; likely the richer read.

## Honest expectation reset (PM preview — put this in the memo, don't fight it)
A basic filter (uncovered, core/extended, content-head zipf≥3, word-not-covered) already yields
**~1,117 candidate_gap / ~832 shade_mismatch** — **NOT the "handful" the brief anticipated.** The
candidate_gap pool is dominated by **Latinate formal vocabulary** (`abolish`, `absurd`, `abrupt`,
`adverse`, `adolescent`…) — which *supports the Advisor's bet* (gaps concentrated at T3, the
formal tier) over Ramunas's. Report the **real** number ranked by commonness; the traps above
(esp. #2/#3) should shrink it, but do not force it to a handful — a large, T3-weighted list is
itself the finding. Flag the Latinate-formal cluster explicitly.

## Deliverables
- `data/analysis/root_coverage/root_tier_coverage.tsv` — every root: anchoring tiers, bucket,
  gloss, gloss-zipf, inventory-tier, prod.
- `data/analysis/root_coverage/candidate_gaps.tsv` — filtered common-but-uncovered roots,
  commonness-ranked, **with a suggested pedagogical tier per row** (zipf→T1/T2/T3).
- `data/analysis/root_coverage/shade_mismatches.tsv` — the granularity-difference candidates.
- `docs/analysis/root_tier_coverage.md` — memo: per-tier coverage %, candidate-gap count **broken
  down by suggested tier (T1/T2/T3)**, the shade-mismatch shape, the Latinate-formal finding, and
  **the bet settled with numbers**: Ramunas (gaps ≈ 1/5 T1, 1/4 T2, ~3× T3) vs Advisor (<5% T1,
  single-digit T2, large T3) — state who was closer. A large T1 gap is a RED FLAG (probably
  English lexicalizing via phrases) — investigate before trusting it.

## Scope / constraints
Read-only on `lexicon_v2.db` and `eo_inventory.json`. Author nothing — the TSVs are review output,
each hit needs a later human glance ("real missing concept, or English lexicalizes it
differently?"). `wordfreq` gate mandatory. Tests for the join + gloss-scorer + bucket split
(fixtures, no network) — include a fixture proving the `"to "`-stripping trap is handled. Update
`docs/pm/progress/root-tier-coverage.md` at session start and end.

## Success criteria
A complete root-vs-tier coverage table; a commonness-ranked `candidate_gaps.tsv` (report its true
size — likely T3-weighted hundreds, not a handful — with the noise traps controlled); a
`shade_mismatches.tsv`; and a memo that settles the bet with numbers and reads the *shape* of what
the tiers miss. The win: the one coverage check that's complete (whole root space), cross-source
(ESPDIC vs English), and corpus-free.
