# Licensing and provenance

This file records the licenses of third-party data and rationale for
project-specific data files committed to this repository. Code in this
repository is licensed separately (see the repository's main license
file).

## Inventory data

### ESPDIC (primary root source)

`src/lexicon/build_eo_inventory.py` derives the Esperanto root inventory
(committed locally to `data/lexicon_db/eo_inventory.json`,
`data/lexicon_db/akademio_roots.txt` — gitignored, regenerated at build
time) from:

  * **Source**: ESPDIC, compiled by Paul Denisowski.
  * **License**: Creative Commons Attribution 3.0 (CC-BY-3.0).
  * **Upstream URL**: <https://raw.githubusercontent.com/drandre2014/ESPDIC/master/espdic.txt>
  * **Fetch**: at build time by the inventory builder; not vendored in
    the repository.

Attribution: glosses and headwords in the generated inventory derive from
Paul Denisowski's ESPDIC and are used under CC-BY-3.0. Re-published
derivatives must retain this attribution.

### Standard Esperanto morphology

The affix, correlative, and ending tables hardcoded in
`build_eo_inventory.py` are public-domain grammatical facts of the
language (no copyrightable expression).

## Project-authored data files

### `data/lexicon_db/eo_roots_supplement.tsv`

Curated modern-roots supplement (Part A of the inventory-hygiene PR).
Human-authored project data: each entry is a short root + factual gloss
+ provenance note. No third-party license entanglement. Glosses are
short factual definitions of modern borrowings (`kampus`, `dvd`, …) and
are not copyrightable expression.

### `data/lexicon_db/eo_reduce_exceptions.txt`

One stem per line that must not be reduced by the orthographic
primitive-extractor (Part B). Human-curated, evidence-driven. No
third-party data.

## Domain data

Domain extractions under `data/domain_db/*.db` source from EUR-Lex,
WCO publications, and other public-sector materials. Their individual
licenses are recorded in `docs/eurlex_pipeline.md` and in the per-source
documentation under `docs/`. Domain `.db` files are gitignored — only
the extractors and schema are committed.
