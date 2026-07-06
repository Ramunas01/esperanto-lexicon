# Programmer brief — D7: Wikidata feasibility probe (names gazetteer)

Self-contained hand-off for a single Programmer agent. **Read-only, bounded probe** —
no lexicon writes, no schema, no gazetteer build. Answer one question with numbers:
**how far down the salience curve does Esperanto-label coverage hold on Wikidata?**
Source brief: `docs/PM_BRIEF_D7_wikidata_probe.md`. Branch `analysis/names-wikidata-probe`;
PR, no merge.

## Operating constraints (verified 2026-07-07 by PM)
- Endpoint `https://query.wikidata.org/sparql` is reachable BUT currently returns **HTTP 429,
  "1 req/min"** (an active WDQS outage, ref 797a132). **Pace at ≤1 request/minute**, cache every
  response to disk, and back off on 429 (exponential, cap ~5 min). The probe is ~18 queries →
  ~20–30 min wall-clock while throttled; that is fine. If the endpoint is fully down when you
  run, retry with backoff a few times, then **report the outage plainly and stop** — do not
  work around it with a full dump (out of scope for a probe).
- Wikidata requires a descriptive **User-Agent**. Use:
  `esperanto-lexicon-probe/0.1 (research; contact team@customsclear.net)`.
  Request `format=json`, `Accept: application/sparql-results+json`. `urllib`/`requests` both fine.
- No API key, no auth (public CC0 endpoint).

## Human-in-the-loop (Ramunas can offload the throttled part)
The programmatic endpoint is throttled to 1 req/min right now, but the **web GUI**
(`https://query.wikidata.org`) is not — a human can run each query in the browser and
**Download → JSON**. Design the probe to work **either way**:
- **P0 emits query files** `data/analysis/names/queries/<set_key>.rq` (one per set) plus a
  `data/analysis/names/MANUAL_PULL_README.md` that lists, per set: the exact query, the GUI
  link hint, and the exact save path `data/analysis/names/manual_pulls/<set_key>.json`.
  This is the **signal to Ramunas** — once these exist, he can start pulling in the browser.
- **P1 consumes-or-fetches:** for each set, if `manual_pulls/<set_key>.json` exists, parse it;
  else fetch via the paced API and cache. The SPARQL JSON the GUI downloads is byte-identical
  in shape to the API response, so **one parser handles both**. Log which sets came from
  manual pulls vs API.
- The probe must **complete fully standalone** if Ramunas does nothing (just slower under the
  throttle) — the manual pulls are an accelerator, not a dependency.

## P0 — harness + QID verification (do this first)
1. Small query runner: one function that takes a SPARQL string, sends it with the UA + 1/min
   pacing + on-disk cache (key = hash of query) under
   `data/analysis/names/_cache/` (gitignored). Re-runs hit cache, not the network. It must
   first check `data/analysis/names/manual_pulls/<set_key>.json` and use that if present.
2. Write the per-set `.rq` files + `MANUAL_PULL_README.md` (above) as early as possible so
   the human can begin.
3. **Verify the anchor QIDs** with a couple of cheap probes before the big pulls (labels drift):
   planet-of-Solar-System (not bare "planet" Q634, which includes exoplanets/dwarfs — prefer
   `wdt:P31 wd:Q634` filtered to Solar-System members, or a curated 8-planet QID list),
   Sun Q525, natural satellite Q2537, star Q523, ocean Q9430, continent Q5107, sea Q165,
   river Q4022, mountain Q8502, mountain range Q46831, desert Q8514, island Q23442,
   lake Q23397, strait Q37901, sovereign state Q3624078, supranational union Q1335818,
   city Q515. Note any that resolve wrong.

## P1 — per-set pulls (salience-sorted, biggest-first)
For each target set below, one SPARQL query: filter by the set's `P31` class, `ORDER BY
DESC(?sitelinks)`, `LIMIT` per the brief. Select `?item ?en ?eo ?sitelinks ?type` and
(OPTIONAL) `skos:altLabel` for en + eo aliases. EO label is OPTIONAL — its absence IS the
measurement. Cache each result.
- **Solar system:** 8 planets + Sun + ~20 major moons + ~5 nearest stars (Proxima, Alpha
  Centauri, Sirius, Barnard's…). (Small curated QID lists are acceptable where a clean P31
  filter is hard — note when you do this.)
- **Physical geography:** 5 oceans, 7 continents, major seas; top ~50 rivers, ~30 mountains,
  ~20 deserts, ~20 ranges, ~30 largest islands, ~20 lakes, ~15 straits.
- **Institutional:** major supranational unions/orgs (EU, UN, NATO, ASEAN, AU…); ~195
  sovereign states.
- **Settlements:** top ~300 cities by sitelinks.

## P2 — the headline measurement
For every set, compute **EO-label coverage %** at salience depths **top-50 / top-200 /
top-1000** (or the set's full size if smaller). This is the deliverable that decides go/no-go:
where does EO coverage fall off (the "coverage cliff")?

## P3 — secondary findings
- **Salience:** is `wikibase:sitelinks` a usable biggest-first ranking per set? (sanity-check
  a few — does the top of each list look right?)
- **Type mapping:** how cleanly does `P31` map to coarse types **celestial /
  physical-geographic / institutional / settlement**? Record messiness (multi-P31 entities,
  a city that is also a country, etc.).
- **Aliases:** does `skos:altLabel` yield alternates for en and eo? Coverage %.
- **Licensing/extraction:** confirm CC0 on Wikidata data; confirm the endpoint is queryable
  cheaply with LIMITs (or, given the current 429s, note the pacing reality).

## Deliverables
- `docs/names/wikidata_feasibility.md` — the memo. Lead with the **per-set EO-coverage % ×
  salience-depth table**, then salience usability, P31→coarse-type mapping + messiness, alias
  availability, licensing/extraction + the observed rate-limit, and a **go / no-go /
  qualified-go** recommendation that **names the coverage cliff explicitly**.
- `data/analysis/names/gazetteer_sample.tsv` — the actual pull:
  `qid, label_en, label_eo, coarse_type, sitelinks, aliases`. If it validates, this is the
  head-start on the seed.
- `data/analysis/names/queries/*.rq` + `MANUAL_PULL_README.md` — committed (durable, lets
  anyone reproduce or hand-pull).
- Tests: a small pytest for the pure bits (query builder, coverage-% computation, TSV writer,
  P31→coarse-type mapper) using cached/fixture JSON — **do not** hit the network in tests.

Gitignore the raw/regenerable bits: `data/analysis/names/_cache/` and
`data/analysis/names/manual_pulls/`. Commit the memo, sample TSV, query files, README, code,
tests, and `docs/pm/progress/names-wikidata-probe.md`.

## Scope bounds
Probe only. No full gazetteer, no `named_entity` schema, no resolver integration, no writes to
`lexicon_v2.db`. Report blockers (endpoint down, a set with poor EO coverage) plainly; don't
work around them.

## Success criteria
Memo answers the coverage question **with numbers** + a go/no-go; the sample TSV demonstrates
the salience-sorted, EO-labelled pull works end-to-end for at least planets, oceans, continents,
countries, and top cities. Update `docs/pm/progress/names-wikidata-probe.md` at start and end
(session-restore convention).
