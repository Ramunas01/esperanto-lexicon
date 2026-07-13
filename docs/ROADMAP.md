# Esperanto-lexicon — Roadmap (for consideration)

*A standing reference for direction and priorities. Not canonical: `CLAUDE.md` remains the
source of truth. Advisory, updated as the project moves.*
*Last updated after: root-vs-tier coverage diagnostic (found the general-adult gap + the
vocabulary-lifecycle model); Tier-3 AWL seed merged (PR #11); names inventory v0 (PR #10);
D7 Wikidata probe GO (PR #9).*

## Purpose

Estimate domain expertise from text via the ratio of specialized terminology to common
vocabulary, using Esperanto roots as a normalizing substrate that collapses morphological
(and, in principle, cross-language) variation to a comparable semantic skeleton. Two layers:
a **root-abstraction engine** and an **expertise/relevance estimator** on top of it.

**Keep the two tier systems distinct.** Pedagogical tiers 1–4 (`concept_lang`; CEFR/Oxford/
Dolch) are the *expertise* axis the hypothesis runs on. Inventory tiers (`core/extended/
tail/modern`; ESPDIC productivity) are a *build-quality* signal, not expertise.

## Where things stand

- **Lexicon: stable.** ~26,439 ESPDIC-derived roots (CC-BY), 99.7% resolution, 0
  truncations/mismatches, `concept_root` set model, successor-variety-guarded reducer.
- **Expertise metric: validated with characterized limits.** On the 29-text customs corpus,
  `T4_ratio` is a strong topic detector and a partial expert/novice separator; co-occurrence
  and Tier-3 anchoring complement it; breadth/variety does *not* separate expertise.
  Predicate-carriers explored and closed (register signal, not expertise).
- **Denominator reliability: measured, then repaired (TinyStories probe → merge, PR #8).**
  `T1+T2` was under-covered by ~8–10% of common vocabulary; the gap-fill closed it.
  **2,192 concepts authored insert-only** (2,113 TinyStories + 79 systematic-set gaps; 201
  Tier-1 / 1,991 Tier-2), all human-reviewed. `number` demoted Tier 3→1 (the one sanctioned
  existing-row change). Post-merge audit PASS: 0/4,713 eo_root mismatches, ~99.7% resolution,
  0 orphans/new duplicates.
- **Loop closed (honest result).** TinyStories UNKNOWN **19.5% → 8.3%**; customs control
  UNKNOWN **27% → 17.3%**, expert/control separation **8.9× → 10.0×**. Expert/**novice**
  separation essentially unchanged (1.51× → 1.53×). Finding: a cleaner denominator sharpens
  *topic* detection but does **not** rescue the *expertise* axis — consistent with the
  register/genre entanglement. `T4_ratio` dipped ~2% (denominator grew; mechanical, benign).
  Awaiting human sign-off on `merge_audit.md` / `loop_closure_report.md` before this becomes
  canonical.
- **Tier 3 seeded from the AWL — DONE (PR #11).** ~2,605 EN forms authored at tier 3
  (`awl_t3`) from Coxhead's Academic Word List (570 families → forms via the "570 decisions →
  3,000 words" family-expansion). Assembly, not discovery: the AWL *is* the list, so no corpus
  loop. Recognition **4.5% → 8.2%**. Audit clean (0 eo_root mismatches; `via`/`dynamic`
  false-friend traps held). **Phase-5 finding (canonical lesson):** a domain-general Tier 3
  *improves coverage* but **weakens `t3_anchor_density` as an expertise discriminator**
  (7.3× → 3.3×) — because recognising domain-general formal vocabulary lifts the Tier-3 signal
  for *everyone*. The measure conflates "uses formal vocabulary" with "is an expert." The T4/
  co-occurrence measures were **bit-for-bit unchanged**, proving the edit surgical and
  confirming expertise routing rightly stays on T4. Net: T3 seed = a coverage win and an honest
  negative result about T3-as-expertise-signal.
- **Names: probe GO + inventory v0 landed.** D7 Wikidata feasibility = **GO, 99.6% EO label
  coverage** across the salient core, no coverage cliff (PR #9) — "seed, don't translate"
  validated. Named-entity inventory v0 (PR #10): **272 physically-permanent entities**
  (celestial + physical-geographic), QID-keyed, EO-labelled, salience-carried, **no tier**
  (R8), in sibling tables that never touch `concept`. The supply side for future derived-T3.
- **Root-vs-tier coverage diagnostic (inventory-driven, corpus-free).** Joined all ~26,439
  ESPDIC roots against tier coverage — a cross-source check (ESPDIC vs English tier-builders)
  that finds gaps no corpus could. Result: obscure 22,653 / covered-T1–3 2,648 / **candidate_gap
  666** / shade_mismatch 480. Gaps concentrate at the top (T1 = 1, T2 = 107, T3 = 558). The 666
  are genuinely common adult words (`carbon`, `democratic`, `retail`, `circuit`, `copyright`) —
  revealing a **missing general-adult layer**: T3 was seeded from the AWL (*academic* formal),
  which by construction excludes *general* high-frequency vocabulary. Fix = a general-frequency
  seed (SUBTLEX/COCA); the 666 file is a first draft of it. `shade_mismatches` (480) = Esperanto
  carving joints English blurs — a resource for the-essence semantic work, not a coverage gap.

### Open data-quality debts (logged, not yet actioned)
- **~693 pre-existing duplicate concepts** in the base lexicon (e.g. `about`/`pri` doubled,
  oxford_3000). Predate the merge; left untouched under insert-only. A dedicated dedup pass
  is worth scheduling.
- **Write-invariant discipline.** The merge's first write silently broke the
  `eo_root == concept_root head` invariant in 692 rows; caught only by the post-write audit,
  then restored-and-rewritten to 0 mismatches. Lesson: the post-write audit gate is
  mandatory on every future lexicon write, not optional.
- **Upstream junk gate.** Misspellings/artifacts (`beachs`) and sense/compound false-flags
  reached human review repeatedly; a `wordfreq` + decomposition sanity check run *before*
  generating review files would stop this class recurring.

## Directions (rough priority)

1. **Common-lexicon gap-fill → re-measure customs — DONE (PR #8).** Merged and loop-closed
   (see above). Remaining tail: US/UK spelling map still to land; sign-off on the two reports.
2. **Tier 3 — core seeded (PR #11); optional depth remains.** AWL core is in (coverage win;
   see the Phase-5 caveat above). Optional next: the AVL (~3,000 modern lemmas) for depth, and
   reclassifying the ~dozen formal words the gap-fill parked in Tier 2. Lower urgency now that
   the coverage need is met and T3-as-expertise-signal is understood to be limited.
3. **Names layer — probe + inventory v0 done; next is the accounting pass.** D7 GO and the
   272-entity v0 store are landed (see above). The near-free next step is **D1** (classify
   UNKNOWN as named-entity + the suppress-from-signal flag) — it delivers the no-UNKNOWN win
   and cleans the expertise confound. The rich ontology (R5/R6, tier-derivation) ripens with
   the-essence track.
4. **Per-area expertise profiles** (7-dim customs vector from the area-attestation infra).
5. **Larger, genre-matched corpus** — *conditional* on proficiency evaluation becoming a
   live goal; the one experiment that could disentangle expertise from register.
6. **Lithuanian common lexicon** (LT Tier 1–2).
7. **Reuse / productization** (`eolex-relevance` package). Specified; deferred.
8. **Story-essence track (parallel).** TinyStories → Esperanto → Tier-1 roots → labelled
   graphs → compare "in essence." The gap-fill is its on-ramp; the names layer (below) is a
   hard dependency for its entity abstraction.

## Principles / discipline

- **Disconfirm first** — run the cheap deflationary test before building machinery.
- **Register ≠ expertise; breadth ≠ expertise; formal-vocabulary coverage ≠ expertise.**
  A recurring law of this project: anything that rewards *formal fluency* measures the
  publishing pipeline, not the person. Caught first in predicate-carriers (register), then in
  the AWL seed (`t3_anchor_density` conflates formal-vocabulary use with expertise). What
  worked is depth of reuse and cross-concept **co-occurrence**. Corollary for any future
  T3-based expertise signal: it must **separate domain-general T3 (AWL) from domain-adjacent
  T3** — the AWL core is the right instrument for *coverage*, the wrong one for *discrimination*.
- **The denominator matters** — under-covered common vocabulary corrupts the ratio silently.
- **Human-gated lexicon writes**; no canonical change without validated findings + approval.
- **The instrument stays descriptive, not editorial** — it measures; it does not adjudicate
  value (see names-layer R7).

---

## Names layer — resolutions & open questions (brainstorm, for consideration)

*Captured from a design brainstorm. A name is a **compression handle**: one token pointing
at a large structure (`Maxwell's equations`, `Mars`, `the Standard Model`), which is exactly
why names matter to both the coverage accounting and the essence abstraction.*

### Resolutions (working agreements)
- **R1 — Accounting first.** The layer's first job is inventory, not linguistics: every
  token must be *classified*, never left as bare UNKNOWN. "Named entity" becomes a first-class
  classification that UNKNOWN drains into, so residual UNKNOWN is genuinely unclassifiable and
  worth investigating.
- **R2 — Open-world recognition, not enumeration.** Names outnumber the lexicon and the set
  is open (new ones constantly). Recognize + type via signals (capitalization, NER,
  gazetteers, name-morphology): a curated gazetteer for the high-salience core, a recognizer
  for the unbounded tail.
- **R3 — Parallel structure, checked before decomposition.** Names are mostly opaque tokens
  with no Esperanto root, so they do **not** belong in `concept`/`concept_root`. A parallel
  `named_entity` structure the resolver consults *before* attempting root decomposition
  (tag-and-skip).
- **R4 — The derivative bridge.** Names spawn productive derivatives that DO enter the common
  lexicon and can take Esperanto roots: demonyms (`American`→`uson-`, `Ukrainian`→`ukrain-`),
  eponymous adjectives (`Newtonian`), `-ism` forms (`Marxism`). This is the one edge from the
  name layer back into the root layer — a lexicon task, worth a small curated list (see D3).
- **R5 — Entity-sense disambiguation.** One string can denote different *entities*
  (`Jupiter` god vs. planet; `Amazon` river vs. company). This is distinct from and sits on
  top of word-sense; the layer stores the candidate entities behind a surface form.
- **R6 — Entity type selects the validation regime.** A name with a physical referent
  (planet-Jupiter) is checkable by **correspondence**; an ideational name (god-Jupiter,
  `Marxism`) only by **internal coherence**. Entity type therefore routes the entity to the
  right half of the-essence's defensible-scope distinction — a genuine link between the names
  layer and the essence project's core.
- **R7 — Salience is measured and neutral.** Some names are load-bearing organizing nodes
  with far more connectivity than others; that is an analyzable graph property (centrality).
  Record salience/meaning-mass as a *sourced, measurable* attribute. The layer inventories
  meaning-mass; it does **not** adjudicate which names/programs are rising or eroding, or what
  that means culturally — interpretation is left to the reader of the output. This keeps the
  instrument trustworthy across users who would disagree about the interpretation.

### Open questions (deliberately unresolved)
- **Q1 — Is there a name-based expertise signal at all?** Intuition: mentioning several
  countries/regions marks specialization. But this collides with two prior findings —
  named entities were excluded as *confounds* (Ireland appears in customs and travel writing
  alike), and *breadth* failed to separate expert from novice. If a signal exists it almost
  certainly runs through **co-occurrence** (entities *reasoned across together*) and is
  **domain-conditional** (five countries inside a customs analysis, not a holiday story), not
  raw count. Testable, and fighting gravity from prior results — so a question, not a
  resolution.
- **Q2 — Type-ontology depth.** How deep the hierarchy goes: celestial → continent → country
  → region → city …; person → human / deity / fictional-character; organisation; and
  works-of-authorship (`Maxwell's equations`, `the Standard Model`) that behave like named
  entities. Depth should be driven by what a track actually needs, not built speculatively.
- **Q3 — Gazetteer sourcing.** Wikidata is the obvious open, permissively-licensed (CC0)
  candidate, and it carries type, aliases, and a native salience proxy (sitelinks/centrality).
  Coverage, extraction cost, and fit-to-our-types to be evaluated (see D7).

### R8 — Tier is derived, not stored (the governing principle for tiers + names)
A term/entity does **not** carry an absolute tier. It carries **commonness relative to
reference groups**; the effective tier is **derived at scoring time** against a chosen
reference population. `Nemunas` is T2-in-Lithuania and T4-globally at once; `Jesus`,
`Sydney`, `Amazon` likewise. Consequences: (a) tier is a shared *axis* across `concept`
and `named_entity`, which stay **two tables** (names have no root); (b) the
suppress-from-signal / counts-as-expertise decision is **computed** — a named entity counts
iff its effective tier is T4 *for the reader's reference group* — not a fixed property;
(c) "migration" T4↔T3 is mostly **virtual** (the audience's knowledge shifts, the lexicon
doesn't) — so no migration/decay machinery is built; `as_of` + re-derivation suffices;
(d) per-group commonness is **unmeasurable** from current corpora, so the schema provides
the socket (store commonness group-relative where known, global otherwise) but is populated
with a single `global` default + coarse tags until real data exists; (e) a large
**group-invariant common core** (`water`, `mother`, `one`, `Moon`) short-circuits the group
machinery — the group-relative margin is where the "natural expert" signal lives.
Initial T1 is **environment-relative** (Mars/Antarctica/Lithuanian toddlers differ);
`global` T1 ≈ "what ~90% of Earth 5-year-olds encounter". Draft data model:
`docs/names/tier_names_schema_draft.md` (v0.1, for iteration).

### R9 — The vocabulary lifecycle (R8 applies to words, not just names)
A term's tier is not only *group-relative* (R8) but *time-relative*: words move through a
lifecycle, and the tier system must have a home for every stage — including the two that sit
*outside* the common T1–T3 band. Direction of travel, not raw commonness, is the sorting key.

- **names layer** → a proper name (`Volt`, `Amper` the men). QID-keyed, no root.
- **`unplaced` (rising, forward-facing)** → coined/newly-relevant terms on the way *up*, not
  yet common (`ampero` just after coinage; a fresh borrowing). A **staging status, explicitly
  EXCLUDED from expertise scoring** — a rising word must not yet count as specialist. Held here,
  inventoried (so the-essence project never re-invents it), until a language community's
  frequency data promotes it to T1–T3. Stays small because it is *transient*: words either
  graduate up or fade into the archive.
- **T1–T3 (common)** → saturated everyday vocabulary. The general-adult layer (the 666) lives
  here once placed.
- **T4 "philology / historical-linguistic" (fading, backward-facing)** → obsolete/archaic/
  dialectal roots no living community uses but that language *scholars* study (a real specialist
  domain: using a dead word signals a philologist/medievalist/poet). **COUNTED as expertise** —
  correctly, unlike `unplaced`.

The metric-critical rule: **`unplaced` and philology-T4 both hold "uncommon" words but get
OPPOSITE scoring treatment** — `unplaced` excluded (rising, not yet specialist), philology-T4
counted (fading, genuinely specialist). They must never merge: collapsing them would either let
rising everyday words inflate expertise (the `ampermetro` trap) or erase genuine scholarly
vocabulary from the signal. One token can traverse the whole arc (`Volt`: name → unplaced →
common → philology-T4 if civilization forgets it); R8's derived-not-fixed tier is what lets it
move without the schema fighting. Intake question is therefore **"which way is it heading?"** —
and for a brand-new word the honest answer is "unknown," which is exactly what `unplaced` is for.

### Guardrails
- **G1 — No document state in the lexicon.** *Which* Jupiter (resolution) and `Peter = he =
  the boy` (coreference) are **per-document** operations. The lexicon/name layer stores the
  global menu (candidate entities, types, salience); the *choice* among them belongs to the
  analysis / story pipeline.
- **G2 — Ship the cheap layer; grow the deep one on demand.** The coverage layer (gazetteer +
  type tag + a "suppress from domain signal" flag) is small and buys the no-UNKNOWN win now.
  The rich ontology (deity/planet split, correspondence-routing, centrality) is the essence
  track's deep end. Don't let the grand version block the near-free one.

### Candidate deliverables (a menu for later — none committed)
Ordered cheap-and-clarifying first; each ties to a resolution/question and says what it buys.
- **D1 — NE accounting pass + `named_entity` tag** (R1, R3, G2). Extend the coverage tooling
  to classify UNKNOWN tokens as person/place/org/other via capitalization + spaCy NER + a
  small gazetteer, and report the *true* residual UNKNOWN. Near-free; delivers the no-UNKNOWN
  win and a suppress-from-domain-signal flag that addresses the expertise confound. **Highest
  value-per-effort.**
- **D2 — `named_entity` table + resolver-hook design** (R3, G1). A schema/DDL sketch (surface
  form(s), type, salience, aliases, source) and the "check before decomposition" hook — a
  design doc, not implementation. Clarifies where names sit relative to `concept`.
- **D3 — Demonym/eponym bridge list** (R4). A curated candidate list of name-derivatives that
  belong in the common lexicon with EO roots (`uson-`, `ukrain-`, `-ism` forms). A normal
  lexicon gap-fill batch, human-reviewed.
- **D4 — Salience/centrality probe** (R7). Build a name co-occurrence graph on a corpus and
  compute centrality — see the "load-bearing node" idea empirically, as a neutral graph
  property, reusing the co-occurrence machinery. A thinking prototype.
- **D5 — Name-expertise co-occurrence test** (Q1). The disconfirm-first experiment: on the
  customs corpus, does *domain-conditioned name co-occurrence* separate expert/novice where
  raw name-count does not? Designed so it can fail.
- **D6 — Entity-sense sketch for the-essence** (R5, R6). Take a handful of ambiguous names
  (`Jupiter`, `Mercury`, `Amazon`, `Phoenix`), lay out their candidate entities, types, and
  which validation regime (correspondence vs. coherence) each routes to. A thought-artifact
  for the essence track.
- **D7 — Wikidata sourcing feasibility note** (Q3). ✅ DONE (PR #9): **GO, 99.6% EO coverage**,
  no cliff across the salient core; five qualifications became build constraints (curate
  celestial by QID; key on primary EO labels + EN fallback; multi-type entities; junk-class
  filter; salient core only, tail unprobed). The 272-entity inventory v0 (PR #10) built on it.
