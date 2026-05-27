#!/usr/bin/env python3
"""Report mwe_conflict entries from a domain DB, with optional cross-domain comparison.

Usage (single DB):
    python3 src/analyzer/conflict_report.py \\
        --db data/domain_db/gpmi_lt_tax.db

Usage (cross-domain, auto-detect shared languages):
    python3 src/analyzer/conflict_report.py \\
        --db data/domain_db/ucc_customs.db \\
        --cross-db data/domain_db/wco_intl.db

Usage (cross-domain, explicit language):
    python3 src/analyzer/conflict_report.py \\
        --db data/domain_db/ucc_customs.db \\
        --cross-db data/domain_db/wco_intl.db \\
        --lang en

--lang accepts: a language code (lt, en, fr, …) or 'auto' (default).
In auto mode the tool finds all languages present in both DBs and
runs conflict detection for each, reporting them grouped by language.
"""

from __future__ import annotations

import argparse
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class ConflictDetail:
    conflict_id: int
    mwe_id_a: int
    mwe_id_b: int
    conflict_type: str
    divergence_detail: str | None
    resolution_status: str
    detected_date: str | None
    phrases_a: list[tuple[str, str, str]]   # (lang, phrase, definition_raw)
    phrases_b: list[tuple[str, str, str]]
    sources_a: list[str]
    sources_b: list[str]


@dataclass
class CrossConflict:
    phrase_normalized: str
    lang: str
    definition_a: str
    definition_b: str
    db_a: str
    db_b: str
    incomplete: bool = False  # True when one side has no definition (coverage gap, not a conflict)


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------


def load_conflicts(conn: sqlite3.Connection) -> list[ConflictDetail]:
    """Load all mwe_conflict entries with full phrase and source detail."""
    rows = conn.execute(
        """
        SELECT id, mwe_id_a, mwe_id_b, conflict_type,
               divergence_detail, resolution_status, detected_date
        FROM mwe_conflict
        ORDER BY id
        """
    ).fetchall()

    results: list[ConflictDetail] = []
    for row in rows:
        cid, mwe_a, mwe_b, ctype, detail, status, detected = row

        phrases_a = _load_phrases(conn, mwe_a)
        phrases_b = _load_phrases(conn, mwe_b)
        sources_a = _load_sources(conn, mwe_a)
        sources_b = _load_sources(conn, mwe_b)

        results.append(
            ConflictDetail(
                conflict_id=cid,
                mwe_id_a=mwe_a,
                mwe_id_b=mwe_b,
                conflict_type=ctype,
                divergence_detail=detail or "",
                resolution_status=status or "open",
                detected_date=detected,
                phrases_a=phrases_a,
                phrases_b=phrases_b,
                sources_a=sources_a,
                sources_b=sources_b,
            )
        )
    return results


def _load_phrases(
    conn: sqlite3.Connection, mwe_id: int
) -> list[tuple[str, str, str]]:
    return conn.execute(
        "SELECT lang, phrase, COALESCE(definition_raw, '') FROM mwe_lang WHERE mwe_id = ? ORDER BY lang",
        (mwe_id,),
    ).fetchall()


def _load_sources(conn: sqlite3.Connection, mwe_id: int) -> list[str]:
    return [
        row[0]
        for row in conn.execute(
            "SELECT DISTINCT source_doc FROM mwe_occurrence WHERE mwe_id = ?",
            (mwe_id,),
        ).fetchall()
    ]


def get_langs(conn: sqlite3.Connection) -> set[str]:
    """Return the set of language codes present in mwe_lang for this DB."""
    return {
        row[0]
        for row in conn.execute("SELECT DISTINCT lang FROM mwe_lang")
    }


def detect_common_langs(
    conn_a: sqlite3.Connection,
    conn_b: sqlite3.Connection,
) -> list[str]:
    """Return sorted list of language codes present in both DBs."""
    return sorted(get_langs(conn_a) & get_langs(conn_b))


def load_cross_conflicts(
    conn_a: sqlite3.Connection,
    conn_b: sqlite3.Connection,
    lang: str,
    db_name_a: str,
    db_name_b: str,
) -> list[CrossConflict]:
    """Find phrases that appear in both DBs for *lang* with different definitions."""
    phrases_a: dict[str, str] = {
        row[0]: row[1]
        for row in conn_a.execute(
            "SELECT phrase_normalized, COALESCE(definition_raw, '') FROM mwe_lang WHERE lang = ?",
            (lang,),
        )
    }
    conflicts: list[CrossConflict] = []
    for phrase_norm, def_b in conn_b.execute(
        "SELECT phrase_normalized, COALESCE(definition_raw, '') FROM mwe_lang WHERE lang = ?",
        (lang,),
    ):
        if phrase_norm not in phrases_a:
            continue
        def_a = phrases_a[phrase_norm]
        if def_a.strip().lower() == def_b.strip().lower():
            continue
        incomplete = not def_a.strip() or not def_b.strip()
        conflicts.append(
            CrossConflict(
                phrase_normalized=phrase_norm,
                lang=lang,
                definition_a=def_a,
                definition_b=def_b,
                db_a=db_name_a,
                db_b=db_name_b,
                incomplete=incomplete,
            )
        )
    return conflicts


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------

_SEP = "═" * 54
_THIN = "─" * 54


def _truncate(text: str, max_len: int = 120) -> str:
    return text if len(text) <= max_len else text[:max_len] + "…"


def format_conflict_report(
    conflicts: list[ConflictDetail], db_name: str
) -> str:
    lines: list[str] = []
    lines += [_SEP, f"CONFLICT REPORT — {db_name}", _SEP]

    n = len(conflicts)
    lines.append(f"{n} conflict{'s' if n != 1 else ''} found.")

    for c in conflicts:
        lines += ["", _THIN]
        lines.append(
            f"CONFLICT #{c.conflict_id}"
            f"  [type: {c.conflict_type}]"
            f"  [status: {c.resolution_status}]"
        )
        lines.append(_THIN)

        for label, phrases, sources, mwe_id in (
            ("A", c.phrases_a, c.sources_a, c.mwe_id_a),
            ("B", c.phrases_b, c.sources_b, c.mwe_id_b),
        ):
            lines.append(f"\nCONCEPT {label}  (mwe_id={mwe_id})")
            for lang, phrase, _ in phrases:
                lines.append(f"  {lang:<4} {phrase}")
            src_str = ", ".join(sources) if sources else "(unknown)"
            lines.append(f"  Source: {src_str}")

        if c.divergence_detail:
            lines.append("\nDIVERGENCE:")
            for part in c.divergence_detail.split(" | "):
                lines.append(f"  {_truncate(part, 100)}")

        if c.detected_date:
            lines.append(f"\nDetected: {c.detected_date}  Resolution: {c.resolution_status}")

    lines += ["", _SEP]
    return "\n".join(lines)


_INCOMPLETE_LABEL = "INCOMPLETE — definition not available in this source"


def format_cross_conflict_report(
    conflicts: list[CrossConflict], db_a: str, db_b: str, lang: str
) -> str:
    real = [c for c in conflicts if not c.incomplete]
    gaps = [c for c in conflicts if c.incomplete]

    lines: list[str] = []
    lines += [_SEP, f"CROSS-DOMAIN CONFLICTS  [{db_a} vs {db_b}]  lang={lang}", _SEP]

    n = len(real)
    lines.append(f"{n} shared phrase{'s' if n != 1 else ''} with diverging definitions.")
    if gaps:
        ng = len(gaps)
        lines.append(
            f"{ng} phrase{'s' if ng != 1 else ''} where one side has no definition (incomplete)."
        )

    for c in real:
        lines += ["", _THIN]
        lines.append(f"PHRASE:  {c.phrase_normalized}")
        lines.append(f"\n  {db_a}:")
        lines.append(f"    {_truncate(c.definition_a, 120)}")
        lines.append(f"\n  {db_b}:")
        lines.append(f"    {_truncate(c.definition_b, 120)}")

    lines += ["", _SEP]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    import sys

    parser = argparse.ArgumentParser(
        description="Report mwe_conflict entries from a domain DB."
    )
    parser.add_argument("--db", required=True, type=Path, help="Primary domain DB")
    parser.add_argument(
        "--cross-db", dest="cross_db", type=Path, default=None,
        help="Second domain DB for cross-domain conflict detection",
    )
    parser.add_argument(
        "--lang", default="auto",
        help=(
            "Language code for cross-DB phrase comparison, or 'auto' to "
            "try all languages present in both DBs (default: auto)"
        ),
    )
    args = parser.parse_args(argv)

    if not args.db.exists():
        print(f"Error: DB not found: {args.db}", file=sys.stderr)
        sys.exit(1)

    conn_a = sqlite3.connect(args.db)
    conflicts = load_conflicts(conn_a)
    print(format_conflict_report(conflicts, args.db.name))

    if args.cross_db:
        if not args.cross_db.exists():
            print(f"Error: cross-DB not found: {args.cross_db}", file=sys.stderr)
            sys.exit(1)
        conn_b = sqlite3.connect(args.cross_db)

        if args.lang == "auto":
            langs = detect_common_langs(conn_a, conn_b)
            if not langs:
                print(f"No languages in common between {args.db.name} and {args.cross_db.name}.")
            for lang in langs:
                cross = load_cross_conflicts(
                    conn_a, conn_b, lang, args.db.name, args.cross_db.name
                )
                print(format_cross_conflict_report(
                    cross, args.db.name, args.cross_db.name, lang
                ))
        else:
            cross = load_cross_conflicts(
                conn_a, conn_b, args.lang, args.db.name, args.cross_db.name
            )
            print(format_cross_conflict_report(
                cross, args.db.name, args.cross_db.name, args.lang
            ))

        conn_b.close()

    conn_a.close()


if __name__ == "__main__":
    main()
