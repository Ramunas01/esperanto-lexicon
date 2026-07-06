# Progress — D7 Wikidata feasibility probe (initiative: names-wikidata-probe)

**Session-restore record.** Programmer: update this at start and end.

- **Advisor brief:** [`../briefs/names-wikidata-probe.md`](../briefs/names-wikidata-probe.md)
- **Programmer brief (execute this):** [`../programmer/names-wikidata-probe.md`](../programmer/names-wikidata-probe.md)
- **Branch:** `analysis/names-wikidata-probe` (stacked on `analysis/merge-and-audit`; probe is
  independent of the lexicon merge — read-only Wikidata — and rebases onto main cleanly).
- **Status:** ⏳ **NOT STARTED — ready for a Programmer session.** PM set up the branch,
  briefs, and human-in-the-loop contract. No queries run yet, no PR.

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
- 2026-07-06 (Programmer, session start): read briefs + progress. Plan: (P0) build paced/cached
  SPARQL runner `src/analyzer/wikidata_probe.py`, emit per-set `.rq` files + `MANUAL_PULL_README.md`
  as the signal for Ramunas, verify anchor QIDs cheaply; (P1) consume-or-fetch per set; (P2) EO
  coverage % @ top-50/200/1000; (P3) salience/type/alias/licensing; write memo + sample TSV; pytest
  pure logic w/ fixtures. Gitignored `_cache/` + `manual_pulls/`. STATUS: 🔧 P0 in progress.
