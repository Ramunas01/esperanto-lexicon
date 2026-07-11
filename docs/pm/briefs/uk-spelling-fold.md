# PM brief — close the coverage arc: British-spelling fold + what's next

Two parts. **Part A** lands the last known common-vocabulary gap (British/Commonwealth
spellings) as the *formal close* of the T1–T3 coverage work. **Part B** is not a task —
it's a short, honest framing of the next chapter (the names layer) so it starts from the
right premise rather than as "more coverage." Do Part A now; Part B is for the record and
for whatever Advisor brief comes next.

---

## Part A — British-spelling normalization (the final coverage crumb)

The UNKNOWN inventory (PR #12) found exactly one real leak: ~17 types / ~1,097 tokens of
British/Commonwealth spellings whose **US form is already a concept in the lexicon**
(`mum`→`mom`, `colourful`→`colorful`, `favourite`, `neighbour`, `aeroplane`, `centre`,
`fertiliser`→`fertilizer`, …). Because the concept already exists, this is **pure
normalization — not new vocabulary**: no Esperanto anchoring, no meaning review, no human
gate on senses. It's the cheapest possible win, and it's the *last* known common-vocab gap.

### Why it's its own tiny task (not folded into the next brief)
Closing it lets us make a clean, evidenced claim: the T1–T3 common foundation is complete.
That seam deserves to be shut deliberately, not to ride along as an afterthought where it
could get lost.

### The work
- **Reuse the existing `uk_to_us` fold** from the gap-fill (it already handled the AWL's
  `analyse→analyze`, `labour→labor`). Extend its map to cover the inventory's British set —
  source the pairs from `data/analysis/unknown_inventory/` (the tokens already sit in the
  `local`/`common_gap`/`true_residual` buckets, US-form-present), plus the standard
  `-our/-or`, `-re/-er`, `-ise/-ize`, `-yse/-yze`, `ae/oe→e`, `-ll-/-l-` classes.
- Apply it as a **resolver-side normalization** (map the British surface form to its existing
  US concept at lookup time) — the same mechanism, **not** new `concept`/`concept_lang` rows.
  If the project's convention is instead to add British `concept_lang(en)` alias rows pointing
  at the existing concept, do that — but keep it insert-only and confirm it does not duplicate
  or alter the existing US entries.
- **Verification, not a big audit:** re-run the UNKNOWN classifier on TinyStories and confirm
  the British-spelling cluster drops out of `local`/`common_gap`/`true_residual`; report the
  before/after UNKNOWN and the residual. `fertiliser` (the lone non-name `true_residual` item)
  should resolve; `stratum` (genuine Latin-origin word, US=UK) legitimately remains — that's
  correct, not a miss.
- Constraints: read-only on existing concepts (no edits to US entries); if adding alias rows,
  insert-only + mandatory post-write audit (the invariant gate stays on). Deterministic; tests
  for the fold map. Branch `analysis/uk-spelling-fold`; PR; no merge without review.

### Definition of done for the whole coverage arc
British-spelling cluster resolves; TinyStories `true_residual` = `stratum` only (expected);
and the memo states plainly: **T1–T3 common-vocabulary coverage is complete** — cross-corpus
true residual is a single genuine word. That sentence formally ends this line of work.

---

## Part B — what's next: the names layer is a *different* problem (framing, not a task)

Do not let momentum carry the team into treating names as "the next coverage batch." It
isn't. Everything so far (gap-fill, AWL, spelling) was **closed-set, root-anchored common
vocabulary** — enumerable, translatable, human-reviewable in an afternoon. The names layer is
**open-world, QID-keyed, tier-relative, per-document-disambiguated** — a genuinely fresh kind
of work governed by the R1–R8 resolutions and the v0.1 schema draft. Carry these into the
next Advisor brief:

- **Start with D1 (accounting), not the ontology.** The near-free win is the named-entity
  *recognition + suppress-from-signal* pass — the reusable classifier from PR #12 is already
  most of it. That drives UNKNOWN toward zero and cleans the expertise confound without
  building the deep model.
- **The 936 name_candidates carry British-spelling contamination** (`mum`, `centre`,
  `organisation` misrouted into `named_entity`). After Part A folds those, **re-run the
  candidate extraction** so the list is clean before anyone curates it into the store — and
  attach that caveat *to the `name_candidates.tsv` file itself*, not just a memo.
- **R8 holds: no stored tier on names.** The v0 inventory (272 entities) is deliberately
  tier-free; keep it that way until the group-relative derivation is actually built.
- **Sequence:** Part A (finish coverage) → D1 (name accounting, drains UNKNOWN's elephant into
  the store) → then the deeper ontology (R5/R6 entity-sense, tier-derivation) *only* where a
  track (the-essence) needs it.

Part B is a note to hold, not to execute. The Advisor will brief the names work when Ramunas
is ready to open that chapter.

---

## PR housekeeping
PR #12 is recommended for merge (clean, read-only, verified). Merging it + Part A's PR closes
the coverage arc in the repo. CLAUDE.md gets the one-line UNKNOWN-accounting entry (already
drafted) plus, after Part A, a "T1–T3 coverage complete" note — with Ramunas's approval, as
always.
