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


# ---------------------------------------------------------------------------
# Lexicon loading
# ---------------------------------------------------------------------------


def load_tier_words(lexicon_db: Path, lang: str) -> tuple[set[str], set[str]]:
    """Return (tier1_words, tier2_words) — lowercased from concept_lang."""
    if not lexicon_db.exists():
        return set(), set()
    conn = sqlite3.connect(lexicon_db)
    tier1: set[str] = set()
    tier2: set[str] = set()
    for word, tier in conn.execute(
        "SELECT LOWER(word), tier FROM concept_lang WHERE lang = ?", (lang,)
    ):
        (tier1 if tier == 1 else tier2).add(word)
    conn.close()
    return tier1, tier2


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


# ---------------------------------------------------------------------------
# Core classification (pure — no spaCy dependency)
# ---------------------------------------------------------------------------


def classify_tokens(
    tokens: list[SimpleToken],
    mwe_phrases: set[str],
    tier1_words: set[str],
    tier2_words: set[str],
) -> list[TokenResult]:
    """Greedily classify *tokens*, longest MWE match wins.

    Algorithm:
      For each position i:
        If the token is a skip token → SKIP, advance 1.
        Else try windows of 3, 2, 1 non-skip tokens:
          - Build phrase from lowercased text and from lemmas
          - If either form is in mwe_phrases → TIER4, advance window_size
        Else check lemma / text against tier1/tier2 sets.
        Else → UNKNOWN.
    """
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
        for window_size in (3, 2, 1):
            if i + window_size > n:
                continue
            window = tokens[i : i + window_size]
            if window_size > 1 and any(t.is_skip for t in window):
                continue

            phrase_text = " ".join(t.text.lower() for t in window)
            phrase_lemma = " ".join(t.lemma.lower() for t in window)

            if phrase_text in mwe_phrases or phrase_lemma in mwe_phrases:
                display = " ".join(t.text for t in window)
                results.append(TokenResult(display, "", "TIER4", window_size))
                i += window_size
                matched = True
                break

        if matched:
            continue

        text_lower = tok.text.lower()
        lemma_lower = tok.lemma.lower()
        if text_lower in tier1_words or lemma_lower in tier1_words:
            results.append(TokenResult(tok.text, tok.lemma, "TIER1"))
        elif text_lower in tier2_words or lemma_lower in tier2_words:
            results.append(TokenResult(tok.text, tok.lemma, "TIER2"))
        else:
            results.append(TokenResult(tok.text, tok.lemma, "UNKNOWN"))

        i += 1

    return results


# ---------------------------------------------------------------------------
# Summary and expertise signal
# ---------------------------------------------------------------------------


def compute_summary(results: list[TokenResult]) -> dict:
    """Compute counts, percentages, and expertise signal from classified tokens."""
    counts: dict[str, int] = {"TIER1": 0, "TIER2": 0, "TIER4": 0, "UNKNOWN": 0, "SKIP": 0}
    for r in results:
        counts[r.category] = counts.get(r.category, 0) + 1

    total = counts["TIER1"] + counts["TIER2"] + counts["TIER4"] + counts["UNKNOWN"]
    pct: dict[str, float] = {}
    if total > 0:
        for k in ("TIER1", "TIER2", "TIER4", "UNKNOWN"):
            pct[k] = counts[k] / total

    common = (counts["TIER1"] + counts["TIER2"]) / total if total > 0 else 0.0
    domain = counts["TIER4"] / total if total > 0 else 0.0
    ratio = domain / common if common > 0 else 0.0

    if ratio < 0.05:
        interpretation = "general audience"
    elif ratio < 0.20:
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
) -> str:
    lines: list[str] = []
    sep = "═" * 52
    lines += [sep, "COVERAGE REPORT", sep]
    lines.append(f'Input  : {input_repr[:72]}')
    lines.append(f"Lang   : {lang}   Domain: {domain}")
    lines.append(sep)
    lines.append("")
    lines.append("Token breakdown:")

    for r in results:
        if r.category == "SKIP":
            continue
        suffix = f"  ({r.category})"
        lines.append(f"  {r.text:<30} {r.category:<8}{suffix}")

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
) -> str:
    payload = {
        "input": input_repr,
        "lang": lang,
        "domain": domain,
        "tokens": [
            {"text": r.text, "lemma": r.lemma, "category": r.category, "n_tokens": r.n_tokens}
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


def spacy_tokenise(text: str, nlp) -> list[SimpleToken]:
    """Convert raw text to SimpleToken list via spaCy."""
    doc = nlp(text)
    tokens: list[SimpleToken] = []
    for tok in doc:
        is_skip = tok.is_punct or tok.is_space or tok.like_num or tok.is_stop
        tokens.append(SimpleToken(tok.text, tok.lemma_, is_skip))
    return tokens


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


def analyse(
    text: str,
    lang: str,
    lexicon_db: Path,
    domain_db: Path | None,
    output_format: str,
) -> str:
    """Run the full coverage analysis and return the formatted report string."""
    tier1, tier2 = load_tier_words(lexicon_db, lang)
    mwe_phrases = load_mwe_phrases(domain_db, lang)

    nlp = _load_nlp(lang)
    tokens = spacy_tokenise(text, nlp)
    results = classify_tokens(tokens, mwe_phrases, tier1, tier2)
    summary = compute_summary(results)

    domain_label = domain_db.stem if domain_db else "none"
    input_repr = text[:120] + ("…" if len(text) > 120 else "")

    if output_format == "json":
        return format_json_report(input_repr, lang, domain_label, results, summary)
    return format_text_report(input_repr, lang, domain_label, results, summary)


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
    )
    print(report)


if __name__ == "__main__":
    main()
