# Programmer brief — cross-corpus UNKNOWN inventory + D1 accounting pass

Self-contained hand-off for a single Programmer agent. Source PM brief:
`docs/pm/briefs/unknown-inventory.md` (read it first — this is the execution plan for it).
Branch `analysis/unknown-inventory` (already created off `main`); **PR, no merge**.

**One-line goal:** turn UNKNOWN from a scalar into a **classified, cross-corpus taxonomy** and
isolate the one diagnostic cell — the **true residual** (non-junk, non-name, non-domain,
non-inflection tokens UNKNOWN across ≥2 corpora). **Read-only diagnostic + accounting pass —
NO lexicon writes, no authoring, no tier changes.** Produces review files + a reusable classifier.

## Repo reality (PM-verified 2026-07-11 — use these, don't rediscover)
- **`wordfreq` is NOT installed and pip is PEP 668-blocked here** (system Python 3.14, no venv;
  same wall that stopped openpyxl/ftfy). The brief makes the `wordfreq` zipf gate **mandatory**
  as the junk filter. **Resolve this FIRST:** install it (a venv, or `pip install --user wordfreq`,
  or `--break-system-packages`); if your env blocks it, ask Ramunas to run
  `! pip install --user wordfreq` in his session. Only if it is genuinely unobtainable, implement
  a **documented fallback** junk gate (e.g. a bundled frequency list / heuristic) and **flag it
  loudly in the memo** — do not silently skip the gate. spaCy `en_core_web_sm` IS available.
- **UNKNOWN pools come from `batch_coverage_report.py`** — `write_unknown_pool()` emits
  `unknown_tokens_pooled.txt`, format **`count\ttoken`** (tab, count first; e.g. `4354\tlily`).
  The top of the TinyStories pool is names (lily/timmy/ben/tom/mommy) — the brief's "elephant",
  visible in the raw data.
- **Per-corpus separation is the whole point.** Do NOT merge pools before counting — the
  diagnostic is *in how many corpora* a token is UNKNOWN. Generate/collect a SEPARATE pool per
  corpus:
  - **TinyStories (child):** `data/analysis/tinystories_run/unknown_tokens_pooled.txt` (~3,819 tokens; regenerable via the TinyStories fetch + batch run).
  - **Customs domain (7 areas):** run `batch_coverage_report.py` over the domain texts in
    `../esperanto-lexicon-corpus/proficiency_eval/` (`corpus-1-law … corpus-7-valuation`,
    +compliance/other) and/or the novice+expert strata.
  - **General controls:** the `control/` stratum (5 texts: recipe/sports/tech/travel/garden).
  Regenerate cleanly per corpus rather than trusting stale on-disk pools (several exist:
  `data/analysis/{,gapfill/,tier3/,tinystories_run/}unknown_tokens_pooled.txt`).
- **Name store (PR #10, on `main`):** `from src.lexicon.query_named_entities import resolve` →
  `resolve(conn, token)` returns a hit or `None`; store has **272** entities. Read-only.
- Lexicon lemma/surface resolution: reuse `src/analyzer/coverage_report.py`
  (`classify_tokens` / `load_inflected_forms`) for the `inflection_miss` test.

## The classifier — `src/analyzer/unknown_classifier.py` (reusable, tested)
One bucket per pooled token, evaluated **in this order** (first match wins):
1. **`junk`** — `wordfreq` zipf ≈ 0 AND not a decomposable compound (OCR/URLs/code/
   numbers-with-units/foreign fragments/misspellings). Filter first; report the count; expect it
   large — do NOT read its volume as signal.
2. **`named_entity`** — matches the `named_entity` store OR spaCy `PROPN` / caps-dominant /
   NER person·place·org. Store match → `confirmed`; absent + salient → **candidate**
   (→ `name_candidates.tsv`). The elephant.
3. **`inflection_miss`** — token's lemma resolves in the lexicon but the surface form didn't
   (pipeline issue, not a gap).
4. **`domain_term`** — concentrated in ONE domain corpus, absent elsewhere → Tier-4, route to
   domain DBs, not a common gap.
5. **`common_gap`** — real cross-corpus common word missing from the lexicon (the class gap-fill
   drained; expect small now).
6. **`true_residual`** — **the deliverable.** What's left: real, non-junk, non-name, non-domain,
   non-inflection tokens UNKNOWN across **≥2 corpora**.
Record per token: per-corpus UNKNOWN counts, **universality** (# corpora UNKNOWN in), bucket,
and diagnostics (zipf, is_propn, lemma, store-match).

## D1 accounting coupling
- Match the `named_entity` bucket against the v0 store; emit unmatched salient tokens →
  `name_candidates.tsv` (future curation; author nothing now).
- **Suppress-from-accounting:** a `named_entity` or `junk` token drops out of the coverage-gap
  tally, so the memo reports a **true residual UNKNOWN %** = raw UNKNOWN − names − junk −
  known-gaps. That number (not raw 8.3%) is the honest measure of what's left.
- Add an **optional** `--classify-unknown` flag to `batch_coverage_report.py` that reports
  classified-UNKNOWN. **Do NOT change its default output** (existing analyses must not break).

## Deliverables
- `data/analysis/unknown_inventory/pooled_unknown_classified.tsv` — every token: per-corpus
  UNKNOWN count, universality, bucket, zipf, is_propn, lemma, store-match.
- `data/analysis/unknown_inventory/true_residual.tsv` — the isolated cell, **universality-ranked**
  (UNKNOWN-everywhere first). The thing to actually read.
- `data/analysis/unknown_inventory/name_candidates.tsv` — name-bucket tokens absent from the store.
- `docs/analysis/unknown_inventory.md` — memo: classified breakdown per corpus + pooled, the
  **true residual UNKNOWN %**, the *shape* of the residual (systematic classes), plain go-forward.
  **Honest reporting: if the residual is boring (more names/junk), say so — that confirms the
  foundation is sound, a valid reassuring result.**

## Scope / constraints
Read-only on `lexicon_v2.db` and `named_entity` — no authoring, no tier changes, no full names
layer, no tier-derivation (R8 stays future). `wordfreq` gate mandatory (see caveat above). Tests
for the classifier with fixtures — no network. Update `docs/pm/progress/unknown-inventory.md` at
session start and end.

## Success criteria
A classified pooled inventory; a **true-residual list that is small and legible** (if it's huge,
either the classification is too coarse or there's a genuine systematic hole — surface either);
a reusable classifier so future coverage reports can show classified-UNKNOWN; the name bucket
matched against the store with candidates emitted; and a memo stating the true-residual UNKNOWN %
and reading the shape of what remains — i.e. whether, after names + gap-fill + AWL, the common
foundation is complete or still leaks.
