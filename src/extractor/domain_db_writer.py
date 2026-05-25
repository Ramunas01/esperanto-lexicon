#!/usr/bin/env python3
"""Write approved definition records from a .jsonl file into a domain SQLite database.

Records sharing the same cross_lang_num represent the same concept in different
languages and are grouped into a single mwe row with one mwe_lang row per language.

Usage:
    python3 src/extractor/domain_db_writer.py \\
        --input data/domain_db/gpmi_definitions.jsonl \\
        --db    data/domain_db/gpmi_lt_tax.db \\
        --domain "personal_income_tax" \\
        --jurisdiction "LT"
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

# schema.py lives in src/lexicon/; resolve relative to this file
sys.path.insert(0, str(Path(__file__).parent.parent))
from lexicon.schema import create_domain_schema


def _today() -> str:
    return date.today().isoformat()


def _normalize_definition(text: str | None) -> str:
    """Lowercase and strip leading/trailing whitespace for comparison."""
    if not text:
        return ""
    return text.strip().lower()


def _lookup_mwe_lang(
    conn: sqlite3.Connection, phrase_normalized: str, lang: str
) -> tuple[int, str] | None:
    """Return (mwe_id, definition_raw) for an existing mwe_lang row, or None."""
    row = conn.execute(
        "SELECT mwe_id, definition_raw FROM mwe_lang WHERE phrase_normalized = ? AND lang = ?",
        (phrase_normalized, lang),
    ).fetchone()
    return (row[0], row[1] or "") if row else None


def _lookup_mwe_lang_same_def(
    conn: sqlite3.Connection, phrase_normalized: str, lang: str, definition_raw: str
) -> int | None:
    """Return mwe_id only when phrase AND definition both match an existing row.

    Used in STEP 1 deduplication to avoid merging two different concepts that
    happen to share the same translated phrase (e.g. two LT terms with identical
    EO translations).
    """
    row = conn.execute(
        "SELECT mwe_id, definition_raw FROM mwe_lang WHERE phrase_normalized = ? AND lang = ?",
        (phrase_normalized, lang),
    ).fetchone()
    if row is None:
        return None
    if _normalize_definition(row[1] or "") != _normalize_definition(definition_raw):
        return None  # Same phrase, different concept — do not merge
    return row[0]


def _count_distinct_sources(conn: sqlite3.Connection, mwe_id: int) -> int:
    row = conn.execute(
        "SELECT COUNT(DISTINCT source_doc) FROM mwe_occurrence WHERE mwe_id = ?",
        (mwe_id,),
    ).fetchone()
    return row[0] if row else 0


def _upgrade_mwe(conn: sqlite3.Connection, mwe_id: int, n_sources: int) -> str:
    """Upgrade scope/status/promotable based on distinct source count. Returns new status."""
    if n_sources >= 3:
        conn.execute(
            "UPDATE mwe SET scope='domain', status='crystallized', promotable=1 WHERE id=?",
            (mwe_id,),
        )
        return "crystallized"
    if n_sources >= 2:
        conn.execute(
            "UPDATE mwe SET scope='domain', status='established', promotable=1 WHERE id=?",
            (mwe_id,),
        )
        return "established"
    return "emerging"


def _clause_ref(rec: dict) -> str | None:
    article = rec.get("article")
    clause_num = rec.get("clause_num")
    return f"Art.{article}.{clause_num}" if article and clause_num else None


def _insert_mwe_lang(
    conn: sqlite3.Connection, mwe_id: int, rec: dict
) -> None:
    conn.execute(
        """
        INSERT INTO mwe_lang
            (mwe_id, lang, phrase, phrase_normalized, definition_raw, abbrev)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            mwe_id,
            rec["lang"],
            rec["term_raw"],
            rec.get("term_normalized") or rec["term_raw"].lower(),
            rec.get("definition_raw") or "",
            rec.get("abbrev"),
        ),
    )


def _insert_occurrence(
    conn: sqlite3.Connection, mwe_id: int, rec: dict, today: str
) -> None:
    conn.execute(
        """
        INSERT INTO mwe_occurrence
            (mwe_id, source_doc, source_lang, clause_ref, date_extracted)
        VALUES (?, ?, ?, ?, ?)
        """,
        (mwe_id, rec.get("source_file") or "", rec["lang"], _clause_ref(rec), today),
    )


def _insert_new_mwe(
    conn: sqlite3.Connection, source_doc: str, today: str, domain: str, jurisdiction: str
) -> int:
    cur = conn.execute(
        """
        INSERT INTO mwe
            (eo_canonical, eo_status, scope, status, first_seen_source,
             first_seen_date, current_tier, domain, jurisdiction, promotable)
        VALUES (NULL, 'pending', 'document_specific', 'emerging', ?, ?, 4, ?, ?, 0)
        """,
        (source_doc, today, domain, jurisdiction),
    )
    return cur.lastrowid  # type: ignore[return-value]


def process_group(
    conn: sqlite3.Connection,
    records: list[dict],
    cross_lang_num: str,
    domain: str,
    jurisdiction: str,
) -> dict:
    """Process a group of same-concept records (same cross_lang_num) across languages.

    Returns a counts dict with keys: new_concepts, lang_counts, merged, conflicts.
    """
    today = _today()

    # STEP 1 — deduplication: find an existing mwe via any lang in the group.
    # Require phrase AND definition to match so that two different concepts sharing
    # the same translated phrase are not incorrectly merged.
    existing_mwe_id: int | None = None
    for rec in records:
        phrase_normalized = rec.get("term_normalized") or rec["term_raw"].lower()
        definition_raw = rec.get("definition_raw") or ""
        found_id = _lookup_mwe_lang_same_def(conn, phrase_normalized, rec["lang"], definition_raw)
        if found_id is not None:
            existing_mwe_id = found_id
            break

    # STEP 2 — NOT FOUND: create one mwe row and one mwe_lang + mwe_occurrence per language
    if existing_mwe_id is None:
        mwe_id = _insert_new_mwe(
            conn, records[0].get("source_file") or "", today, domain, jurisdiction
        )
        lang_counts: dict[str, int] = {}
        conflicts = 0
        for rec in records:
            phrase_normalized = rec.get("term_normalized") or rec["term_raw"].lower()
            definition_raw = rec.get("definition_raw") or ""
            _insert_mwe_lang(conn, mwe_id, rec)
            _insert_occurrence(conn, mwe_id, rec, today)
            lang_counts[rec["lang"]] = lang_counts.get(rec["lang"], 0) + 1

            # Detect same phrase + different definition in an already-existing mwe
            for existing_mwe_id_other, existing_def in conn.execute(
                "SELECT mwe_id, definition_raw FROM mwe_lang"
                " WHERE phrase_normalized=? AND lang=? AND mwe_id!=?",
                (phrase_normalized, rec["lang"], mwe_id),
            ):
                if _normalize_definition(existing_def or "") != _normalize_definition(definition_raw):
                    detail = f"A: {(existing_def or '')[:100]} | B: {definition_raw[:100]}"
                    conn.execute(
                        """
                        INSERT INTO mwe_conflict
                            (mwe_id_a, mwe_id_b, conflict_type, divergence_detail,
                             resolution_status, detected_date)
                        VALUES (?, ?, 'text_divergence', ?, 'open', ?)
                        """,
                        (existing_mwe_id_other, mwe_id, detail, today),
                    )
                    print(f"CONFLICT: {rec['term_raw']} ({rec['lang']}) — text divergence recorded")
                    conflicts += 1

        _LANG_ORDER = {"lt": 0, "eo": 1, "en": 2}
        ordered = sorted(records, key=lambda r: _LANG_ORDER.get(r["lang"], 99))
        phrases_str = " | ".join(r["term_raw"] for r in ordered)
        print(f"NEW [clause {cross_lang_num}]: {phrases_str}")
        return {"new_concepts": 1, "lang_counts": lang_counts, "merged": 0, "conflicts": conflicts}

    # STEP 3 — FOUND: apply per-language merge / conflict logic against the existing mwe
    mwe_id = existing_mwe_id
    lang_counts = {}
    merged = 0
    conflicts = 0

    for rec in records:
        lang = rec["lang"]
        phrase_normalized = rec.get("term_normalized") or rec["term_raw"].lower()
        definition_raw = rec.get("definition_raw") or ""

        found = _lookup_mwe_lang(conn, phrase_normalized, lang)

        if found is None:
            # Language not yet recorded for this concept — add it
            _insert_mwe_lang(conn, mwe_id, rec)
            _insert_occurrence(conn, mwe_id, rec, today)
            lang_counts[lang] = lang_counts.get(lang, 0) + 1
            merged += 1

        elif _normalize_definition(found[1]) == _normalize_definition(definition_raw):
            # Same definition, new source — add occurrence and consider promotion
            _insert_occurrence(conn, mwe_id, rec, today)
            n = _count_distinct_sources(conn, mwe_id)
            new_status = _upgrade_mwe(conn, mwe_id, n)
            row = conn.execute("SELECT scope FROM mwe WHERE id=?", (mwe_id,)).fetchone()
            print(f"MERGED: {rec['term_raw']} (now {new_status}, scope={row[0] if row else '?'})")
            merged += 1

        else:
            # Same phrase, different definition — record conflict
            mwe_id_b = _insert_new_mwe(
                conn, rec.get("source_file") or "", today, domain, jurisdiction
            )
            _insert_mwe_lang(conn, mwe_id_b, rec)
            _insert_occurrence(conn, mwe_id_b, rec, today)
            existing_def = found[1]
            detail = f"A: {existing_def[:100]} | B: {definition_raw[:100]}"
            conn.execute(
                """
                INSERT INTO mwe_conflict
                    (mwe_id_a, mwe_id_b, conflict_type, divergence_detail,
                     resolution_status, detected_date)
                VALUES (?, ?, 'text_divergence', ?, 'open', ?)
                """,
                (mwe_id, mwe_id_b, detail, today),
            )
            print(f"CONFLICT: {rec['term_raw']} ({lang}) — text divergence recorded")
            conflicts += 1

    return {"new_concepts": 0, "lang_counts": lang_counts, "merged": merged, "conflicts": conflicts}


def _group_records(records: list[dict]) -> list[tuple[str, list[dict]]]:
    """Group records by cross_lang_num, sorted numerically where possible."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for rec in records:
        key = str(rec.get("cross_lang_num") or rec.get("clause_num") or "?")
        groups[key].append(rec)

    def _sort_key(k: str) -> tuple:
        try:
            return (0, int(k))
        except ValueError:
            return (1, k)

    return sorted(groups.items(), key=lambda item: _sort_key(item[0]))


def run(
    input_path: Path,
    db_path: Path,
    domain: str,
    jurisdiction: str,
) -> None:
    """Load approved records, group by cross_lang_num, write to domain DB."""
    records: list[dict] = []
    with input_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rec = json.loads(line)
                if rec.get("approved") is True:
                    records.append(rec)

    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    create_domain_schema(conn)

    total_new = 0
    total_lang_counts: dict[str, int] = {}
    total_merged = 0
    total_conflicts = 0

    for cross_lang_num, group in _group_records(records):
        result = process_group(conn, group, cross_lang_num, domain, jurisdiction)
        total_new += result["new_concepts"]
        total_merged += result["merged"]
        total_conflicts += result["conflicts"]
        for lang, count in result["lang_counts"].items():
            total_lang_counts[lang] = total_lang_counts.get(lang, 0) + count

    conn.commit()

    total_concepts = conn.execute("SELECT COUNT(*) FROM mwe").fetchone()[0]
    total_mwe_lang = conn.execute("SELECT COUNT(*) FROM mwe_lang").fetchone()[0]
    conn.close()

    lang_str = ", ".join(
        f"{lang}={count}" for lang, count in sorted(total_lang_counts.items())
    )
    print()
    print(f"New concepts   : {total_new}")
    print(f"Languages      : {lang_str}")
    print(f"Merged         : {total_merged}")
    print(f"Conflicts      : {total_conflicts}")
    print(f"Total concepts : {total_concepts}")
    print(f"Total mwe_lang : {total_mwe_lang}")


def main(argv: list[str] | None = None) -> None:
    """Entry point for domain_db_writer."""
    parser = argparse.ArgumentParser(
        description="Write approved definition records into a domain SQLite database."
    )
    parser.add_argument("--input", required=True, type=Path, help="Path to .jsonl file")
    parser.add_argument("--db", required=True, type=Path, help="Path to domain .db file")
    parser.add_argument("--domain", required=True, help="Domain label (e.g. personal_income_tax)")
    parser.add_argument("--jurisdiction", required=True, help="Jurisdiction code (e.g. LT)")
    args = parser.parse_args(argv)

    if not args.input.exists():
        print(f"Error: input file not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    run(args.input, args.db, args.domain, args.jurisdiction)


if __name__ == "__main__":
    main()
