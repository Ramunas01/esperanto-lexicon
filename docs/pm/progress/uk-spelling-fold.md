# Progress — British-spelling fold (initiative: uk-spelling-fold)

**Session-restore record.** Programmer: update this at start and end.

- **Advisor/PM brief:** [`../briefs/uk-spelling-fold.md`](../briefs/uk-spelling-fold.md) (Part A = task; Part B = names framing note)
- **Programmer brief (execute this):** [`../programmer/uk-spelling-fold.md`](../programmer/uk-spelling-fold.md)
- **Branch:** `analysis/uk-spelling-fold` (off `main`, not stacked).
- **Status:** 🔧 **IN PROGRESS (Programmer, 2026-07-11) — insert-only inflected_forms; PR, no merge.**

## The job
Resolve the British/Commonwealth-spelling cluster (the last known common-vocab leak, found by
the UNKNOWN inventory PR #12) as **pure normalization** to existing US concepts. Formally closes
the T1–T3 coverage arc. No new vocab, no EO anchoring, no human gate.

## PM-verified repo reality (2026-07-11) — locked design
- **Mechanism = insert-only `inflected_forms` rows** (`inflected_word=british`, `lemma=us`,
  `lang='en'`, `form_description='british_spelling'`, `tier`=US form's tier). The resolver
  (`coverage_report.classify_tokens` + `load_inflected_forms`) already consults this table
  before UNKNOWN. NOT resolver-code changes, NOT `concept_lang` alias rows (those would inflate
  coverage as "new" vocab). Table currently 49 rows; UNIQUE(inflected_word,lemma,lang) = dedup.
- **`uk_to_us` fold** lives in `src/lexicon/build_gapfill_worksheet.py:210` (used by AWL too) —
  **currently PARTIAL**: covers `-our*`/`-tre`/some explicit; MISSES `-ise/-ize`, `-iser/-izer`,
  full `-re/-er`, `ae/oe→e`, and irregulars (mum→mom, grey→gray, aeroplane→airplane). Extend it.
- **Data-driven + guarded:** iterate `data/analysis/unknown_inventory/pooled_unknown_classified.tsv`
  (local/common_gap/true_residual), fold, emit a row ONLY if the US form is an existing en
  concept word. Guard rejects junk (verified: `suprised`→`suprized` skipped) and covers British
  inflections directly (colours/coloured/colouring each get a row).
- **Measured coverage:** of the top British cluster, ~11 fold cleanly (US present: colour→color
  [T1], favourite→favorite [T1], aeroplane→airplane [T2], behaviour, theatre, rumour, flavour,
  neighbour, organised…). **`fertiliser` will NOT fold — `fertilizer` is absent from the lexicon
  → a genuine 1-word gap, not a spelling fix.** DoD corrected: post-fold TinyStories
  `true_residual` = `stratum` (+ `fertiliser` unless `fertilizer` is added later). Report
  US-form-absent tokens as genuine gaps; don't force them.

## Out of scope
Names (Part B — regenerate the 936 name_candidates AFTER this fold to clear British
contamination; that's the next initiative). No edits to existing US entries. No R8/tier work.

## Log
- 2026-07-11 (PM): PR #12 (UNKNOWN inventory) merged to `main`; branch + briefs set up. Verified
  the fold mechanism (inflected_forms), measured real fold coverage (~11 clean; fertiliser is a
  genuine US-absent gap — brief's DoD corrected), locked insert-only inflected_forms design.
  Awaiting Programmer.
- 2026-07-11 (Programmer, start): explored data-driven. Two refinements found vs the naive map:
  (1) `-re→-er` needs a **min-stem guard** (else `pre`→`per`, `tore`→`toer` — junk that the
  US-present guard can't catch when the mangled form is a real word like `per`); (2) British
  **plurals/inflections** (`colours`,`neighbours`,`centres`) must fold to the concept **lemma**
  (`color`,`neighbor`,`center`) via de-inflection — the lexicon stores base forms, not `colors`.
  With both: **18 folds / 270 tokens** (all US lemmas Tier-1/2 — good, since the resolver's
  inflected path only checks T1/T2), **7 US-absent gaps** (`fertiliser`,`apologised`,`centimetres`,
  `capitalising`,`equaliser`,`mesmerised` genuine; `suprised` a typo, correctly rejected). Building
  extended `uk_to_us` + `apply_uk_spelling_fold.py` (insert-only inflected_forms, backup+txn+audit).
- 2026-07-11 (Programmer, end): **COMPLETE — PR open, not merged.** Extended `uk_to_us` (all
  classes: -ise/-iser, -yse, -re/-er w/ min-stem guard, irregulars) + `apply_uk_spelling_fold.py`
  (data-driven from the inventory, fold→concept-lemma guard). **Committed 18 inflected_forms
  `british_spelling` rows** (49→67; backup + txn + audit PASS: concept/concept_lang unchanged,
  0 dupes). Also fixed a schema.py drift (inflected_forms was missing the UNIQUE the live DB has).
  **Before/after (UNKNOWN classifier re-run):** TinyStories UNKNOWN 8.12%→8.04% (−268); pooled
  34,077→33,805; `local` 560→311, `common_gap` 47→25; all 18 folds resolve; no British class left.
  **true_residual unchanged = `stratum` (US=UK) + `fertiliser` (US-absent gap)** — genuine single
  words, not a systematic hole. 7 `us_form_absent` gaps reported (fertiliser + 5 real + `suprised`
  typo). `mum`/`mummy`/`organisation` (misrouted to named_entity) deferred to the name-candidate
  regeneration initiative per the brief. Full suite 896 passed. Deliverables: `british_folds.tsv`,
  `after/` inventory, memo `docs/analysis/uk_spelling_fold.md`. **T1–T3 common-vocab coverage arc
  formally closed.**
