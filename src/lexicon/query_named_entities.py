"""Read-only lookup helper for the named-entity inventory (v0).

Resolves a surface term against the ``named_entity`` / ``named_entity_type`` /
``named_entity_alias`` tables in ``lexicon_v2.db`` and returns the matching
entity, its coarse type(s) with R6 validation regime, and its aliases.

This is the shape the future resolver's *"check names before decomposition"*
hook (roadmap **R3**) will call. It is a **read-only** demonstration: it opens
the DB, never writes, and is **not** wired into the analyzer.

Resolution order (first match wins), recording *how* it matched in
``match_field``:

1. exact ``qid`` (e.g. ``Q111``),
2. exact ``named_entity.label_eo``,
3. exact ``named_entity.label_en``,
4. ``named_entity_alias.alias`` (an ``eo`` alias is preferred over an ``en``
   alias when both match),

then a second pass repeating 2-4 case-insensitively if no exact hit is found.

Roadmap **R8** reminder: these entities carry **no stored tier**. The store
records only a sourced, dated ``sitelinks`` salience; ``global_core`` is a
group-invariance flag, not a tier. This helper surfaces salience and
``global_core`` but never invents a tier.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class NamedEntityHit:
    """A resolved named-entity lookup result.

    Attributes:
        entity_id: Internal ``named_entity.id`` primary key.
        qid: Wikidata QID (CC0 provenance).
        label_eo: Primary Esperanto label (may be ``None`` for ~0.4% of rows).
        label_en: English label / documented fallback.
        sitelinks: Salience datum (sourced, not derived); may be ``None``.
        sitelinks_asof: ISO date the salience was captured.
        global_core: Group-invariance flag (1 = truly reference-group-invariant,
            e.g. Moon, oceans, continents). This is NOT a tier.
        status: Row status (default ``'active'``).
        source: Provenance source (default ``'wikidata'``).
        types: Coarse type(s) as ``(ne_type, validation)`` tuples.
        aliases: Aliases as ``(alias, lang)`` tuples.
        match_field: How the term matched — one of ``qid``, ``label_eo``,
            ``label_en``, ``alias:eo``, ``alias:en`` (optionally suffixed
            ``:ci`` for a case-insensitive second-pass match).
    """

    entity_id: int
    qid: str
    label_eo: Optional[str]
    label_en: Optional[str]
    sitelinks: Optional[int]
    sitelinks_asof: Optional[str]
    global_core: int
    status: Optional[str]
    source: Optional[str]
    match_field: str
    types: list[tuple[str, str]] = field(default_factory=list)
    aliases: list[tuple[str, str]] = field(default_factory=list)


def _load_hit(
    conn: sqlite3.Connection, entity_id: int, match_field: str
) -> NamedEntityHit:
    """Build a :class:`NamedEntityHit` for ``entity_id`` with its types/aliases."""
    row = conn.execute(
        """
        SELECT id, qid, label_eo, label_en, sitelinks, sitelinks_asof,
               global_core, status, source
        FROM named_entity
        WHERE id = ?
        """,
        (entity_id,),
    ).fetchone()

    type_rows = conn.execute(
        """
        SELECT ne_type, validation
        FROM named_entity_type
        WHERE entity_id = ?
        ORDER BY ne_type
        """,
        (entity_id,),
    ).fetchall()

    alias_rows = conn.execute(
        """
        SELECT alias, lang
        FROM named_entity_alias
        WHERE entity_id = ?
        ORDER BY lang, alias
        """,
        (entity_id,),
    ).fetchall()

    return NamedEntityHit(
        entity_id=row[0],
        qid=row[1],
        label_eo=row[2],
        label_en=row[3],
        sitelinks=row[4],
        sitelinks_asof=row[5],
        global_core=row[6],
        status=row[7],
        source=row[8],
        match_field=match_field,
        types=[(t[0], t[1]) for t in type_rows],
        aliases=[(a[0], a[1]) for a in alias_rows],
    )


def _match_alias(
    conn: sqlite3.Connection, term: str, case_insensitive: bool
) -> Optional[tuple[int, str]]:
    """Resolve ``term`` against aliases, preferring an ``eo`` alias over ``en``.

    Returns ``(entity_id, match_field)`` or ``None``. ``match_field`` is
    ``alias:<lang>`` (with a ``:ci`` suffix when matched case-insensitively).
    """
    if case_insensitive:
        rows = conn.execute(
            """
            SELECT entity_id, lang
            FROM named_entity_alias
            WHERE alias = ? COLLATE NOCASE
            """,
            (term,),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT entity_id, lang
            FROM named_entity_alias
            WHERE alias = ?
            """,
            (term,),
        ).fetchall()

    if not rows:
        return None

    # Prefer an eo alias over an en alias when both match.
    ranked = sorted(rows, key=lambda r: 0 if r[1] == "eo" else 1)
    entity_id, lang = ranked[0][0], ranked[0][1]
    suffix = ":ci" if case_insensitive else ""
    return entity_id, f"alias:{lang}{suffix}"


def resolve(conn: sqlite3.Connection, term: str) -> Optional[NamedEntityHit]:
    """Resolve a surface ``term`` to a :class:`NamedEntityHit`, or ``None``.

    Read-only. Resolution order and case handling are documented at the module
    level. The first match wins; ``match_field`` records how it matched.

    Args:
        conn: An open connection to a DB carrying the named-entity schema.
        term: The surface form to look up (a QID, an EO/EN label, or an alias).

    Returns:
        A :class:`NamedEntityHit` if the term resolves, otherwise ``None``.
    """
    if term is None:
        return None
    term = term.strip()
    if not term:
        return None

    # 1. exact qid
    row = conn.execute(
        "SELECT id FROM named_entity WHERE qid = ?", (term,)
    ).fetchone()
    if row is not None:
        return _load_hit(conn, row[0], "qid")

    # 2. exact label_eo
    row = conn.execute(
        "SELECT id FROM named_entity WHERE label_eo = ?", (term,)
    ).fetchone()
    if row is not None:
        return _load_hit(conn, row[0], "label_eo")

    # 3. exact label_en
    row = conn.execute(
        "SELECT id FROM named_entity WHERE label_en = ?", (term,)
    ).fetchone()
    if row is not None:
        return _load_hit(conn, row[0], "label_en")

    # 4. exact alias (eo preferred over en)
    alias_hit = _match_alias(conn, term, case_insensitive=False)
    if alias_hit is not None:
        return _load_hit(conn, alias_hit[0], alias_hit[1])

    # Second pass: repeat 2-4 case-insensitively.
    row = conn.execute(
        "SELECT id FROM named_entity WHERE label_eo = ? COLLATE NOCASE", (term,)
    ).fetchone()
    if row is not None:
        return _load_hit(conn, row[0], "label_eo:ci")

    row = conn.execute(
        "SELECT id FROM named_entity WHERE label_en = ? COLLATE NOCASE", (term,)
    ).fetchone()
    if row is not None:
        return _load_hit(conn, row[0], "label_en:ci")

    alias_hit = _match_alias(conn, term, case_insensitive=True)
    if alias_hit is not None:
        return _load_hit(conn, alias_hit[0], alias_hit[1])

    return None


def format_hit(term: str, hit: NamedEntityHit) -> str:
    """Render a resolved hit as a readable multi-line block for the CLI."""
    lines: list[str] = []
    lines.append(f"'{term}' resolved -> {hit.qid}")
    lines.append(f"  matched by   : {hit.match_field}")
    lines.append(f"  label_eo     : {hit.label_eo or '(none)'}")
    lines.append(f"  label_en     : {hit.label_en or '(none)'}")
    if hit.types:
        type_str = ", ".join(f"{t}[{v}]" for t, v in hit.types)
    else:
        type_str = "(none)"
    lines.append(f"  type(s)      : {type_str}")
    salience = "(none)" if hit.sitelinks is None else str(hit.sitelinks)
    asof = hit.sitelinks_asof or "(undated)"
    lines.append(f"  salience     : {salience} (as of {asof})")
    lines.append(f"  global_core  : {'yes' if hit.global_core else 'no'}")
    lines.append(f"  source       : {hit.source or '(unknown)'}")
    lines.append(f"  status       : {hit.status or '(unknown)'}")
    if hit.aliases:
        alias_str = ", ".join(f"{a} ({lang})" for a, lang in hit.aliases)
    else:
        alias_str = "(none)"
    lines.append(f"  aliases      : {alias_str}")
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entry point. Returns a process exit code (0 = resolved)."""
    parser = argparse.ArgumentParser(
        description=(
            "Read-only lookup against the named-entity inventory in "
            "lexicon_v2.db. Resolves a QID, EO/EN label, or alias."
        )
    )
    parser.add_argument("term", help="Surface term to resolve (QID, label, or alias)")
    parser.add_argument(
        "--db",
        type=Path,
        default=Path("data/lexicon_db/lexicon_v2.db"),
        help="Path to the lexicon DB (default: data/lexicon_db/lexicon_v2.db)",
    )
    args = parser.parse_args(argv)

    if not args.db.exists():
        print(f"Error: DB not found: {args.db}", file=sys.stderr)
        return 2

    # Read-only: open via URI in read-only mode so we never write.
    uri = f"file:{args.db}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        hit = resolve(conn, args.term)
    finally:
        conn.close()

    if hit is None:
        print(f"no match: '{args.term}' did not resolve to any named entity")
        return 1

    print(format_hit(args.term, hit))
    return 0


if __name__ == "__main__":
    sys.exit(main())
