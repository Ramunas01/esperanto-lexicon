# PM brief — D7: Wikidata feasibility probe for the names gazetteer

A **bounded, read-only feasibility probe** (not a build). Answer one decision: is Wikidata a
viable source to *seed* the physically-anchored names core — CC0, salience-sortable, and
already carrying **Esperanto labels** so we avoid the one-by-one translation grind the
common-lexicon gap-fill required? Produce a memo + a sample pull. No lexicon writes, no
schema design (that's a later item), no human gate needed — leave the memo for review.

## The one question that decides everything
**How far down the salience curve does Esperanto-label coverage hold?** The whole
"seed, don't translate" plan rests on Wikidata having `eo` labels for these entities. So the
headline deliverable is a **per-set EO-label coverage %** at increasing salience depth
(e.g. top-50 / top-200 / top-1000 by sitelinks). If EO coverage is ~complete for the salient
core and only thins in the tail, the answer is "seed it." If it's patchy even for salient
entities, we fall back toward discovery-from-documents.

## Secondary questions
- **Salience signal:** does `wikibase:sitelinks` give a usable "biggest first" ranking to
  threshold each set (avoids overcrowding)? This doubles as the R7 salience attribute.
- **Type mapping:** how cleanly does `P31` (instance-of) map to our intended coarse types
  — celestial / physical-geographic / institutional / settlement? Note messiness (e.g. a
  city that is also a country).
- **Aliases:** does `skos:altLabel` give alternate names (both en and eo)?
- **Licensing/extraction:** confirm CC0; confirm the public SPARQL endpoint
  (`https://query.wikidata.org/sparql`) is queryable cheaply with `LIMIT`s, or whether a dump
  is needed.

## Target closed sets to pull (bounded — a few thousand entities total)
Salience-thresholded, biggest-first:
- **Solar system:** 8 planets, the Sun, ~20 major moons, a handful of nearest stars
  (Proxima/Alpha Centauri, Sirius, Barnard's).
- **Physical geography:** 5 oceans, 7 continents, major seas; top ~50 rivers, ~30 mountains,
  ~20 deserts, ~20 mountain ranges, ~30 largest islands, ~20 lakes, ~15 notable straits.
- **Institutional (Searle's institutional facts — the "fictional" tier):** major supranational
  unions/orgs (EU, UN, NATO, ASEAN, African Union…); ~195 current sovereign states.
- **Settlements:** top ~300 cities by sitelinks.

## Method
SPARQL against `https://query.wikidata.org/sparql` (the user's environment has open internet;
be polite — `LIMIT`, cache results locally, don't hammer). For each set: filter by the right
`P31` class, pull `?item`, English label, **Esperanto label (may be absent)**, `sitelinks`,
`P31` type, aliases. Example shape:

```sparql
SELECT ?item ?en ?eo ?sitelinks ?type WHERE {
  ?item wdt:P31 wd:Q6256 .                 # instance of: country (adjust QID per set)
  ?item wikibase:sitelinks ?sitelinks .
  OPTIONAL { ?item rdfs:label ?en FILTER(lang(?en)="en") }
  OPTIONAL { ?item rdfs:label ?eo FILTER(lang(?eo)="eo") }   # the coverage question
  OPTIONAL { ?item wdt:P31 ?type }
} ORDER BY DESC(?sitelinks) LIMIT 300
```
Useful QIDs to anchor the queries (verify): planet Q634 / planet-of-Solar-System, ocean
Q9430, continent Q5107, sovereign state Q3624078, city Q515, river Q4022, mountain Q8502,
desert Q8514, island Q23442, natural-satellite Q2537, supranational-union Q1335818.

## Deliverables
- `docs/names/wikidata_feasibility.md` — the memo: per-set **EO-coverage % vs salience depth**
  (the headline table), salience-ranking usability, `P31`→coarse-type mapping notes and
  messiness, alias availability, licensing/extraction method, and a clear **go / no-go /
  qualified-go** recommendation with the coverage cliff (where EO coverage falls off) named
  explicitly.
- `data/analysis/names/gazetteer_sample.tsv` — the actual sample pull
  (`qid, label_en, label_eo, coarse_type, sitelinks, aliases`). If it validates, this *is* the
  start of the seed, so the probe doubles as a head-start.

## Scope bounds (keep it a probe)
Do NOT build the full gazetteer, design the `named_entity` table, integrate with the resolver,
or write anything to `lexicon_v2.db`. Just: pull the closed core, measure EO coverage, write
the memo. Branch `analysis/names-wikidata-probe`; PR; no merge.

## Success criteria
The memo answers the headline coverage question **with numbers** and a go/no-go; the sample
TSV demonstrates the salience-sorted, EO-labelled pull works end-to-end for at least the
planets, oceans, continents, countries, and top cities. Anything blocked (endpoint limits,
a set with poor EO coverage) is reported plainly rather than worked around.
