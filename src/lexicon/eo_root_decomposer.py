#!/usr/bin/env python3
"""Rewrite ``concept.eo_root`` / ``eo_prefix`` / ``eo_suffix`` from the
ESPDIC-derived, tiered Esperanto inventory.

This is a one-shot migration over ``lexicon_v2.db``. It uses the inventory at
``data/lexicon_db/eo_inventory.json`` (produced by ``build_eo_inventory.py``,
ESPDIC + public-domain affix tables) as the authority for what counts as a
root, suffix, prefix, correlative, or function word. The inventory now tags
every root with a confidence tier (``core``, ``extended``, ``tail``); the
decomposer prefers analyses whose primitive roots are higher-tier.

Hard constraints (see ``CLAUDE.md``):
    * Touches only ``concept.eo_root``, ``concept.eo_prefix``,
      ``concept.eo_suffix``. Never modifies ``tier``, ``word``, ``cefr_level``,
      ``source``, or any ``concept_lang`` / ``inflected_forms`` row.
    * Idempotent — a row whose ``eo_root`` is already a bare inventory root or
      a function word is detected as already-processed and skipped; the
      pre-existing affix columns are NOT cleared on a skip.
    * ``--dry-run`` performs the full analysis and prints would-be changes
      without writing anything.
    * Outside of ``--dry-run``, the DB file is backed up (timestamped) before
      the first write, and updates run inside a single transaction.

Algorithm:

  Rule 1 — Solid root short-circuit. If the stem is itself a ``core`` or
    ``extended`` root, or a number root, return SINGLE_ROOT immediately and
    do not decompose. This is what keeps ``maŝin`` (core/extended) whole
    rather than wrongly splitting it into ``maŝ + in``.

  Rule 2 — Function word. If the stem is in ``correlatives`` or ``other``
    (or such a word plus a trailing accusative ``-n``), return FUNCTION_WORD.
    Checked BEFORE Rule 1 because some entries (``kun``, ``ili``) appear in
    both ``roots`` and ``other``; the function-word identity wins.

  Rule 3 — Enumerate every valid analysis:
    * the whole-stem-as-root analysis, IF the stem is in ``roots`` (any tier
      — a ``tail`` root is included as a candidate but not auto-kept by Rule 1);
    * every prefix-strip where the residue fully resolves;
    * every suffix-strip (longest suffix first) where the residue fully
      resolves;
    * every compound split ``leading-root + [connecting-vowel] + residue``
      where ``leading-root`` is in the inventory and the residue resolves.

  Rule 4 — Selection. Pick the candidate that minimises the lexicographic key
    ``(worst_tier_rank, morpheme_count, -leading_root_len)`` with
    ``core=0, extended=1, tail=2``. The tier component is what makes a
    candidate whose primitives are all core beat one that requires a tail
    root, even when both are valid.

  Otherwise — UNRESOLVED.

Memoized per stem.

DECISION SURFACED TO HUMANS — compound anchoring
    The schema has a single ``eo_root`` column. A compound like ``vaporŝip``
    has two content roots; overwriting ``eo_root`` with one component would
    corrupt the concept's lexical identity. This pass leaves ``eo_root``
    unchanged for compounds and emits the breakdown (including each
    component's tier) to ``eo_compounds.jsonl``. The follow-up decision is
    flagged in the PR body.

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

CONNECTING_VOWELS: str = "oaei"
ACCUSATIVE_N: str = "n"

TIER_CORE = "core"
TIER_EXTENDED = "extended"
TIER_TAIL = "tail"

TIER_RANK: dict[str, int] = {
    TIER_CORE: 0,
    TIER_EXTENDED: 1,
    TIER_TAIL: 2,
}

SOLID_TIERS: frozenset[str] = frozenset({TIER_CORE, TIER_EXTENDED})

# Bare-affix exemplars used in the ``artifact`` unresolved category — unioned
# with the inventory's full prefix and suffix sets at runtime.
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
    prefix first, outermost suffix last). For COMPOUND ``components`` lists
    the content roots left-to-right and ``connectors`` holds the connecting
    vowel between each pair (``""`` when none).
    """

    kind: str
    root: str | None = None
    prefixes: tuple[str, ...] = ()
    suffixes: tuple[str, ...] = ()
    components: tuple[str, ...] = ()
    connectors: tuple[str, ...] = ()
    morpheme_count: int = 0


# ---------------------------------------------------------------------------
# Decomposer
# ---------------------------------------------------------------------------


class Decomposer:
    """Analyse Esperanto stems against the tiered ESPDIC-derived inventory."""

    def __init__(self, inventory: dict) -> None:
        # roots is a dict ``{root: {gloss, prod, tier}}`` in the new format.
        raw_roots = inventory.get("roots", {})
        self.tier_of: dict[str, str] = {}
        for r, info in raw_roots.items():
            tier = (info or {}).get("tier", TIER_TAIL) if isinstance(info, dict) else TIER_TAIL
            self.tier_of[r.lower()] = tier

        # number_roots are loaded as core-tier regardless of any pre-existing
        # entry in ``roots`` (some — ``du``, ``ok`` — are tagged ``tail`` in
        # ESPDIC but every reader treats them as bedrock).
        self.number_roots: set[str] = {
            n.lower() for n in inventory.get("number_roots", [])
        }
        for nr in self.number_roots:
            self.tier_of[nr] = TIER_CORE

        self.roots: set[str] = set(self.tier_of.keys())

        # Affix and grammar tables come straight from the JSON — do not
        # hardcode or extend.
        self.suffixes: list[str] = sorted(
            {s.lower() for s in inventory.get("suffixes", [])},
            key=len,
            reverse=True,
        )
        self.prefixes: set[str] = {
            p.lower() for p in inventory.get("prefixes", [])
        }
        self.correlatives: set[str] = {
            c.lower() for c in inventory.get("correlatives", [])
        }
        self.other: set[str] = {o.lower() for o in inventory.get("other", [])}
        # Stored for completeness; not consumed by the algorithm itself
        # (stems in concept.eo_root are already endingless).
        self.verb_endings: set[str] = {
            v.lower() for v in inventory.get("verb_endings", [])
        }
        self.nominal_endings: set[str] = {
            v.lower() for v in inventory.get("nominal_endings", [])
        }

        self.bare_affix_set: set[str] = (
            set(self.suffixes) | self.prefixes | EXPLICIT_BARE_AFFIXES
        )

        self._cache: dict[str, Decomposition | None] = {}

    # -- public ---------------------------------------------------------

    def decompose(self, stem: str) -> Decomposition:
        """Top-level analysis: Rules 2 → 1 → (3+4) → UNRESOLVED.

        Rule 2 precedes Rule 1 because some BRO-style stems are in both
        ``roots`` and ``other`` (``kun``, ``ili``); the function-word
        identity wins. Inside recursion this priority does not apply —
        residues aren't function words.
        """
        if not stem:
            return Decomposition(kind=KIND_UNRESOLVED)
        s = stem.strip().lower()

        # Rule 2 — function word (precedence over Rule 1 for ambiguous stems).
        if self._is_function_word(s):
            return Decomposition(kind=KIND_FUNCTION_WORD)

        # Rule 1 — solid root short-circuit.
        if self._is_solid_root(s):
            return Decomposition(
                kind=KIND_SINGLE_ROOT, root=s, morpheme_count=1
            )

        result = self._analyze(s)
        if result is None:
            return Decomposition(kind=KIND_UNRESOLVED)
        return result

    # -- classification helpers ----------------------------------------

    def _is_function_word(self, s: str) -> bool:
        if s in self.correlatives or s in self.other:
            return True
        if s.endswith(ACCUSATIVE_N) and len(s) > 1:
            base = s[:-1]
            if base in self.correlatives or base in self.other:
                return True
        return False

    def _is_solid_root(self, s: str) -> bool:
        """True iff *s* is a root we never decompose further (Rule 1)."""
        if s in self.number_roots:
            return True
        if s in self.tier_of and self.tier_of[s] in SOLID_TIERS:
            return True
        return False

    # -- selection metrics ---------------------------------------------

    def _worst_tier_rank(self, d: Decomposition) -> int:
        """0=core, 1=extended, 2=tail. Used as the primary selection key."""
        if d.kind == KIND_SINGLE_ROOT and d.root is not None:
            return TIER_RANK.get(self.tier_of.get(d.root, TIER_TAIL), 2)
        if d.kind == KIND_COMPOUND and d.components:
            return max(
                TIER_RANK.get(self.tier_of.get(c, TIER_TAIL), 2)
                for c in d.components
            )
        return 2

    def _leading_root_len(self, d: Decomposition) -> int:
        if d.kind == KIND_SINGLE_ROOT and d.root is not None:
            return len(d.root)
        if d.kind == KIND_COMPOUND and d.components:
            return len(d.components[0])
        return 0

    def _selection_key(self, d: Decomposition) -> tuple[int, int, int]:
        return (
            self._worst_tier_rank(d),
            d.morpheme_count,
            -self._leading_root_len(d),
        )

    # -- internal recursion --------------------------------------------

    def _analyze(self, s: str) -> Decomposition | None:
        """Return the best Decomposition for residue *s*, or ``None``.

        Always returns SINGLE_ROOT or COMPOUND — residues aren't function
        words. Memoised on *s*.
        """
        if s in self._cache:
            return self._cache[s]
        if len(s) < 1:
            self._cache[s] = None
            return None

        # Solid roots short-circuit inside recursion too: no point exploring
        # alternative analyses when we have a high-confidence single-root
        # answer that costs only 1 morpheme.
        if self._is_solid_root(s):
            result: Decomposition | None = Decomposition(
                kind=KIND_SINGLE_ROOT, root=s, morpheme_count=1
            )
            self._cache[s] = result
            return result

        candidates: list[Decomposition] = []

        # Whole-stem-as-root candidate — only when ``s`` is in the inventory
        # at all (i.e. a tail root). Core/extended already short-circuited
        # above; non-roots have no whole-stem candidate.
        if s in self.tier_of:
            candidates.append(
                Decomposition(
                    kind=KIND_SINGLE_ROOT, root=s, morpheme_count=1
                )
            )

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

        # Rule 4 — compound split (longest leading root first iterated; final
        # tie-break is handled by the selection key, so iteration order only
        # affects which equivalent candidate is recorded first).
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

        candidates.sort(key=self._selection_key)
        best = candidates[0]
        self._cache[s] = best
        return best

    # -- tier inspection for reporting ---------------------------------

    def root_tier(self, root: str) -> str | None:
        """Return the inventory tier of *root* (``core`` / ``extended`` /
        ``tail``), or ``None`` if not in inventory."""
        return self.tier_of.get(root.lower())


# ---------------------------------------------------------------------------
# Unresolved classification
# ---------------------------------------------------------------------------


def classify_unresolved(
    stem: str, decomposer: Decomposer
) -> tuple[str, str]:
    """Return ``(category, note)`` for an UNRESOLVED stem.

    Categories with the tiered ESPDIC inventory: ``artifact`` dominates the
    residual (single letters, bare affixes left behind in the DB by earlier
    migrations); ``compound_number`` is rare (number roots are loaded);
    ``loanword`` and ``unknown`` are best-effort labels for stems that
    ESPDIC genuinely doesn't cover.
    """
    s = stem.lower()
    if len(s) <= 2:
        return "artifact", f"length {len(s)} <= 2"
    if s in decomposer.bare_affix_set:
        return "artifact", "stem is a bare affix"

    # compound_number heuristic: starts with a number root and the tail also
    # starts with one (but the whole thing didn't resolve, so a piece must be
    # missing or mistyped).
    for nr in sorted(decomposer.number_roots, key=len, reverse=True):
        if s.startswith(nr) and s != nr:
            tail = s[len(nr):]
            if any(tail.startswith(o) for o in decomposer.number_roots):
                return (
                    "compound_number",
                    f"begins with number root {nr!r} but {tail!r} unresolved",
                )
            break

    return "unknown", "no inventory analysis found"


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
    # SINGLE_ROOT resolutions counted by tier of the chosen root (a
    # confidence signal on the result).
    decomposed_by_tier: Counter = dataclasses.field(default_factory=Counter)
    unresolved_by_category: Counter = dataclasses.field(default_factory=Counter)

    @property
    def decomposed_successfully(self) -> int:
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
        if self.decomposed_by_tier:
            lines.append("  Single roots by tier:")
            for tier in (TIER_CORE, TIER_EXTENDED, TIER_TAIL):
                n = self.decomposed_by_tier.get(tier, 0)
                if n:
                    lines.append(f"    {tier:<10}: {n}")
        if self.unresolved_by_category:
            lines.append("  Unresolved by category:")
            for cat in sorted(self.unresolved_by_category):
                lines.append(
                    f"    {cat:<16}: {self.unresolved_by_category[cat]}"
                )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# DB pass
# ---------------------------------------------------------------------------


def _join_chain(parts: tuple[str, ...]) -> str:
    return "+".join(parts) if parts else ""


def _component_tiers(
    decomposer: Decomposer, components: tuple[str, ...]
) -> list[str]:
    return [decomposer.root_tier(c) or "unknown" for c in components]


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
    returned structures still describe what *would* have happened.
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
                tier = decomposer.root_tier(new_root) or TIER_TAIL
                summary.decomposed_by_tier[tier] += 1

                is_bare_root_and_no_affixes = (
                    new_root == stem.lower()
                    and not dec.prefixes
                    and not dec.suffixes
                )
                if is_bare_root_and_no_affixes:
                    summary.already_correct += 1
                    continue
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
                    "component_tiers": _component_tiers(
                        decomposer, dec.components
                    ),
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
    """Load and lightly validate the tiered inventory JSON."""
    if not path.exists():
        raise FileNotFoundError(f"Inventory not found: {path}")
    with path.open(encoding="utf-8") as fh:
        inv = json.load(fh)
    required_keys = (
        "roots", "suffixes", "prefixes", "correlatives", "other",
        "number_roots",
    )
    for key in required_keys:
        if key not in inv:
            raise ValueError(
                f"Inventory missing required key {key!r}: {path}"
            )
    # Spot-check the new ``{gloss, prod, tier}`` shape so a stale BRO-format
    # file fails fast rather than producing garbage decompositions.
    if inv["roots"]:
        sample_key = next(iter(inv["roots"]))
        sample_val = inv["roots"][sample_key]
        if not isinstance(sample_val, dict) or "tier" not in sample_val:
            raise ValueError(
                f"Inventory at {path} appears to use the legacy "
                "list-of-glosses format; expected "
                "{root: {gloss, prod, tier}}."
            )
    return inv


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _print_dryrun_preview(updates: list[tuple], limit: int = 20) -> None:
    if not updates:
        print("(dry-run) no would-be updates.")
        return
    print(
        f"(dry-run) {len(updates)} would-be updates; "
        f"first {min(limit, len(updates))}:"
    )
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
            "Rewrite concept.eo_root/eo_prefix/eo_suffix from the tiered "
            "ESPDIC inventory. Idempotent. --dry-run shows the diff "
            "without touching the DB."
        )
    )
    parser.add_argument(
        "--db", required=True, type=Path,
        help="Path to lexicon_v2.db",
    )
    parser.add_argument(
        "--inventory", required=True, type=Path,
        help="Path to eo_inventory.json (new {gloss, prod, tier} format)",
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
