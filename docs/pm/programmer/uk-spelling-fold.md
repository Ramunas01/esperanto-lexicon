# Programmer brief — British-spelling fold (close the T1–T3 coverage arc)

Self-contained hand-off for a single Programmer agent. Source PM brief:
`docs/pm/briefs/uk-spelling-fold.md` (Part A is the task; Part B is a framing note, not work).
Branch `analysis/uk-spelling-fold` (already created off `main`); **PR, no merge**.

**One-line goal:** resolve the British/Commonwealth-spelling cluster that the UNKNOWN inventory
(PR #12) found — the last known common-vocab leak — as **pure normalization** (map British
surface forms to their already-existing US concept). No new vocabulary, no Esperanto anchoring,
no sense review, no human gate.

## LOCKED design (PM ruling — the project already has the mechanism)
Land the fold as **insert-only `inflected_forms` rows**, NOT resolver-code changes and NOT
`concept_lang`/`concept` edits.
- `inflected_forms(inflected_word, lemma, lang, form_description, tier)`, UNIQUE
  `(inflected_word, lemma, lang)` — the resolver (`coverage_report.classify_tokens` via
  `load_inflected_forms`) already consults it (surface→lemma) before falling back to UNKNOWN.
- For each British token, write a row: `inflected_word=<british>`, `lemma=<us form>`,
  `lang='en'`, `form_description='british_spelling'`, `tier=<the US concept's tier>` (copy it
  from the US form's `concept_lang.tier`). Insert-only; UNIQUE key is the idempotency guard.
- **Do NOT edit or duplicate the existing US `concept`/`concept_lang` rows.** This is why
  `inflected_forms` (surface→lemma) is preferred over adding British `concept_lang(en)` alias
  rows: aliases would inject "new" en vocabulary into coverage counts; inflected_forms just
  makes the British surface resolve to the existing concept. (The brief allows the alias route
  as a fallback — don't take it unless inflected_forms proves unworkable.)

## Data-driven generation (handles inflections + guards against junk)
Do **not** hand-list pairs. Iterate the committed inventory
`data/analysis/unknown_inventory/pooled_unknown_classified.tsv` (buckets `local`,
`common_gap`, `true_residual`), fold each token with an **extended** `uk_to_us`, and emit a row
**only when the folded US form is an existing en concept word** (`SELECT ... FROM concept_lang
WHERE lang='en' AND LOWER(word)=?`). This guard is essential — it:
- covers British *inflections* directly (`colours`, `coloured`, `colouring` each get their own
  row → the resolver never re-lemmatizes them), and
- rejects junk/misspellings the regex would mangle (verified: `suprised`→`suprized` is a typo,
  US form absent → correctly skipped; `stratum` unchanged → stays residual, correct).

## Extend the `uk_to_us` map (it is currently partial — verified)
`src/lexicon/build_gapfill_worksheet.py:uk_to_us` today covers `-our*`/`-tre`/some explicit;
it MISSES classes present in the cluster. Extend it (keep the change in that one function so the
gap-fill/AWL callers benefit too) to cover:
- `-ise→-ize`, `-ised→-ized`, `-ising→-izing`, `-iser→-izer` (`recognise`, `organiser`,
  `apologised`, `capitalising`, `mesmerised`),
- `-yse→-yze` (`analyse`—already via AWL, keep),
- `-re→-er` (`centre`, `theatre`, `metre`, `litre` → center/theater/meter/liter),
- `ae/oe→e` where the US word is real (guarded),
- explicit irregulars where the US form is a *different word*: `mum→mom`, `mummy→mommy`,
  `grey→gray`, `aeroplane→airplane`, `pyjamas→pajamas`, `plough→plow` (only those attested +
  US-present). Add unit tests for every class.

## Verification (not a big audit)
1. Apply the fold (backup DB + single transaction + insert-only; the invariant gate stays on —
   though `inflected_forms` doesn't touch `concept.eo_root`, run the standard post-write check:
   0 rows altered on `concept`/`concept_lang`, no dupes).
2. Re-run the UNKNOWN classifier (`build_unknown_inventory.py` / `--classify-unknown`) on
   TinyStories with `inflected_forms` loaded; confirm the British cluster drops out of
   `local`/`common_gap`/`true_residual`. Report before/after UNKNOWN % and residual.
3. **Honest DoD correction (PM-verified):** `fertiliser`'s US form `fertilizer` is **NOT in the
   lexicon**, so it CANNOT fold — it is a genuine (1-word) common gap, not a spelling miss. Do
   **not** force it. Expected post-fold TinyStories `true_residual` = `stratum` **and possibly
   `fertiliser`**. List any British tokens whose US form is genuinely absent as
   `us_form_absent` residual gaps in the memo (candidates for a trivial future 1-word add, out
   of scope here). `stratum` legitimately remains (US=UK).

## Deliverables
- Extended `uk_to_us` + the fold generator (reuse the gap-fill's planned `british_spellings.tsv`
  shape: `uk_form, us_form, total_freq, us_in_lexicon`); write the emitted pairs to
  `data/analysis/uk_spelling/british_folds.tsv` for review-in-PR.
- The `inflected_forms` writer (insert-only, backup+txn+audit).
- Tests for the fold map (deterministic, every class; no network).
- `docs/analysis/uk_spelling_fold.md` — memo: pairs folded, before/after UNKNOWN + residual, the
  `us_form_absent` list (incl. `fertiliser`), and the plain closing line: **T1–T3 common-vocab
  coverage is complete — cross-corpus true residual is genuine single words (`stratum`,
  + any US-absent gaps flagged), not a systematic hole.**

## Scope / constraints
Read-only on existing `concept`/`concept_lang` (no edits to US entries). Adding `inflected_forms`
rows = insert-only + backup + transaction + post-write audit. Deterministic; no human gate on
senses (pure normalization). No names work (Part B is a note for the next Advisor brief, not this
task). Update `docs/pm/progress/uk-spelling-fold.md` at session start and end.

## Success criteria
British-spelling cluster with a present US form resolves via `inflected_forms`; TinyStories
`true_residual` reduces to genuine single words (`stratum` [+ `fertiliser` if `fertilizer` not
added]); a reusable extended fold; and a memo that formally states the T1–T3 coverage arc is
closed. Note for Part B: after this lands, the 936 `name_candidates` should be regenerated so the
British contamination (`mum`/`centre`/`organisation` misrouted to `named_entity`) clears before
curation — that is the next initiative, not this one.
