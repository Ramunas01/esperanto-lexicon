"""Runtime relevance scorer — loads only a bundle, no lexicon DB, no network.

This is the class downstream projects import::

    from eolex_relevance import RelevanceScorer
    scorer = RelevanceScorer.load("customs_law_med.bundle")
    res = scorer.score("La importinstanco kontrolis la deklaron.", lang="eo")
    res.vector            # [0.81, 0.12, 0.03]
    res.as_dict()         # {"customs": 0.81, "law": 0.12, "medicine": 0.03}
    res.coverage          # 0.92
    res.explain("customs")

Scoring is a transparent TF-IDF-over-roots cosine — no embeddings, no training.
See :mod:`eolex_relevance.build` for the exact compile-time math; the score-time
half is documented inline below and is its mirror image.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

import numpy as np

from .bundle import Bundle
from .resolver import Resolver, TokenResolution

NORMALIZE_MODES = ("none", "l1", "max")


def _l2_normalize(v: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(v))
    if norm == 0.0:
        return v
    return v / norm


@dataclass
class ScoreResult:
    """The outcome of scoring one text against a bundle's domains."""

    domains: list[str]
    vector: list[float]
    coverage: float
    normalize: str
    raw_vector: list[float]
    resolution: float
    n_content_tokens: int
    n_resolved_tokens: int
    n_covered_tokens: int
    _u: np.ndarray = field(repr=False, default=None)
    _bundle: Bundle = field(repr=False, default=None)

    def as_dict(self) -> dict[str, float]:
        """Map domain name → (output-normalized) relevance score."""
        return dict(zip(self.domains, self.vector))

    def top(self, k: int = 3) -> list[tuple[str, float]]:
        """The k highest-scoring domains as ``(name, score)`` pairs."""
        pairs = sorted(
            zip(self.domains, self.vector), key=lambda kv: kv[1], reverse=True
        )
        return pairs[:k]

    def explain(self, domain: str, top_k: int = 10) -> list[dict]:
        """Top contributing roots for *domain*, most influential first.

        Each entry is ``{root, contribution, text_weight, domain_weight,
        gloss}``. ``contribution = text_weight * domain_weight``; the sum over
        all roots equals the raw (pre-output-normalization) cosine for the
        domain. Useful for interpreting *why* a text scored as it did.
        """
        if domain not in self.domains:
            raise KeyError(
                f"Unknown domain {domain!r}; known: {self.domains}"
            )
        di = self.domains.index(domain)
        b = self._bundle
        w = b.vectors[di]
        contrib = self._u * w
        order = np.argsort(contrib)[::-1]
        out: list[dict] = []
        for j in order:
            c = float(contrib[j])
            if c <= 0.0:
                break
            root = b.vocab[j]
            out.append(
                {
                    "root": root,
                    "contribution": c,
                    "text_weight": float(self._u[j]),
                    "domain_weight": float(w[j]),
                    "gloss": b.gloss_of(root),
                }
            )
            if len(out) >= top_k:
                break
        return out


class RelevanceScorer:
    """Score text relevance against the domains compiled into a bundle."""

    def __init__(self, bundle: Bundle, *, use_spacy: bool = True) -> None:
        self.bundle = bundle
        self.resolver = Resolver(
            bundle.inventory,
            bundle.word_root_map,
            bundle.langs,
            use_spacy=use_spacy,
        )

    @classmethod
    def load(cls, path, *, use_spacy: bool = True) -> "RelevanceScorer":
        return cls(Bundle.load(path), use_spacy=use_spacy)

    @property
    def domains(self) -> list[str]:
        return self.bundle.domains

    def resolve(self, text: str, lang: str) -> list[TokenResolution]:
        """Expose the resolver output (mainly for debugging / inspection)."""
        return self.resolver.resolve(text, lang)

    def score(
        self, text: str, lang: str, *, normalize: str = "none"
    ) -> ScoreResult:
        """Score *text* (in language *lang*) against every bundle domain.

        ``normalize`` controls the output vector: ``none`` (raw cosines,
        default), ``l1`` (components sum to 1 — a domain profile), or ``max``
        (largest component scaled to 1).
        """
        if normalize not in NORMALIZE_MODES:
            raise ValueError(
                f"normalize must be one of {NORMALIZE_MODES}, got {normalize!r}"
            )

        resolutions = self.resolver.resolve(text, lang)
        n_content = len(resolutions)
        b = self.bundle
        ridx = b.root_index

        # Content-root multiset c(r) — every root of every content token,
        # so a compound credits each of its roots.
        c: Counter[str] = Counter()
        n_resolved = 0
        n_covered = 0
        for tr in resolutions:
            if tr.roots:
                n_resolved += 1
            if any(r in ridx for r in tr.roots):
                n_covered += 1
            for r in tr.roots:
                c[r] += 1

        total_roots = sum(c.values())
        u = np.zeros(len(b.vocab), dtype=np.float64)
        if total_roots > 0:
            for root, count in c.items():
                j = ridx.get(root)
                if j is None:
                    continue  # OOV for scoring; still counted for coverage
                tf = count / total_roots
                u[j] = tf * b.idf[j]
        u = _l2_normalize(u)

        # relevance_i = cosine(u, w_i); rows of b.vectors are L2-normalized.
        raw = b.vectors @ u  # shape (D,)
        raw_vec = [float(x) for x in raw]
        vector = self._apply_normalize(raw, normalize)

        coverage = (n_covered / n_content) if n_content else 0.0
        resolution = (n_resolved / n_content) if n_content else 0.0

        return ScoreResult(
            domains=list(b.domains),
            vector=vector,
            coverage=coverage,
            normalize=normalize,
            raw_vector=raw_vec,
            resolution=resolution,
            n_content_tokens=n_content,
            n_resolved_tokens=n_resolved,
            n_covered_tokens=n_covered,
            _u=u,
            _bundle=b,
        )

    @staticmethod
    def _apply_normalize(raw: np.ndarray, mode: str) -> list[float]:
        if mode == "none":
            return [float(x) for x in raw]
        if mode == "l1":
            s = float(raw.sum())
            return [float(x / s) if s > 0 else 0.0 for x in raw]
        if mode == "max":
            m = float(raw.max()) if raw.size else 0.0
            return [float(x / m) if m > 0 else 0.0 for x in raw]
        raise ValueError(mode)  # pragma: no cover
