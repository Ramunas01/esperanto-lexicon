# PM brief — Named-entity inventory v0: the physically-permanent core

Goal: turn the validated D7 sample (PR #9, 786 rows, 99.6% EO) into a **persistent,
queryable inventory** of the physically-permanent named entities — the closed, stable
objects (celestial bodies + fixed physical geography) that don't change over human
timescales. This is an **inventory build**, deliberately NOT a tier assignment and NOT the
full names layer. It gives the reservoir the near-empty Tier-3 work will draw from.

Scope discipline is the point of this task: build the store, fill it with the permanent
core, stop. No people, no institutions, no discovery-from-documents, no tier stamping.

## The one rule that must not be violated
Per roadmap **R8**: these entities do **not** get a stored tier. Their tier is *derived
later* against a reference group. So the inventory records **salience** (the sourced
datum) and leaves tier out entirely. Anyone who adds a `tier` column has broken the design.
`global_core` membership (truly group-invariant: `Moon`, `ocean`, `continent`) MAY be
flagged, but a numeric tier per entity MUST NOT.

## What goes in (physically-permanent types only)
From the D7 coarse types, include **celestial** and **physical-geographic** only:
planets, the Sun, curated major moons, nearest stars; oceans, seas, continents, major
rivers, mountains, mountain ranges, deserts, large islands, major lakes, notable straits.
**Exclude for now:** institutional (EU/UN — not physical, subject to R6-coherence and to
change) and settlement (cities — mutable, and a much larger open set). Those are later
phases; note them as deferred.

## Deliverables

### 1. The store — a sibling table set in `lexicon_v2.db`
Same DB (resolver co-location, free joins) but **strictly separate tables** — never touch
`concept`/`concept_root`. Implement from the v0.1 draft (`docs/names/tier_names_schema_draft.md`),
minimally:
- `named_entity(id, qid UNIQUE, label_eo, label_en, sitelinks, sitelinks_asof, status)`
- `named_entity_type(entity_id, ne_type, validation)` — junction; `validation` = R6 regime
  (`correspondence` for all rows in this permanent-physical set, since all have physical
  referents). Multi-type supported (though rare in this subset).
- `named_entity_alias(entity_id, alias, lang)` — carry EO aliases where present (thin), and
  the EN label as fallback for the ~0.4% missing-EO rows.
- **No `tier` column anywhere in these tables.** (Commonness/derivation is a separate,
  later concern.)

### 2. The loader — `src/lexicon/load_named_entities.py`
Insert-only, idempotent (key on `qid`; re-run = no-op / update salience only). Reads the
committed `data/analysis/names/gazetteer_sample.tsv`, filters to the two permanent types,
and populates the tables. Handle the known D7 gaps explicitly: `ASEAN`/`Cardiff` are
institutional/settlement so out of this scope anyway; drop the `Tschardakenhof` junk row
(the mis-typed sovereign state) — it wouldn't pass the type filter regardless, but assert it.
Back up the DB first; transaction; report inserted counts by type.

### 3. A tiny read API / query helper
A function + CLI to look up an entity by `label_eo` (primary) or `label_en` (fallback) or
`qid`, returning its type(s), validation regime, and salience — the shape the future
resolver's "check names before decomposition" hook (R3) will call. Read-only demonstration;
do not wire it into the analyzer yet.

## Constraints
- No lexicon writes to `concept`/`concept_root`/`concept_lang`; no schema changes there.
- No tier stamping (R8). No discovery, no institutions, no cities in v0.
- CC0 provenance (Wikidata) recorded; `sitelinks_asof` stamped so salience is dated.
- Human gate on the write: emit an inventory preview (counts by type + the full row list)
  for Ramunas to eyeball before the actual insert. PR; no merge without review.
- Idempotent + backed up, so re-running as the sample grows is safe.

## Success criteria
`named_entity` populated with the permanent-physical core (~celestial + physical-geographic
subset of the 786), every row carrying a QID, an EO label (EN fallback recorded for the
handful lacking one), a coarse type, `validation='correspondence'`, and a dated salience —
and **no tier**. The read helper resolves `Marso`, `Atlantiko`, `Everesto`, `Nilo`. Deferred
scope (institutions, settlements, tier derivation, discovery) listed plainly in the memo.

## Why this serves the T3 urgency (state it in the memo)
Tier 3 is near-empty and the urge is to fill it. This inventory is the *supply side* for
that: a clean, salience-ranked, EO-labelled reservoir of stable entities. When we build the
tier-derivation step, promoting the group-invariant ones (`Moon`, `ocean`, continents) into
the derived-T2/T3 common set is then a query against this store — not a fresh collection
effort. We are stocking the shelf now so the T3 work is assembly, not gathering.
