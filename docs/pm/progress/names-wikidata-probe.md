# Progress — D7 Wikidata feasibility probe (initiative: names-wikidata-probe)

**Session-restore record.** Programmer: update this at start and end.

- **Advisor brief:** [`../briefs/names-wikidata-probe.md`](../briefs/names-wikidata-probe.md)
- **Programmer brief (execute this):** [`../programmer/names-wikidata-probe.md`](../programmer/names-wikidata-probe.md)
- **Branch:** `analysis/names-wikidata-probe` (stacked on `analysis/merge-and-audit`; probe is
  independent of the lexicon merge — read-only Wikidata — and rebases onto main cleanly).
- **Status:** ✅ **COMPLETE — memo + sample TSV delivered, PR open (not merged).**

## The one question
How far down the salience curve does **Esperanto-label coverage** hold on Wikidata? Deliver a
per-set EO-coverage % × salience-depth table (top-50/200/1000) + go / no-go / qualified-go.

## Known constraint (PM-verified 2026-07-07)
Wikidata SPARQL API `https://query.wikidata.org/sparql` is reachable but **HTTP 429,
1 req/min** (active WDQS outage 797a132). Pace ≤1/min + cache, or use the **web GUI**
(not throttled) for manual pulls — see the human-in-the-loop contract in the Programmer brief.

## Human-in-the-loop
Ramunas can run queries in the browser GUI and drop `Download → JSON` files into
`data/analysis/names/manual_pulls/<set_key>.json`. The Programmer emits the `.rq` query files
+ `data/analysis/names/MANUAL_PULL_README.md` early (P0) as the signal for where to step in,
then consumes-or-fetches per set. Probe must also complete standalone.

## Deliverables (target)
`docs/names/wikidata_feasibility.md` (memo), `data/analysis/names/gazetteer_sample.tsv`,
`data/analysis/names/queries/*.rq` + README, tests. Gitignore `_cache/` + `manual_pulls/`.
Branch PR, no merge.

## Log
- 2026-07-07 (PM): branch + briefs set up; endpoint throttle verified; awaiting Programmer.

## Result (2026-07-06, Programmer)
**GO (qualified).** EO primary-label coverage = **783/786 = 99.6%** across all 17
closed sets, flat from top-of-list to the deepest depth probed (top-300 cities, 199
states). **No coverage cliff inside the salient core.** Memo:
[`../../names/wikidata_feasibility.md`](../../names/wikidata_feasibility.md).
Key findings:
- Coverage by coarse type: celestial 100%, physical-geo 100%, institutional 99.1%,
  settlement 99.7%. Only 3 genuine gaps in 786: ASEAN (no eo), Cardiff (eo alias only),
  Tschardakenhof (junk entry mis-typed as a sovereign state).
- **The "1 req/min WDQS outage" was a client-header artifact**, not a real limit: WMF
  edge 429s any request missing `Accept-Encoding`. Adding `Accept-Encoding: gzip`
  → healthy/fast. Probe now paces politely (3s) with 429 backoff as a safety net.
- **GUI "Download → JSON" ≠ SPARQL results JSON** (it's a simplified flat array).
  Parser accepts both; 6 sets came from Ramunas's GUI pulls, 11 from the API.
- Salience via `wikibase:sitelinks` is a clean biggest-first signal EXCEPT bare-`P31`
  celestial filters (major moons carry specific subclasses → curate small celestial
  sets by QID; fixed moons/stars this way).
- `P31`→coarse-type is clean for geo/settlement; Singapore correctly surfaces as
  multi-type (institutional+settlement) — schema must allow multi-type entities.
- Qualifications for the eventual build: seed salient core only (deep tail unprobed),
  curate celestial, key on primary eo labels (eo *aliases* thin: 23–89%), filter junk
  class members, carry `en` fallback for the ~0.4% gaps.

Deliverables: memo, `data/analysis/names/gazetteer_sample.tsv` (786 rows),
`queries/*.rq` + README, `src/analyzer/wikidata_probe.py`, `tests/test_wikidata_probe.py`
(37 tests, no network; full suite 733 passed). Scope respected: no lexicon writes, no
schema, no gazetteer.
- 2026-07-06 (Programmer, session start): read briefs + progress. Plan: (P0) build paced/cached
  SPARQL runner `src/analyzer/wikidata_probe.py`, emit per-set `.rq` files + `MANUAL_PULL_README.md`
  as the signal for Ramunas, verify anchor QIDs cheaply; (P1) consume-or-fetch per set; (P2) EO
  coverage % @ top-50/200/1000; (P3) salience/type/alias/licensing; write memo + sample TSV; pytest
  pure logic w/ fixtures. Gitignored `_cache/` + `manual_pulls/`. STATUS: 🔧 P0 in progress.
