#!/usr/bin/env python3
"""Statistical MWE detection for domain-specific terminology.

Stage 2 of the Tier 4 extraction pipeline: surfaces domain-specific
multi-word expressions ranked for human review, using:
  * POS-shape filtering (keeps noun-phrase patterns only)
  * Lemma-based lexicon filtering (removes common-word bigrams correctly)
  * Document-boundary-aware counting (DOC_DELIMITER-separated article segments)
  * Log-likelihood / PMI association scoring

Candidates are ranked by (doc_count DESC, association_score DESC, frequency DESC)
and emitted as JSONL for human review via review_cli.py.

Usage:
    python3 src/extractor/statistical_mwe_detector.py \\
        --input ~/projects/esperanto-lexicon-corpus/mining/customs_expert/mine_00.txt \\
        --lang en \\
        --lexicon data/lexicon_db/lexicon_v2.db \\
        --domain-db data/domain_db/ucc_customs.db \\
        --output data/domain_db/expert_corpus_candidates.jsonl \\
        --min-doc-count 3 \\
        --top-n 500
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
from typing import NamedTuple


# ---------------------------------------------------------------------------
# Module constants
# ---------------------------------------------------------------------------

# Separator between articles in concatenated expert-corpus files.
# Written by the corpus preparation step; one ♥ between consecutive articles.
DOC_DELIMITER = "♥"


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
# Token type — used for POS-aware tokenisation
# ---------------------------------------------------------------------------


class Token(NamedTuple):
    text: str   # lowercased surface form (display / n-gram key)
    lemma: str  # lowercased lemma (for lexicon comparison)
    pos: str    # spaCy universal POS tag


# ---------------------------------------------------------------------------
# POS filter patterns
# ---------------------------------------------------------------------------

# PROPN is treated as equivalent to NOUN for shape matching (covers "hs code", "cn heading").
_NOUN_LIKE = frozenset({"NOUN", "PROPN"})

# Any n-gram containing one of these POS tags is rejected.
_REJECT_ANY = frozenset({"VERB", "AUX", "PRON", "DET", "ADV", "CCONJ", "SCONJ", "PART"})

# An n-gram starting or ending with one of these is rejected.
_REJECT_BOUNDARY = frozenset({"ADP", "DET"})


def _pos_shape_ok(pos_pattern: str) -> bool:
    """Return True if *pos_pattern* is a valid noun-phrase shape.

    Accepted shapes:
      bigram:  ADJ NOUN  |  NOUN NOUN  (NOUN includes PROPN)
      trigram: ADJ ADJ NOUN | ADJ NOUN NOUN | NOUN NOUN NOUN | NOUN ADP NOUN
      4-gram:  any combination of the above; at most one internal ADP allowed
    Rejection rules (applied to any size):
      - contains VERB, AUX, PRON, DET, ADV, CCONJ, SCONJ, or PART
      - starts or ends with ADP or DET
      - more than one ADP token (prevents "change of tariff of" shapes)
      - any position outside {NOUN, PROPN, ADJ, ADP}
    """
    parts = pos_pattern.split()
    if len(parts) < 2:
        return False

    if any(p in _REJECT_ANY for p in parts):
        return False

    if parts[0] in _REJECT_BOUNDARY or parts[-1] in _REJECT_BOUNDARY:
        return False

    if sum(1 for p in parts if p == "ADP") > 1:
        return False

    allowed = _NOUN_LIKE | {"ADJ", "ADP"}
    if not all(p in allowed for p in parts):
        return False

    return True


# ---------------------------------------------------------------------------
# Step 1 — document and line loading
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


def load_documents(path: Path) -> list[str]:
    """Split *path* on DOC_DELIMITER (♥) into document segments.

    The first segment is typically a header comment; empty segments are dropped.
    Returns at least one segment even if no delimiter is found.
    """
    text = path.read_text(encoding="utf-8")
    return [seg for seg in text.split(DOC_DELIMITER) if seg.strip()]


def load_lines(path: Path) -> list[str]:
    """Load text file, discarding amendment markers and noise lines."""
    return [raw for raw in path.read_text(encoding="utf-8").splitlines() if not _skip_line(raw)]


# ---------------------------------------------------------------------------
# spaCy loading and tokenisation (isolated so tests can bypass them)
# ---------------------------------------------------------------------------

_MODEL_MAP = {
    "lt": "lt_core_news_sm",
    "en": "en_core_web_sm",
    "fr": "fr_core_news_sm",
}


def _load_nlp(lang: str):
    """Load spaCy model for *lang*. Prints install hint and exits on failure."""
    try:
        import spacy  # noqa: PLC0415
    except ImportError:
        print("spaCy is not installed.  Run: pip install spacy", file=sys.stderr)
        sys.exit(1)

    model = _MODEL_MAP.get(lang, "xx_ent_wiki_sm")
    try:
        nlp = spacy.load(model)
        if not nlp.has_pipe("sentencizer") and not nlp.has_pipe("parser"):
            nlp.add_pipe("sentencizer")
        return nlp
    except OSError:
        print(
            f"spaCy model {model!r} not found.  Run:\n"
            f"  python3 -m spacy download {model}",
            file=sys.stderr,
        )
        sys.exit(1)


def tokenise(lines: list[str], nlp, lang: str) -> list[list[Token]]:
    """Tokenise *lines* with spaCy, returning sentence-segmented Token lists.

    Filters punctuation, spaces, numbers, symbols, and stop words.
    Each Token carries text (surface, lowercased), lemma (lowercased), and POS.
    """
    text = "\n".join(lines)
    doc = nlp(text)
    sentences: list[list[Token]] = []

    for sent in doc.sents:
        tokens: list[Token] = []
        for tok in sent:
            if not tok.is_alpha:
                continue
            if tok.is_stop or tok.pos_ in ("PUNCT", "SPACE", "NUM", "SYM"):
                continue
            tokens.append(Token(
                text=tok.text.lower(),
                lemma=tok.lemma_.lower(),
                pos=tok.pos_,
            ))
        if tokens:
            sentences.append(tokens)

    return sentences


def tokenise_document(doc_text: str, nlp, lang: str) -> list[list[Token]]:
    """Tokenise one DOC_DELIMITER-separated segment after noise-line filtering."""
    lines = [ln for ln in doc_text.splitlines() if not _skip_line(ln)]
    return tokenise(lines, nlp, lang)


# ---------------------------------------------------------------------------
# Step 2 — n-gram counting
# ---------------------------------------------------------------------------


def count_ngrams(
    sentences: list[list[str]],
    max_ngram: int = 4,
) -> tuple[Counter, ...]:
    """Count unigrams and n-grams from sentence-segmented token lists.

    Accepts plain string token lists (backward-compatible entry point used by
    tests and the LT pipeline).  Sliding window never crosses sentence boundaries.
    Returns a tuple of *max_ngram* Counters: (uni, bi, tri, quad, …).
    """
    counters: list[Counter] = [Counter() for _ in range(max_ngram)]

    for sent in sentences:
        for tok in sent:
            counters[0][tok] += 1
        n = len(sent)
        for size in range(2, max_ngram + 1):
            for i in range(n - size + 1):
                counters[size - 1][tuple(sent[i : i + size])] += 1

    return tuple(counters)


def count_with_metadata(
    docs_tokens: list[list[list[Token]]],
    max_ngram: int = 4,
) -> tuple[tuple[Counter, ...], dict[tuple, int], dict[tuple, str], dict[str, str]]:
    """Count n-grams across documents with POS, doc-count, and lemma metadata.

    Args:
        docs_tokens: outer = documents; middle = sentences; inner = Tokens.
        max_ngram:   maximum n-gram size to count.

    Returns:
        ngram_counters: (uni, bi, tri, …) — same format as count_ngrams().
                        Unigram counter uses str keys; n-gram counters use tuple keys.
        doc_counts:     n-gram tuple → number of distinct documents containing it.
        ngram_to_pos:   n-gram tuple → POS pattern string (first occurrence).
        word_to_lemma:  surface text → lemma (for lexicon comparison).
    """
    uni: Counter[str] = Counter()
    ngram_counters: list[Counter] = [Counter() for _ in range(max_ngram - 1)]
    doc_presence: dict[tuple, set[int]] = {}
    ngram_to_pos: dict[tuple, str] = {}
    word_to_lemma: dict[str, str] = {}

    for doc_idx, doc_sentences in enumerate(docs_tokens):
        doc_ngrams_seen: set[tuple] = set()

        for sent in doc_sentences:
            for tok in sent:
                uni[tok.text] += 1
                if tok.text not in word_to_lemma:
                    word_to_lemma[tok.text] = tok.lemma

            n = len(sent)
            for size in range(2, max_ngram + 1):
                for i in range(n - size + 1):
                    window = sent[i : i + size]
                    text_key = tuple(t.text for t in window)
                    ngram_counters[size - 2][text_key] += 1
                    doc_ngrams_seen.add(text_key)
                    if text_key not in ngram_to_pos:
                        ngram_to_pos[text_key] = " ".join(t.pos for t in window)

        for key in doc_ngrams_seen:
            doc_presence.setdefault(key, set()).add(doc_idx)

    doc_counts = {key: len(s) for key, s in doc_presence.items()}
    all_counters = (uni,) + tuple(ngram_counters)
    return tuple(all_counters), doc_counts, ngram_to_pos, word_to_lemma


# ---------------------------------------------------------------------------
# Step 3 — PMI and G2 scoring
# ---------------------------------------------------------------------------


def _safe_log2(x: float) -> float:
    return math.log2(x) if x > 0 else 0.0


def _safe_log(x: float) -> float:
    return math.log(x) if x > 0 else 0.0


def _g2_bigram(
    w1: str, w2: str, uni: Counter, bi: Counter, N: int
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


def _pmi_ngram(words: tuple, uni: Counter, ngram_counter: Counter, N: int) -> float:
    """PMI = log2( P(w1..wn) / prod P(wi) ) for any n-gram size."""
    f_ngram = ngram_counter[words]
    if f_ngram == 0:
        return -math.inf
    for w in words:
        if uni[w] == 0:
            return -math.inf
    n = len(words)
    return (
        _safe_log2(f_ngram)
        + (n - 1) * _safe_log2(N)
        - sum(_safe_log2(uni[w]) for w in words)
    )


def build_scored_candidates(
    uni: Counter,
    bi: Counter,
    tri: Counter,
    min_freq: int,
    min_pmi: float,
    lang: str,
    source_file: str,
    *extra_ngrams: Counter,
    ngram_to_pos: dict[tuple, str] | None = None,
    doc_counts: dict[tuple, int] | None = None,
) -> list[dict]:
    """Score all n-grams above the frequency and PMI thresholds.

    *extra_ngrams* are additional counters for sizes 4, 5, … (each positional arg
    corresponds to ngram_size = 4, 5, …).

    Keyword-only args (optional — backward-compatible with tests that omit them):
        ngram_to_pos:  n-gram tuple → POS pattern string; populates pos_pattern field.
        doc_counts:    n-gram tuple → distinct-document count; populates doc_count field.

    Returns a list of candidate dicts (novel/common component fields are added later
    by apply_filters; overlaps_known_term and sample_context by the run() enrichment step).
    """
    N = sum(uni.values())
    if N == 0:
        return []

    candidates: list[dict] = []
    all_ngram_counters = [(2, bi), (3, tri)] + [
        (4 + i, ctr) for i, ctr in enumerate(extra_ngrams)
    ]

    for size, counter in all_ngram_counters:
        for words, freq in counter.items():
            if freq < min_freq:
                continue
            pmi = _pmi_ngram(words, uni, counter, N)
            if pmi < min_pmi:
                continue
            phrase = " ".join(words)
            g2 = _g2_bigram(*words, uni, counter, N) if size == 2 else None
            pos_pattern = (ngram_to_pos or {}).get(words)
            doc_count = (doc_counts or {}).get(words, 0)
            # association_score: prefer G2 (log-likelihood) for bigrams; PMI otherwise
            if g2 is not None:
                assoc_score = round(g2, 4)
                assoc_metric = "log_likelihood"
            else:
                assoc_score = round(pmi, 4)
                assoc_metric = "pmi"
            candidates.append(
                {
                    "phrase": phrase,
                    "phrase_normalized": phrase,
                    "phrase_inflected": None,
                    "lang": lang,
                    "ngram_size": size,
                    "pos_pattern": pos_pattern,
                    "frequency": freq,
                    "doc_count": doc_count,
                    "association_score": assoc_score,
                    "assoc_metric": assoc_metric,
                    "pmi": round(pmi, 4),
                    "g2": round(g2, 4) if g2 is not None else None,
                    "source_file": source_file,
                    "extraction_method": "statistical_pmi",
                    "approved": False,
                    "tier_suggestion": 4,
                    "subsumed_by": None,
                    "notes": "",
                    "overlaps_known_term": None,
                    "sample_context": None,
                }
            )

    return candidates


# ---------------------------------------------------------------------------
# Step 3b — Lithuanian nominative normalisation
# ---------------------------------------------------------------------------

_LT_ENDING_MAP: list[tuple[str, str]] = [
    ("ių", "ys"),
    ("ės", "ė"),
    ("io", "is"),
    ("ui", "us"),
    ("os", "a"),
    ("ą", "as"),
    ("ę", "ė"),
    ("į", "is"),
]


def normalize_lt_phrase(phrase: str) -> str:
    """Apply heuristic nominative normalisation to the last word of a Lithuanian phrase."""
    words = phrase.split()
    if not words:
        return phrase
    last = words[-1]
    for ending, replacement in _LT_ENDING_MAP:
        if last.endswith(ending) and len(last) > len(ending):
            new_last = last[: -len(ending)] + replacement
            return " ".join(words[:-1] + [new_last])
    return phrase


def apply_lt_normalisation(candidates: list[dict]) -> list[dict]:
    """Normalise LT phrase endings in-place; set phrase_inflected when changed."""
    result = []
    for cand in candidates:
        if cand.get("lang") != "lt":
            result.append(cand)
            continue
        original = cand["phrase"]
        normalised = normalize_lt_phrase(original)
        if normalised != original:
            print(f"  NORMALISED: {original!r} → {normalised!r}")
            cand = {**cand, "phrase": normalised, "phrase_normalized": normalised, "phrase_inflected": original}
        result.append(cand)
    return result


# ---------------------------------------------------------------------------
# Step 3c — Subsumption filter
# ---------------------------------------------------------------------------


def apply_subsumption_filter(candidates: list[dict]) -> tuple[list[dict], int]:
    """Remove shorter candidates subsumed by longer ones.

    Candidate X is subsumed by Y when:
      - X.phrase is a contiguous substring of Y.phrase
      - Y.frequency >= X.frequency * 0.5
      - Y.pmi >= X.pmi - 2.0
    """
    subsumed: set[str] = set()

    for cand in candidates:
        phrase_x = cand["phrase"]
        freq_x = cand["frequency"]
        pmi_x = cand["pmi"]
        for other in candidates:
            phrase_y = other["phrase"]
            if phrase_y == phrase_x:
                continue
            if phrase_x not in phrase_y:
                continue
            if other["frequency"] < freq_x * 0.5:
                continue
            if other["pmi"] < pmi_x - 2.0:
                continue
            subsumed.add(phrase_x)
            break

    surviving = [c for c in candidates if c["phrase"] not in subsumed]
    return surviving, len(subsumed)


# ---------------------------------------------------------------------------
# Step 4 — filtering
# ---------------------------------------------------------------------------


def load_common_words(lexicon_db: Path, lang: str) -> set[str]:
    """Load common vocabulary lemmas for *lang* from lexicon_v2.db concept_lang table."""
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


def load_known_terms_all(domain_dbs: list[Path], lang: str) -> list[tuple[str, str]]:
    """Load all known phrases with their domain name for overlap detection."""
    result: list[tuple[str, str]] = []
    for db in domain_dbs:
        if not db.exists():
            continue
        conn = sqlite3.connect(db)
        for row in conn.execute(
            "SELECT phrase_normalized FROM mwe_lang WHERE lang = ?", (lang,)
        ):
            result.append((row[0], db.stem))
        conn.close()
    return result


def apply_pos_filter(candidates: list[dict]) -> tuple[list[dict], int]:
    """Remove candidates whose POS pattern is not a noun-phrase shape.

    Candidates with no pos_pattern (e.g. from legacy callers) pass through unchanged.
    """
    surviving: list[dict] = []
    n_removed = 0
    for cand in candidates:
        pos_pat = cand.get("pos_pattern")
        if pos_pat is None or _pos_shape_ok(pos_pat):
            surviving.append(cand)
        else:
            n_removed += 1
    return surviving, n_removed


def apply_filters(
    candidates: list[dict],
    common_words: set[str],
    known_phrases: set[str],
    lemma_map: dict[str, str] | None = None,
) -> tuple[list[dict], list[dict]]:
    """Apply all filters and return (after_lexicon, after_domain).

    Filter A — lexicon: discard n-grams where ALL component lemmas are common words.
               When *lemma_map* is provided, each surface-form word is mapped to its
               lemma before the common-word membership test.  Without it, surface forms
               are compared directly (backward-compatible behaviour).
    Filter B — domain DB: discard n-grams already recorded as mwe_lang entries.
    Filter C — noise: discard n-grams with single-char or pure-number components.

    Component annotation fields (novel_components, common_components,
    all_components_common) are added to surviving candidates.
    """
    after_lexicon: list[dict] = []
    for cand in candidates:
        words = cand["phrase"].split()

        # Filter C — noise
        if any(len(w) <= 1 or _PURE_NUMBER_RE.match(w) for w in words):
            continue

        # Resolve each surface word to its lemma for lexicon comparison
        resolved = [lemma_map.get(w, w) if lemma_map else w for w in words]

        novel = [w for w, r in zip(words, resolved) if r not in common_words]
        common = [w for w, r in zip(words, resolved) if r in common_words]

        # Filter A — all components resolve to common words
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
# Step 4b — context and overlap enrichment
# ---------------------------------------------------------------------------


def _find_sample_context(phrase: str, source_text: str, max_len: int = 200) -> str | None:
    """Return one sentence from *source_text* containing *phrase* (case-insensitive)."""
    phrase_lower = phrase.lower()
    for sent in re.split(r"(?<=[.!?])\s+", source_text):
        if phrase_lower in sent.lower():
            s = sent.strip()
            if len(s) > max_len:
                idx = s.lower().find(phrase_lower)
                start = max(0, idx - 60)
                end = min(len(s), idx + len(phrase) + 60)
                prefix = "…" if start > 0 else ""
                suffix = "…" if end < len(s) else ""
                s = prefix + s[start:end] + suffix
            return s
    return None


def _check_overlap(phrase: str, known_terms: list[tuple[str, str]]) -> str | None:
    """Return 'term (domain)' if phrase overlaps an existing term by substring, else None."""
    p = phrase.lower()
    for term, domain in known_terms:
        t = term.lower()
        if p in t or t in p:
            return f"{term} ({domain})"
    return None


# ---------------------------------------------------------------------------
# Step 5 — main pipeline and CLI
# ---------------------------------------------------------------------------


def run(
    input_path: Path,
    lang: str,
    lexicon_db: Path,
    domain_db: Path | None,
    output_path: Path,
    top_n: int,
    min_freq: int,
    min_pmi: float,
    max_ngram: int = 4,
    min_doc_count: int = 3,
    extra_domain_dbs: list[Path] | None = None,
) -> None:
    """Full MWE detection pipeline."""
    # Step 1 — load documents, tokenise each separately
    raw_docs = load_documents(input_path)
    nlp = _load_nlp(lang)
    print(f"Tokenising {input_path.name} ({lang}) …")
    docs_tokens: list[list[list[Token]]] = [
        tokenise_document(doc, nlp, lang) for doc in raw_docs
    ]
    n_docs = len(docs_tokens)

    # Step 2 — count n-grams with doc-boundary-aware metadata
    ngram_counters, doc_counts, ngram_to_pos, word_to_lemma = count_with_metadata(
        docs_tokens, max_ngram
    )
    uni = ngram_counters[0]
    bi = ngram_counters[1] if len(ngram_counters) > 1 else Counter()
    tri = ngram_counters[2] if len(ngram_counters) > 2 else Counter()
    extra = tuple(ngram_counters[3:])
    N = sum(uni.values())

    # Step 3 — score (applies min_freq + min_pmi thresholds)
    candidates = build_scored_candidates(
        uni, bi, tri, min_freq, min_pmi, lang, input_path.name, *extra,
        ngram_to_pos=ngram_to_pos,
        doc_counts=doc_counts,
    )
    n_raw = len(candidates)

    # Step 3b — LT nominative normalisation
    if lang == "lt":
        candidates = apply_lt_normalisation(candidates)

    # Step 3c — subsumption filter
    candidates, n_subsumed = apply_subsumption_filter(candidates)

    # Step 4a — POS shape filter
    candidates, n_pos_removed = apply_pos_filter(candidates)
    n_after_pos = len(candidates)

    # Step 4b — lexicon filter (lemma-based) + domain filter
    common_words = load_common_words(lexicon_db, lang)
    known_phrases = load_known_phrases(domain_db, lang)
    after_lexicon, after_domain = apply_filters(
        candidates, common_words, known_phrases, lemma_map=word_to_lemma
    )
    n_after_lexicon = len(after_lexicon)
    n_after_domain = len(after_domain)

    # Step 4c — min_doc_count threshold
    after_doc_count = [c for c in after_domain if c.get("doc_count", 0) >= min_doc_count]
    n_after_doc_count = len(after_doc_count)

    # Step 5 — rank: doc_count DESC, association_score DESC, frequency DESC
    after_doc_count.sort(
        key=lambda c: (-c.get("doc_count", 0), -c["association_score"], -c["frequency"])
    )
    top_candidates = after_doc_count[:top_n]

    # Step 6 — enrich with sample context and overlap detection
    source_text = input_path.read_text(encoding="utf-8")
    all_domain_dbs = ([domain_db] if domain_db else []) + (extra_domain_dbs or [])
    known_terms = load_known_terms_all([d for d in all_domain_dbs if d], lang)

    for cand in top_candidates:
        cand["overlaps_known_term"] = _check_overlap(cand["phrase"], known_terms)
        cand["sample_context"] = _find_sample_context(cand["phrase"], source_text)

    # Step 7 — write
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as fh:
        for rec in top_candidates:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print(f"\nDocuments (♥-split)  : {n_docs}")
    print(f"Tokens analysed      : {N}")
    print(f"N-gram candidates    : {n_raw}  (before filters)")
    print(f"After POS filter     : {n_after_pos}")
    print(f"After lexicon filter : {n_after_lexicon}")
    print(f"After domain filter  : {n_after_domain}")
    print(f"After doc_count >={min_doc_count:<2}  : {n_after_doc_count}")
    print(f"Candidates written   : {len(top_candidates)}  (ranked, top-{top_n} applied)")
    print(f"Output               : {output_path}")


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
    parser.add_argument("--top-n", dest="top_n", type=int, default=500,
                        help="Number of top candidates to write (default 500)")
    parser.add_argument("--min-freq", dest="min_freq", type=int, default=3,
                        help="Minimum n-gram frequency (default 3)")
    parser.add_argument("--min-pmi", dest="min_pmi", type=float, default=2.0,
                        help="Minimum PMI score (default 2.0)")
    parser.add_argument("--max-ngram", dest="max_ngram", type=int, default=4,
                        choices=range(2, 6), metavar="N",
                        help="Maximum n-gram size to generate (2-5, default 4)")
    parser.add_argument("--min-doc-count", dest="min_doc_count", type=int, default=3,
                        help="Minimum number of documents a candidate must appear in (default 3)")
    args = parser.parse_args(argv)

    run(
        input_path=args.input,
        lang=args.lang,
        lexicon_db=args.lexicon,
        domain_db=args.domain_db,
        output_path=args.output,
        top_n=args.top_n,
        min_freq=args.min_freq,
        min_pmi=args.min_pmi,
        max_ngram=args.max_ngram,
        min_doc_count=args.min_doc_count,
    )


if __name__ == "__main__":
    main()
