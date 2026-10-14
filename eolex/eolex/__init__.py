"""eolex — thin read-side API over the Esperanto lexicon.

Provides morphological decomposition, multilingual word→root resolution,
and pedagogical tier / CEFR lookups — all from a single portable bundle,
no lexicon database or network access required at runtime.

Typical use::

    from eolex import Lexicon
    lex = Lexicon.load()                        # packaged bundle
    lex.roots("akvobirdo", lang="eo")           # ["akv", "bird"]
    lex.inventory_tier("akv")                   # "core"
    lex.pedagogical_tier("akvo", lang="eo")     # 1
    lex.cefr("akvo", lang="eo")                 # "A1"

For advanced use, ``Bundle``, ``Decomposer``, and ``Resolver`` are importable
directly. ``RelevanceScorer`` lives in the ``eolex_relevance`` package.
"""

from __future__ import annotations

from pathlib import Path

from .bundle import Bundle
from .eo_decomposer import Decomposer, Decomposition
from .resolver import Resolver

__version__ = "0.1.0"
__all__ = ["Lexicon", "Bundle", "Decomposer", "Decomposition", "Resolver", "__version__"]


class Lexicon:
    """Read-side facade over a lexicon bundle.

    Exposes morphology (inventory side) and expertise labels (pedagogical side)
    under distinct, clearly named methods so the two tier systems cannot be
    confused:

    * ``inventory_tier(root)``  → core / extended / tail / modern
    * ``pedagogical_tier(word, lang)`` → 1 / 2 / 3 / 4
    """

    def __init__(self, bundle: Bundle) -> None:
        self._bundle = bundle
        self._decomposer = Decomposer(bundle.inventory)

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Lexicon":
        """Load from a bundle file, or from the packaged default bundle.

        ``path=None`` loads the bundle shipped with the package — no lexicon
        DB or network access is needed.
        """
        if path is None:
            from importlib.resources import files

            path = files("eolex").joinpath("data/lexicon.bundle")
        return cls(Bundle.load(path))

    # -- morphology / inventory side -----------------------------------------

    def roots(self, word: str, lang: str = "eo") -> list[str]:
        """Content roots for *word* in *lang*.

        For Esperanto: morphological decomposition; a compound yields multiple
        roots. For other languages: lookup in the word→root map.
        """
        if lang == "eo":
            return list(self._decomposer.decompose_word(word).roots)
        return list(self._bundle.word_root_map.get((lang, word.strip().lower()), []))

    def decompose(self, word: str, lang: str = "eo") -> Decomposition:
        """Full morphological decomposition (Esperanto only).

        Returns a :class:`~eolex.eo_decomposer.Decomposition` with
        ``head``, ``roots``, ``is_compound``, prefixes, and suffixes.
        """
        if lang != "eo":
            raise ValueError(f"decompose() requires lang='eo'; got {lang!r}")
        return self._decomposer.decompose_word(word)

    def inventory_tier(self, root: str) -> str | None:
        """Inventory productivity tier of *root*: core / extended / tail / None.

        This is the ESPDIC-derived tier indicating how productive the root is
        in word-building — NOT the pedagogical expertise ladder.
        """
        info = (self._bundle.inventory.get("roots") or {}).get(root.lower())
        if not info:
            return None
        return info.get("tier")

    def gloss(self, root: str) -> str | None:
        """English gloss for *root*, or None if unknown."""
        return self._bundle.gloss_of(root.lower())

    # -- expertise / abstraction side ----------------------------------------

    def pedagogical_tier(self, word: str, lang: str = "eo") -> int | None:
        """Pedagogical tier (1–4) for *word* in *lang*, or None.

        Tier 1 = child / A1; Tier 2 = adolescent / A2–B2;
        Tier 3 = adult general / C1+; Tier 4 = domain expert.
        This is the expertise ladder used by the abstraction axis — distinct
        from ``inventory_tier`` which measures morphological productivity.

        For Esperanto (lang='eo'), the tier is derived from the concept's
        associated language entries (minimum across languages).
        """
        entry = self._bundle.concept_lang_map.get((lang, word.strip().lower()))
        return entry[0] if entry else None

    def cefr(self, word: str, lang: str = "eo") -> str | None:
        """CEFR level for *word* in *lang* (e.g. 'A1', 'B2'), or None."""
        entry = self._bundle.concept_lang_map.get((lang, word.strip().lower()))
        return entry[1] if entry else None
