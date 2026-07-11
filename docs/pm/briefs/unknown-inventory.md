# PM brief — cross-corpus UNKNOWN inventory + the D1 accounting pass

Goal: turn UNKNOWN from a scalar (8.3%) into a **classified taxonomy pooled across every
corpus we've analyzed**, so we can isolate the one diagnostic cell — the **true residual**:
the non-junk, non-name, non-domain, non-inflection tokens that are UNKNOWN *across multiple
corpora*. Everything else in the pile we already understand; the residual is the only part
that can surprise us and tell us whether the common-vocabulary foundation is actually
complete or still leaking somewhere we haven't looked.

Framing to carry to the Programmer (it sets the success criterion): **the goal is NOT to
rediscover that names are the biggest bucket — we know that, and the names layer exists for
it.** The goal is to *subtract* the known elephant (names), the junk, the domain terms, and
the known gaps, and see what's left. Couple this with **D1** (the named-entity accounting
pass) so the name bucket drains into the real `named_entity` store from inventory-v0, not
into a report we re-read.

This is a **read-only diagnostic + accounting pass. No lexicon writes.** It produces review
files (candidate gaps, candidate names) and a reusable classifier; it authors nothing.

## Corpora to pool
Every corpus that's been run through `batch_coverage_report.py`: TinyStories (child),
the 29-text customs set (7 domain areas), and its control texts (recipe / sports / tech /
travel / garden — general topics). Pool their `unknown_tokens_pooled.txt` outputs. The
diversity is the point — a token UNKNOWN in *all* corpora is a structural hole; UNKNOWN in
*one* is a local/domain/name artifact.

## The classifier (`src/analyzer/unknown_classifier.py`, reusable)
For each pooled UNKNOWN token, assign exactly one bucket, evaluated in this order:
1. **`junk`** — `wordfreq` zipf ≈ 0 AND not a decomposable compound: OCR errors, URLs, code,
   numbers-with-units, foreign fragments, misspellings. Filter first; report the count; do
   **not** mistake its volume for signal (real corpora are noisy — this bucket will be large).
2. **`named_entity`** — matches the `named_entity` store (PR #10), OR spaCy `PROPN` /
   caps-dominant / NER person·place·org. **This is the elephant.** Match against the store:
   already-present → confirmed; absent + salient → **candidate** (→ `name_candidates.tsv`).
3. **`inflection_miss`** — the token's lemma resolves in the lexicon but the surface form
   didn't (a pipeline issue, not a gap).
4. **`domain_term`** — concentrated in one domain corpus, absent elsewhere → Tier-4 domain
   vocabulary, out of common-lexicon scope (route to domain DBs, don't treat as a gap).
5. **`common_gap`** — a real, cross-corpus common word missing from the lexicon (the class the
   TinyStories gap-fill drained; expect this to be small now).
6. **`true_residual`** — **the deliverable.** What's left after all the above: real, non-junk,
   non-name, non-domain, non-inflection tokens UNKNOWN across **≥2 corpora**. The surprises —
   a systematic class the lexicon structurally misses, a tokenization pathology, a spelling
   regime, a vocabulary layer neither the gap-fill nor the AWL covered.

## The cross-corpus dimension (what makes it diagnostic)
For every token record **in how many corpora it is UNKNOWN**. Rank `common_gap` and
`true_residual` by that universality: UNKNOWN-everywhere = a foundation hole; UNKNOWN-in-one =
mostly names/domain you'd handle via the names layer / Tier 4 anyway. The
universally-uncovered non-name tokens are the highest-value output.

## D1 coupling (so the name bucket goes somewhere)
- Match the `named_entity` bucket against the v0 store; emit unmatched salient ones as
  `name_candidates.tsv` for future curation.
- Add a **suppress-from-accounting** flag: a token classified `named_entity` (or `junk`) is
  removed from the "coverage gap" tally, so the report can state a **true residual UNKNOWN %**
  = raw UNKNOWN − names − junk − known-gaps. That number, not the raw 8.3%, is the honest
  measure of what's left to fix.
- Wire the classifier so `batch_coverage_report.py` can *optionally* report classified-UNKNOWN
  (not just the scalar) on future runs. (Do NOT change its default output in a way that breaks
  existing analyses; add a flag.)

## Deliverables
- `data/analysis/unknown_inventory/pooled_unknown_classified.tsv` — every token: per-corpus
  UNKNOWN count, bucket, diagnostics (zipf, is_propn, lemma, store-match).
- `data/analysis/unknown_inventory/true_residual.tsv` — the isolated diagnostic cell,
  universality-ranked. **The thing to actually read.**
- `data/analysis/unknown_inventory/name_candidates.tsv` — name-bucket tokens absent from the
  store.
- `docs/analysis/unknown_inventory.md` — memo: the classified breakdown per corpus + pooled,
  the **true residual UNKNOWN %**, the *shape* of the residual (what systematic classes appear),
  and a plain go-forward. Honest reporting: **if the residual is boring** (just more names/junk),
  say so — that itself confirms the foundation is sound, which is a valid, reassuring result.

## Scope / constraints
Read-only on `lexicon_v2.db` and `named_entity` — no authoring, no tier changes, no full names
layer, no tier-derivation (R8 stays future). Classify, match, isolate, report. `wordfreq` gate
mandatory (the upstream junk filter we keep wishing for — this is where it earns its place).
Branch `analysis/unknown-inventory`; PR; no merge without review; tests for the classifier
(fixtures, no network).

## Success criteria
A classified pooled inventory; a **true-residual list that is small and legible** (if it's
huge, either the classification is too coarse or there's a genuine systematic hole — either is
a finding worth surfacing); a reusable classifier so future coverage reports show
classified-UNKNOWN; the name bucket matched against the store with candidates emitted; and a
memo that states the true-residual UNKNOWN % and reads the shape of what remains. The win is
knowing, after names + gap-fill + AWL, whether the foundation is complete — or where it still
leaks.
