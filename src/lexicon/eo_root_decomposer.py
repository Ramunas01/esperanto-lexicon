#!/usr/bin/env python3
"""Decompose every concept into its ordered root set + affix chain, and
populate the ``concept_root`` table that anchors compounds faithfully.

This pass replaces the single-``eo_root`` anchor with a many-to-many root
set. Each concept gets one ``concept_root`` row per content root with a
position, a tier, and an ``is_head`` flag (true only on the final root —
the Esperanto semantic head). ``eo_root`` is now the head root for every
concept, simple and compound alike; the full ordered set lives in
``concept_root``. Affix chains stay in ``eo_prefix`` / ``eo_suffix``.

Hard constraints (see ``CLAUDE.md``):
    * Writes only ``concept.eo_root``, ``concept.eo_prefix``,
      ``concept.eo_suffix``, and the ``concept_root`` table.
    * Never touches ``tier``, ``word``, ``cefr_level``, ``source``, or any
      ``concept_lang`` / ``inflected_forms`` row.
    * Idempotent by construction: the working stem is derived from
      ``concept.eo_word`` (a fixed input), the decomposition is deterministic,
      and ``concept_root`` is fully rebuilt via DELETE+INSERT inside a single
      transaction. Outside ``--dry-run`` the DB is backed up first.

Algorithm:

  Rule 1 — Solid root short-circuit. If the working stem is itself an
    inventory root and is either ``core``/``extended``, a number root, or
    has ``prod >= 2``, return SINGLE_ROOT and do not decompose. The
    productivity floor (prod>=2) is what stops the tier-preference selection
    from over-splitting lexicalized words like ``interpret``, ``period``,
    ``element``, ``tradici`` into core-root + affix. Only the
    *low-confidence singleton* (``tier == tail`` AND ``prod == 1``) is
    allowed to compete against alternative decompositions, so that words
    like ``interkonsent``, ``laŭlong``, ``surfac`` get correctly split.

  Rule 2 — Function word. If the stem is in ``correlatives`` or ``other``
    (or such a word plus a trailing accusative ``-n``), return
    FUNCTION_WORD. Checked BEFORE Rule 1 because stems like ``kun`` and
    ``ili`` appear in both ``roots`` and ``other``; the function-word
    identity wins for them.

  Rule 3 — Enumerate every valid analysis:
    * the whole-stem-as-root candidate, IF the stem is in the inventory
      (any tier — Rule 1 already short-circuited the high-confidence ones);
    * every prefix-strip with a fully-resolving residue;
    * every suffix-strip (longest first) with a fully-resolving residue;
    * every compound split (leading-root + [connecting vowel] + residue).

  Rule 4 — Selection by ``(worst_tier_rank, morpheme_count, -leading_root_len)``
    with ``core=0, extended=1, tail=2``. Tier-rank is primary: a candidate
    whose worst primitive is core beats one needing a tail root.

The working stem is sourced from ``concept.eo_word`` via ``strip_flexion``,
not from the previously-stored ``concept.eo_root`` (which the v1→v2
migration sometimes truncated). This makes ``eo_root`` a pure OUTPUT.
Concepts with no usable ``eo_word`` are skipped and counted as
``no_word``.

CLI::

    python3 src/lexicon/eo_root_decomposer.py \\
        --db data/lexicon_db/lexicon_v2.db \\
        --inventory data/lexicon_db/eo_inventory.json \\
        [--dry-run]

Unresolved stems are emitted to ``data/lexicon_db/eo_unresolved_stems.jsonl``.
The previous ``eo_compounds.jsonl`` is no longer needed — compounds are
exactly ``SELECT concept_id FROM concept_root GROUP BY concept_id HAVING
COUNT(*) > 1``.
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

# Allow `python3 src/lexicon/eo_root_decomposer.py …` to resolve
# `from src.lexicon...` imports. Tests run from the project root so this is
# a no-op there; the harmless re-insert just lets the CLI work too.
_project_root = Path(__file__).resolve().parents[2]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

# strip_flexion is the single source of truth for endingless-stem extraction;
# the inventory builder uses it the same way during root extraction.
from src.lexicon.build_eo_inventory import strip_flexion  # noqa: E402


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CONNECTING_VOWELS: str = "oaei"
ACCUSATIVE_N: str = "n"

TIER_CORE = "core"
TIER_EXTENDED = "extended"
# `modern` is the tier carried by entries from eo_roots_supplement.tsv —
# curated modern borrowings absent from ESPDIC. Treated like `extended`
# for keep-whole / selection rules so a supplement entry is never a
# low-confidence singleton that competes against decompositions.
TIER_MODERN = "modern"
TIER_TAIL = "tail"

TIER_RANK: dict[str, int] = {
    TIER_CORE: 0,
    TIER_EXTENDED: 1,
    TIER_MODERN: 1,
    TIER_TAIL: 2,
}

# Rule 1 productivity floor: a tail root with prod >= this value still
# short-circuits Rule 1. The threshold of 2 means "attested by at least two
# distinct ESPDIC headwords" — strong enough evidence that the stem is a
# lexical unit and shouldn't be re-analysed.
PROD_FLOOR_FOR_TAIL: int = 2

SOLID_TIERS: frozenset[str] = frozenset(
    {TIER_CORE, TIER_EXTENDED, TIER_MODERN}
)

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
class ContentRoot:
    """One content root in a decomposition with its inventory tier and the
    0-based position it occupies within the word."""

    root: str
    tier: str
    position: int


@dataclasses.dataclass(frozen=True)
class Decomposition:
    """Unified representation of every decomposer outcome.

    For SINGLE_ROOT, ``content_roots`` has exactly one entry; for COMPOUND,
    two or more. The semantic head is always the **last** content root
    (Esperanto convention). FUNCTION_WORD and UNRESOLVED have no
    ``content_roots``.

    ``connectors`` carries the connecting vowel between each pair of
    components (``""`` when none); ``prefixes`` and ``suffixes`` are the
    word-level affix chains.
    """

    kind: str
    content_roots: tuple[ContentRoot, ...] = ()
    prefixes: tuple[str, ...] = ()
    suffixes: tuple[str, ...] = ()
    connectors: tuple[str, ...] = ()
    morpheme_count: int = 0

    @property
    def head(self) -> ContentRoot | None:
        return self.content_roots[-1] if self.content_roots else None

    @property
    def is_compound(self) -> bool:
        return len(self.content_roots) >= 2


# ---------------------------------------------------------------------------
# Decomposer
# ---------------------------------------------------------------------------


class Decomposer:
    """Analyse Esperanto stems against the tiered ESPDIC-derived inventory."""

    def __init__(self, inventory: dict) -> None:
        raw_roots = inventory.get("roots", {})
        self.tier_of: dict[str, str] = {}
        self.prod_of: dict[str, int] = {}
        for r, info in raw_roots.items():
            info = info or {}
            tier = info.get("tier", TIER_TAIL) if isinstance(info, dict) else TIER_TAIL
            prod = info.get("prod", 0) if isinstance(info, dict) else 0
            key = r.lower()
            self.tier_of[key] = tier
            self.prod_of[key] = prod

        # Number roots are loaded as core-tier regardless of any pre-existing
        # entry in ``roots`` (a handful — ``du``, ``ok`` — are tagged ``tail``
        # in ESPDIC but every reader treats them as bedrock).
        self.number_roots: set[str] = {
            n.lower() for n in inventory.get("number_roots", [])
        }
        for nr in self.number_roots:
            self.tier_of[nr] = TIER_CORE
            self.prod_of.setdefault(nr, 1)

        self.roots: set[str] = set(self.tier_of.keys())

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

        self.bare_affix_set: set[str] = (
            set(self.suffixes) | self.prefixes | EXPLICIT_BARE_AFFIXES
        )

        self._cache: dict[str, Decomposition | None] = {}

    # -- public API ------------------------------------------------------

    def decompose(self, stem: str) -> Decomposition:
        """Decompose an endingless stem.

        Rule 2 → Rule 1 → recursive Rule 3+4 → UNRESOLVED. Inside recursion
        function-word checks do not apply (residues aren't function words).
        """
        if not stem:
            return Decomposition(kind=KIND_UNRESOLVED)
        s = stem.strip().lower()

        if self._is_function_word(s):
            return Decomposition(kind=KIND_FUNCTION_WORD)

        if self._is_solid_root(s):
            return Decomposition(
                kind=KIND_SINGLE_ROOT,
                content_roots=(self._root_record(s, position=0),),
                morpheme_count=1,
            )

        result = self._analyze(s)
        if result is None:
            return Decomposition(kind=KIND_UNRESOLVED)
        return result

    def decompose_word(self, eo_word: str) -> Decomposition:
        """Strip flexion then decompose. The DB pass uses this so callers
        don't have to duplicate the strip step.

        Function-word check runs on the RAW lowercased word before
        ``strip_flexion`` — otherwise particles whose final letter
        coincides with the accusative ``-n`` (``kun``, ``sen``) would be
        truncated and lose their identity.
        """
        if not eo_word:
            return Decomposition(kind=KIND_UNRESOLVED)
        raw = eo_word.strip().lower()
        if self._is_function_word(raw):
            return Decomposition(kind=KIND_FUNCTION_WORD)
        stem = strip_flexion(raw)
        return self.decompose(stem)

    def root_tier(self, root: str) -> str | None:
        return self.tier_of.get(root.lower())

    # -- classification helpers -----------------------------------------

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
        tier = self.tier_of.get(s)
        if tier is None:
            return False
        if tier in SOLID_TIERS:
            return True
        # tier == tail: only protect when productivity meets the floor.
        return self.prod_of.get(s, 0) >= PROD_FLOOR_FOR_TAIL

    def _root_record(self, root: str, position: int) -> ContentRoot:
        return ContentRoot(
            root=root,
            tier=self.tier_of.get(root, TIER_TAIL),
            position=position,
        )

    # -- selection metrics ----------------------------------------------

    def _worst_tier_rank(self, d: Decomposition) -> int:
        if not d.content_roots:
            return 2
        return max(TIER_RANK.get(cr.tier, 2) for cr in d.content_roots)

    def _leading_root_len(self, d: Decomposition) -> int:
        if not d.content_roots:
            return 0
        return len(d.content_roots[0].root)

    def _selection_key(self, d: Decomposition) -> tuple[int, int, int]:
        return (
            self._worst_tier_rank(d),
            d.morpheme_count,
            -self._leading_root_len(d),
        )

    # -- composition helpers --------------------------------------------

    def _wrap_with_prefix(
        self, inner: Decomposition, prefix: str
    ) -> Decomposition:
        return dataclasses.replace(
            inner,
            prefixes=(prefix,) + inner.prefixes,
            morpheme_count=inner.morpheme_count + 1,
        )

    def _wrap_with_suffix(
        self, inner: Decomposition, suffix: str
    ) -> Decomposition:
        return dataclasses.replace(
            inner,
            suffixes=inner.suffixes + (suffix,),
            morpheme_count=inner.morpheme_count + 1,
        )

    def _prepend_component(
        self,
        leading: str,
        connector: str,
        inner: Decomposition,
    ) -> Decomposition:
        """Build a COMPOUND by prepending one root + connector to ``inner``.

        Renumbers ``content_roots`` so positions are contiguous from 0.
        """
        leading_record = self._root_record(leading, position=0)
        inner_records = tuple(
            ContentRoot(cr.root, cr.tier, position=cr.position + 1)
            for cr in inner.content_roots
        )
        return Decomposition(
            kind=KIND_COMPOUND,
            content_roots=(leading_record,) + inner_records,
            prefixes=inner.prefixes,
            suffixes=inner.suffixes,
            connectors=(connector,) + inner.connectors,
            morpheme_count=1 + inner.morpheme_count,
        )

    # -- internal recursion ---------------------------------------------

    def _analyze(self, s: str) -> Decomposition | None:
        """Return the best Decomposition for residue *s*, or ``None``.

        Always returns SINGLE_ROOT or COMPOUND. Memoised.
        """
        if s in self._cache:
            return self._cache[s]
        if len(s) < 1:
            self._cache[s] = None
            return None

        # High-confidence roots short-circuit inside recursion too.
        if self._is_solid_root(s):
            result: Decomposition | None = Decomposition(
                kind=KIND_SINGLE_ROOT,
                content_roots=(self._root_record(s, position=0),),
                morpheme_count=1,
            )
            self._cache[s] = result
            return result

        candidates: list[Decomposition] = []

        # Whole-stem-as-root candidate — only when ``s`` is in the inventory
        # at all. Core/extended and prod>=2 tail short-circuited above; what
        # falls through is the prod=1 tail (low-confidence singleton).
        if s in self.tier_of:
            candidates.append(
                Decomposition(
                    kind=KIND_SINGLE_ROOT,
                    content_roots=(self._root_record(s, position=0),),
                    morpheme_count=1,
                )
            )

        # Rule 3a — prefix strip.
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
            candidates.append(self._wrap_with_prefix(inner, p))

        # Rule 3b — suffix strip (longest first).
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
            candidates.append(self._wrap_with_suffix(inner, suf))

        # Rule 4 — compound split (longest leading root first iterated; the
        # selection key handles the final ordering).
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
                candidates.append(
                    self._prepend_component(
                        leading,
                        s[i] if connector_len else "",
                        inner,
                    )
                )

        if not candidates:
            self._cache[s] = None
            return None

        candidates.sort(key=self._selection_key)
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

    Categories: ``artifact`` (length ≤ 2 or stem is a bare affix),
    ``compound_number`` (number-root prefix with unresolved tail),
    ``loanword`` (reserved for stems clearly outside ESPDIC; not auto-set
    here without external evidence), ``unknown`` (default).
    """
    s = stem.lower()
    if len(s) <= 2:
        return "artifact", f"length {len(s)} <= 2"
    if s in decomposer.bare_affix_set:
        return "artifact", "stem is a bare affix"

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
    skipped_no_word: int = 0
    simple: int = 0
    compound: int = 0
    function_word: int = 0
    unresolved: int = 0
    eo_root_changed: int = 0
    eo_root_unchanged: int = 0
    concept_root_rows: int = 0
    head_tier_distribution: Counter = dataclasses.field(default_factory=Counter)
    unresolved_by_category: Counter = dataclasses.field(default_factory=Counter)

    def render(self) -> str:
        lines = [
            "EO root decomposer — summary",
            "=" * 32,
            f"Concepts processed         : {self.processed}",
            f"Skipped (no eo_word)       : {self.skipped_no_word}",
            f"Simple (1 root)            : {self.simple}",
            f"Compound (>=2 roots)       : {self.compound}",
            f"Function words             : {self.function_word}",
            f"Unresolved                 : {self.unresolved}",
            f"concept_root rows written  : {self.concept_root_rows}",
            f"eo_root changed            : {self.eo_root_changed}",
            f"eo_root unchanged          : {self.eo_root_unchanged}",
        ]
        if self.head_tier_distribution:
            lines.append("  Head-root tiers:")
            for tier in (TIER_CORE, TIER_EXTENDED, TIER_MODERN, TIER_TAIL):
                n = self.head_tier_distribution.get(tier, 0)
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


_CONCEPT_ROOT_DDL = """
CREATE TABLE IF NOT EXISTS concept_root (
    concept_id INTEGER NOT NULL REFERENCES concept(id),
    root       TEXT    NOT NULL,
    position   INTEGER NOT NULL,
    is_head    INTEGER NOT NULL DEFAULT 0,
    tier       TEXT,
    PRIMARY KEY (concept_id, position)
);
"""

_CONCEPT_ROOT_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_concept_root_root "
    "ON concept_root(root);"
)


def _join_chain(parts: tuple[str, ...]) -> str:
    return "+".join(parts) if parts else ""


def _ensure_concept_root_table(conn: sqlite3.Connection) -> None:
    conn.execute(_CONCEPT_ROOT_DDL)
    conn.execute(_CONCEPT_ROOT_INDEX)


def process_db(
    db_path: Path,
    decomposer: Decomposer,
    *,
    dry_run: bool,
    out_dir: Path | None = None,
) -> tuple[
    SummaryReport,
    list[tuple],            # (id, new_root, new_prefix, new_suffix) updates
    list[tuple],            # (concept_id, root, position, is_head, tier) rows
    list[dict],             # unresolved jsonl records
]:
    """Walk every concept and rebuild ``concept_root`` + the three concept
    morphology columns from ``eo_word``.

    Returns ``(summary, concept_updates, concept_root_rows, unresolved_records)``.
    When ``dry_run`` is True, no DB writes or jsonl files are produced; the
    returned structures describe what *would* have happened.
    """
    if out_dir is not None:
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
        _ensure_concept_root_table(conn)

        rows = conn.execute(
            "SELECT id, eo_root, eo_word, eo_prefix, eo_suffix "
            "FROM concept"
        ).fetchall()

        summary = SummaryReport()
        concept_updates: list[tuple] = []
        concept_root_rows: list[tuple] = []
        unresolved_records: list[dict] = []

        for cid, eo_root, eo_word, eo_prefix, eo_suffix in rows:
            summary.processed += 1
            existing_root = eo_root or ""
            existing_prefix = eo_prefix or ""
            existing_suffix = eo_suffix or ""

            if not (eo_word and eo_word.strip()):
                summary.skipped_no_word += 1
                summary.eo_root_unchanged += 1
                continue

            stem = strip_flexion(eo_word.strip().lower())
            dec = decomposer.decompose_word(eo_word)

            if dec.kind == KIND_FUNCTION_WORD:
                summary.function_word += 1
                summary.eo_root_unchanged += 1
                continue

            if dec.kind == KIND_UNRESOLVED:
                summary.unresolved += 1
                summary.eo_root_unchanged += 1
                category, note = classify_unresolved(stem, decomposer)
                summary.unresolved_by_category[category] += 1
                unresolved_records.append({
                    "concept_id": cid,
                    "eo_word": eo_word,
                    "working_stem": stem,
                    "stored_eo_root": existing_root,
                    "category": category,
                    "note": note,
                })
                continue

            # SINGLE_ROOT or COMPOUND — both flow through the same path now.
            if dec.is_compound:
                summary.compound += 1
            else:
                summary.simple += 1

            head = dec.head
            assert head is not None  # has content_roots → head exists
            summary.head_tier_distribution[head.tier] += 1

            new_root = head.root
            new_prefix = _join_chain(dec.prefixes)
            new_suffix = _join_chain(dec.suffixes)

            if (
                new_root != existing_root
                or new_prefix != existing_prefix
                or new_suffix != existing_suffix
            ):
                concept_updates.append(
                    (cid, new_root, new_prefix, new_suffix)
                )
            if new_root != existing_root:
                summary.eo_root_changed += 1
            else:
                summary.eo_root_unchanged += 1

            # Build concept_root rows — one per content root.
            last_index = len(dec.content_roots) - 1
            for cr in dec.content_roots:
                concept_root_rows.append(
                    (
                        cid,
                        cr.root,
                        cr.position,
                        1 if cr.position == last_index else 0,
                        cr.tier,
                    )
                )

        summary.concept_root_rows = len(concept_root_rows)

        if not dry_run:
            # Full rebuild of concept_root — guarantees byte-identical state
            # on rerun and dodges any prior partial-update ambiguity.
            conn.execute("DELETE FROM concept_root")
            if concept_root_rows:
                conn.executemany(
                    "INSERT INTO concept_root "
                    "(concept_id, root, position, is_head, tier) "
                    "VALUES (?, ?, ?, ?, ?)",
                    concept_root_rows,
                )
            if concept_updates:
                conn.executemany(
                    "UPDATE concept "
                    "SET eo_root = ?, eo_prefix = ?, eo_suffix = ? "
                    "WHERE id = ?",
                    [(r, p, s, cid) for cid, r, p, s in concept_updates],
                )
            conn.commit()

            if out_dir is not None:
                _write_jsonl(
                    out_dir / "eo_unresolved_stems.jsonl",
                    unresolved_records,
                )
        else:
            conn.rollback()

        return summary, concept_updates, concept_root_rows, unresolved_records
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
        print("(dry-run) no would-be concept updates.")
        return
    print(
        f"(dry-run) {len(updates)} would-be concept updates; "
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
            "Decompose every concept's eo_word into its root set + affix "
            "chain. Populates concept_root and rewrites the three concept "
            "morphology columns. Idempotent. --dry-run shows the diff "
            "without touching the DB."
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
        "--out-dir", required=False, type=Path, default=None,
        help=(
            "Directory for eo_unresolved_stems.jsonl. If omitted, defaults "
            "to the directory holding --db."
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
    out_dir = args.out_dir or args.db.parent

    summary, updates, _root_rows, _unresolved = process_db(
        args.db, decomposer, dry_run=args.dry_run, out_dir=out_dir,
    )

    if args.dry_run:
        _print_dryrun_preview(updates)
    print(summary.render())


if __name__ == "__main__":
    main()
