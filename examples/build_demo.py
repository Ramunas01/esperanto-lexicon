#!/usr/bin/env python3
"""Build a demo bundle from three toy domains (customs / cooking / law).

Run from the repo root (needs lexicon_v2.db + eo_inventory.json)::

    python examples/build_demo.py

Writes ``examples/demo.bundle``, which score_demo.py then loads.
"""

from __future__ import annotations

from pathlib import Path

from eolex_relevance.build import build_bundle

REPO = Path(__file__).resolve().parents[1]
LEXICON_DB = REPO / "data" / "lexicon_db" / "lexicon_v2.db"
INVENTORY = REPO / "data" / "lexicon_db" / "eo_inventory.json"
OUT = Path(__file__).resolve().parent / "demo.bundle"

# Domains as explicit Esperanto term lists. (Swap in source="corpus" with a
# path, or source="db" with a query, for the other two ingestion modes.)
DOMAIN_SPECS = [
    {
        "name": "customs",
        "source": "terms",
        "lang": "eo",
        "terms": ["importi", "eksporti", "deklaro", "imposto", "doganaĵo",
                  "tarifo", "transito"],
    },
    {
        "name": "cooking",
        "source": "terms",
        "lang": "eo",
        "terms": ["kuiri", "baki", "boli", "rostita", "pomo", "legomo",
                  "spico", "recepto"],
    },
    {
        "name": "law",
        "source": "terms",
        "lang": "eo",
        "terms": ["leĝo", "juĝisto", "kontrakto", "verdikto", "tribunalo",
                  "rajto", "kulpa"],
    },
]


def main() -> None:
    if not (LEXICON_DB.exists() and INVENTORY.exists()):
        raise SystemExit(
            "Missing lexicon assets. Regenerate eo_inventory.json "
            "(src/lexicon/build_eo_inventory.py) and lexicon_v2.db first."
        )
    bundle = build_bundle(
        DOMAIN_SPECS,
        lexicon_db=LEXICON_DB,
        inventory=INVENTORY,
        out_path=OUT,
        langs=["eo", "en", "lt"],
        use_spacy=False,
    )
    print(f"Built {OUT}")
    print(f"  domains : {bundle.domains}")
    print(f"  vocab   : {len(bundle.vocab)} roots")
    print(f"  built   : {bundle.meta['build_date']}")


if __name__ == "__main__":
    main()
