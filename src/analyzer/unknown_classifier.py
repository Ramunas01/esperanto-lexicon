#!/usr/bin/env python3
"""Cross-corpus UNKNOWN token classifier (read-only diagnostic).

Turns UNKNOWN from a scalar into a taxonomy. Each pooled UNKNOWN token is placed
in exactly one bucket, evaluated **in this order** (first match wins):

  1. ``junk``          — structural noise or a token that is essentially not an
                         English word (``wordfreq`` zipf below :data:`JUNK_ZIPF`).
                         Filtered FIRST; its volume is not signal.
  2. ``named_entity``  — resolves in the ``named_entity`` store (``confirmed``) or
                         looks like a name (spaCy PROPN / proper-noun casing) but is
                         absent from the store (``candidate`` → name_candidates.tsv).
                         The known elephant.
  3. ``inflection_miss``— the token's lemma resolves in the lexicon though the
                         surface form did not (a pipeline miss, not a gap).
  4. ``domain_term``   — UNKNOWN only within domain-tagged corpora (e.g. customs),
                         absent from the general/child corpora → Tier-4, not a
                         common gap.
  5. ``common_gap``    — an ordinary common English word (zipf ≥ :data:`COMMON_ZIPF`)
                         UNKNOWN across ≥2 corpora (incl. a non-domain one) — a plain
                         gap the gap-fill would take.
  6. ``true_residual`` — the deliverable: what's left, UNKNOWN across ≥2 corpora.
                         The surprises.

Tokens UNKNOWN in only ONE (non-domain) corpus that fall through are tagged
``local`` — a single-corpus artifact, reported but not part of the true residual.

**Universality** = the number of corpora a token is UNKNOWN in; it is the ranking
key for ``common_gap`` / ``true_residual`` (UNKNOWN-everywhere = a structural hole).

This module is pure and import-safe: :func:`classify_token` takes a
:class:`TokenFeatures` (all features precomputed) and returns a
:class:`Classification`. Feature computation (wordfreq, spaCy, the name store,
lemma resolution) lives in the driver so the logic is testable without a network
or heavy models.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

# --- tunable thresholds (documented in the memo) ---------------------------
# zipf is log10(freq per billion words) + 9. zipf < 1.5 ≈ appears < ~1 in 30M
# words — essentially not a real English word (real rare words like 'embargo'
# ≈3.5, 'hippopotamus' ≈2.6 sit well above). COMMON_ZIPF ≈ 3.0 marks an ordinary
# everyday word.
JUNK_ZIPF = 1.5
COMMON_ZIPF = 3.0
MIN_UNIVERSALITY = 2  # "cross-corpus" = UNKNOWN in ≥2 corpora

BUCKETS = (
    "junk", "named_entity", "inflection_miss",
    "domain_term", "common_gap", "true_residual", "local",
)

_URLISH = re.compile(r"https?://|www\.|\.com|\.org|/|@|\\")
_HAS_DIGIT = re.compile(r"\d")
_ALPHA_HYPHEN = re.compile(r"^[a-zà-ÿ]+(?:-[a-zà-ÿ]+)*$", re.IGNORECASE)


def is_structural_junk(token: str) -> bool:
    """Structural noise independent of frequency: too short, digits, URLs, symbols.

    Pure alphabetic tokens (optionally internally hyphenated, ``co-operate``) are
    NOT structural junk — they are judged by frequency downstream.
    """
    t = token.strip()
    if len(t) < 2:
        return True
    if _HAS_DIGIT.search(t) or _URLISH.search(t):
        return True
    return not _ALPHA_HYPHEN.match(t)


@dataclass(frozen=True)
class TokenFeatures:
    """Everything the classifier needs about one pooled UNKNOWN token."""

    token: str
    universality: int          # number of corpora UNKNOWN in
    n_domain_corpora: int      # of those, how many are domain-tagged
    n_nondomain_corpora: int   # of those, how many are non-domain
    zipf: float                # wordfreq zipf (0.0 if unknown to wordfreq)
    is_propn: bool             # ever tagged spaCy PROPN
    is_name_cased: bool        # ever appeared with proper-noun casing
    lemma_resolves: bool       # token's lemma resolves in the lexicon
    store_match: bool          # resolves in the named_entity store

    @property
    def looks_like_name(self) -> bool:
        return self.is_propn or self.is_name_cased


@dataclass
class Classification:
    bucket: str
    subtype: str = ""  # e.g. 'confirmed'/'candidate' for named_entity


def classify_token(f: TokenFeatures) -> Classification:
    """Assign one bucket to a token from its precomputed features (pure)."""
    # 1. junk — structural, or essentially-not-a-word by frequency. A token that
    #    resolves in the name store or clearly looks like a name is exempted here
    #    (a rare real name can have a low zipf) and handled by bucket 2.
    if is_structural_junk(f.token):
        return Classification("junk", "structural")
    if f.zipf < JUNK_ZIPF and not f.store_match and not f.looks_like_name:
        return Classification("junk", "low_freq")

    # 2. named_entity — the elephant. A store hit is authoritative. The
    #    heuristic candidate path (spaCy PROPN / name casing) is noisy on
    #    lowercased pooled tokens, so it excludes anything whose base form is a
    #    known common word — those are inflections spaCy mis-tagged as PROPN
    #    (sentence-initial "Loved"), not names, and belong to inflection_miss.
    if f.store_match:
        return Classification("named_entity", "confirmed")
    if f.is_name_cased:  # strong: proper-noun casing seen off sentence-start
        return Classification("named_entity", "candidate")
    if f.is_propn and not f.lemma_resolves:  # weak PROPN-only, base not a real word
        return Classification("named_entity", "candidate")

    # 3. inflection_miss — lemma resolves though the surface form did not.
    if f.lemma_resolves:
        return Classification("inflection_miss")

    # 4. domain_term — UNKNOWN only inside domain corpora.
    if f.n_domain_corpora >= 1 and f.n_nondomain_corpora == 0:
        return Classification("domain_term")

    # 5/6. cross-corpus residual (≥2 corpora, and reaches a non-domain corpus).
    if f.universality >= MIN_UNIVERSALITY:
        if f.zipf >= COMMON_ZIPF:
            return Classification("common_gap")
        return Classification("true_residual")

    # Single-corpus, non-domain leftover.
    return Classification("local")


# ---------------------------------------------------------------------------
# Aggregation helpers (pure) — used by the driver and by tests.
# ---------------------------------------------------------------------------


@dataclass
class TokenRecord:
    """A fully-classified token row for the output TSVs."""

    token: str
    per_corpus_counts: dict[str, int]
    universality: int
    total_count: int
    zipf: float
    is_propn: bool
    is_name_cased: bool
    lemma: str
    lemma_resolves: bool
    store_match: bool
    bucket: str
    subtype: str = ""
    corpora: list[str] = field(default_factory=list)


def summarise_buckets(records: list[TokenRecord]) -> dict[str, dict[str, int]]:
    """Return ``{bucket: {'types': n_distinct, 'tokens': sum_of_counts}}``."""
    out: dict[str, dict[str, int]] = {b: {"types": 0, "tokens": 0} for b in BUCKETS}
    for r in records:
        out[r.bucket]["types"] += 1
        out[r.bucket]["tokens"] += r.total_count
    return out


def true_residual_pct(
    per_corpus_total_tokens: dict[str, int],
    records: list[TokenRecord],
    corpus: Optional[str] = None,
) -> float:
    """True-residual UNKNOWN % = residual UNKNOWN tokens / total tokens.

    If *corpus* is given, restrict to that corpus's counts; else pool across all.
    'Residual' = the ``true_residual`` bucket (the honest leftover after names +
    junk + domain + inflection + common-gap are subtracted).
    """
    if corpus is not None:
        total = per_corpus_total_tokens.get(corpus, 0)
        resid = sum(
            r.per_corpus_counts.get(corpus, 0)
            for r in records if r.bucket == "true_residual"
        )
    else:
        total = sum(per_corpus_total_tokens.values())
        resid = sum(r.total_count for r in records if r.bucket == "true_residual")
    return round(100.0 * resid / total, 3) if total else 0.0
