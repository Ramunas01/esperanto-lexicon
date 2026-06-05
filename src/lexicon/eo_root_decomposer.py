#!/usr/bin/env python3
"""Rewrite ``concept.eo_root`` / ``eo_prefix`` / ``eo_suffix`` to the BRO
canonical decomposition.

This is a one-shot migration over ``lexicon_v2.db``. It uses the BRO inventory
(``data/lexicon_db/eo_inventory.json``) as the authority for what counts as a
root, suffix, prefix, correlative, or function word, then walks every concept
whose ``eo_root`` is set and rewrites the morphological columns so that
``eo_root`` holds the **true root** and the affix columns spell out the chain.

Hard constraints (see ``CLAUDE.md``):
    * Touches only ``concept.eo_root``, ``concept.eo_prefix``,
      ``concept.eo_suffix``. Never modifies ``tier``, ``word``, ``cefr_level``,
      ``source``, or any ``concept_lang`` / ``inflected_forms`` row.
    * Idempotent — a row whose ``eo_root`` is already a bare inventory root
      (or function word) is detected as already-processed and skipped; the
      pre-existing affix columns are NOT cleared on a skip.
    * ``--dry-run`` performs the full analysis and prints would-be changes
      without writing anything.
    * Outside of ``--dry-run``, the DB file is backed up (timestamped) before
      the first write, and the updates run inside a single transaction.

Decomposition algorithm (in strict precedence order):

  Rule 1 — Inventory root wins outright. If the stem itself is in the
    root set (including the loaded number roots), it is returned as
    SINGLE_ROOT with no affix stripping attempted. This protects lexicalized
    roots that happen to end in affix-like letters (``maŝin``, ``magazen``).

  Rule 2 — Function word. If the stem is in ``correlatives`` or ``other``
    (or in those sets after stripping a trailing accusative ``-n``), it is a
    FUNCTION_WORD: ``eo_root`` is left untouched and the row is counted only.

  Rule 3 — Affix-strip with validated residue. Try each known prefix; if the
    stem starts with it AND the remainder fully decomposes to a SINGLE_ROOT
    or COMPOUND, accept. Then try each suffix (longest first), same rule.
    Affixes are NEVER stripped speculatively — only when the residue resolves.

  Rule 4 — Compound split. Scan split points from the longest leading root
    down; if ``s[:i]`` is an inventory root and ``s[i:]`` (optionally after
    consuming one connecting vowel from ``o a e i``) fully decomposes, the
    stem is a compound of two or more content roots.

  Otherwise — UNRESOLVED.

Determinism: amongst the candidates produced by rules 3 and 4 the result
with the **fewest morphemes** wins; ties are broken by the **longest matched
root**. Memoized on the residue string.

DECISION SURFACED TO HUMANS — compound anchoring
    The schema has a single ``eo_root`` column, so overwriting a compound's
    root with one component would corrupt the concept's lexical identity.
    This pass deliberately **leaves ``eo_root`` unchanged for compounds** and
    emits the component breakdown to ``eo_compounds.jsonl``. A follow-up
    decision is needed on how compounds should be anchored — see the PR body.

CLI::

    python3 src/lexicon/eo_root_decomposer.py \\
        --db data/lexicon_db/lexicon_v2.db \\
        --inventory data/lexicon_db/eo_inventory.json \\
        --out-dir data/lexicon_db/ \\
        [--dry-run]
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import shutil
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Number roots that BRO does not list in ``roots`` but every reader of
# Esperanto treats as content roots; loading them prevents compound numbers
# (``dudek``, ``tricent``) from drifting into UNRESOLVED.
NUMBER_ROOTS: frozenset[str] = frozenset({
    "nul", "unu", "du", "tri", "kvar", "kvin", "ses", "sep", "ok", "naŭ",
    "dek", "cent", "mil",
})

# Prepositional particles that also act as productive prefixes. The BRO
# inventory already covers most prefixes, but a handful of common particles
# (``sen``, ``sub``, ``retro``) are listed only in ``other`` even though they
# attach productively. Union these into the prefix set.
EXTRA_PREFIXES: frozenset[str] = frozenset({
    "ekster", "kontraŭ", "sen", "sub", "super", "trans", "sur", "tra",
    "for", "retro",
})

CONNECTING_VOWELS: str = "oaei"
ACCUSATIVE_N: str = "n"

# Common bare affixes called out in the spec as "artifact" exemplars; unioned
# with the full prefix/suffix sets at runtime.
EXPLICIT_BARE_AFFIXES: frozenset[str] = frozenset({
    "mal", "re", "ebl", "ul", "il", "in", "er", "ar", "et", "ĉef",
    "estr", "uj",
})

KIND_SINGLE_ROOT = "SINGLE_ROOT"
KIND_FUNCTION_WORD = "FUNCTION_WORD"
KIND_COMPOUND = "COMPOUND"
KIND_UNRESOLVED = "UNRESOLVED"


# ---------------------------------------------------------------------------
# Decomposition record
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class Decomposition:
    """Result of analysing one stem.

    For SINGLE_ROOT ``root`` is the content root; ``prefixes`` and
    ``suffixes`` list the affix chain in application order (outermost
    prefix first, outermost suffix last).

    For COMPOUND ``components`` lists the content roots left-to-right and
    ``connectors`` holds the connecting vowel between each pair (``""`` when
    none). ``prefixes`` / ``suffixes`` belong to the compound as a whole.
    """

    kind: str
    root: str | None = None
    prefixes: tuple[str, ...] = ()
    suffixes: tuple[str, ...] = ()
    components: tuple[str, ...] = ()
    connectors: tuple[str, ...] = ()
    morpheme_count: int = 0

    @property
    def representative_root_len(self) -> int:
        """Longest content-root length, used as the tie-breaker."""
        if self.kind == KIND_SINGLE_ROOT and self.root:
            return len(self.root)
        if self.kind == KIND_COMPOUND:
            return max((len(c) for c in self.components), default=0)
        return 0


# ---------------------------------------------------------------------------
# Decomposer
# ---------------------------------------------------------------------------


class Decomposer:
    """Analyse Esperanto stems against a BRO-derived inventory."""

    def __init__(self, inventory: dict) -> None:
        roots = {r.lower() for r in inventory.get("roots", {})}
        roots.update(NUMBER_ROOTS)
        self.roots: set[str] = roots
        self.suffixes: list[str] = sorted(
            {s.lower() for s in inventory.get("suffixes", [])},
            key=len,
            reverse=True,
        )
        self.prefixes: set[str] = (
            {p.lower() for p in inventory.get("prefixes", [])} | EXTRA_PREFIXES
        )
        self.correlatives: set[str] = {
            c.lower() for c in inventory.get("correlatives", [])
        }
        self.other: set[str] = {o.lower() for o in inventory.get("other", [])}
        # For "stem is itself a bare affix" artifact classification.
        self.bare_affix_set: set[str] = (
            set(self.suffixes) | set(self.prefixes) | EXPLICIT_BARE_AFFIXES
        )
        self._cache: dict[str, Decomposition | None] = {}

    # -- public ---------------------------------------------------------

    def decompose(self, stem: str) -> Decomposition:
        """Top-level analysis: applies rules 1, 2, then delegates to ``_analyze``.

        ``_analyze`` only ever returns SINGLE_ROOT / COMPOUND / None; the
        function-word check lives here because residues during recursion are
        not candidates for function-word classification.
        """
        if not stem:
            return Decomposition(kind=KIND_UNRESOLVED)
        s = stem.strip().lower()

        # Rule 1 — inventory root wins outright.
        if s in self.roots:
            return Decomposition(
                kind=KIND_SINGLE_ROOT, root=s, morpheme_count=1
            )

        # Rule 2 — function word (with optional accusative ``-n``).
        if s in self.correlatives or s in self.other:
            return Decomposition(kind=KIND_FUNCTION_WORD)
        if s.endswith(ACCUSATIVE_N) and len(s) > 1:
            base = s[:-1]
            if base in self.correlatives or base in self.other:
                return Decomposition(kind=KIND_FUNCTION_WORD)

        # Rules 3 + 4.
        result = self._analyze(s)
        if result is None:
            return Decomposition(kind=KIND_UNRESOLVED)
        return result

    # -- internal -------------------------------------------------------

    def _analyze(self, s: str) -> Decomposition | None:
        """Return the best Decomposition for residue *s*, or ``None``.

        Used recursively. Always returns SINGLE_ROOT or COMPOUND (never
        FUNCTION_WORD — residues aren't function words). Memoized on *s*.
        """
        if s in self._cache:
            return self._cache[s]
        if len(s) < 2:
            # Rule 1 below catches single-char roots that exist (e.g. none in
            # BRO, but keep the check honest); shorter than 1 is meaningless.
            if len(s) == 1 and s in self.roots:
                result: Decomposition | None = Decomposition(
                    kind=KIND_SINGLE_ROOT, root=s, morpheme_count=1
                )
            else:
                result = None
            self._cache[s] = result
            return result

        # Rule 1 — inventory root wins outright, even inside recursion.
        if s in self.roots:
            result = Decomposition(
                kind=KIND_SINGLE_ROOT, root=s, morpheme_count=1
            )
            self._cache[s] = result
            return result

        candidates: list[Decomposition] = []

        # Rule 3a — prefix strip with validated residue.
        for p in self.prefixes:
            if len(p) >= len(s):
                continue
            if not s.startswith(p):
                continue
            inner = self._analyze(s[len(p):])
            if inner is None or inner.kind not in (
                KIND_SINGLE_ROOT, KIND_COMPOUND
            ):
                continue
            candidates.append(
                dataclasses.replace(
                    inner,
                    prefixes=(p,) + inner.prefixes,
                    morpheme_count=inner.morpheme_count + 1,
                )
            )

        # Rule 3b — suffix strip with validated residue (longest first).
        for suf in self.suffixes:
            if len(suf) >= len(s):
                continue
            if not s.endswith(suf):
                continue
            inner = self._analyze(s[: -len(suf)])
            if inner is None or inner.kind not in (
                KIND_SINGLE_ROOT, KIND_COMPOUND
            ):
                continue
            candidates.append(
                dataclasses.replace(
                    inner,
                    suffixes=inner.suffixes + (suf,),
                    morpheme_count=inner.morpheme_count + 1,
                )
            )

        # Rule 4 — compound split (longest leading root first).
        for i in range(len(s) - 1, 1, -1):
            leading = s[:i]
            if leading not in self.roots:
                continue
            for connector_len in (0, 1):
                if connector_len == 1 and (
                    i >= len(s) or s[i] not in CONNECTING_VOWELS
                ):
                    continue
                residue_start = i + connector_len
                if residue_start >= len(s):
                    continue
                residue = s[residue_start:]
                inner = self._analyze(residue)
                if inner is None or inner.kind not in (
                    KIND_SINGLE_ROOT, KIND_COMPOUND
                ):
                    continue
                if inner.kind == KIND_SINGLE_ROOT:
                    inner_components: tuple[str, ...] = (inner.root or "",)
                    inner_connectors: tuple[str, ...] = ()
                else:
                    inner_components = inner.components
                    inner_connectors = inner.connectors
                candidates.append(
                    Decomposition(
                        kind=KIND_COMPOUND,
                        prefixes=inner.prefixes,
                        suffixes=inner.suffixes,
                        components=(leading,) + inner_components,
                        connectors=(
                            (s[i] if connector_len else "",)
                            + inner_connectors
                        ),
                        morpheme_count=1 + inner.morpheme_count,
                    )
                )

        if not candidates:
            self._cache[s] = None
            return None

        # Determinism: fewest morphemes, then longest representative root.
        candidates.sort(
            key=lambda c: (c.morpheme_count, -c.representative_root_len)
        )
        best = candidates[0]
        self._cache[s] = best
        return best


# ---------------------------------------------------------------------------
# Unresolved classification
# ---------------------------------------------------------------------------


def classify_unresolved(
    stem: str, decomposer: Decomposer
) -> tuple[str, str]:
    """Return ``(category, note)`` for an UNRESOLVED stem.

    Categories: ``artifact``, ``compound_number``, ``loanword``,
    ``international_root``, ``unknown``. The note records why.
    """
    s = stem.lower()
    if len(s) <= 2:
        return "artifact", f"length {len(s)} <= 2"
    if s in decomposer.bare_affix_set:
        return "artifact", "stem is a bare affix"

    # compound_number heuristic: any number root anywhere in the stem and
    # the rest looks number-shaped (i.e. composed of digits-of-letters) but
    # didn't fully resolve.
    for nr in NUMBER_ROOTS:
        if s.startswith(nr) and s != nr:
            tail = s[len(nr):]
            if any(tail.startswith(o) for o in NUMBER_ROOTS):
                return (
                    "compound_number",
                    f"begins with number root {nr!r} but {tail!r} unresolved",
                )

    # international_root advisory: ≥5 chars with a Latinate consonant cluster.
    if len(s) >= 5:
        latinate_clusters = ("nt", "nc", "ks", "pr", "tr", "kr", "sp", "st")
        if any(cl in s for cl in latinate_clusters):
            return (
                "international_root",
                "len >= 5 with Latinate cluster (advisory)",
            )

    if len(s) >= 3:
        return "loanword", "no inventory match"

    return "unknown", "no heuristic matched"


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class SummaryReport:
    processed: int = 0
    already_correct: int = 0
    updated: int = 0
    single_root_via_strip: int = 0
    function_word: int = 0
    compounds: int = 0
    unresolved: int = 0
    unresolved_by_category: Counter = dataclasses.field(
        default_factory=Counter
    )

    @property
    def decomposed_successfully(self) -> int:
        # SINGLE_ROOT (whether already correct or via stripping) + COMPOUND +
        # FUNCTION_WORD all count as "the decomposer reached a decision".
        return (
            self.already_correct
            + self.single_root_via_strip
            + self.compounds
            + self.function_word
        )

    def render(self) -> str:
        lines = [
            "EO root decomposer — summary",
            "=" * 32,
            f"Concepts processed         : {self.processed}",
            f"Decomposed successfully    : {self.decomposed_successfully}",
            f"Already correct (skipped)  : {self.already_correct}",
            f"Function words (skipped)   : {self.function_word}",
            f"Updated                    : {self.updated}",
            f"Compounds                  : {self.compounds}",
            f"Unresolved                 : {self.unresolved}",
        ]
        if self.unresolved_by_category:
            lines.append("  by category:")
            for cat in sorted(self.unresolved_by_category):
                lines.append(
                    f"    {cat:<22} : {self.unresolved_by_category[cat]}"
                )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# DB pass
# ---------------------------------------------------------------------------


def _join_chain(parts: tuple[str, ...]) -> str:
    return "+".join(parts) if parts else ""


def process_db(
    db_path: Path,
    decomposer: Decomposer,
    out_dir: Path,
    *,
    dry_run: bool,
) -> tuple[SummaryReport, list[tuple], list[dict], list[dict]]:
    """Walk every concept with a non-empty ``eo_root`` and apply the decomposer.

    Returns ``(summary, updates, compound_records, unresolved_records)``.

    When ``dry_run`` is True, no DB writes or jsonl files are produced; the
    returned data structures still describe what *would* have happened.
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    if not dry_run:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = db_path.with_name(
            f"{db_path.stem}.bak.{timestamp}{db_path.suffix}"
        )
        shutil.copy2(db_path, backup)
        print(f"Backup created: {backup}")

    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT id, eo_root, eo_word, eo_prefix, eo_suffix "
            "FROM concept "
            "WHERE eo_root IS NOT NULL AND eo_root <> ''"
        ).fetchall()

        summary = SummaryReport()
        updates: list[tuple] = []
        compound_records: list[dict] = []
        unresolved_records: list[dict] = []

        for cid, eo_root, eo_word, eo_prefix, eo_suffix in rows:
            summary.processed += 1
            existing_prefix = eo_prefix or ""
            existing_suffix = eo_suffix or ""
            stem = eo_root

            dec = decomposer.decompose(stem)

            if dec.kind == KIND_FUNCTION_WORD:
                summary.function_word += 1
                continue

            if dec.kind == KIND_UNRESOLVED:
                summary.unresolved += 1
                category, note = classify_unresolved(stem, decomposer)
                summary.unresolved_by_category[category] += 1
                unresolved_records.append({
                    "concept_id": cid,
                    "eo_root_stem": stem,
                    "eo_word": eo_word,
                    "category": category,
                    "note": note,
                })
                continue

            if dec.kind == KIND_SINGLE_ROOT:
                new_root = dec.root or stem
                new_prefix = _join_chain(dec.prefixes)
                new_suffix = _join_chain(dec.suffixes)
                is_bare_root_and_no_affixes = (
                    new_root == stem.lower()
                    and not dec.prefixes
                    and not dec.suffixes
                )
                if is_bare_root_and_no_affixes:
                    summary.already_correct += 1
                    continue
                # Only write if anything actually changes — also covers the
                # "previously partially-decomposed, now correct" case.
                if (
                    new_root != stem
                    or new_prefix != existing_prefix
                    or new_suffix != existing_suffix
                ):
                    updates.append((cid, new_root, new_prefix, new_suffix))
                    summary.updated += 1
                    summary.single_root_via_strip += 1
                else:
                    summary.already_correct += 1
                continue

            if dec.kind == KIND_COMPOUND:
                summary.compounds += 1
                # eo_root stays as the full compound stem — see DECISION in
                # the module docstring. Outer affixes still get written.
                new_prefix = _join_chain(dec.prefixes)
                new_suffix = _join_chain(dec.suffixes)
                if (
                    new_prefix != existing_prefix
                    or new_suffix != existing_suffix
                ):
                    updates.append((cid, stem, new_prefix, new_suffix))
                    summary.updated += 1
                compound_records.append({
                    "concept_id": cid,
                    "eo_root_stem": stem,
                    "eo_word": eo_word,
                    "component_roots": list(dec.components),
                    "connectors": list(dec.connectors),
                })
                continue

        if not dry_run:
            if updates:
                conn.executemany(
                    "UPDATE concept "
                    "SET eo_root = ?, eo_prefix = ?, eo_suffix = ? "
                    "WHERE id = ?",
                    [(r, p, s, cid) for cid, r, p, s in updates],
                )
            conn.commit()
            _write_jsonl(out_dir / "eo_compounds.jsonl", compound_records)
            _write_jsonl(
                out_dir / "eo_unresolved_stems.jsonl", unresolved_records
            )
        else:
            conn.rollback()

        return summary, updates, compound_records, unresolved_records
    finally:
        conn.close()


def _write_jsonl(path: Path, records: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# Inventory loading
# ---------------------------------------------------------------------------


def load_inventory(path: Path) -> dict:
    """Load and lightly validate the BRO inventory JSON."""
    if not path.exists():
        raise FileNotFoundError(f"Inventory not found: {path}")
    with path.open(encoding="utf-8") as fh:
        inv = json.load(fh)
    for key in ("roots", "suffixes", "prefixes", "correlatives", "other"):
        if key not in inv:
            raise ValueError(
                f"Inventory missing required key {key!r}: {path}"
            )
    return inv


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _print_dryrun_preview(updates: list[tuple], limit: int = 20) -> None:
    if not updates:
        print("(dry-run) no would-be updates.")
        return
    print(f"(dry-run) {len(updates)} would-be updates; first {min(limit, len(updates))}:")
    for cid, root, pfx, suf in updates[:limit]:
        print(
            f"  concept_id={cid}: eo_root={root!r} "
            f"eo_prefix={pfx!r} eo_suffix={suf!r}"
        )
    if len(updates) > limit:
        print(f"  ... and {len(updates) - limit} more")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Rewrite concept.eo_root/eo_prefix/eo_suffix from BRO inventory. "
            "Idempotent. --dry-run shows the diff without touching the DB."
        )
    )
    parser.add_argument(
        "--db", required=True, type=Path,
        help="Path to lexicon_v2.db",
    )
    parser.add_argument(
        "--inventory", required=True, type=Path,
        help="Path to eo_inventory.json",
    )
    parser.add_argument(
        "--out-dir", required=True, type=Path,
        help=(
            "Directory for eo_compounds.jsonl and eo_unresolved_stems.jsonl"
        ),
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Compute and print summary + would-be changes; write nothing",
    )
    args = parser.parse_args(argv)

    if not args.db.exists():
        print(f"Error: database not found: {args.db}", file=sys.stderr)
        sys.exit(1)

    inv = load_inventory(args.inventory)
    decomposer = Decomposer(inv)

    summary, updates, _compounds, _unresolved = process_db(
        args.db, decomposer, args.out_dir, dry_run=args.dry_run,
    )

    if args.dry_run:
        _print_dryrun_preview(updates)
    print(summary.render())


if __name__ == "__main__":
    main()
