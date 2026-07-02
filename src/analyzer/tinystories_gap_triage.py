#!/usr/bin/env python3
"""Triage the pooled UNKNOWN tokens from a TinyStories coverage probe.

This is a *common-vocabulary hygiene* tool, not an expertise analysis.
It consumes the pooled UNKNOWN-token file produced by
``batch_coverage_report`` (RUN A, no domain DBs) plus the raw TinyStories
corpus, and answers a single question: *which* of the tokens the pipeline
could not classify represent genuine Tier-1/2 lexicon gaps, and which are
noise (proper nouns) or pipeline lemmatisation misses.

Buckets (mutually exclusive, evaluated in this order):

  inflection_miss
      The token's isolated spaCy lemma resolves in ``concept_lang`` (any
      tier) for the language, OR the token / its lemma appears in the
      lexicon's ``inflected_forms``.  These are *not* lexicon gaps — the
      base word is already known; the pipeline simply failed to reduce the
      surface form to it in context.  Because the analyzer already performs
      lemma and inflected-form lookup, this bucket is expected to be SMALL.
      A large bucket signals a lemmatisation bug and should be flagged.

  proper_noun
      The token is majority-capitalised in corpus context and/or was tagged
      ``PROPN`` by spaCy, and its lemma is unresolved (Peter, Lily, Timmy).
      Expected and ignorable for common-lexicon purposes.

  common_gap
      Everything else.  This frequency-ranked bucket IS the prioritised
      Tier-1/2 gap-fill queue for human review.

The script is strictly READ-ONLY on the lexicon.  It never writes to the
lexicon DB and never changes any tier, word, cefr_level, or source.  The
gap queue and tier-3 misassignment flags are OUTPUT FOR HUMAN REVIEW.

Usage::

    python3 src/analyzer/tinystories_gap_triage.py \\
        --pooled data/analysis/tinystories_run/unknown_tokens_pooled.txt \\
        --corpus ~/projects/esperanto-lexicon-corpus/tinystories \\
        --lexicon data/lexicon_db/lexicon_v2.db \\
        --lang en \\
        --output-tsv data/analysis/tinystories_unknown_triaged.tsv
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

# Bucket labels (single source of truth).
BUCKET_INFLECTION_MISS = "inflection_miss"
BUCKET_PROPER_NOUN = "proper_noun"
BUCKET_COMMON_GAP = "common_gap"


@dataclass
class UnknownToken:
    """One pooled UNKNOWN token with the features needed for bucketing."""

    token: str
    frequency: int
    lemma: str  # isolated spaCy lemma, lowercased
    is_propn: bool  # ever tagged PROPN in corpus context
    is_capitalized: bool  # majority-capitalised across corpus occurrences


# ---------------------------------------------------------------------------
# Pooled-file parsing
# ---------------------------------------------------------------------------


def parse_pooled_unknowns(path: Path) -> Counter[str]:
    """Parse a ``COUNT\\tTOKEN`` pooled-unknown file into a Counter.

    Malformed lines (wrong field count, non-integer count) are skipped.
    """
    counter: Counter[str] = Counter()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) != 2:
            continue
        count_str, token = parts
        try:
            counter[token] = int(count_str)
        except ValueError:
            continue
    return counter


# ---------------------------------------------------------------------------
# Lexicon loading (READ-ONLY)
# ---------------------------------------------------------------------------


def load_lexicon_words(lexicon_db: Path, lang: str) -> set[str]:
    """Return every lowercased ``concept_lang.word`` for *lang* (any tier)."""
    if not lexicon_db.exists():
        return set()
    conn = sqlite3.connect(lexicon_db)
    try:
        return {
            row[0]
            for row in conn.execute(
                "SELECT LOWER(word) FROM concept_lang WHERE lang = ?", (lang,)
            )
        }
    finally:
        conn.close()


def load_inflected_words(lexicon_db: Path, lang: str) -> set[str]:
    """Return the union of lowercased inflected forms and their lemmas for *lang*."""
    if not lexicon_db.exists():
        return set()
    conn = sqlite3.connect(lexicon_db)
    try:
        words: set[str] = set()
        for inflected, lemma in conn.execute(
            "SELECT LOWER(inflected_word), LOWER(lemma) FROM inflected_forms"
            " WHERE lang = ?",
            (lang,),
        ):
            words.add(inflected)
            words.add(lemma)
        return words
    finally:
        conn.close()


def load_tier3_words(lexicon_db: Path, lang: str) -> set[str]:
    """Return lowercased Tier 3 words from ``concept_lang`` for *lang*."""
    if not lexicon_db.exists():
        return set()
    conn = sqlite3.connect(lexicon_db)
    try:
        return {
            row[0]
            for row in conn.execute(
                "SELECT LOWER(word) FROM concept_lang WHERE lang = ? AND tier = 3",
                (lang,),
            )
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Pure logic: bucketing, ranking, tier-3 frequencies
# ---------------------------------------------------------------------------


def classify_bucket(
    unknown: UnknownToken,
    lexicon_words: set[str],
    inflected_words: set[str],
) -> str:
    """Assign one UNKNOWN token to a triage bucket.

    Evaluation order (first match wins): inflection_miss → proper_noun →
    common_gap.  ``lexicon_words`` is the set of all lowercased
    ``concept_lang`` words (any tier); ``inflected_words`` is the union of
    lowercased inflected forms and lemmas from ``inflected_forms``.
    """
    token_l = unknown.token.lower()
    lemma_l = unknown.lemma.lower()

    resolves_in_lexicon = lemma_l in lexicon_words or token_l in lexicon_words
    in_inflected = token_l in inflected_words or lemma_l in inflected_words
    if resolves_in_lexicon or in_inflected:
        return BUCKET_INFLECTION_MISS

    if unknown.is_propn or unknown.is_capitalized:
        return BUCKET_PROPER_NOUN

    return BUCKET_COMMON_GAP


def rank_unknowns(counter: Counter[str]) -> list[tuple[str, int]]:
    """Return ``(token, frequency)`` pairs sorted by frequency desc, token asc."""
    return sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))


def tier3_frequencies(
    tier3_words: set[str],
    corpus_counts: Counter[str],
) -> list[tuple[str, int]]:
    """Return ``(tier3_word, corpus_frequency)`` sorted by frequency desc.

    ``corpus_counts`` is a frequency map over lowercased corpus token text.
    Tier 3 words absent from the corpus are reported with frequency 0.
    """
    return sorted(
        ((w, corpus_counts.get(w, 0)) for w in tier3_words),
        key=lambda kv: (-kv[1], kv[0]),
    )


# ---------------------------------------------------------------------------
# spaCy passes (integration glue — not unit-tested)
# ---------------------------------------------------------------------------


def _corpus_txt_files(corpus: Path) -> list[Path]:
    """Return ``.txt`` files in *corpus* subdirectories (skip root-level files).

    Mirrors ``batch_coverage_report``'s corpus-walk rule so the triage sees
    exactly the same files the coverage run classified.
    """
    return sorted(p for p in corpus.rglob("*.txt") if p.parent != corpus)


def isolated_lemmas(tokens: list[str], nlp) -> dict[str, str]:
    """Return ``{token: lowercased_lemma}`` by lemmatising each token in isolation.

    Isolated (context-free) lemmatisation deliberately differs from the
    analyzer's in-context lemma: a token that resolves here but was UNKNOWN
    in context is a genuine context-dependent lemmatisation miss.
    """
    result: dict[str, str] = {}
    for token, doc in zip(tokens, nlp.pipe(tokens)):
        lemma = doc[0].lemma_.lower() if len(doc) else token.lower()
        result[token] = lemma
    return result


def corpus_features(
    corpus: Path,
    nlp,
    unknown_set: set[str],
) -> tuple[dict[str, dict[str, int]], Counter[str]]:
    """Single corpus pass gathering case/PROPN features and a token frequency map.

    Returns ``(features, corpus_counts)`` where:
      * ``features[token]`` = ``{"caps": n, "total": n, "propn": n}`` for
        each lowercased token in ``unknown_set``;
      * ``corpus_counts`` counts every lowercased alphabetic token in the
        corpus (used for Tier-3 frequency reporting).
    """
    features: dict[str, dict[str, int]] = {}
    corpus_counts: Counter[str] = Counter()
    texts = [p.read_text(encoding="utf-8") for p in _corpus_txt_files(corpus)]
    for doc in nlp.pipe(texts, disable=["parser", "ner"]):
        for tok in doc:
            if not tok.is_alpha:
                continue
            lower = tok.text.lower()
            corpus_counts[lower] += 1
            if lower not in unknown_set:
                continue
            feat = features.setdefault(lower, {"caps": 0, "total": 0, "propn": 0})
            feat["total"] += 1
            if tok.text[:1].isupper():
                feat["caps"] += 1
            if tok.pos_ == "PROPN":
                feat["propn"] += 1
    return features, corpus_counts


def build_unknown_tokens(
    counter: Counter[str],
    lemmas: dict[str, str],
    features: dict[str, dict[str, int]],
) -> list[UnknownToken]:
    """Combine pooled counts, isolated lemmas, and corpus features.

    A token is ``is_propn`` if it was ever tagged PROPN; ``is_capitalized``
    if the majority of its corpus occurrences were capitalised.
    """
    tokens: list[UnknownToken] = []
    for token, freq in counter.items():
        feat = features.get(token, {"caps": 0, "total": 0, "propn": 0})
        total = feat["total"]
        is_capitalized = total > 0 and feat["caps"] * 2 > total
        tokens.append(
            UnknownToken(
                token=token,
                frequency=freq,
                lemma=lemmas.get(token, token.lower()),
                is_propn=feat["propn"] > 0,
                is_capitalized=is_capitalized,
            )
        )
    return tokens


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def write_tsv(
    ranked: list[tuple[str, int]],
    buckets: dict[str, str],
    path: Path,
    unknown_index: dict[str, UnknownToken] | None = None,
) -> None:
    """Write frequency-ranked triage rows.

    Base columns are ``token``, ``frequency``, ``bucket``. When
    *unknown_index* (``{token: UnknownToken}``) is supplied, three diagnostic
    columns are appended — ``is_propn``, ``caps_majority``, ``lemma`` — so the
    ``proper_noun`` bucket is auditable: a row with ``bucket=proper_noun`` but
    ``is_propn=False`` was bucketed purely on capitalisation and may be a
    common word (an address term like *mommy*, a personified animal like
    *rabbit*) leaking out of the gap queue.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if unknown_index is None:
        lines = ["token\tfrequency\tbucket"]
        lines += [f"{tok}\t{freq}\t{buckets[tok]}" for tok, freq in ranked]
    else:
        lines = ["token\tfrequency\tbucket\tis_propn\tcaps_majority\tlemma"]
        for tok, freq in ranked:
            u = unknown_index.get(tok)
            is_propn = int(bool(u and u.is_propn))
            caps = int(bool(u and u.is_capitalized))
            lemma = u.lemma if u else tok.lower()
            lines.append(
                f"{tok}\t{freq}\t{buckets[tok]}\t{is_propn}\t{caps}\t{lemma}"
            )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Triage pooled UNKNOWN tokens from a TinyStories coverage probe."
    )
    parser.add_argument(
        "--pooled",
        required=True,
        type=Path,
        help="Pooled UNKNOWN-token file (COUNT\\tTOKEN) from RUN A.",
    )
    parser.add_argument(
        "--corpus",
        required=True,
        type=Path,
        help="TinyStories corpus root (walked for .txt in subdirs).",
    )
    parser.add_argument(
        "--lexicon", required=True, type=Path, help="Path to lexicon_v2.db (read-only)."
    )
    parser.add_argument("--lang", default="en", choices=["en", "lt", "eo"])
    parser.add_argument(
        "--output-tsv",
        required=True,
        type=Path,
        help="Destination for the token\\tfrequency\\tbucket TSV.",
    )
    parser.add_argument(
        "--tier3-flag-threshold",
        type=int,
        default=50,
        help="Report Tier-3 words occurring at least this often as misassignment "
        "candidates (default: 50).",
    )
    args = parser.parse_args(argv)

    # Late import so the pure logic stays importable without spaCy installed.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from coverage_report import _load_nlp  # noqa: E402

    counter = parse_pooled_unknowns(args.pooled.expanduser())
    if not counter:
        print("No UNKNOWN tokens found in pooled file.", file=sys.stderr)
        sys.exit(1)

    lexicon_words = load_lexicon_words(args.lexicon, args.lang)
    inflected_words = load_inflected_words(args.lexicon, args.lang)
    tier3_words = load_tier3_words(args.lexicon, args.lang)

    nlp = _load_nlp(args.lang)
    unique_tokens = list(counter)
    lemmas = isolated_lemmas(unique_tokens, nlp)
    features, corpus_counts = corpus_features(
        args.corpus.expanduser(), nlp, set(unique_tokens)
    )

    unknowns = build_unknown_tokens(counter, lemmas, features)
    buckets = {
        u.token: classify_bucket(u, lexicon_words, inflected_words) for u in unknowns
    }

    ranked = rank_unknowns(counter)
    unknown_index = {u.token: u for u in unknowns}
    write_tsv(ranked, buckets, args.output_tsv.expanduser(), unknown_index)

    bucket_counts = Counter(buckets.values())
    total_unknown_occurrences = sum(counter.values())

    print(f"Unique UNKNOWN tokens : {len(counter)}")
    print(f"Total UNKNOWN occurrences: {total_unknown_occurrences}")
    print("Bucket counts (unique tokens):")
    for bucket in (BUCKET_COMMON_GAP, BUCKET_PROPER_NOUN, BUCKET_INFLECTION_MISS):
        print(f"  {bucket:<16}: {bucket_counts.get(bucket, 0)}")

    print("\nTop 50 common_gap tokens (Tier-1/2 gap-fill queue):")
    shown = 0
    for tok, freq in ranked:
        if buckets[tok] != BUCKET_COMMON_GAP:
            continue
        print(f"  {freq:>6}  {tok}")
        shown += 1
        if shown >= 50:
            break

    t3_freqs = tier3_frequencies(tier3_words, corpus_counts)
    flagged = [(w, f) for w, f in t3_freqs if f >= args.tier3_flag_threshold]
    print(
        f"\nTier-3 misassignment flags (freq >= {args.tier3_flag_threshold}) "
        f"[REPORT ONLY — tiers are never changed]:"
    )
    if flagged:
        for w, f in flagged:
            print(f"  {f:>6}  {w}")
    else:
        print("  (none)")

    print(f"\nTSV written: {args.output_tsv.expanduser()}")


if __name__ == "__main__":
    main()
