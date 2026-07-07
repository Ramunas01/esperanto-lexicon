# D7 — Wikidata feasibility probe for the names gazetteer

**Read-only feasibility probe. No lexicon writes, no schema, no gazetteer build.**
Programmer session 2026-07-06, branch `analysis/names-wikidata-probe`.

One decision to answer with numbers: **is Wikidata a viable source to *seed* the
physically-anchored names core — CC0, salience-sortable, and already carrying
Esperanto labels** so we skip the one-by-one translation grind the common-lexicon
gap-fill required? The whole "seed, don't translate" plan rests on Wikidata having
`eo` labels for salient entities, so the headline is **EO-label coverage % vs.
salience depth**, per set.

## TL;DR — GO (qualified)

**EO primary-label coverage is effectively complete for the salient core: 783 / 786
= 99.6%** across every closed set we pulled, holding flat from the top of each list
down to the deepest depth we probed (top-300 cities, 199 sovereign states). **There
is no coverage cliff within the salient range.** Seed it.

The three qualifications (none block a GO):
1. **The deep settlement tail is unprobed.** We only reached top-300 cities and ~199
   states — every salient entity. Coverage almost certainly thins for the long tail
   (villages, minor rivers/peaks below the top few hundred per set); that tail was
   out of scope and remains unmeasured. Seed the salient core; treat the tail as
   discovery-from-documents until measured.
2. **Celestial minor bodies need curated QID lists, not a bare `P31` filter.** A naive
   `?x wdt:P31 wd:Q2537` (natural satellite) ranked by sitelinks surfaces obscure
   provisional-designation moons (`S/2015 (136472) 1` …) with ~3% EO coverage and
   *misses every famous moon*. The major moons all have EO labels (Luno, Eŭropo,
   Titano, Ganimedo…, 13/13); they carry more specific `P31` subclasses, so the bare
   filter never returns them. Use curated lists for small celestial sets (as we did
   for planets and stars).
3. **Do not rely on EO *aliases*.** Primary `eo` labels are ~complete, but `eo`
   `skos:altLabel` coverage is thin and uneven (23–89% per set; 40% for cities).
   English aliases are much richer. Alias-based matching in EO will miss; primary-
   label matching will not.

A handful of individual gaps exist and are named below (ASEAN, Cardiff, one junk
"sovereign state") — three entities out of 786. Fall back to `en` for those or add a
one-off `eo` label; they do not change the picture.

---

## Headline — EO primary-label coverage × salience depth

Coverage = share of entities in the top-N-by-sitelinks whose Wikidata record carries
a non-empty `eo` `rdfs:label`. Depth collapses to set size when the set is smaller
than the depth (reported as the actual `n`). Salience-sorted biggest-first by
`wikibase:sitelinks`.

| set | coarse type | n | src | @50 | @200 | @1000 | eo-alias % |
| --- | --- | ---: | --- | --- | --- | --- | ---: |
| planets | celestial | 8 | manual | 100% (8/8) | 100% | 100% | 25% |
| sun | celestial | 1 | manual | 100% (1/1) | 100% | 100% | 100% |
| moons (curated major) | celestial | 13 | api | 100% (13/13) | 100% | 100% | 23% |
| stars | celestial | 6 | api | 100% (6/6) | 100% | 100% | 33% |
| oceans | physical-geo | 10 | api | 100% (10/10) | 100% | 100% | 50% |
| continents | physical-geo | 12 | manual | 100% (12/12) | 100% | 100% | 33% |
| seas | physical-geo | 40 | api | 100% (40/40) | 100% | 100% | 42% |
| rivers | physical-geo | 50 | api | 100% (50/50) | 100% | 100% | 34% |
| mountains | physical-geo | 30 | api | 100% (30/30) | 100% | 100% | 40% |
| deserts | physical-geo | 20 | manual | 100% (20/20) | 100% | 100% | 65% |
| ranges | physical-geo | 20 | api | 100% (20/20) | 100% | 100% | 50% |
| islands | physical-geo | 30 | manual | 100% (30/30) | 100% | 100% | 57% |
| lakes | physical-geo | 20 | api | 100% (20/20) | 100% | 100% | 45% |
| straits | physical-geo | 15 | api | 100% (15/15) | 100% | 100% | 40% |
| orgs | institutional | 12 | api | 92% (11/12) | 92% | 92% | 75% |
| sovereign_states | institutional | 199 | manual | 100% (50/50) | 99% (198/199) | 99% | 89% |
| cities | settlement | 300 | manual | 100% (50/50) | 100% (199/200) | 100% (299/300) | 40% |

**By coarse type:** celestial 28/28 = 100.0% · physical-geographic 247/247 = 100.0% ·
institutional 209/211 = 99.1% · settlement 299/300 = 99.7%. **Grand total 783/786 =
99.6%.**

`src` = whether the set came from a human GUI pull (`manual`) or the paced API
(`api`/`cache`). Both formats parsed by one parser; see Extraction below.

### The only genuine EO gaps in the salient core (3 of 786)
- **ASEAN** (`Q7768`, orgs) — no `eo` label on Wikidata at all. (The other 11 orgs
  incl. UN, NATO, WTO, IMF, OPEC, WHO all have `eo` labels.)
- **Tschardakenhof** (`sovereign_states`) — **not a real state**; a junk entity
  mis-typed `P31 = sovereign state`. Illustrates that class filters need a junk
  filter, not that states lack EO. The other 198 states all have `eo` labels.
- **Cardiff** (`Q10690`, cities) — has an `eo` *alias* ("Kardifo") but no `eo`
  primary label. 1 of 300.

### Where the cliff actually is
Not inside anything we measured. The genuine EO drop-offs sit **outside the salient
core**: (a) obscure/provisional celestial bodies (irrelevant to a names core), and —
by strong inference, unprobed here — (b) the deep settlement/feature tail below the
top few hundred per set. For the entities a Tier-1–3 world model actually needs, EO
coverage does not fall off.

---

## Secondary findings

### Salience — is `wikibase:sitelinks` a usable biggest-first ranking?
**Yes, for every set except naive celestial filters.** Spot-checks of the list heads
are exactly right: cities → London, Paris, New York…; states → United States,
Germany, France…; continents → Europe, Africa, Asia…; deserts → Sahara, Gobi….
`sitelinks` is a clean, cheap salience signal and doubles as the R7 salience
attribute. **One gotcha:** ranking a bare `P31` class by sitelinks assumes the famous
members carry that exact `P31` — false for moons (major moons use more specific
subclasses), so the bare filter returns only the long-tail members. Curate small
celestial sets; the class-filter approach is sound for geography, states, and cities.

### Type mapping — how cleanly does `P31` map to coarse types?
Cleanly for the buckets that matter. Each set declares its authoritative coarse type
(used in the sample TSV); independently, a `P31`→coarse mapper classified every raw
`P31` QID each entity carries. Result over 786 rows: **765 map to exactly the intended
coarse type, 2 are genuinely mixed, 19 are "unmapped".**
- **Mixed (2):** **Singapore** = `institutional + settlement` — the textbook
  "city that is also a country". It legitimately appears in both `sovereign_states`
  and `cities`. This is real cross-type-ness the schema must represent (an entity can
  hold multiple coarse types), not an error.
- **Unmapped (19):** concentrated in `moons` (13) and `stars` (4) — celestial bodies
  carry many specific subclass QIDs (e.g. "moon of Jupiter") the curated mapper does
  not enumerate — plus 2 orgs. These are mapper-coverage gaps, not data problems; the
  set's declared coarse type is authoritative. Physical-geography and settlements map
  with zero ambiguity.

Takeaway: `P31` → coarse type is reliable for geography/settlement, needs a small
curated subclass table for celestial, and **must allow multi-type entities**
(Singapore). No entity was silently mis-bucketed.

### Aliases — does `skos:altLabel` yield alternates?
- **English aliases: rich** — 45–100% of rows per set carry ≥1 `en` alias (e.g. Earth:
  "The Blue Planet", "Mother Earth"; USA: "the USA", "US of America", …).
- **Esperanto aliases: thin and uneven** — 23–89% per set, 40% for cities. Usable as a
  *bonus* recall signal where present, **not** as a dependency. Primary `eo` labels
  are the reliable key.

### Licensing / extraction
- **Licensing: CC0.** Wikidata's structured data is released under Creative Commons
  CC0 1.0 (public-domain dedication) — no attribution required, free to seed a lexicon.
- **Endpoint is queryable cheaply with `LIMIT`s.** With the fix below, all 17 sets
  pulled in well under a minute of network time; the subquery-then-annotate query
  shape keeps joins small even for 300-city pulls.
- **The reported "1 req/min WDQS outage" was a client-header artifact, not a real
  rate limit.** The WMF SPARQL CDN edge hard-throttles (`HTTP 429`, `Retry-After:
  1000`, Wikimedia error HTML) **any request that omits an `Accept-Encoding` header** —
  an anti-scraper heuristic that fires regardless of pacing. An identical `curl`
  (which sends `Accept-Encoding` by default) returned `200` instantly at the same
  moment the bare `urllib` probe got `429`. Adding `Accept-Encoding: gzip, deflate`
  (and gzip-decoding the response) made the endpoint fast and healthy. The earlier
  "outage" diagnosis was almost certainly the same missing-header artifact in a naive
  probe client. We still pace politely (3 s between requests) and keep exponential
  `429` backoff as a genuine-overload safety net.
- **Two JSON shapes in the wild.** The API returns SPARQL results-object JSON
  (`{"results":{"bindings":[{"item":{"value":…}}]}}`); the Wikidata GUI's
  **"Download → JSON"** returns a *simplified flat array*
  (`[{"item":"http://…/Q42","en":"Earth",…}]`). These are **not** byte-identical (the
  brief assumed they were). The probe's parser accepts both, so human GUI pulls and
  API fetches are interchangeable — which is how 6 of the 17 sets in this run came
  straight from Ramunas's browser downloads.

---

## Human-in-the-loop outcome
The probe emitted 17 per-set `.rq` files + `MANUAL_PULL_README.md` first (P0), so
Ramunas could hand-pull in the unthrottled GUI immediately. He pulled 6 sets
(`planets`, `continents`, `deserts`, `islands`, `sovereign_states`, `cities`); the
probe consumed those and fetched the other 11 via the paced API. Both paths produced
identical Row shapes and the run completed end-to-end. The manual pulls were an
accelerator, not a dependency — the probe would have completed standalone.

---

## Recommendation

**GO (qualified): seed the physically-anchored + institutional + top-settlement names
core from Wikidata.** EO primary labels are effectively complete (99.6%) for salient
entities, which removes the translation grind that motivated the question. Proceed to
design the `named_entity` schema (separate item) with these constraints baked in:

1. **Seed the salient core only** (top-N by sitelinks per set); leave the deep tail to
   document-discovery until its EO coverage is measured.
2. **Curate small celestial sets** by QID; do not rely on bare `P31` + sitelinks for
   moons/stars.
3. **Key on primary `eo` labels; treat `eo` aliases as optional recall.** Carry `en`
   as the documented fallback (`eo → en → source_language`) for the ~0.4% of salient
   entities with no `eo` label (ASEAN, Cardiff, …).
4. **Filter junk class members** (e.g. `Tschardakenhof` typed as a sovereign state) —
   a sitelinks floor plus a sanity check on the label handles most.
5. **Model multi-type entities** — Singapore is both institutional and settlement; the
   schema must allow an entity to carry more than one coarse type.

## Reproducing / artifacts
- Code: `src/analyzer/wikidata_probe.py` (`emit-queries` | `verify` | `run`).
- Queries: `data/analysis/names/queries/*.rq` (committed) + `MANUAL_PULL_README.md`.
- Sample pull: `data/analysis/names/gazetteer_sample.tsv`
  (`qid, label_en, label_eo, coarse_type, sitelinks, aliases`; 786 rows) — this is the
  head-start on the seed.
- Machine-readable run summary: `data/analysis/names/run_report.json`.
- Raw cache + manual GUI pulls: `data/analysis/names/_cache/`,
  `data/analysis/names/manual_pulls/` (both gitignored — regenerable).
- Tests: `tests/test_wikidata_probe.py` (37 tests, fixtures only — no network).
