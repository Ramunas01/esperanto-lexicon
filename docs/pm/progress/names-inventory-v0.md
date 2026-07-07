# Progress — Named-entity inventory v0 (initiative: names-inventory-v0)

**Session-restore record.**

- **Brief:** [`../../PM_BRIEF_names_inventory_v0.md`](../../PM_BRIEF_names_inventory_v0.md)
- **Branch:** `analysis/names-inventory-v0` (stacked on `analysis/names-wikidata-probe`,
  which carries the D7 sample TSV this loads).
- **Status:** ✅ **COMPLETE — load committed (human-gated), PR open, not merged.**

## What was built
Turned the D7 sample (786 rows) into a persistent, queryable inventory of the
physically-permanent core (celestial + physical-geographic only).

- **Store** — `schema.create_named_entity_schema`: `named_entity` /
  `named_entity_type` / `named_entity_alias` in `lexicon_v2.db`, strictly separate
  from `concept*`. **No `tier` column** (R8); only dated `sitelinks` salience.
  `global_core` = group-invariance flag (Moon/oceans/continents), not a tier.
  Applied via `migrate_named_entities.py` (additive, backed up).
- **Loader** — `src/lexicon/load_named_entities.py`: reads
  `data/analysis/names/gazetteer_sample.tsv`, filters to the two permanent types,
  insert-only + idempotent on `qid` (re-run refreshes salience only), backs up the DB,
  preview-by-default / `--commit`-gated. 12 tests.
- **Read API** — `src/lexicon/query_named_entities.py`: `resolve()` + CLI, order
  qid → label_eo → label_en → alias (eo>en), then case-insensitive. Read-only. 13 tests.
- **Memo** — `docs/names/named_entity_inventory_v0.md`.

## Loaded (committed 2026-07-07, Ramunas approved the preview gate)
272 distinct entities (28 celestial + 244 physical_geographic; 275 raw rows − 3 cross-set
duplicate QIDs: Indian Ocean/English Channel/Caspian Sea). `global_core`=13. All
`validation='correspondence'`; all 272 carry an EO label; aliases 1213 en + 221 eo.
`concept` untouched (4974). No tier column (asserted). Idempotent re-run verified.
Read API resolves `Marso`, `Atlantiko`, `Nilo`, `Luno` (label_eo), `Everesto`
(eo alias; primary label `Ĉomolungmo`), `Q98` (qid); `sukero` → no match.

## Data-quality fix caught at the gate (matters for D7 / PR #9)
The preview surfaced 5 drifted `stars` QIDs in the D7 sample pointing to unrelated
items *with* EO labels (Q11002→sugar/`sukero`, Q3037→Kathmandu, Q3033→Göttingen,
Q12167→malnutrition, Q14001→malware) — they had falsely scored as celestial coverage
in the probe. Corrected `_STAR_QIDS` in `wikidata_probe.py` (Sirius Q3409, Proxima
Q14266, Barnard's Q14268, Betelgeuse Q12124, Vega Q3427; Alpha Centauri Q12176 kept),
removed the stale `manual_pulls/stars.json`, regenerated the sample. Also lang-tagged
the sample's alias column (`en:`/`eo:`) so the alias table could be populated faithfully.

## Deferred (stated in memo)
Institutional + settlement entities, tier derivation, discovery-from-documents.

## Log
- 2026-07-07: built store + loader + read API + memo via 2 parallel programmer agents;
  caught & fixed the D7 star-QID drift at the preview gate; Ramunas approved; load
  committed; PR opened (no merge).
