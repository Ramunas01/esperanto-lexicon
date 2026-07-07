#!/usr/bin/env python3
"""Load the physically-permanent named-entity core into ``lexicon_v2.db``.

Insert-only, idempotent loader for the D7 Wikidata gazetteer sample. Reads
``data/analysis/names/gazetteer_sample.tsv``, filters to the two physically-
permanent coarse types (``celestial`` and ``physical_geographic``), and
populates the sibling ``named_entity`` / ``named_entity_type`` /
``named_entity_alias`` tables. It never touches ``concept`` /
``concept_root`` / ``concept_lang``.

Design rules (roadmap R8 — enforced by the schema, honoured here):
  * No ``tier`` is ever stored. The inventory records only sourced ``sitelinks``
    salience, dated via ``sitelinks_asof``.
  * ``global_core`` is a group-INVARIANCE flag (the Moon, the canonical oceans
    and continents) — NOT a tier and NOT a numeric level. It merely marks the
    entities a future tier-derivation step will promote wholesale.

Idempotency: keyed on ``qid``. ``named_entity`` uses ``ON CONFLICT(qid)`` to
refresh salience only (never duplicate); the type/alias junctions use
``INSERT OR IGNORE`` (their UNIQUE constraints make re-runs no-ops).

Human gate: the loader defaults to a PREVIEW (dry-run) that writes nothing and
prints counts by type, the global_core count, alias counts by lang, and the
full row list. An explicit ``--commit`` is required to persist; ``--commit``
backs up the DB first, then runs one transaction.

Usage:
    python3 src/lexicon/load_named_entities.py            # preview (rolls back)
    python3 src/lexicon/load_named_entities.py --commit   # gated real write
"""

from __future__ import annotations

import argparse
import csv
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from schema import create_named_entity_schema  # noqa: E402

# Physically-permanent coarse types kept by this loader. Everything else
# (institutional, settlement) is deferred to later phases (see PM brief).
PERMANENT_TYPES = frozenset({"celestial", "physical_geographic"})

# global_core = group-INVARIANCE flag, NOT a tier. This curated allowlist is the
# set of truly reference-group-independent entities: the Moon, the five canonical
# oceans, and the seven continents. A future tier-derivation step promotes these
# wholesale into the common set; the flag does not encode any numeric level.
GLOBAL_CORE_QIDS = frozenset(
    {
        "Q405",  # Moon
        # Oceans
        "Q97",  # Atlantic Ocean
        "Q98",  # Pacific Ocean
        "Q1239",  # Indian Ocean
        "Q788",  # Arctic Ocean
        "Q7354",  # Southern Ocean
        # Continents
        "Q46",  # Europe
        "Q15",  # Africa
        "Q48",  # Asia
        "Q18",  # South America
        "Q51",  # Antarctica
        "Q49",  # North America
        "Q55643",  # Oceania
    }
)

# The known junk row: an institutional entity mis-typed as a sovereign state.
# It is dropped by the type filter; we assert its absence to prove it.
JUNK_QID = "Q105646554"  # Tschardakenhof

DEFAULT_SITELINKS_ASOF = "2026-07-06"  # the D7 pull date


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _parse_aliases(raw: str) -> list[tuple[str, str]]:
    """Parse the ``aliases`` cell into ``[(lang, alias), ...]``.

    Tokens are ``;``-joined and each is split on its FIRST ``:`` into a
    lang tag and the alias text (which may itself contain colons). Empty or
    tagless tokens are skipped.
    """
    out: list[tuple[str, str]] = []
    for token in raw.split(";"):
        token = token.strip()
        if not token or ":" not in token:
            continue
        lang, _, alias = token.partition(":")
        lang, alias = lang.strip(), alias.strip()
        if lang and alias:
            out.append((lang, alias))
    return out


def load_rows(tsv_path: Path) -> list[dict]:
    """Read the gazetteer TSV and filter to physically-permanent types.

    Returns the kept, qid-deduplicated rows as dicts with a parsed
    ``alias_pairs`` list and a resolved ``global_core`` int. The current sample
    contains a handful of exact duplicate-qid rows (e.g. Q1239 Indian Ocean),
    so first occurrence wins here — this mirrors the loader's write-time
    idempotency (upsert on ``qid``) and keeps the preview counts honest. Asserts
    the known junk row and any institutional/settlement rows did not leak
    through the type filter.
    """
    with tsv_path.open(encoding="utf-8") as fh:
        raw_rows = list(csv.DictReader(fh, delimiter="\t"))

    kept: list[dict] = []
    seen_qids: set[str] = set()
    for r in raw_rows:
        coarse_type = (r.get("coarse_type") or "").strip()
        if coarse_type not in PERMANENT_TYPES:
            continue
        qid = (r.get("qid") or "").strip()
        if qid in seen_qids:
            continue  # exact duplicate-qid row — first occurrence already kept
        seen_qids.add(qid)
        label_eo = (r.get("label_eo") or "").strip()
        label_en = (r.get("label_en") or "").strip()
        alias_pairs = _parse_aliases(r.get("aliases") or "")
        # EN-label fallback: rows with no EO primary label carry their EN label
        # as an alias so the resolver can still find them by name. In the current
        # sample zero permanent-type rows lack an EO label (the only EO gaps,
        # Cardiff/ASEAN, are institutional/settlement and thus excluded), so this
        # path is defensive for when the sample grows.
        if not label_eo and label_en:
            alias_pairs = alias_pairs + [("en", label_en)]
        kept.append(
            {
                "qid": qid,
                "label_eo": label_eo,  # "" here means "no EO label" → NULL on write
                "label_en": label_en,
                "coarse_type": coarse_type,
                "sitelinks": int((r.get("sitelinks") or "0").strip() or 0),
                "alias_pairs": alias_pairs,
                "global_core": 1 if qid in GLOBAL_CORE_QIDS else 0,
            }
        )

    kept_qids = {r["qid"] for r in kept}
    assert JUNK_QID not in kept_qids, (
        f"junk row {JUNK_QID} (Tschardakenhof) leaked past the type filter"
    )
    leaked = {r["coarse_type"] for r in kept} - PERMANENT_TYPES
    assert not leaked, f"non-permanent types leaked through the filter: {leaked}"
    return kept


def _upsert_rows(conn: sqlite3.Connection, rows: list[dict], asof: str) -> dict:
    """Insert/update all kept rows inside the caller's open transaction.

    Returns a stats dict. ``named_entity`` upserts on ``qid`` (refresh salience);
    the type/alias junctions use ``INSERT OR IGNORE`` so re-runs are no-ops.
    """
    inserted_by_type: dict[str, int] = {}
    updated_by_type: dict[str, int] = {}
    alias_by_lang: dict[str, int] = {}

    for r in rows:
        existing = conn.execute(
            "SELECT id FROM named_entity WHERE qid = ?", (r["qid"],)
        ).fetchone()
        is_new = existing is None

        conn.execute(
            """
            INSERT INTO named_entity
                (qid, label_eo, label_en, sitelinks, sitelinks_asof,
                 source, global_core, status)
            VALUES (?, ?, ?, ?, ?, 'wikidata', ?, 'active')
            ON CONFLICT(qid) DO UPDATE SET
                sitelinks = excluded.sitelinks,
                sitelinks_asof = excluded.sitelinks_asof
            """,
            (
                r["qid"],
                r["label_eo"] or None,  # empty EO label → NULL
                r["label_en"] or None,
                r["sitelinks"],
                asof,
                r["global_core"],
            ),
        )
        entity_id = conn.execute(
            "SELECT id FROM named_entity WHERE qid = ?", (r["qid"],)
        ).fetchone()[0]

        conn.execute(
            """
            INSERT OR IGNORE INTO named_entity_type (entity_id, ne_type, validation)
            VALUES (?, ?, 'correspondence')
            """,
            (entity_id, r["coarse_type"]),
        )
        for lang, alias in r["alias_pairs"]:
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO named_entity_alias (entity_id, alias, lang)
                VALUES (?, ?, ?)
                """,
                (entity_id, alias, lang),
            )
            if cur.rowcount:
                alias_by_lang[lang] = alias_by_lang.get(lang, 0) + 1

        bucket = inserted_by_type if is_new else updated_by_type
        bucket[r["coarse_type"]] = bucket.get(r["coarse_type"], 0) + 1

    return {
        "inserted_by_type": inserted_by_type,
        "updated_by_type": updated_by_type,
        "alias_by_lang": alias_by_lang,
    }


def _count_raw_kept(tsv_path: Path) -> int:
    """Count TSV rows of a permanent type BEFORE qid de-duplication."""
    with tsv_path.open(encoding="utf-8") as fh:
        return sum(
            1
            for r in csv.DictReader(fh, delimiter="\t")
            if (r.get("coarse_type") or "").strip() in PERMANENT_TYPES
        )


def _print_report(rows: list[dict], stats: dict, asof: str, raw_kept: int) -> None:
    """Print the human-gate preview: counts, global_core, and the full row list."""
    ins, upd = stats["inserted_by_type"], stats["updated_by_type"]
    types = sorted(PERMANENT_TYPES)
    global_core_count = sum(r["global_core"] for r in rows)

    print(f"sitelinks_asof     : {asof}")
    if raw_kept != len(rows):
        print(
            f"raw permanent rows : {raw_kept}  "
            f"({raw_kept - len(rows)} duplicate-qid row(s) collapsed)"
        )
    print(f"distinct entities  : {len(rows)}")
    for t in types:
        print(
            f"  {t:<20}: inserted {ins.get(t, 0):>4}   "
            f"updated {upd.get(t, 0):>4}   "
            f"total {sum(1 for r in rows if r['coarse_type'] == t):>4}"
        )
    print(f"global_core (flag) : {global_core_count}")
    print(f"alias inserts/lang : {dict(sorted(stats['alias_by_lang'].items()))}")
    print("")
    print("full row list (qid | label | type | sitelinks | global_core):")
    for r in sorted(rows, key=lambda x: (-x["sitelinks"], x["qid"])):
        label = r["label_eo"] if r["label_eo"] else f"«EN:{r['label_en']}»"
        gc = "★" if r["global_core"] else " "
        print(
            f"  {r['qid']:<10} {label:<28} {r['coarse_type']:<20} "
            f"{r['sitelinks']:>5}  {gc}"
        )


def main(argv: list[str] | None = None) -> int:
    root = _repo_root()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--lexicon",
        type=Path,
        default=root / "data" / "lexicon_db" / "lexicon_v2.db",
        help="path to lexicon_v2.db",
    )
    ap.add_argument(
        "--tsv",
        type=Path,
        default=root / "data" / "analysis" / "names" / "gazetteer_sample.tsv",
        help="path to the gazetteer sample TSV",
    )
    ap.add_argument(
        "--sitelinks-asof",
        default=DEFAULT_SITELINKS_ASOF,
        help="ISO date stamped on every row's salience (default: the D7 pull date)",
    )
    ap.add_argument(
        "--commit",
        action="store_true",
        help="persist the write (backs up the DB first); default is a preview",
    )
    args = ap.parse_args(argv)

    if not args.lexicon.exists():
        print(f"ERROR: DB not found: {args.lexicon}", file=sys.stderr)
        return 2
    if not args.tsv.exists():
        print(f"ERROR: TSV not found: {args.tsv}", file=sys.stderr)
        return 2

    rows = load_rows(args.tsv)

    if args.commit:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = args.lexicon.with_suffix(f".db.bak-ne-{stamp}")
        shutil.copy2(args.lexicon, backup)
        print(f"backup: {backup}")

    conn = sqlite3.connect(args.lexicon)
    try:
        create_named_entity_schema(conn)  # self-sufficient / idempotent
        conn.execute("BEGIN")
        stats = _upsert_rows(conn, rows, args.sitelinks_asof)
        _print_report(rows, stats, args.sitelinks_asof, _count_raw_kept(args.tsv))
        if args.commit:
            conn.commit()
            print("\nCOMMITTED.")
        else:
            conn.execute("ROLLBACK")
            print("\nDRY-RUN — rolled back, nothing written.")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
