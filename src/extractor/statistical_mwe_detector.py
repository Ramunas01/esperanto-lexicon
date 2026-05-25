#!/usr/bin/env python3
"""Statistical MWE detection for domain-specific terminology.

Stage 2 of the Tier 4 extraction pipeline: surfaces domain-specific
multi-word expressions by PMI scoring over the full corpus text, filtered
against the common lexicon and already-known domain terms.

Usage:
    python3 src/extractor/statistical_mwe_detector.py \\
        --input  ~/projects/esperanto-lexicon-corpus/tax_law/GPMI-LT.txt \\
        --lang   lt \\
        --lexicon data/lexicon_db/lexicon_v2.db \\
        --domain-db data/domain_db/gpmi_lt_tax.db \\
        --output data/domain_db/gpmi_statistical_candidates.jsonl \\
        --top-n  200
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path


# ---------------------------------------------------------------------------
# Amendment-line skip patterns (shared with extract_definitions.py)
# ---------------------------------------------------------------------------

_SKIP_LINE_RE = re.compile(
    r"^(?:Nr\.|Straipsnio|Papildyta|Ŝanĝoj|Aldonita|TAR pastaba|Noto pri|N-ro)",
    re.IGNORECASE,
)
_SKIP_CONTENT_RE = re.compile(r"publikigita en la TAR", re.IGNORECASE)
_PURE_NUMBER_RE = re.compile(r"^\d+$")


# ---------------------------------------------------------------------------
# Step 1 — line loading
# ---------------------------------------------------------------------------


def _skip_line(line: str) -> bool:
    """True when a line should be excluded from analysis."""
    stripped = line.strip()
    if not stripped:
        return True
    if len(stripped) < 10:
        return True
    if _PURE_NUMBER_RE.match(stripped):
        return True
    if _SKIP_LINE_RE.match(stripped):
        return True
    if _SKIP_CONTENT_RE.search(stripped):
        return True
    return False


def load_lines(path: Path) -> list[str]:
    """Load text file, discarding amendment markers and noise lines."""
    return [raw for raw in path.read_text(encoding="utf-8").splitlines() if not _skip_line(raw)]


# ---------------------------------------------------------------------------
# spaCy loading and tokenisation (isolated so tests can bypass them)
# ---------------------------------------------------------------------------


def _load_nlp(lang: str):
    """Load spaCy model for *lang*. Prints install hint and exits on failure."""
    try:
        import spacy  # noqa: PLC0415
    except ImportError:
        print("spaCy is not installed.  Run: pip install spacy", file=sys.stderr)
        sys.exit(1)

    model = "lt_core_news_sm" if lang == "lt" else "xx_ent_wiki_sm"
    try:
        return spacy.load(model)
    except OSError:
        print(
            f"spaCy model {model!r} not found.  Run:\n"
            f"  python3 -m spacy download {model}",
            file=sys.stderr,
        )
        sys.exit(1)


def tokenise(
    lines: list[str], nlp, lang: str
) -> tuple[list[list[str]], set[str], set[str]]:
    """Tokenise *lines* with spaCy.

    Returns:
        sentences      — sentence-segmented lists of lowercased content tokens
        propn_words    — lowercased words tagged PROPN by spaCy
        cap_words      — lowercased words that appear capitalised mid-sentence
                         (sentence-initial capitals are excluded to avoid false positives)
    """
    text = "\n".join(lines)
    doc = nlp(text)
    sentences: list[list[str]] = []
    propn_words: set[str] = set()
    cap_words: set[str] = set()

    for sent in doc.sents:
        tokens: list[str] = []
        sent_toks = list(sent)
        for i, tok in enumerate(sent_toks):
            if not tok.is_alpha:
                continue
            if tok.is_stop or tok.pos_ in ("PUNCT", "SPACE", "NUM", "SYM"):
                continue
            lower = tok.text.lower()
            tokens.append(lower)
            if tok.pos_ == "PROPN":
                propn_words.add(lower)
            # Mid-sentence capital: skip the very first token of the sentence
            if i > 0 and tok.text[0].isupper():
                cap_words.add(lower)
        if tokens:
            sentences.append(tokens)

    return sentences, propn_words, cap_words


# ---------------------------------------------------------------------------
# Step 2 — ngram counting
# ---------------------------------------------------------------------------


def count_ngrams(
    sentences: list[list[str]],
) -> tuple[Counter[str], Counter[tuple[str, str]], Counter[tuple[str, str, str]]]:
    """Count unigrams, bigrams, and trigrams from sentence-segmented token lists.

    Sliding window never crosses a sentence boundary.
    """
    uni: Counter[str] = Counter()
    bi: Counter[tuple[str, str]] = Counter()
    tri: Counter[tuple[str, str, str]] = Counter()

    for sent in sentences:
        for tok in sent:
            uni[tok] += 1
        n = len(sent)
        for i in range(n - 1):
            bi[(sent[i], sent[i + 1])] += 1
        for i in range(n - 2):
            tri[(sent[i], sent[i + 1], sent[i + 2])] += 1

    return uni, bi, tri


# ---------------------------------------------------------------------------
# Step 3 — PMI and G2 scoring
# ---------------------------------------------------------------------------


def _safe_log2(x: float) -> float:
    return math.log2(x) if x > 0 else 0.0


def _safe_log(x: float) -> float:
    return math.log(x) if x > 0 else 0.0


def _pmi_bigram(
    w1: str, w2: str, uni: Counter[str], bi: Counter[tuple[str, str]], N: int
) -> float:
    """PMI = log2( P(w1,w2) / (P(w1) * P(w2)) ) where P(w) = freq(w)/N."""
    f1, f2, f12 = uni[w1], uni[w2], bi[(w1, w2)]
    if f12 == 0 or f1 == 0 or f2 == 0:
        return -math.inf
    return _safe_log2(f12 * N) - _safe_log2(f1) - _safe_log2(f2)


def _g2_bigram(
    w1: str, w2: str, uni: Counter[str], bi: Counter[tuple[str, str]], N: int
) -> float:
    """Log-likelihood G² for a bigram (Dunning 1993)."""
    f1, f2, f12 = uni[w1], uni[w2], bi[(w1, w2)]
    O11 = f12
    O12 = f1 - f12
    O21 = f2 - f12
    O22 = N - f1 - f2 + f12
    E11 = f1 * f2 / N
    E12 = f1 * (N - f2) / N
    E21 = (N - f1) * f2 / N
    E22 = (N - f1) * (N - f2) / N

    def _cell(o: float, e: float) -> float:
        return o * _safe_log(o / e) if o > 0 and e > 0 else 0.0

    return 2.0 * (_cell(O11, E11) + _cell(O12, E12) + _cell(O21, E21) + _cell(O22, E22))


def _pmi_trigram(
    w1: str,
    w2: str,
    w3: str,
    uni: Counter[str],
    tri: Counter[tuple[str, str, str]],
    N: int,
) -> float:
    """PMI = log2( P(w1,w2,w3) / (P(w1)*P(w2)*P(w3)) )."""
    f1, f2, f3 = uni[w1], uni[w2], uni[w3]
    f123 = tri[(w1, w2, w3)]
    if f123 == 0 or f1 == 0 or f2 == 0 or f3 == 0:
        return -math.inf
    # log2(f123 * N^2 / (f1 * f2 * f3))
    return _safe_log2(f123) + 2 * _safe_log2(N) - _safe_log2(f1) - _safe_log2(f2) - _safe_log2(f3)


def build_scored_candidates(
    uni: Counter[str],
    bi: Counter[tuple[str, str]],
    tri: Counter[tuple[str, str, str]],
    min_freq: int,
    min_pmi: float,
    lang: str,
    source_file: str,
) -> list[dict]:
    """Score all ngrams above the frequency and PMI thresholds.

    Returns a list of candidate dicts (without component annotation fields,
    which are added later by apply_filters).
    """
    N = sum(uni.values())
    if N == 0:
        return []

    candidates: list[dict] = []

    for (w1, w2), freq in bi.items():
        if freq < min_freq:
            continue
        pmi = _pmi_bigram(w1, w2, uni, bi, N)
        if pmi < min_pmi:
            continue
        g2 = _g2_bigram(w1, w2, uni, bi, N)
        phrase = f"{w1} {w2}"
        candidates.append(
            {
                "phrase": phrase,
                "phrase_normalized": phrase,
                "lang": lang,
                "ngram_size": 2,
                "frequency": freq,
                "pmi": round(pmi, 4),
                "g2": round(g2, 4),
                "source_file": source_file,
                "extraction_method": "statistical_pmi",
                "approved": False,
                "tier_suggestion": 4,
                "notes": "",
            }
        )

    for (w1, w2, w3), freq in tri.items():
        if freq < min_freq:
            continue
        pmi = _pmi_trigram(w1, w2, w3, uni, tri, N)
        if pmi < min_pmi:
            continue
        phrase = f"{w1} {w2} {w3}"
        candidates.append(
            {
                "phrase": phrase,
                "phrase_normalized": phrase,
                "lang": lang,
                "ngram_size": 3,
                "frequency": freq,
                "pmi": round(pmi, 4),
                "g2": None,  # G2 defined for bigrams only
                "source_file": source_file,
                "extraction_method": "statistical_pmi",
                "approved": False,
                "tier_suggestion": 4,
                "notes": "",
            }
        )

    return candidates


# ---------------------------------------------------------------------------
# Step 4 — filtering
# ---------------------------------------------------------------------------


def load_common_words(lexicon_db: Path, lang: str) -> set[str]:
    """Load common vocabulary for *lang* from lexicon_v2.db concept_lang table."""
    if not lexicon_db.exists():
        return set()
    conn = sqlite3.connect(lexicon_db)
    rows = conn.execute(
        "SELECT LOWER(word) FROM concept_lang WHERE lang = ?", (lang,)
    ).fetchall()
    conn.close()
    return {r[0] for r in rows}


def load_known_phrases(domain_db: Path | None, lang: str) -> set[str]:
    """Load already-known phrase_normalized values for *lang* from the domain DB."""
    if domain_db is None or not domain_db.exists():
        return set()
    conn = sqlite3.connect(domain_db)
    rows = conn.execute(
        "SELECT phrase_normalized FROM mwe_lang WHERE lang = ?", (lang,)
    ).fetchall()
    conn.close()
    return {r[0] for r in rows}


def apply_filters(
    candidates: list[dict],
    common_words: set[str],
    known_phrases: set[str],
) -> tuple[list[dict], list[dict]]:
    """Apply all filters in two stages and return (after_lexicon, after_domain).

    Filter A — lexicon: discard ngrams where ALL words are in the common lexicon.
    Filter B — domain DB: discard ngrams already recorded as mwe_lang entries.
    Filter C — noise: discard ngrams with single-char or pure-number components.

    Component annotation fields (all_components_common, novel_components,
    common_components) are added to surviving candidates.
    """
    after_lexicon: list[dict] = []
    for cand in candidates:
        words = cand["phrase"].split()

        # Filter C — noise
        if any(len(w) <= 1 or _PURE_NUMBER_RE.match(w) for w in words):
            continue

        novel = [w for w in words if w not in common_words]
        common = [w for w in words if w in common_words]

        # Filter A — all components are common words → discard
        if not novel:
            continue

        after_lexicon.append(
            {
                **cand,
                "all_components_common": False,
                "novel_components": novel,
                "common_components": common,
            }
        )

    # Filter B — phrase already in domain DB
    after_domain = [c for c in after_lexicon if c["phrase_normalized"] not in known_phrases]

    return after_lexicon, after_domain


# ---------------------------------------------------------------------------
# Step 4b — Named-entity candidate classification
# ---------------------------------------------------------------------------

# Lithuanian genitive endings typical of country/place-name adjectives
_NE_GEO_RE = re.compile(r"\b\w+(?:ijos|ietišk)\b", re.IGNORECASE)

# Organisation-type words (stem-based to cover inflected forms)
_NE_ORG_RE = re.compile(r"\b(?:organizacij|asociacij|grupė|fondas)\b", re.IGNORECASE)

# Person-indicator words
_NE_PERSON_RE = re.compile(r"\b(?:vardas|pavardė|asmens)\b", re.IGNORECASE)


def ne_type(
    phrase: str,
    words: list[str],
    propn_words: set[str],
    cap_words: set[str],
) -> str | None:
    """Return NE type suggestion if the candidate looks like a named entity, else None.

    Detection fires on any of:
      1. spaCy tagged a component word as PROPN
      2. A component word appears capitalised mid-sentence in the corpus
      3. The phrase matches a known NE pattern (geographical, organisation, person)
    """
    has_propn = any(w in propn_words for w in words)
    has_cap = any(w in cap_words for w in words)
    has_geo = bool(_NE_GEO_RE.search(phrase))
    has_org = bool(_NE_ORG_RE.search(phrase))
    has_person = bool(_NE_PERSON_RE.search(phrase))

    if not (has_propn or has_cap or has_geo or has_org or has_person):
        return None

    if has_geo:
        return "geographical"
    if has_org:
        return "organisation"
    if has_person:
        return "person"
    return "unknown"


# ---------------------------------------------------------------------------
# Step 5 — main pipeline and CLI
# ---------------------------------------------------------------------------


def run(
    input_path: Path,
    lang: str,
    lexicon_db: Path,
    domain_db: Path | None,
    output_path: Path,
    output_ne_path: Path | None,
    top_n: int,
    min_freq: int,
    min_pmi: float,
) -> None:
    """Full MWE detection pipeline."""
    # Step 1 — load and tokenise
    lines = load_lines(input_path)
    nlp = _load_nlp(lang)
    print(f"Tokenising {input_path.name} ({lang}) …")
    sentences, propn_words, cap_words = tokenise(lines, nlp, lang)

    # Step 2 — count
    uni, bi, tri = count_ngrams(sentences)
    N = sum(uni.values())

    # Step 3 — score (applies min_freq + min_pmi thresholds)
    candidates = build_scored_candidates(uni, bi, tri, min_freq, min_pmi, lang, input_path.name)
    bigram_before = sum(1 for c in candidates if c["ngram_size"] == 2)
    trigram_before = sum(1 for c in candidates if c["ngram_size"] == 3)

    # Step 4 — filter
    common_words = load_common_words(lexicon_db, lang)
    known_phrases = load_known_phrases(domain_db, lang)
    after_lexicon, after_domain = apply_filters(candidates, common_words, known_phrases)

    # Rank: PMI descending, then frequency descending
    after_domain.sort(key=lambda c: (-c["pmi"], -c["frequency"]))
    top_candidates = after_domain[:top_n]

    # Step 4b — split into MWE and NE candidates
    mwe_candidates: list[dict] = []
    ne_candidates: list[dict] = []
    for cand in top_candidates:
        words = cand["phrase"].split()
        ne_t = ne_type(cand["phrase"], words, propn_words, cap_words)
        if ne_t is not None:
            ne_candidates.append({**cand, "ne_type_suggestion": ne_t})
        else:
            mwe_candidates.append(cand)

    # Step 5 — write
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as fh:
        for rec in mwe_candidates:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    if output_ne_path is not None:
        output_ne_path.parent.mkdir(parents=True, exist_ok=True)
        with output_ne_path.open("w", encoding="utf-8") as fh:
            for rec in ne_candidates:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print(f"\nTokens analysed    : {N}")
    print(f"Unique unigrams    : {len(uni)}")
    print(f"Bigram candidates  : {bigram_before}  (before filter)")
    print(f"Trigram candidates : {trigram_before}  (before filter)")
    print(f"After lexicon filter   : {len(after_lexicon)} remaining")
    print(f"After domain filter    : {len(after_domain)} remaining")
    print(f"MWE candidates written : {len(mwe_candidates)}")
    print(f"NE candidates written  : {len(ne_candidates)}")
    if output_ne_path is not None:
        print(f"  (ne output: {output_ne_path})")


def main(argv: list[str] | None = None) -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Statistical MWE detection for domain-specific terminology."
    )
    parser.add_argument("--input", required=True, type=Path, help="Input plain-text corpus file")
    parser.add_argument("--lang", required=True, choices=["lt", "en", "eo"], help="Language code")
    parser.add_argument("--lexicon", required=True, type=Path, help="Path to lexicon_v2.db")
    parser.add_argument(
        "--domain-db", dest="domain_db", type=Path, default=None,
        help="Path to domain .db (optional; skips domain filter if absent)",
    )
    parser.add_argument("--output", required=True, type=Path, help="Output .jsonl path for MWE candidates")
    parser.add_argument(
        "--output-ne", dest="output_ne", type=Path, default=None,
        help="Output .jsonl path for named-entity candidates (optional)",
    )
    parser.add_argument("--top-n", dest="top_n", type=int, default=200,
                        help="Number of top candidates to write (default 200)")
    parser.add_argument("--min-freq", dest="min_freq", type=int, default=3,
                        help="Minimum ngram frequency (default 3)")
    parser.add_argument("--min-pmi", dest="min_pmi", type=float, default=2.0,
                        help="Minimum PMI score (default 2.0)")
    args = parser.parse_args(argv)

    run(
        input_path=args.input,
        lang=args.lang,
        lexicon_db=args.lexicon,
        domain_db=args.domain_db,
        output_path=args.output,
        output_ne_path=args.output_ne,
        top_n=args.top_n,
        min_freq=args.min_freq,
        min_pmi=args.min_pmi,
    )


if __name__ == "__main__":
    main()
