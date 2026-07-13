# PM brief — inventory-vs-tier coverage: which Esperanto roots do our Tiers miss?

A **read-only, corpus-free** diagnostic. Flip from corpus-driven coverage (what's uncovered
in the texts we have) to **inventory-driven** coverage (what's in the language's root space
that our Tiers don't reach). No text sieving, no large disk ops, no WSL strain — it's a join
between two files already in the repo: `eo_inventory.json` (~26,439 ESPDIC roots) and
`lexicon_v2.db` (concepts + their pedagogical tiers). Nothing is authored.

## Why this finds what UNKNOWN could not
The tiers were built from **English** sources (Oxford, Dolch, AWL, TinyStories). The root
inventory came from **ESPDIC**, independently. Laying the two over each other is a
**cross-source consistency check**: the mismatches are concepts one source treats as common
that the other missed — and they surface *without any corpus*, so they include gaps no
quantity of TinyStories could ever reveal.

## The core join
For every Esperanto root in `eo_inventory.json`, determine which pedagogical tiers (1–4) have
a `concept` anchored on it (via `concept_root` → `concept` → `concept_lang.tier`). Bucket:
- **covered_T1_3** — a T1/T2/T3 English concept anchors this root (the common foundation).
- **T4_or_none** — only a Tier-4 domain concept anchors it, or no concept at all (specialist
  or genuinely obscure — **out of scope**, ignore per Ramunas).
- **candidate_gap** — the root is in the inventory, its **ESPDIC gloss reads as everyday
  English**, yet **no T1–T3 concept anchors it.** This is the prize: a concept the *language*
  treats as basic that our *tiers* never picked up.

## The commonness filter (essential — or the list is all noise)
Most uncovered roots are legitimately obscure (ESPDIC carries archaic/technical roots nobody
needs). Separate "we missed a common word" from "ESPDIC has an obscure root" by scoring the
**English gloss** with `wordfreq`: keep a root as `candidate_gap` only if its gloss's head
word(s) are reasonably common (e.g. zipf ≥ ~3.0) and short/everyday. Report the rest as
`obscure_root` (counted, not listed). This is the same discipline the UNKNOWN work used.

## The second, more interesting output: meaning-shade mismatches
Some roots won't be *missing* concepts — they'll be Esperanto roots that **carve meaning at a
joint English blurs**: `leporo` (hare) vs `kuniklo` (rabbit), where English has one loose word
and Esperanto two precise roots, or vice versa. These aren't gaps — they're **granularity
differences**. Flag separately as `shade_mismatch`: a root whose gloss overlaps an
already-covered English concept but denotes a distinguishable sense. This is likely the
*richer* finding than raw gaps; keep it in its own file for human reading.

## Deliverables
- `data/analysis/root_coverage/root_tier_coverage.tsv` — every root: anchoring tiers, bucket,
  gloss, gloss-zipf.
- `data/analysis/root_coverage/candidate_gaps.tsv` — the filtered common-but-uncovered roots,
  gloss-commonness-ranked. **The thing to read.**
- `data/analysis/root_coverage/shade_mismatches.tsv` — the granularity-difference candidates.
- `docs/analysis/root_tier_coverage.md` — memo: per-tier coverage %, the candidate-gap count
  **broken down by which tier the gap's commonness suggests it belongs to (T1/T2/T3)**, the
  shade-mismatch shape, honest caveats, go-forward.

## The bet (record it in the memo, then check it)
Two predictions are on the table; the memo should report the actual per-tier gap fractions
against both:
- **Ramunas:** gaps ≈ 1/5 of T1, 1/4 of T2, ~3× of T3 (many shade-variants).
- **Advisor:** gaps concentrated at the *top* of the stack — **<5% at T1**, single digits at
  T2, **large at T3** (youngest/thinnest tier, seeded from one source). Rationale: coverage
  completeness tracks *source agreement*, which is near-total for universal toddler concepts
  and weakest for freshly-seeded formal vocabulary.
The memo states who was closer and by how much. (A large T1 gap would be a red flag —
probably English lexicalizing via phrases, not a real hole — investigate before trusting it.)

## Scope / constraints
Read-only on `lexicon_v2.db` and `eo_inventory.json`. Author nothing — candidate gaps and
shade-mismatches are **review output**, not writes. `wordfreq` gate mandatory. Each hit needs
a later human glance ("real missing concept, or does English lexicalize it differently?") —
this task only *produces the reviewable list*. Branch `analysis/root-tier-coverage`; PR; no
merge without review; tests for the join + filter (fixtures, no network).

## Success criteria
A complete root-vs-tier coverage table; a **short, legible `candidate_gaps.tsv`** (expected
small — quite possibly a handful); a `shade_mismatches.tsv` that's the more interesting read;
and a memo that settles the bet with numbers and reads the *shape* of what the tiers miss.
The win: the one coverage check that's complete (whole root space), cross-source (ESPDIC vs
English), and corpus-free — finding what no amount of text sieving could.
