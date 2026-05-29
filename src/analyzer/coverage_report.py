#!/usr/bin/env python3
"""Coverage report: classify each token of an input text against the lexicon.

This is the first test of the core hypothesis: the ratio of domain-specific (Tier 4)
vocabulary to common vocabulary is a proxy for the author's expertise level.

Usage:
    python3 src/analyzer/coverage_report.py \\
        --input "Gyventojas gauna pajamas natūra." \\
        --lang lt \\
        --lexicon data/lexicon_db/lexicon_v2.db \\
        --domain-db data/domain_db/gpmi_lt_tax.db \\
        --output-format text
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path


# ---------------------------------------------------------------------------
# Token representation (spaCy-free; used directly in tests)
# ---------------------------------------------------------------------------


@dataclass
class SimpleToken:
    """Minimal token representation compatible with both spaCy and test mocks."""

    text: str
    lemma: str
    is_skip: bool  # True for punct, space, number, stop word


@dataclass
class TokenResult:
    """Classification result for one display unit (may span multiple source tokens)."""

    text: str               # display text; multi-word for TIER4 greedy matches
    lemma: str              # base form (empty for multi-word TIER4)
    category: str           # TIER1 | TIER2 | TIER4 | UNKNOWN | SKIP
    n_tokens: int = 1       # source tokens consumed
    via_fallback: bool = False  # True when matched via fallback_lang, not primary lang
    synonym_of: str | None = None  # canonical synonym phrase, if any
    matched_phrase: str | None = None  # phrase_normalized key that produced a TIER4 hit


# ---------------------------------------------------------------------------
# Lexicon loading
# ---------------------------------------------------------------------------


def load_tier_words(lexicon_db: Path, lang: str) -> tuple[set[str], set[str]]:
    """Return (tier1_words, tier2_words) — lowercased from concept_lang.

    Only tiers 1 and 2 are loaded. Tier 3 and above are intentionally
    excluded so they can be classified separately by classify_tokens.
    """
    if not lexicon_db.exists():
        return set(), set()
    conn = sqlite3.connect(lexicon_db)
    tier1: set[str] = set()
    tier2: set[str] = set()
    for word, tier in conn.execute(
        "SELECT LOWER(word), tier FROM concept_lang WHERE lang = ? AND tier IN (1, 2)",
        (lang,)
    ):
        (tier1 if tier == 1 else tier2).add(word)
    conn.close()
    return tier1, tier2


def load_tier3_words(lexicon_db: Path, lang: str) -> set[str]:
    """Return lowercased Tier 3 words from concept_lang for *lang*."""
    if not lexicon_db.exists():
        return set()
    conn = sqlite3.connect(lexicon_db)
    words = {
        row[0]
        for row in conn.execute(
            "SELECT LOWER(word) FROM concept_lang WHERE lang = ? AND tier = 3", (lang,)
        )
    }
    conn.close()
    return words


def load_mwe_phrases(domain_db: Path | None, lang: str) -> set[str]:
    """Return lowercased phrase_normalized values from mwe_lang for *lang*."""
    if domain_db is None or not domain_db.exists():
        return set()
    conn = sqlite3.connect(domain_db)
    phrases = {
        row[0]
        for row in conn.execute(
            "SELECT phrase_normalized FROM mwe_lang WHERE lang = ?", (lang,)
        )
    }
    conn.close()
    return phrases


def load_inflected_forms(lexicon_db: Path, lang: str) -> dict[str, str]:
    """Return {inflected_word → lemma} for non-self-referential entries in *lang*.

    When multiple rows exist for the same inflected_word (e.g. 'is → be' and
    'is → is'), only the row where inflected_word != lemma is loaded (the
    meaningful mapping).  Self-referential rows (inflected_word == lemma) are
    skipped entirely — they add nothing beyond what concept_lang already covers.
    """
    if not lexicon_db.exists():
        return {}
    conn = sqlite3.connect(lexicon_db)
    result: dict[str, str] = {}
    for inflected, lemma in conn.execute(
        "SELECT LOWER(inflected_word), LOWER(lemma) FROM inflected_forms"
        " WHERE lang = ? AND LOWER(inflected_word) != LOWER(lemma)",
        (lang,),
    ):
        result[inflected] = lemma
    conn.close()
    return result


def load_synonym_map(domain_db: Path | None, lang: str) -> dict[str, str]:
    """Return {phrase_normalized → canonical_synonym_phrase} for TIER4 synonym notation.

    When a matched phrase has a synonym link, the other phrase is shown in the report
    as: 'matched_phrase  TIER4  (≡ canonical_synonym)'.
    """
    if domain_db is None or not domain_db.exists():
        return {}
    conn = sqlite3.connect(domain_db)
    # Synonym conflict: mwe_id_b phrase is matched → show mwe_id_a phrase as canonical
    rows = conn.execute(
        """
        SELECT lb.phrase_normalized, la.phrase
        FROM mwe_conflict c
        JOIN mwe_lang la ON la.mwe_id = c.mwe_id_a AND la.lang = ?
        JOIN mwe_lang lb ON lb.mwe_id = c.mwe_id_b AND lb.lang = ?
        WHERE c.conflict_type = 'synonym'
        """,
        (lang, lang),
    ).fetchall()
    conn.close()
    return {row[0]: row[1] for row in rows}


# ---------------------------------------------------------------------------
# Core classification (pure — no spaCy dependency)
# ---------------------------------------------------------------------------

# KNOWN LIMITATION: lt_core_news_sm lemmatisation quality
# The Lithuanian spaCy model mislemmatises some adjective inflections
# (e.g. "individualia" → "individualias" instead of "individuali").
# This means inflected MWE tokens may not match stored base forms via
# the exact-lemma path.
#
# Workaround: Phase 2 prefix matching (below) catches cases where the
# inflected text form starts with the stored base form (e.g.
# "individualia".startswith("individuali") → True), and the remaining
# words match exactly. This covers the most common Lithuanian adjective
# inflection patterns.
#
# Proper fix: integrate Stanza lt model for better lemmatisation.
# See CLAUDE.md § Known limitations.


def classify_tokens(
    tokens: list[SimpleToken],
    mwe_phrases: set[str],
    tier1_words: set[str],
    tier2_words: set[str],
    *,
    tier3_words: set[str] | None = None,
    fallback_tier1: set[str] | None = None,
    fallback_tier2: set[str] | None = None,
    synonym_map: dict[str, str] | None = None,
    inflected_forms: dict[str, str] | None = None,
) -> list[TokenResult]:
    """Greedily classify *tokens*, longest MWE match wins.

    Algorithm:
      For each position i:
        If the token is a skip token → SKIP, advance 1.
        Phase 1 — exact MWE match (text or lemma form, windows 3→2→1).
        Phase 2 — prefix partial match for inflected first tokens (multi-word only).
        Else check lemma/text against tier1/tier2 sets.
          If no primary match and fallback sets provided, try those.
        Else → UNKNOWN.
    """
    # Build prefix index: first_word → [phrase, …] for all multi-word phrases.
    # Used in Phase 2 to catch inflected first tokens whose text starts with
    # the stored base form (e.g. "individualia".startswith("individuali")).
    mwe_prefix_index: dict[str, list[str]] = {}
    for phrase in mwe_phrases:
        words = phrase.split()
        if len(words) >= 2:
            mwe_prefix_index.setdefault(words[0], []).append(phrase)

    results: list[TokenResult] = []
    n = len(tokens)
    i = 0

    while i < n:
        tok = tokens[i]

        if tok.is_skip:
            results.append(TokenResult(tok.text, tok.lemma, "SKIP"))
            i += 1
            continue

        matched = False

        # Phase 1: exact MWE match — try windows 3 → 2 → 1
        for window_size in (3, 2, 1):
            if i + window_size > n:
                continue
            window = tokens[i : i + window_size]
            if window_size > 1 and any(t.is_skip for t in window):
                continue

            phrase_text = " ".join(t.text.lower() for t in window)
            phrase_lemma = " ".join(t.lemma.lower() for t in window)

            matched_phrase = phrase_text if phrase_text in mwe_phrases else (phrase_lemma if phrase_lemma in mwe_phrases else None)
            if matched_phrase is not None:
                display = " ".join(t.text for t in window)
                synonym = (synonym_map or {}).get(matched_phrase)
                results.append(TokenResult(display, "", "TIER4", window_size, synonym_of=synonym, matched_phrase=matched_phrase))
                i += window_size
                matched = True
                break

        # Phase 2: prefix partial match for inflected first tokens (multi-word only).
        # Applies when the first token's text (or lemma) starts with — but is not
        # equal to — a stored phrase's first word, suggesting inflection.
        if not matched and mwe_prefix_index:
            for window_size in (3, 2, 1):
                if i + window_size > n or matched:
                    continue
                window = tokens[i : i + window_size]
                if any(t.is_skip for t in window):
                    continue

                first_text = window[0].text.lower()
                first_lemma = window[0].lemma.lower()

                for candidate_first, phrases in mwe_prefix_index.items():
                    if matched:
                        break
                    # The window's first token is an inflected form of candidate_first
                    # when it starts with (but differs from) the stored base.
                    is_inflected_text = (
                        first_text.startswith(candidate_first)
                        and first_text != candidate_first
                    )
                    is_inflected_lemma = (
                        first_lemma.startswith(candidate_first)
                        and first_lemma != candidate_first
                    )
                    if not (is_inflected_text or is_inflected_lemma):
                        continue

                    for phrase in phrases:
                        phrase_words = phrase.split()
                        if len(phrase_words) != window_size:
                            continue
                        rest_ok = all(
                            window[j].text.lower() == phrase_words[j]
                            or window[j].lemma.lower() == phrase_words[j]
                            for j in range(1, window_size)
                        )
                        if rest_ok:
                            display = " ".join(t.text for t in window)
                            synonym = (synonym_map or {}).get(phrase)
                            results.append(TokenResult(display, "", "TIER4", window_size, synonym_of=synonym, matched_phrase=phrase))
                            i += window_size
                            matched = True
                            break

                if matched:
                    break

        if matched:
            continue

        # TIER1 / TIER2 lookup — primary lang, then optional fallback lang
        # Step 1-2: direct concept_lang lookup (text form, then spaCy lemma)
        text_lower = tok.text.lower()
        lemma_lower = tok.lemma.lower()

        if text_lower in tier1_words or lemma_lower in tier1_words:
            results.append(TokenResult(tok.text, tok.lemma, "TIER1"))
        elif text_lower in tier2_words or lemma_lower in tier2_words:
            results.append(TokenResult(tok.text, tok.lemma, "TIER2"))
        else:
            # Steps 3-4: inflected_forms → canonical lemma → concept_lang lookup.
            # Catches common words like 'is'/'are' that live in inflected_forms
            # (as 'is → be') but are absent from concept_lang directly.
            tier_via_inflected: str | None = None
            if inflected_forms:
                canon = inflected_forms.get(text_lower) or inflected_forms.get(lemma_lower)
                if canon:
                    if canon in tier1_words:
                        tier_via_inflected = "TIER1"
                    elif canon in tier2_words:
                        tier_via_inflected = "TIER2"

            if tier_via_inflected:
                results.append(TokenResult(tok.text, tok.lemma, tier_via_inflected))
            elif tier3_words and (text_lower in tier3_words or lemma_lower in tier3_words):
                results.append(TokenResult(tok.text, tok.lemma, "TIER3"))
            elif fallback_tier1 and (text_lower in fallback_tier1 or lemma_lower in fallback_tier1):
                results.append(TokenResult(tok.text, tok.lemma, "TIER1", via_fallback=True))
            elif fallback_tier2 and (text_lower in fallback_tier2 or lemma_lower in fallback_tier2):
                results.append(TokenResult(tok.text, tok.lemma, "TIER2", via_fallback=True))
            else:
                results.append(TokenResult(tok.text, tok.lemma, "UNKNOWN"))

        i += 1

    return results


# ---------------------------------------------------------------------------
# Summary and expertise signal
# ---------------------------------------------------------------------------


def compute_summary(results: list[TokenResult]) -> dict:
    """Compute counts, percentages, and expertise signal from classified tokens."""
    counts: dict[str, int] = {
        "TIER1": 0, "TIER2": 0, "TIER3": 0, "TIER4": 0, "UNKNOWN": 0, "SKIP": 0
    }
    for r in results:
        counts[r.category] = counts.get(r.category, 0) + 1

    total = counts["TIER1"] + counts["TIER2"] + counts["TIER3"] + counts["TIER4"] + counts["UNKNOWN"]
    pct: dict[str, float] = {}
    if total > 0:
        for k in ("TIER1", "TIER2", "TIER3", "TIER4", "UNKNOWN"):
            pct[k] = counts[k] / total

    common = (counts["TIER1"] + counts["TIER2"]) / total if total > 0 else 0.0
    domain = counts["TIER4"] / total if total > 0 else 0.0

    # Preferred signal: ratio = T4 / (T1+T2) — measures domain density relative to known
    # common words. Falls back to domain_pct directly when no common words are identified
    # (e.g. primary lexicon absent), so the interpretation remains meaningful.
    if common > 0:
        ratio = domain / common
        ratio_basis = "t4_vs_common"
    else:
        ratio = 0.0
        ratio_basis = "t4_vs_total"

    # Interpretation thresholds apply to ratio when common > 0, else to domain_pct.
    signal = ratio if ratio_basis == "t4_vs_common" else domain
    if signal < 0.05:
        interpretation = "general audience"
    elif signal < 0.20:
        interpretation = "mixed audience"
    else:
        interpretation = "specialist"

    return {
        "counts": counts,
        "pct": {k: round(v, 4) for k, v in pct.items()},
        "expertise_signal": {
            "common_pct": round(common, 4),
            "domain_pct": round(domain, 4),
            "ratio": round(ratio, 4),
            "ratio_basis": ratio_basis,
            "interpretation": interpretation,
        },
    }


# ---------------------------------------------------------------------------
# Output formatters
# ---------------------------------------------------------------------------


def _pct(v: float) -> str:
    return f"{v * 100:.1f}%"


def format_text_report(
    input_repr: str,
    lang: str,
    domain: str,
    results: list[TokenResult],
    summary: dict,
    *,
    fallback_lang: str | None = None,
) -> str:
    lines: list[str] = []
    sep = "═" * 52
    lines += [sep, "COVERAGE REPORT", sep]
    if fallback_lang:
        lines.append(
            f"! {lang} not in common lexicon — "
            f"using {fallback_lang} as Tier 1/2 fallback (approximate)"
        )
        lines.append(sep)
    lines.append(f'Input  : {input_repr[:72]}')
    lines.append(f"Lang   : {lang}   Domain: {domain}")
    lines.append(sep)
    lines.append("")
    lines.append("Token breakdown:")

    for r in results:
        if r.category == "SKIP":
            continue
        if r.via_fallback and fallback_lang:
            cat_label = f"{r.category}~"
            suffix = f"  ({r.category} via {fallback_lang})"
        else:
            cat_label = r.category
            suffix = f"  ({r.category})"
        if r.synonym_of:
            suffix += f"  (≡ {r.synonym_of})"
        lines.append(f"  {r.text:<30} {cat_label:<8}{suffix}")

    lines.append("")
    lines.append("Summary:")
    c = summary["counts"]
    p = summary["pct"]
    lines.append(f"  Tier 1 tokens  : {c['TIER1']:>4}  ({_pct(p.get('TIER1', 0))})")
    lines.append(f"  Tier 2 tokens  : {c['TIER2']:>4}  ({_pct(p.get('TIER2', 0))})")
    lines.append(f"  Tier 4 tokens  : {c['TIER4']:>4}  ({_pct(p.get('TIER4', 0))})")
    lines.append(f"  Unknown        : {c['UNKNOWN']:>4}  ({_pct(p.get('UNKNOWN', 0))})")
    lines.append(f"  Skipped        : {c['SKIP']:>4}")

    es = summary["expertise_signal"]
    lines.append("")
    lines.append("Expertise signal:")
    lines.append(f"  Common (T1+T2) : {_pct(es['common_pct'])}")
    lines.append(f"  Domain (T4)    : {_pct(es['domain_pct'])}")
    if es.get("ratio_basis") == "t4_vs_total":
        lines.append(f"  Domain% (approx): {_pct(es['domain_pct'])}  [no common words — using domain% directly]")
    else:
        lines.append(f"  Ratio T4/common: {es['ratio']:.2f}")
    lines.append("")
    lines.append("  Interpretation:")
    lines.append("    < 0.05  — general audience text")
    lines.append("    0.05-0.20 — mixed audience")
    lines.append("    > 0.20  — specialist text")
    lines.append(f"  → {es['interpretation'].upper()}")

    return "\n".join(lines)


def format_json_report(
    input_repr: str,
    lang: str,
    domain: str,
    results: list[TokenResult],
    summary: dict,
    *,
    fallback_lang: str | None = None,
) -> str:
    warnings: list[str] = []
    if fallback_lang:
        warnings.append(
            f"{lang} not in common lexicon — "
            f"using {fallback_lang} as Tier 1/2 fallback (approximate)"
        )
    payload = {
        "input": input_repr,
        "lang": lang,
        "domain": domain,
        "warnings": warnings,
        "tokens": [
            {
                "text": r.text,
                "lemma": r.lemma,
                "category": r.category,
                "n_tokens": r.n_tokens,
                "via_fallback": r.via_fallback,
                "synonym_of": r.synonym_of,
            }
            for r in results
        ],
        "summary": summary,
        "expertise_signal": summary["expertise_signal"],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# spaCy tokenisation (isolated so tests can bypass it)
# ---------------------------------------------------------------------------


def _load_nlp(lang: str):
    try:
        import spacy  # noqa: PLC0415
    except ImportError:
        print("spaCy is not installed.  Run: pip install spacy", file=sys.stderr)
        sys.exit(1)

    MODEL_MAP = {
        "lt": "lt_core_news_sm",
        "en": "en_core_web_sm",
        "fr": "fr_core_news_sm",
    }
    model = MODEL_MAP.get(lang, "xx_ent_wiki_sm")
    try:
        return spacy.load(model)
    except OSError:
        print(
            f"spaCy model {model!r} not found.  Run:\n"
            f"  python3 -m spacy download {model}",
            file=sys.stderr,
        )
        sys.exit(1)


def spacy_tokenise(text: str, nlp) -> list[SimpleToken]:
    """Convert raw text to SimpleToken list via spaCy."""
    doc = nlp(text)
    tokens: list[SimpleToken] = []
    for tok in doc:
        is_skip = tok.is_punct or tok.is_space or tok.like_num or tok.is_stop
        tokens.append(SimpleToken(tok.text, tok.lemma_, is_skip))
    return tokens


def spacy_tokenise_sentences(
    text: str, nlp
) -> tuple[list[SimpleToken], list[list[SimpleToken]]]:
    """Tokenise text, returning both a flat token list and sentence-segmented lists.

    The flat list is identical to what spacy_tokenise() returns.
    Sentences containing only skip tokens are omitted from the sentence list.
    Sentence boundaries come from spaCy's dependency parser (or sentencizer pipe
    if the model has no parser).
    """
    doc = nlp(text)
    all_tokens: list[SimpleToken] = []
    sentences: list[list[SimpleToken]] = []
    for sent in doc.sents:
        sent_toks: list[SimpleToken] = []
        for tok in sent:
            is_skip = tok.is_punct or tok.is_space or tok.like_num or tok.is_stop
            token = SimpleToken(tok.text, tok.lemma_, is_skip)
            all_tokens.append(token)
            sent_toks.append(token)
        if any(not t.is_skip for t in sent_toks):
            sentences.append(sent_toks)
    return all_tokens, sentences


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


def analyse(
    text: str,
    lang: str,
    lexicon_db: Path,
    domain_db: Path | None,
    output_format: str,
    fallback_lang: str | None = None,
) -> str:
    """Run the full coverage analysis and return the formatted report string."""
    tier1, tier2 = load_tier_words(lexicon_db, lang)
    mwe_phrases = load_mwe_phrases(domain_db, lang)
    synonym_map = load_synonym_map(domain_db, lang)
    inflected = load_inflected_forms(lexicon_db, lang)

    fb_tier1: set[str] = set()
    fb_tier2: set[str] = set()
    if fallback_lang:
        fb_tier1, fb_tier2 = load_tier_words(lexicon_db, fallback_lang)

    nlp = _load_nlp(lang)
    tokens = spacy_tokenise(text, nlp)
    results = classify_tokens(
        tokens, mwe_phrases, tier1, tier2,
        fallback_tier1=fb_tier1 if fallback_lang else None,
        fallback_tier2=fb_tier2 if fallback_lang else None,
        synonym_map=synonym_map if synonym_map else None,
        inflected_forms=inflected if inflected else None,
    )
    summary = compute_summary(results)

    domain_label = domain_db.stem if domain_db else "none"
    input_repr = text[:120] + ("…" if len(text) > 120 else "")

    if output_format == "json":
        return format_json_report(
            input_repr, lang, domain_label, results, summary, fallback_lang=fallback_lang
        )
    return format_text_report(
        input_repr, lang, domain_label, results, summary, fallback_lang=fallback_lang
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Classify tokens of an input text against the lexicon and domain DB."
    )
    parser.add_argument("--input", required=True, help="Input text string or path to .txt file")
    parser.add_argument("--lang", required=True, choices=["lt", "en", "eo"], help="Language code")
    parser.add_argument("--lexicon", required=True, type=Path, help="Path to lexicon_v2.db")
    parser.add_argument(
        "--domain-db", dest="domain_db", type=Path, default=None,
        help="Path to domain .db (optional)",
    )
    parser.add_argument(
        "--output-format", dest="output_format", choices=["text", "json"], default="text",
        help="Output format (default: text)",
    )
    parser.add_argument(
        "--fallback-lang", dest="fallback_lang", default=None,
        help="Fallback language for Tier 1/2 lookup when primary lang has no common lexicon entries",
    )
    args = parser.parse_args(argv)

    # --input may be a file path or a literal string
    input_path = Path(args.input)
    if input_path.exists() and input_path.is_file():
        text = input_path.read_text(encoding="utf-8").strip()
    else:
        text = args.input

    report = analyse(
        text=text,
        lang=args.lang,
        lexicon_db=args.lexicon,
        domain_db=args.domain_db,
        output_format=args.output_format,
        fallback_lang=args.fallback_lang,
    )
    print(report)


if __name__ == "__main__":
    main()
