# Manual pull instructions -- D7 Wikidata names probe

The programmatic SPARQL endpoint is throttled to ~1 req/min (WDQS
outage). The **web GUI is not throttled**. You can run any/all of the
queries below in the browser to speed the probe up; the probe also
completes standalone if you do nothing.

## How to hand-pull a set
1. Open <https://query.wikidata.org>.
2. Open the query file `data/analysis/names/queries/<set_key>.rq`,
   paste its body into the editor (the leading `#` comment lines are
   fine to include), and run it (Ctrl+Enter).
3. Click **Download -> JSON**.
4. Save it to `data/analysis/names/manual_pulls/<set_key>.json`
   (exact set_key from the table below -- the filename is the contract).

The probe checks `manual_pulls/<set_key>.json` first for every set; if
present it uses your file, else it fetches via the paced API. Either
way it logs the source per set.

## Sets

| set_key | what | limit | save as |
| --- | --- | --- | --- |
| `planets` | Planets of the Solar System | 10 | `manual_pulls/planets.json` |
| `sun` | The Sun | 5 | `manual_pulls/sun.json` |
| `moons` | Major natural satellites | 30 | `manual_pulls/moons.json` |
| `stars` | Nearest / brightest named stars | 10 | `manual_pulls/stars.json` |
| `oceans` | Oceans | 10 | `manual_pulls/oceans.json` |
| `continents` | Continents | 12 | `manual_pulls/continents.json` |
| `seas` | Seas | 40 | `manual_pulls/seas.json` |
| `rivers` | Rivers | 50 | `manual_pulls/rivers.json` |
| `mountains` | Mountains | 30 | `manual_pulls/mountains.json` |
| `deserts` | Deserts | 20 | `manual_pulls/deserts.json` |
| `ranges` | Mountain ranges | 20 | `manual_pulls/ranges.json` |
| `islands` | Largest islands | 30 | `manual_pulls/islands.json` |
| `lakes` | Lakes | 20 | `manual_pulls/lakes.json` |
| `straits` | Straits | 15 | `manual_pulls/straits.json` |
| `orgs` | Supranational unions / major orgs | 15 | `manual_pulls/orgs.json` |
| `sovereign_states` | Sovereign states | 200 | `manual_pulls/sovereign_states.json` |
| `cities` | Cities by sitelinks | 300 | `manual_pulls/cities.json` |

All sets are salience-sorted `ORDER BY DESC(?sitelinks)`. EO label
is OPTIONAL in every query -- its absence is exactly what we are
measuring, so do not filter it out.
