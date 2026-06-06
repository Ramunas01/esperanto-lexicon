#!/usr/bin/env python3
"""Read-only consistency audit of stored ``eo_root`` vs. what the decomposer
would compute from ``eo_word``.

This tool never writes to the database — it only reports. The audit is the
diagnostic lens for:

  * confirming the eo_word-sourced decomposer pass eliminated the
    truncation class of mismatches (``klim`` for ``klimato``,
    ``apar`` for ``aparato``);
  * surfacing build-time false merges that should be added to
    ``eo_reduce_exceptions.txt`` (e.g. ``prezid → prez``).

For every concept with a usable ``eo_word`` and ``eo_root``, the decomposer
runs on ``strip_flexion(eo_word)``. The result is classified as one of:

  * ``ok`` — stored root matches the computed head; not written, only counted.
  * ``truncation`` — stored root is a strict prefix of the working stem
    (and shorter). The classic v1→v2 truncation signature.
  * ``mismatch`` — stored root is neither the computed head nor a prefix
    of the working stem; an inconsistency worth eyeballing.
  * ``over_reduced_candidate`` — the decomposition went via a short
    suffix-strip (≤2 chars) to a head root that is *not* the working stem,
    and the inventory's English gloss for the head root shares no
    significant token with the concept's English ``concept_lang`` word.
    These are the build-time false-merge candidates for the Part B
    exceptions list.

CLI::

    python3 src/lexicon/audit_root_consistency.py \\
        --db data/lexicon_db/lexicon_v2.db \\
        --inventory data/lexicon_db/eo_inventory.json \\
        --out data/lexicon_db/eo_root_audit.jsonl
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

# Same sys.path bootstrap pattern as eo_root_decomposer.py — allows the CLI
# to resolve `from src.lexicon...` when invoked directly from the project
# root.
_project_root = Path(__file__).resolve().parents[2]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from src.lexicon.build_eo_inventory import strip_flexion  # noqa: E402
from src.lexicon.eo_root_decomposer import (  # noqa: E402
    KIND_COMPOUND,
    KIND_SINGLE_ROOT,
    Decomposer,
    load_inventory,
)


ISSUE_OK = "ok"
ISSUE_TRUNCATION = "truncation"
ISSUE_MISMATCH = "mismatch"
ISSUE_OVER_REDUCED = "over_reduced_candidate"

SHORT_SUFFIX_THRESHOLD = 2


_TOKEN_RE = re.compile(r"[a-zA-Z]+")


def _meaningful_tokens(text: str) -> set[str]:
    """Lowercased alphabetic tokens of length > 3 — used for the soft
    gloss-relatedness check. Length > 3 filters out generic English glue
    words (``a``, ``to``, ``the``) that would otherwise create spurious
    overlap."""
    if not text:
        return set()
    return {t.lower() for t in _TOKEN_RE.findall(text) if len(t) > 3}


def looks_unrelated(en_word: str | None, head_gloss: str | None) -> bool:
    """Heuristic relatedness check.

    Returns True only when both sides have meaningful tokens AND none of
    them share evidence of being morphologically related. We consider three
    forms of relatedness, any one of which makes the pair "related":

      * any exact token match (``active`` vs ``active``);
      * one token is a substring of the other (both ≥4 chars), which
        catches ``active``/``activity`` and ``rapid``/``rapidly``;
      * a shared 4-char prefix (both ≥4 chars), which catches
        ``actor``/``actress``.

    The spec also mentioned a ``prod == 1`` constraint on the head, but on
    real data over-collapsed roots are typically *high*-prod precisely
    because they wrongly absorbed unrelated derivations (e.g. ``rap``
    "turnip" with prod=16 absorbing ``rapid``-class stems). Dropping the
    prod check is what lets the audit actually surface those.

    Missing data → not flagged (``False``)."""
    en_tokens = _meaningful_tokens(en_word or "")
    gloss_tokens = _meaningful_tokens(head_gloss or "")
    if not en_tokens or not gloss_tokens:
        return False
    if en_tokens & gloss_tokens:
        return False
    for et in en_tokens:
        for gt in gloss_tokens:
            if len(et) >= 4 and len(gt) >= 4 and (et in gt or gt in et):
                return False
            if len(et) >= 4 and len(gt) >= 4 and et[:4] == gt[:4]:
                return False
    return True


def fetch_en_word(conn: sqlite3.Connection, concept_id: int) -> str | None:
    row = conn.execute(
        "SELECT word FROM concept_lang "
        "WHERE concept_id = ? AND lang = 'en' "
        "ORDER BY id LIMIT 1",
        (concept_id,),
    ).fetchone()
    return row[0] if row else None


def classify(
    working_stem: str,
    stored_eo_root: str,
    computed_head: str,
    computed_roots: list[str],
    decomposition_kind: str,
    decomposition_suffixes: tuple[str, ...],
    head_gloss: str,
    en_word: str | None,
    working_stem_in_inventory: bool,
) -> str:
    """Return the issue label for a single concept."""
    # First decide the primary class (ok / truncation / mismatch).
    if stored_eo_root == computed_head:
        primary = ISSUE_OK
    elif (
        stored_eo_root
        and len(stored_eo_root) < len(working_stem)
        and working_stem.startswith(stored_eo_root)
    ):
        primary = ISSUE_TRUNCATION
    else:
        primary = ISSUE_MISMATCH

    # Then check for over_reduced_candidate signal. This can override primary
    # — a truly over-reduced concept may already have a "matching" stored
    # root (because a previous run wrote the over-reduced head), so the gloss
    # check is what surfaces the build-time false merge regardless of how
    # the stored eo_root looks.
    if (
        decomposition_kind == KIND_SINGLE_ROOT
        and not working_stem_in_inventory
        and decomposition_suffixes
        and max(len(s) for s in decomposition_suffixes) <= SHORT_SUFFIX_THRESHOLD
        and computed_head != working_stem
        and looks_unrelated(en_word, head_gloss)
    ):
        return ISSUE_OVER_REDUCED

    return primary


def audit(
    db_path: Path, inventory_path: Path, out_path: Path
) -> tuple[Counter, Counter, int]:
    """Run the audit and write ``eo_root_audit.jsonl``.

    Returns ``(issue_counts, top_over_reduced_heads, total_examined)``.
    """
    inv = load_inventory(inventory_path)
    decomposer = Decomposer(inv)
    inventory_roots = set(decomposer.roots)
    gloss_of_root = {
        r.lower(): (info or {}).get("gloss", "")
        for r, info in inv["roots"].items()
        if isinstance(info, dict)
    }

    issue_counts: Counter = Counter()
    over_reduced_heads: Counter = Counter()
    records: list[dict] = []
    total_examined = 0

    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT id, eo_word, eo_root FROM concept"
        ).fetchall()

        for cid, eo_word, eo_root in rows:
            if not (eo_word and eo_word.strip() and eo_root):
                continue
            total_examined += 1

            working_stem = strip_flexion(eo_word.strip().lower())
            dec = decomposer.decompose_word(eo_word)

            # Skip outcomes the audit doesn't have an opinion on.
            if dec.kind not in (KIND_SINGLE_ROOT, KIND_COMPOUND):
                continue

            head = dec.head
            assert head is not None
            computed_head = head.root
            computed_roots = [cr.root for cr in dec.content_roots]

            en_word = fetch_en_word(conn, cid)
            head_gloss = gloss_of_root.get(computed_head, "")

            issue = classify(
                working_stem=working_stem,
                stored_eo_root=eo_root,
                computed_head=computed_head,
                computed_roots=computed_roots,
                decomposition_kind=dec.kind,
                decomposition_suffixes=dec.suffixes,
                head_gloss=head_gloss,
                en_word=en_word,
                working_stem_in_inventory=working_stem in inventory_roots,
            )
            issue_counts[issue] += 1
            if issue == ISSUE_OVER_REDUCED:
                over_reduced_heads[computed_head] += 1

            if issue == ISSUE_OK:
                continue  # don't write ok records

            records.append({
                "concept_id": cid,
                "eo_word": eo_word,
                "stored_eo_root": eo_root,
                "computed_head_root": computed_head,
                "computed_roots": computed_roots,
                "issue": issue,
            })
    finally:
        conn.close()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    return issue_counts, over_reduced_heads, total_examined


def render_summary(
    issue_counts: Counter,
    over_reduced_heads: Counter,
    total_examined: int,
    out_path: Path,
) -> str:
    lines = [
        "EO root audit — summary",
        "=" * 32,
        f"Concepts examined          : {total_examined}",
    ]
    for issue in (
        ISSUE_OK, ISSUE_TRUNCATION, ISSUE_MISMATCH, ISSUE_OVER_REDUCED,
    ):
        lines.append(f"  {issue:<22} : {issue_counts.get(issue, 0)}")
    if over_reduced_heads:
        lines.append("")
        lines.append("Top heads feeding over_reduced_candidate:")
        for head, n in over_reduced_heads.most_common(10):
            lines.append(f"  {head:<14} ({n})")
    lines.append("")
    lines.append(f"Audit JSONL written to: {out_path}")
    lines.append("(ok records omitted; written records: "
                 f"{sum(issue_counts.get(i, 0) for i in (ISSUE_TRUNCATION, ISSUE_MISMATCH, ISSUE_OVER_REDUCED))})")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only audit of stored eo_root vs the decomposer's "
            "recomputation from eo_word. Emits eo_root_audit.jsonl and a "
            "summary; never writes to the DB."
        )
    )
    parser.add_argument(
        "--db", required=True, type=Path, help="Path to lexicon_v2.db",
    )
    parser.add_argument(
        "--inventory", required=True, type=Path,
        help="Path to eo_inventory.json",
    )
    parser.add_argument(
        "--out", required=True, type=Path,
        help="Output JSONL path (one record per inconsistent concept)",
    )
    args = parser.parse_args(argv)

    if not args.db.exists():
        print(f"Error: database not found: {args.db}", file=sys.stderr)
        sys.exit(1)
    if not args.inventory.exists():
        print(
            f"Error: inventory not found: {args.inventory}", file=sys.stderr
        )
        sys.exit(1)

    issue_counts, over_reduced_heads, total_examined = audit(
        args.db, args.inventory, args.out
    )
    print(render_summary(
        issue_counts, over_reduced_heads, total_examined, args.out
    ))


if __name__ == "__main__":
    main()
