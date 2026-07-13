"""Text → content-root resolver, shared by builder and runtime scorer.

The resolver turns text in a supported language into a list of content tokens,
each mapped to the Esperanto content roots it resolves to.

Resolution paths
----------------
* **Esperanto (``eo``)** — morphological decomposition via the bundled
  inventory (:class:`eolex.eo_decomposer.Decomposer`). Function words and
  bare affixes are dropped.
* **en / lt / other supported langs** — lemmatize then look up lemma in
  the word→root map. spaCy is used when installed; otherwise the lowercase
  surface form is used directly (reduced recall).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .eo_decomposer import (
    KIND_FUNCTION_WORD,
    Decomposer,
    strip_flexion,
)

_TOKEN_RE = re.compile(r"[^\W\d_]+", re.UNICODE)

MODEL_MAP = {
    "en": "en_core_web_sm",
    "lt": "lt_core_news_sm",
}


@dataclass(frozen=True)
class TokenResolution:
    """One content token and the content roots it resolved to."""

    surface: str
    lemma: str
    roots: tuple[str, ...]

    @property
    def resolved(self) -> bool:
        return len(self.roots) > 0


def tokenize(text: str) -> list[str]:
    """Lowercase, strip punctuation, return letter-only tokens."""
    return [m.group(0).lower() for m in _TOKEN_RE.finditer(text or "")]


class Resolver:
    """Resolve text in a supported language to content-root sequences."""

    def __init__(
        self,
        inventory: dict,
        word_root_map: dict[tuple[str, str], list[str]],
        langs: list[str],
        *,
        use_spacy: bool = True,
    ) -> None:
        self._decomposer = Decomposer(inventory)
        self._word_root = word_root_map
        self.langs = list(langs)
        self._use_spacy = use_spacy
        self._nlp_cache: dict[str, object | None] = {}

    # -- spaCy (optional) ----------------------------------------------------

    def _nlp(self, lang: str):
        if not self._use_spacy:
            return None
        if lang in self._nlp_cache:
            return self._nlp_cache[lang]
        model = MODEL_MAP.get(lang)
        nlp = None
        if model is not None:
            try:
                import spacy  # type: ignore

                nlp = spacy.load(model, disable=["ner", "parser"])
            except Exception:
                nlp = None
        self._nlp_cache[lang] = nlp
        return nlp

    @property
    def spacy_available(self) -> bool:
        return any(self._nlp(l) is not None for l in self.langs if l != "eo")

    # -- public API ----------------------------------------------------------

    def resolve(self, text: str, lang: str) -> list[TokenResolution]:
        if lang == "eo":
            return self._resolve_eo(text)
        return self._resolve_pack(text, lang)

    # -- Esperanto -----------------------------------------------------------

    def _resolve_eo(self, text: str) -> list[TokenResolution]:
        out: list[TokenResolution] = []
        for tok in tokenize(text):
            dec = self._decomposer.decompose_word(tok)
            if dec.kind == KIND_FUNCTION_WORD:
                continue
            stem = strip_flexion(tok)
            if not stem or stem in self._decomposer.bare_affix_set:
                continue
            out.append(
                TokenResolution(surface=tok, lemma=stem, roots=dec.roots)
            )
        return out

    # -- language packs (en / lt / …) ----------------------------------------

    def _resolve_pack(self, text: str, lang: str) -> list[TokenResolution]:
        nlp = self._nlp(lang)
        if nlp is not None:
            return self._resolve_pack_spacy(text, lang, nlp)
        return self._resolve_pack_surface(text, lang)

    def _resolve_pack_spacy(self, text, lang, nlp) -> list[TokenResolution]:
        out: list[TokenResolution] = []
        for tok in nlp(text or ""):
            if tok.is_space or tok.is_punct or tok.like_num or tok.is_stop:
                continue
            if not tok.text or not any(c.isalpha() for c in tok.text):
                continue
            lemma = (tok.lemma_ or tok.text).lower()
            surface = tok.text.lower()
            roots = self._lookup(lang, lemma) or self._lookup(lang, surface)
            out.append(
                TokenResolution(surface=surface, lemma=lemma, roots=tuple(roots))
            )
        return out

    def _resolve_pack_surface(self, text, lang) -> list[TokenResolution]:
        out: list[TokenResolution] = []
        for tok in tokenize(text):
            roots = self._lookup(lang, tok)
            out.append(TokenResolution(surface=tok, lemma=tok, roots=tuple(roots)))
        return out

    def _lookup(self, lang: str, word: str) -> list[str]:
        return list(self._word_root.get((lang, word), ()))
