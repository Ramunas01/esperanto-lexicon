#!/usr/bin/env python3
"""Read-only consistency audit of stored ``eo_root`` vs. what the decomposer
would compute from ``eo_word``.

This tool never writes to the database — it only reports. The audit is the
diagnostic lens for:

  * confirming the eo_word-sourced decomposer pass eliminated the
    truncation class of mismatches (``klim`` for ``klimato``,
    ``apar`` for ``aparato``);
  * surfacing build-time false merges that should be added to
    ``eo_reduce_exceptions.txt`` (e.g. ``koler → kol``).

For every concept with a usable ``eo_word`` and ``eo_root``, the decomposer
runs on ``strip_flexion(eo_word)``. The result is classified as one of:

  * ``ok`` — stored root matches the computed head; not written, only counted.
  * ``truncation`` — stored root is a strict prefix of the working stem
    (and shorter). The classic v1→v2 truncation signature.
  * ``mismatch`` — stored root is neither the computed head nor a prefix
    of the working stem; an inconsistency worth eyeballing.
  * ``over_reduced_candidate`` — a longer, productive root was discarded
    between the computed head and the word stem (Harris successor-variety
    detector). Replaces the older gloss-similarity heuristic, which gave
    too many false positives on regular derivations (active/activity).

Over-reduction detection (the SV signal)
    For a word stem ``W`` and head root ``H`` with ``H ⊊ W``, walk every
    intermediate stem ``L`` (``len(H) < len(L) ≤ len(W)``). If any such
    ``L`` is itself an attested basic word (``L+a/i/o/e`` is in the
    ESPDIC headword set) AND ``L`` has successor variety ≥ threshold
    (default 5), then ``L`` is a real-language root the reducer threw
    away — and ``H`` was reached via over-reduction.

CLI::

    python3 src/lexicon/audit_root_consistency.py \\
        --db data/lexicon_db/lexicon_v2.db \\
        --inventory data/lexicon_db/eo_inventory.json \\
        --out data/lexicon_db/eo_root_audit.jsonl
"""

from __future__ import annotations

import argparse
import json
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

# Default successor-variety threshold for the over-reduced detector.
# Setting 5 catches borderline cases like ``regul`` (SV ≈ 5) at the cost of
# a little extra review noise; raising to 6 is stricter.
SV_THRESHOLD: int = 5

# Endings used to probe whether an intermediate stem ``L`` is attested as a
# basic ESPDIC headword (some inflection of ``L`` appears in the dictionary).
_BASIC_ENDINGS: tuple[str, ...] = ("a", "i", "o", "e")


def build_successor_index(heads: set[str]) -> dict[str, set[str]]:
    """``succ[prefix] = set of chars that can follow `prefix``` over ``heads``.

    Mirrors ``build_eo_inventory.build_successor_index`` so audit and builder
    use the same SV measure.
    """
    succ: dict[str, set[str]] = defaultdict(set)
    for h in heads:
        for i in range(1, len(h)):
            succ[h[:i]].add(h[i])
    return succ


def over_reduced(
    word_stem: str,
    head_root: str,
    heads: set[str],
    succ: dict[str, set[str]],
    sv_threshold: int = SV_THRESHOLD,
) -> bool:
    """Return True iff a productive intermediate root was discarded between
    ``head_root`` and ``word_stem``.

    Returns False unless ``head_root`` is a strict prefix of ``word_stem``;
    the audit only invokes this branch when the decomposer split off a
    suffix.
    """
    if not word_stem.startswith(head_root) or word_stem == head_root:
        return False
    for n in range(len(head_root) + 1, len(word_stem) + 1):
        candidate = word_stem[:n]
        attested_basic = any(
            (candidate + e) in heads for e in _BASIC_ENDINGS
        )
        if attested_basic and len(succ.get(candidate, ())) >= sv_threshold:
            return True
    return False


def classify(
    working_stem: str,
    stored_eo_root: str,
    computed_head: str,
    decomposition_kind: str,
    heads: set[str],
    succ: dict[str, set[str]],
    sv_threshold: int = SV_THRESHOLD,
) -> str:
    """Return the issue label for a single concept.

    The over-reduction check can override the primary class — a truly
    over-reduced concept may already have a "matching" stored root (because
    a previous decomposer run wrote the over-reduced head), so the SV signal
    surfaces the build-time false merge regardless of how the stored root
    looks.
    """
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

    # Over-reduction is meaningful only when the decomposer arrived at a
    # SINGLE_ROOT via suffix-stripping (head_root ⊊ working_stem).
    if (
        decomposition_kind == KIND_SINGLE_ROOT
        and computed_head != working_stem
        and over_reduced(
            working_stem, computed_head, heads, succ, sv_threshold
        )
    ):
        return ISSUE_OVER_REDUCED

    return primary


def audit(
    db_path: Path,
    inventory_path: Path,
    out_path: Path,
    sv_threshold: int = SV_THRESHOLD,
) -> tuple[Counter, Counter, int]:
    """Run the audit and write ``eo_root_audit.jsonl``.

    Returns ``(issue_counts, top_over_reduced_heads, total_examined)``.
    The DB is opened read-only in spirit (only SELECT queries) — no
    UPDATE/INSERT/DELETE is ever issued.
    """
    inv = load_inventory(inventory_path)
    decomposer = Decomposer(inv)

    # The audit's SV signal requires the same HEADS set the builder used.
    # That set is shipped in the inventory JSON's ``headwords`` field; this
    # avoids re-fetching ESPDIC at audit time. Inventories built before
    # this revision lack the field — fall back to the root set as a
    # best-effort approximation and warn on stderr.
    raw_heads = inv.get("headwords")
    if raw_heads:
        heads: set[str] = set(raw_heads)
    else:
        print(
            "WARN: inventory missing 'headwords'; falling back to root "
            "keys (rebuild with the SV-guarded build_eo_inventory.py for "
            "accurate over-reduction detection).",
            file=sys.stderr,
        )
        heads = set(decomposer.roots)
    succ = build_successor_index(heads)

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

            issue = classify(
                working_stem=working_stem,
                stored_eo_root=eo_root,
                computed_head=computed_head,
                decomposition_kind=dec.kind,
                heads=heads,
                succ=succ,
                sv_threshold=sv_threshold,
            )
            issue_counts[issue] += 1
            if issue == ISSUE_OVER_REDUCED:
                over_reduced_heads[computed_head] += 1

            if issue == ISSUE_OK:
                continue

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
    written = sum(
        issue_counts.get(i, 0)
        for i in (ISSUE_TRUNCATION, ISSUE_MISMATCH, ISSUE_OVER_REDUCED)
    )
    lines.append(f"(ok records omitted; written records: {written})")
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
    parser.add_argument(
        "--sv-threshold", type=int, default=SV_THRESHOLD,
        help=(
            "Successor-variety threshold for over-reduction detection "
            f"(default: {SV_THRESHOLD}). Raise to 6 for stricter; lower "
            "to 4 if you want to surface more candidates."
        ),
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
        args.db, args.inventory, args.out, sv_threshold=args.sv_threshold,
    )
    print(render_summary(
        issue_counts, over_reduced_heads, total_examined, args.out
    ))


if __name__ == "__main__":
    main()
