"""Esperanto morphological decomposer — self-contained port.

This is a faithful, dependency-free port of the decomposition algorithm in
``src/lexicon/eo_root_decomposer.py`` (the lexicon repo's canonical
implementation). It is vendored here so the *runtime* scorer can decompose
arbitrary Esperanto text using only the tables carried inside a ``.bundle``,
with no dependency on the lexicon repo, its database, or the network.

The algorithm is identical to the canonical one; a ``slow`` parity test in the
test-suite cross-checks the two implementations on a sample of real stems so
they cannot silently diverge. See the canonical module's docstring for the full
rule description (Rule 1 solid-root short-circuit, Rule 2 function word, Rule 3
prefix/suffix/compound enumeration, Rule 4 selection key).

``strip_flexion`` and the grammatical ending tables (``VERB_END`` /
``NOMINAL_END``) are public-domain facts of Esperanto grammar and are inlined
here verbatim from ``build_eo_inventory.py``.
"""

from __future__ import annotations

import dataclasses

# ---------------------------------------------------------------------------
# Grammatical ending tables (public-domain Esperanto grammar)
# ---------------------------------------------------------------------------

VERB_END = ["as", "is", "os", "us", "u", "i"]
NOMINAL_END = ["o", "a", "e"]


def strip_flexion(s: str) -> str:
    """Strip the grammatical ending from a lowercased Esperanto word.

    Verbatim port of ``build_eo_inventory.strip_flexion`` — the single source
    of truth for endingless-stem extraction in the lexicon repo.
    """
    if s.endswith("n"):
        s = s[:-1]
    if s.endswith("j"):
        s = s[:-1]
    for e in VERB_END + NOMINAL_END:
        if s.endswith(e) and len(s) > len(e):
            return s[: -len(e)]
    return s


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CONNECTING_VOWELS = "oaei"
ACCUSATIVE_N = "n"

TIER_CORE = "core"
TIER_EXTENDED = "extended"
TIER_TAIL = "tail"

TIER_RANK = {TIER_CORE: 0, TIER_EXTENDED: 1, TIER_TAIL: 2}

PROD_FLOOR_FOR_TAIL = 2
SOLID_TIERS = frozenset({TIER_CORE, TIER_EXTENDED})

KIND_SINGLE_ROOT = "SINGLE_ROOT"
KIND_FUNCTION_WORD = "FUNCTION_WORD"
KIND_COMPOUND = "COMPOUND"
KIND_UNRESOLVED = "UNRESOLVED"


@dataclasses.dataclass(frozen=True)
class ContentRoot:
    root: str
    tier: str
    position: int


@dataclasses.dataclass(frozen=True)
class Decomposition:
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

    @property
    def roots(self) -> tuple[str, ...]:
        """Just the content-root strings, in position order."""
        return tuple(cr.root for cr in self.content_roots)


class Decomposer:
    """Analyse Esperanto stems against a tiered root inventory.

    ``inventory`` is the same dict shape the lexicon ``eo_inventory.json``
    uses: ``roots`` maps ``root -> {tier, prod, ...}``, plus list-valued
    ``suffixes`` / ``prefixes`` / ``correlatives`` / ``other`` /
    ``number_roots`` keys.
    """

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
        self.prefixes: set[str] = {p.lower() for p in inventory.get("prefixes", [])}
        self.correlatives: set[str] = {
            c.lower() for c in inventory.get("correlatives", [])
        }
        self.other: set[str] = {o.lower() for o in inventory.get("other", [])}

        self.bare_affix_set: set[str] = set(self.suffixes) | self.prefixes

        self._cache: dict[str, Decomposition | None] = {}

    # -- public API ------------------------------------------------------

    def decompose(self, stem: str) -> Decomposition:
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
        return result if result is not None else Decomposition(kind=KIND_UNRESOLVED)

    def decompose_word(self, eo_word: str) -> Decomposition:
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
        if s in self.number_roots:
            return True
        tier = self.tier_of.get(s)
        if tier is None:
            return False
        if tier in SOLID_TIERS:
            return True
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

    def _wrap_with_prefix(self, inner: Decomposition, prefix: str) -> Decomposition:
        return dataclasses.replace(
            inner,
            prefixes=(prefix,) + inner.prefixes,
            morpheme_count=inner.morpheme_count + 1,
        )

    def _wrap_with_suffix(self, inner: Decomposition, suffix: str) -> Decomposition:
        return dataclasses.replace(
            inner,
            suffixes=inner.suffixes + (suffix,),
            morpheme_count=inner.morpheme_count + 1,
        )

    def _prepend_component(
        self, leading: str, connector: str, inner: Decomposition
    ) -> Decomposition:
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
        if s in self._cache:
            return self._cache[s]
        if len(s) < 1:
            self._cache[s] = None
            return None

        if self._is_solid_root(s):
            result: Decomposition | None = Decomposition(
                kind=KIND_SINGLE_ROOT,
                content_roots=(self._root_record(s, position=0),),
                morpheme_count=1,
            )
            self._cache[s] = result
            return result

        candidates: list[Decomposition] = []

        if s in self.tier_of:
            candidates.append(
                Decomposition(
                    kind=KIND_SINGLE_ROOT,
                    content_roots=(self._root_record(s, position=0),),
                    morpheme_count=1,
                )
            )

        for p in self.prefixes:
            if len(p) >= len(s) or not s.startswith(p):
                continue
            inner = self._analyze(s[len(p):])
            if inner is None or inner.kind not in (KIND_SINGLE_ROOT, KIND_COMPOUND):
                continue
            candidates.append(self._wrap_with_prefix(inner, p))

        for suf in self.suffixes:
            if len(suf) >= len(s) or not s.endswith(suf):
                continue
            inner = self._analyze(s[: -len(suf)])
            if inner is None or inner.kind not in (KIND_SINGLE_ROOT, KIND_COMPOUND):
                continue
            candidates.append(self._wrap_with_suffix(inner, suf))

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
                    KIND_SINGLE_ROOT,
                    KIND_COMPOUND,
                ):
                    continue
                candidates.append(
                    self._prepend_component(
                        leading, s[i] if connector_len else "", inner
                    )
                )

        if not candidates:
            self._cache[s] = None
            return None

        candidates.sort(key=self._selection_key)
        best = candidates[0]
        self._cache[s] = best
        return best
