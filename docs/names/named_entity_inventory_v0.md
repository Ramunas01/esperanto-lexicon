# Named-entity inventory v0 — the physically-permanent core

**Status:** build memo. Programmer session, branch `analysis/names-inventory-v0`.
Builds on the D7 Wikidata feasibility probe (`docs/names/wikidata_feasibility.md`,
786-row sample, 99.6% EO primary-label coverage → GO).

This is an **inventory build**, deliberately not a tier assignment and not the full
names layer. It stocks the reservoir the near-empty Tier-3 work will draw from, and
then stops.

---

## What was built

Three sibling tables in `lexicon_v2.db`, **strictly separate** from `concept` /
`concept_root` / `concept_lang` (co-located only for free resolver joins; the names
code never touches the lexicon tables). The authoritative schema is
`src/lexicon/schema.py :: create_named_entity_schema`:

- **`named_entity`** — `id, qid UNIQUE, label_eo, label_en, sitelinks,
  sitelinks_asof, source, global_core, status`.
- **`named_entity_type`** — junction `(entity_id, ne_type, validation)`; multi-type
  supported (rare in this physical subset). `validation` is the R6 regime —
  `correspondence` for every row here, because all entities in the permanent-physical
  set have physical referents.
- **`named_entity_alias`** — `(entity_id, alias, lang)`; carries EO aliases where
  present (thin) and the EN label as fallback for the handful of rows lacking an EO
  primary label.

The **loader** — `src/lexicon/load_named_entities.py` (built in parallel) — populates
these tables from the committed `data/analysis/names/gazetteer_sample.tsv`. It is
insert-only and **idempotent** (keyed on `qid`; a re-run is a no-op / salience
refresh only), **human-gated** (emits an inventory preview of counts-by-type + the
row list for eyeballing before the write), and **backs up the DB** before the
transaction. It filters the sample to the two permanent physical types and asserts
the junk `Tschardakenhof` row is excluded.

This memo's own deliverable is the **read helper** —
`src/lexicon/query_named_entities.py` — a read-only lookup function + CLI (below).

---

## The R8 rule, stated plainly

**These entities carry no stored tier.** The store records only a sourced, dated
`sitelinks` salience; **tier is derived later** against a reference group. There is
deliberately no `tier` column anywhere in these three tables — anyone who adds one has
broken the design.

`global_core` is a **group-invariance flag, not a tier.** It marks the entities that
are reference-group-independent (the Moon, the oceans, the continents) — the ones a
future tier-derivation step will promote wholesale into the common set. It carries no
numeric level.

---

## Contents / counts

The permanent-physical core = the **celestial + physical_geographic** subset of the
786-row D7 sample:

| coarse type | raw rows | distinct entities loaded |
| --- | ---: | ---: |
| celestial | 28 | 28 |
| physical_geographic | 247 | 244 |
| **total** | **275** | **272** |

The 275 raw rows collapse to **272 distinct entities**: three QIDs appear in two
physical-geographic sets each and so are listed twice in the per-set sample —
**Indian Ocean** (`Q1239`; oceans + seas), **English Channel** (`Q34640`; seas +
straits), and **Caspian Sea** (`Q5484`; seas + lakes). The loader de-duplicates on
`qid` (first occurrence wins; the duplicate rows are identical), which is also why
`global_core` counts 13, not 14 — the Indian Ocean is a `global_core` ocean that would
otherwise be double-counted. These multi-set entities are a hint that the schema's
multi-type junction will eventually carry more than one physical type per entity
(a sea that is also a lake); v0 records the single sampled coarse type.

**Data-quality fix caught at the preview gate.** The build's inventory preview surfaced
five garbage rows in the D7 `stars` set — the curated star QIDs had drifted to unrelated
items that happen to carry EO labels (`sukero`/sugar, `Katmanduo`/Kathmandu,
`Göttingen`, `subnutrado`/malnutrition, `fiprogramaro`/malware), so they had falsely
scored as "covered" in the probe. The star QIDs were corrected at the probe source and
the sample regenerated before loading; the celestial core is now six real stars
(Siriuso, Alfa Centaŭro, Betelĝuzo, Proksima Centaŭro, Vego, Barnarda Stelo).

Every row carries:
- a **QID** (Wikidata, CC0 provenance),
- an **EO primary label** — in this subset **all 272 have one** (0 EO gaps; verified
  by counting empty `label_eo` in the subset). The only EO gaps in the whole D7 sample
  — Cardiff, ASEAN — are settlement / institutional and thus excluded from this build.
  The EN-fallback path (`eo → en → source_language`) exists in the schema and helper
  for future rows that lack an EO label, but no row in this v0 core exercises it.
- a **coarse type** (`celestial` | `physical_geographic`),
- `validation = 'correspondence'` (R6 regime; all have physical referents),
- a **dated salience** (`sitelinks` + `sitelinks_asof`),
- **no tier.**

**`global_core` curated allowlist = 13**: the Moon + the 5 oceans + the 7 continents —
the truly group-invariant physical entities. This is a curated allowlist, not a
derived quantity; it flags the wholesale-promotion candidates for the later
tier-derivation step.

**Provenance:** Wikidata structured data, **CC0 1.0** (public-domain dedication — no
attribution required, free to seed a lexicon). Salience is **dated** via
`sitelinks_asof` so the ranking is a sourced, timestamped datum rather than a derived
weight.

---

## Read-API demonstration

`src/lexicon/query_named_entities.py` exposes `resolve(conn, term) -> Optional[
NamedEntityHit]` and a CLI. Resolution order (first match wins), recording *how* it
matched in `match_field`: exact **qid** → exact **label_eo** → exact **label_en** →
**alias** (an `eo` alias preferred over an `en` alias when both match), then a second
pass repeating the label/alias steps **case-insensitively**. The hit returns the
entity (qid, both labels, salience + `asof`, `global_core`, status, source), its
type(s) as `(ne_type, validation)`, and its aliases as `(alias, lang)`. It is
**read-only** (opens the DB `mode=ro`) and is **not** wired into the analyzer — it is
the shape the future resolver's "check names before decomposition" hook (roadmap R3)
will call.

The load was **committed** on 2026-07-07 after Ramunas approved the preview gate: 272
entities are live in `lexicon_v2.db` (28 celestial + 244 physical_geographic, 13
`global_core`, 1213 en + 221 eo aliases; `concept*` untouched). The output below is
from the read CLI run against that **real loaded DB**:

```
$ query_named_entities.py Marso
'Marso' resolved -> Q111
  matched by   : label_eo
  type(s)      : celestial[correspondence]
  salience     : 290 (as of 2026-07-06)
  global_core  : no

$ query_named_entities.py Atlantiko
'Atlantiko' resolved -> Q97
  matched by   : label_eo
  type(s)      : physical_geographic[correspondence]
  salience     : 269 (as of 2026-07-06)
  global_core  : yes

$ query_named_entities.py Nilo
'Nilo' resolved -> Q3392
  matched by   : label_eo
  type(s)      : physical_geographic[correspondence]

$ query_named_entities.py Everesto
'Everesto' resolved -> Q513
  matched by   : alias:eo          <-- resolved via an EO *alias*
  label_eo     : Ĉomolungmo        <-- the primary EO label is NOT "Everesto"
  type(s)      : physical_geographic[correspondence]
```

Note explicitly: **`Everesto` resolves via an EO alias**, not a primary label. Mount
Everest's `label_eo` is `Ĉomolungmo`; `Everesto` is carried as an `eo` alias of
`Q513`. This is precisely why the D7 probe warned against relying on primary EO labels
alone for recall, and why the helper's resolution order includes an alias step — a
label-only lookup would miss it. Unknown terms print a clear "no match" line and the
CLI exits non-zero.

---

## Deferred scope (all later phases)

- **Institutional** (EU, UN, NATO, …) — not physical referents; subject to R6
  coherence-regime handling and to change over time. Out of v0.
- **Settlement** (cities) — mutable and a much larger open set. Out of v0.
- **Tier derivation** — assigning derived commonness against a reference group. This
  inventory deliberately stores none; it is a separate, later concern.
- **Discovery-from-documents** — mining names from corpus text (the deep, unprobed
  tail below the salient core). Later, once its EO coverage is measured.

---

## Why this serves the Tier-3 urgency

Tier 3 is near-empty and the pull is to fill it. **This inventory is the supply side**
for that work: a clean, salience-ranked, EO-labelled reservoir of stable entities.
When the tier-derivation step is built, promoting the group-invariant ones — the Moon,
the oceans, the continents, i.e. the `global_core` rows — into the derived common set
becomes a **query against this store**, not a fresh collection effort. We are stocking
the shelf now so the T3 work is assembly, not gathering.
