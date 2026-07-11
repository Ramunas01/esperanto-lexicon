#!/usr/bin/env python3
"""Inventory-vs-tier root coverage (read-only, corpus-free diagnostic).

Flips coverage analysis from corpus-driven to **inventory-driven**: joins the
ESPDIC root inventory (``eo_inventory.json`` — 26k roots + English glosses) against
``lexicon_v2.db`` (concepts + pedagogical tiers) to surface the Esperanto roots the
*language* treats as common that our T1–T3 tiers never picked up. A cross-source
consistency check (ESPDIC vs the English tier sources) that needs no corpus.

**Read-only. Authors nothing.** The output TSVs are review material — each hit needs
a later human glance ("real missing concept, or does English lexicalize it
differently?").

Per uncovered root, the ESPDIC gloss is scored for commonness with ``wordfreq``,
handling three measured traps:
  1. Verb glosses start ``"to "`` / noun glosses with an article — a naive head
     scorer scores ``to`` (zipf 7.4) for every verb. We strip leading function
     words and score the *content* word.
  2. A common head word != a common concept (``incens``="to burn incense"). We
     require the gloss's first sense to reduce to a **single common content word**;
     multi-word / phrasal / parenthetical glosses are treated as obscure.
  3. Derived-form glosses (``abrad``="abrasive") cause false gaps. Before deciding a
     gloss word is "not a concept", we normalize it (spaCy lemma + ``inflected_forms``
     + the British ``uk_to_us`` fold) against the concept ``en`` words.

Buckets (per root):
  * ``covered_T1_3``   — a T1/T2/T3 en concept anchors this root.
  * ``obscure_root``   — uncovered and the gloss fails the commonness gate. Counted.
  * ``candidate_gap``  — uncovered, single common content word, AND that word is NOT
                         already a concept. The prize (a suggested tier is attached).
  * ``shade_mismatch`` — uncovered, gloss common, but the English word IS already a
                         concept: Esperanto splits a sense English blurs
                         (``lepor``="hare, rabbit" uncovered while ``kunikl`` covered).

The pure functions (scoring, bucket logic) are import-safe and unit-tested with
fixtures; ``wordfreq`` / spaCy / DB access live in the driver.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional

# Leading (and internal, for the word count) function words to strip so the
# *content* head is scored, not "to"/"a"/"of".
FUNCTION_WORDS = frozenset({
    "to", "a", "an", "the", "be", "of", "with", "in", "on", "for", "at", "by",
    "as", "or", "and", "into", "from", "one's", "someone", "something", "s.o", "s.t",
})

# Closed-class English stopwords. A gloss whose head reduces to one of these is a
# grammatical morpheme root (pronoun/conjunction/particle: `mi`=my, `sed`=but,
# `ĉi`=all) — a covered function word with a very high zipf, NOT a lexical gap or a
# meaningful granularity split. Prefer spaCy's standard list; fall back to a core
# set so the pure module needs no model.
try:
    from spacy.lang.en.stop_words import STOP_WORDS as _SPACY_STOP  # static import
    STOPWORDS = frozenset(_SPACY_STOP)
except Exception:  # pragma: no cover - defensive fallback
    STOPWORDS = frozenset({
        "i", "me", "my", "we", "us", "our", "you", "your", "he", "him", "his",
        "she", "her", "it", "its", "they", "them", "their", "this", "that",
        "these", "those", "who", "whom", "which", "what", "all", "any", "some",
        "no", "not", "and", "or", "but", "so", "if", "as", "than", "then",
        "here", "there", "when", "where", "why", "how", "be", "is", "are", "was",
        "were", "have", "has", "had", "do", "does", "did", "will", "would",
        "can", "could", "may", "might", "must", "of", "to", "in", "on", "at",
        "by", "for", "with", "about", "up", "out", "off", "over", "again",
    })

MIN_GLOSS_ZIPF = 3.0  # content word must be at least this common
# Commonness -> suggested pedagogical tier (zipf bands).
TIER_ZIPF_BANDS = ((5.0, 1), (4.0, 2), (3.0, 3))

_PAREN = re.compile(r"[()\[\]]")
_ALPHA = re.compile(r"^[a-z][a-z'\-]*$")


def first_sense(gloss: str) -> str:
    """The first comma/semicolon-separated sense of a gloss (original case, stripped)."""
    return re.split(r"[,;]", gloss, maxsplit=1)[0].strip()


def content_words(sense: str) -> list[str]:
    """Alphabetic content words of a sense (function words + non-alpha removed).

    Preserves original case (the proper-noun signal); function-word filtering is
    case-insensitive. Hyphenated tokens are kept as single tokens so the scorer can
    reject them (they are compounds/modern coinages, not single common roots).
    """
    out: list[str] = []
    for tok in sense.replace("/", " ").split():
        tok = tok.strip(".!?\"'")
        low = tok.lower()
        if low in FUNCTION_WORDS:
            continue
        if _ALPHA.match(low):
            out.append(tok)
    return out


@dataclass
class ScoredGloss:
    """Commonness verdict for a gloss's first sense."""

    head: str            # the scored content word, lowercased ("" if none)
    zipf: float          # its wordfreq zipf (0.0 if not scored)
    common_short: bool   # passes the single-common-word gate
    reason: str          # ok | paren | multiword | empty | proper_noun | hyphenated | low_zipf


def score_gloss(gloss: str, zipf_fn: Callable[[str], float],
                min_zipf: float = MIN_GLOSS_ZIPF) -> ScoredGloss:
    """Score a gloss's first sense: single common *common-noun* content word.

    Guards, in order:
      * trap #1 — leading ``to``/articles stripped by :func:`content_words`;
      * trap #2 — phrasal / multi-word / parenthetical sense -> obscure (a common
        head word is not a common concept);
      * **proper nouns / demonyms** (``American``, ``Google``, ``Louis``) — a
        capitalised content word is a name, out of scope for the common lexicon
        (the names layer owns those) -> obscure;
      * **hyphenated compounds / modern coinages** (``e-book``, ``co-author``) ->
        obscure;
      * commonness — ``zipf >= min_zipf``.
    """
    sense = first_sense(gloss)
    if _PAREN.search(sense):
        return ScoredGloss("", 0.0, False, "paren")
    cw = content_words(sense)  # original case preserved
    if not cw:
        return ScoredGloss("", 0.0, False, "empty")
    if len(cw) != 1:  # phrasal / multi-word -> obscure (trap #2)
        return ScoredGloss(cw[0].lower(), 0.0, False, "multiword")
    raw = cw[0]
    if raw[:1].isupper():  # proper noun / demonym -> names layer, not common lexicon
        return ScoredGloss(raw.lower(), 0.0, False, "proper_noun")
    if "-" in raw:  # compound / modern coinage
        return ScoredGloss(raw.lower(), 0.0, False, "hyphenated")
    head = raw.lower()
    if head in STOPWORDS:  # grammatical morpheme root (pronoun/conjunction/particle)
        return ScoredGloss(head, 0.0, False, "stopword")
    z = zipf_fn(head)
    if z < min_zipf:
        return ScoredGloss(head, round(z, 2), False, "low_zipf")
    return ScoredGloss(head, round(z, 2), True, "ok")


def suggest_tier(zipf: float) -> int:
    """Map a commonness zipf to a suggested pedagogical tier (T1 most common)."""
    for threshold, tier in TIER_ZIPF_BANDS:
        if zipf >= threshold:
            return tier
    return 3


# ---------------------------------------------------------------------------
# Covered-word check (trap #3: normalize before deciding "not a concept")
# ---------------------------------------------------------------------------


def normalized_forms(
    word: str,
    lemma_fn: Callable[[str], str],
    inflected_map: dict[str, str],
    uk_fold: Callable[[str], str],
) -> set[str]:
    """All lexicon-facing forms of a gloss word to test against concept en words.

    Covers inflection (spaCy lemma), the ``inflected_forms`` surface->lemma map
    (which now carries the British spelling fold), and the ``uk_to_us`` fold
    directly — so derived/inflected/British glosses don't read as false gaps.
    """
    w = word.lower()
    forms = {w, lemma_fn(w), uk_fold(w)}
    if w in inflected_map:
        forms.add(inflected_map[w])
    us = uk_fold(w)
    if us in inflected_map:
        forms.add(inflected_map[us])
    return {f for f in forms if f}


def word_is_covered(
    word: str, en_words: frozenset[str], lemma_fn, inflected_map, uk_fold
) -> bool:
    """True if *word* (any normalized form) is already an existing concept en word."""
    return bool(normalized_forms(word, lemma_fn, inflected_map, uk_fold) & en_words)


def gloss_words_all(gloss: str) -> list[str]:
    """Content words across ALL senses of a gloss (for the shade-mismatch check)."""
    seen: list[str] = []
    for sense in re.split(r"[,;]", gloss):
        for w in content_words(sense.strip().lower()):
            if w not in seen:
                seen.append(w)
    return seen


# ---------------------------------------------------------------------------
# Per-root classification
# ---------------------------------------------------------------------------

BUCKETS = ("covered_T1_3", "obscure_root", "candidate_gap", "shade_mismatch")


@dataclass
class RootRecord:
    root: str
    gloss: str
    inv_tier: str            # core | extended | tail | modern (ESPDIC confidence)
    prod: int
    covered_tiers: list[int]  # pedagogical tiers anchoring this root ([] if none)
    bucket: str
    gloss_head: str = ""
    gloss_zipf: float = 0.0
    suggested_tier: Optional[int] = None
    matched_word: str = ""    # for shade_mismatch: the covered English word
    reason: str = ""


def classify_root(
    root: str,
    entry: dict,
    covered_tiers: list[int],
    en_words: frozenset[str],
    zipf_fn,
    lemma_fn,
    inflected_map,
    uk_fold,
) -> RootRecord:
    """Assign one bucket to a root given its inventory entry and coverage."""
    gloss = entry.get("gloss", "") or ""
    rec = RootRecord(
        root=root, gloss=gloss, inv_tier=entry.get("tier", ""),
        prod=int(entry.get("prod", 0) or 0), covered_tiers=sorted(covered_tiers),
        bucket="", gloss_head="", gloss_zipf=0.0,
    )
    if covered_tiers:
        rec.bucket = "covered_T1_3"
        return rec

    scored = score_gloss(gloss, zipf_fn)
    rec.gloss_head, rec.gloss_zipf, rec.reason = scored.head, scored.zipf, scored.reason
    if not scored.common_short:
        rec.bucket = "obscure_root"
        return rec

    # Gap vs shade vs derivative turns on WHICH sense is already covered (trap #3
    # normalization applied throughout):
    #   * primary sense head already covered  -> a derivative/compound/synonym of a
    #     covered concept (`kronometr`="to time", `uzad`="to use"), not a novel
    #     entry -> obscure.
    #   * primary head uncovered but a LATER sense covered -> a genuine granularity
    #     split (`lepor`="hare, rabbit": hare uncovered, rabbit covered).
    #   * no sense covered -> a real missing concept (candidate_gap), unless the
    #     tail prior applies.
    covered = lambda w: word_is_covered(w, en_words, lemma_fn, inflected_map, uk_fold)
    if covered(scored.head):
        rec.bucket = "obscure_root"
        rec.reason = "primary_covered"
        return rec
    later_covered = next(
        (w for w in gloss_words_all(gloss)
         if w != scored.head and w not in STOPWORDS and covered(w)), ""
    )
    if later_covered:
        rec.bucket = "shade_mismatch"
        rec.matched_word = later_covered
    elif rec.inv_tier == "tail":
        # A common single-word gloss on a *tail*-confidence root is far more often
        # an obscure concept ESPDIC glossed with a common word than a genuinely
        # missing common concept. Tail is a strong obscure prior (per the brief).
        rec.bucket = "obscure_root"
        rec.reason = "tail_prior"
    else:
        rec.bucket = "candidate_gap"
        rec.suggested_tier = suggest_tier(scored.zipf)
    return rec


def summarise(records: Iterable[RootRecord]) -> dict:
    """Bucket counts + candidate-gap breakdown by suggested tier."""
    from collections import Counter

    recs = list(records)
    buckets = Counter(r.bucket for r in recs)
    gap_by_tier = Counter(
        r.suggested_tier for r in recs if r.bucket == "candidate_gap"
    )
    inv_tier_of_gaps = Counter(
        r.inv_tier for r in recs if r.bucket == "candidate_gap"
    )
    return {
        "buckets": dict(buckets),
        "candidate_gap_by_suggested_tier": {t: gap_by_tier.get(t, 0) for t in (1, 2, 3)},
        "candidate_gap_by_inventory_tier": dict(inv_tier_of_gaps),
    }
