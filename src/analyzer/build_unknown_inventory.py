#!/usr/bin/env python3
"""Build the cross-corpus UNKNOWN inventory (read-only diagnostic).

Regenerates a SEPARATE UNKNOWN pool per corpus with the *current* lexicon
(common-lexicon only — no domain DBs, so domain vocabulary surfaces as UNKNOWN
and is sorted by the classifier's ``domain_term`` bucket via cross-corpus
concentration), captures per-token name/lemma features during one spaCy pass,
classifies every token with :mod:`unknown_classifier`, and emits:

  * ``pooled_unknown_classified.tsv`` — every token: per-corpus UNKNOWN counts,
    universality, bucket, zipf, is_propn, lemma, store-match.
  * ``true_residual.tsv``            — the isolated cell, universality-ranked.
  * ``name_candidates.tsv``          — name-bucket tokens absent from the store.

Plus a printed classified breakdown per corpus + pooled, and the honest
**true-residual UNKNOWN %** (raw UNKNOWN minus names, junk, domain, inflection,
common-gap).

READ-ONLY: opens ``lexicon_v2.db`` and the ``named_entity`` store read-only;
writes nothing to either. Authors nothing.

Usage::

    python3 src/analyzer/build_unknown_inventory.py \\
        --lexicon data/lexicon_db/lexicon_v2.db \\
        --corpus-root ../esperanto-lexicon-corpus \\
        --out-dir data/analysis/unknown_inventory
"""

from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent / "lexicon"))

from coverage_report import (  # noqa: E402
    classify_tokens,
    load_inflected_forms,
    load_tier3_words,
    load_tier_words,
    _load_nlp,
)
from unknown_classifier import (  # noqa: E402
    TokenFeatures,
    TokenRecord,
    classify_token,
    summarise_buckets,
    true_residual_pct,
)


# ---------------------------------------------------------------------------
# Corpus registry — (name, relative path, is_domain)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Corpus:
    name: str
    rel_path: str
    is_domain: bool


DEFAULT_CORPORA = (
    Corpus("tinystories", "tinystories/stories", False),   # child vocabulary
    Corpus("control", "proficiency_eval/control", False),  # general topics
    Corpus("novice", "proficiency_eval/novice", True),     # customs (novice)
    Corpus("expert", "proficiency_eval/expert", True),     # customs (expert)
)

# Inflectional suffixes only. Derivational endings (-er/-est/-ly) are deliberately
# excluded: an "-er" agent noun (importer) or comparative is a distinct lexeme, not
# an inflection miss, and stripping them wrongly "resolves" names (peter→pet).
_SUFFIX_STRIPS = (
    ("ies", "y"), ("ied", "y"), ("es", ""), ("ed", ""), ("ing", ""), ("s", ""),
)


def _deinflect_candidates(token: str) -> set[str]:
    """Cheap de-inflection variants for the inflection-miss test."""
    out: set[str] = set()
    for suf, repl in _SUFFIX_STRIPS:
        if token.endswith(suf) and len(token) - len(suf) >= 2:
            out.add(token[: -len(suf)] + repl)
    return out


# ---------------------------------------------------------------------------
# Per-corpus UNKNOWN extraction (+ name/lemma features), reusing the analyzer
# ---------------------------------------------------------------------------


@dataclass
class _Feat:
    count: int = 0
    propn: bool = False
    name_cased: bool = False
    lemma: str = ""


def scan_corpus(
    corpus_dir: Path, nlp, tier1, tier2, tier3, inflected
) -> tuple[dict[str, _Feat], int]:
    """Return ``({token_lower: _Feat} for UNKNOWN tokens, n_content_tokens)``.

    Classification uses the same ``classify_tokens`` the coverage report uses
    (common lexicon only). During the single spaCy pass we capture, per token,
    whether it was ever a PROPN, ever proper-noun-cased (capitalised off
    sentence-start), and its lemma — the signals the name/inflection gates need —
    and count content tokens for the true-residual %.
    """
    feats: dict[str, _Feat] = defaultdict(_Feat)
    content_tokens = 0
    from coverage_report import SimpleToken  # local import (module already loaded)

    for path in sorted(corpus_dir.glob("*.txt")):
        text = path.read_text(encoding="utf-8", errors="replace")
        doc = nlp(text)
        simple = [
            SimpleToken(t.text, t.lemma_, t.is_punct or t.is_space or t.like_num or t.is_stop)
            for t in doc
        ]
        content_tokens += sum(1 for st in simple if not st.is_skip)
        results = classify_tokens(
            simple, set(), tier1, tier2,
            tier3_words=tier3 or None, inflected_forms=inflected or None,
        )
        # Count ONLY the occurrences actually classified UNKNOWN. A word like
        # "playing" is TIER1 where spaCy lemmatised it to "play" and UNKNOWN only
        # in the positions where lemmatisation failed — counting every occurrence
        # would wildly over-state UNKNOWN.
        unknown_counter = Counter(
            r.text.lower() for r in results if r.category == "UNKNOWN"
        )
        by_lower: dict[str, list] = defaultdict(list)
        for t in doc:
            by_lower[t.text.lower()].append(t)
        for tok_l, cnt in unknown_counter.items():
            fe = feats[tok_l]
            fe.count += cnt
            for t in by_lower.get(tok_l, []):
                if t.pos_ == "PROPN":
                    fe.propn = True
                if t.text[:1].isupper() and not t.is_sent_start:
                    fe.name_cased = True
                if not fe.lemma and t.lemma_.lower() != tok_l:
                    fe.lemma = t.lemma_.lower()
    return feats, content_tokens


# ---------------------------------------------------------------------------
# Assemble + classify
# ---------------------------------------------------------------------------


def build_records(
    per_corpus: dict[str, dict[str, _Feat]],
    corpora: tuple[Corpus, ...],
    known_words: set[str],
    zipf_fn,
    store_resolve,
) -> list[TokenRecord]:
    """Join per-corpus features, compute token features, and classify each token."""
    domain_names = {c.name for c in corpora if c.is_domain}
    all_tokens: set[str] = set()
    for d in per_corpus.values():
        all_tokens.update(d.keys())

    records: list[TokenRecord] = []
    for tok in all_tokens:
        counts = {c.name: per_corpus[c.name][tok].count
                  for c in corpora if tok in per_corpus[c.name]}
        corpora_hit = [c.name for c in corpora if tok in per_corpus[c.name]]
        universality = len(corpora_hit)
        n_domain = sum(1 for c in corpora_hit if c in domain_names)
        n_nondomain = universality - n_domain

        propn = any(per_corpus[c][tok].propn for c in corpora_hit)
        name_cased = any(per_corpus[c][tok].name_cased for c in corpora_hit)
        lemma = next((per_corpus[c][tok].lemma for c in corpora_hit
                      if per_corpus[c][tok].lemma), "")

        lemma_resolves = False
        if lemma and lemma in known_words:
            lemma_resolves = True
        else:
            for cand in _deinflect_candidates(tok):
                if cand in known_words:
                    lemma_resolves = True
                    lemma = lemma or cand
                    break

        store_match = store_resolve(tok)
        zipf = zipf_fn(tok)

        feats = TokenFeatures(
            token=tok, universality=universality,
            n_domain_corpora=n_domain, n_nondomain_corpora=n_nondomain,
            zipf=zipf, is_propn=propn, is_name_cased=name_cased,
            lemma_resolves=lemma_resolves, store_match=store_match,
        )
        cl = classify_token(feats)
        records.append(TokenRecord(
            token=tok, per_corpus_counts=counts, universality=universality,
            total_count=sum(counts.values()), zipf=round(zipf, 2),
            is_propn=propn, is_name_cased=name_cased, lemma=lemma,
            lemma_resolves=lemma_resolves, store_match=store_match,
            bucket=cl.bucket, subtype=cl.subtype, corpora=corpora_hit,
        ))
    return records


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def classify_from_counters(
    strata_counters: dict[str, Counter],
    domain_strata: set[str],
    known_words: set[str],
    zipf_fn,
    store_resolve,
) -> list[TokenRecord]:
    """Classify UNKNOWN tokens from per-stratum count-only pools (no spaCy).

    Used by ``batch_coverage_report --classify-unknown`` where PROPN / name-casing
    features are not available: the name bucket here relies on the store match and
    a de-inflection lemma test only (weaker than the standalone inventory, which
    also uses casing/PROPN). Universality = number of strata a token is UNKNOWN in.
    """
    all_tokens: set[str] = set()
    for c in strata_counters.values():
        all_tokens.update(c)
    records: list[TokenRecord] = []
    for tok in all_tokens:
        counts = {s: c[tok] for s, c in strata_counters.items() if tok in c}
        strata_hit = list(counts)
        universality = len(strata_hit)
        n_domain = sum(1 for s in strata_hit if s in domain_strata)
        lemma_resolves, lemma = False, ""
        for cand in _deinflect_candidates(tok):
            if cand in known_words:
                lemma_resolves, lemma = True, cand
                break
        feats = TokenFeatures(
            token=tok, universality=universality, n_domain_corpora=n_domain,
            n_nondomain_corpora=universality - n_domain, zipf=zipf_fn(tok),
            is_propn=False, is_name_cased=False,
            lemma_resolves=lemma_resolves, store_match=store_resolve(tok),
        )
        cl = classify_token(feats)
        records.append(TokenRecord(
            token=tok, per_corpus_counts=counts, universality=universality,
            total_count=sum(counts.values()), zipf=round(feats.zipf, 2),
            is_propn=False, is_name_cased=False, lemma=lemma,
            lemma_resolves=lemma_resolves, store_match=feats.store_match,
            bucket=cl.bucket, subtype=cl.subtype, corpora=strata_hit,
        ))
    return records


def _sort_key(r: TokenRecord):
    return (-r.universality, -r.total_count, r.token)


def write_classified(records: list[TokenRecord], corpora, path: Path) -> None:
    cols = (["token", "bucket", "subtype", "universality", "total_count"]
            + [f"c_{c.name}" for c in corpora]
            + ["zipf", "is_propn", "is_name_cased", "lemma", "lemma_resolves", "store_match"])
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow(cols)
        for r in sorted(records, key=_sort_key):
            w.writerow(
                [r.token, r.bucket, r.subtype, r.universality, r.total_count]
                + [r.per_corpus_counts.get(c.name, 0) for c in corpora]
                + [r.zipf, int(r.is_propn), int(r.is_name_cased), r.lemma,
                   int(r.lemma_resolves), int(r.store_match)]
            )


def write_true_residual(records, corpora, path: Path) -> None:
    resid = [r for r in records if r.bucket == "true_residual"]
    cols = (["token", "universality", "total_count"]
            + [f"c_{c.name}" for c in corpora] + ["zipf", "lemma"])
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow(cols)
        for r in sorted(resid, key=_sort_key):
            w.writerow([r.token, r.universality, r.total_count]
                       + [r.per_corpus_counts.get(c.name, 0) for c in corpora]
                       + [r.zipf, r.lemma])


def write_name_candidates(records, path: Path) -> None:
    cands = [r for r in records
             if r.bucket == "named_entity" and r.subtype == "candidate"]
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow(["token", "total_count", "universality", "is_propn", "is_name_cased", "zipf"])
        for r in sorted(cands, key=lambda r: (-r.total_count, r.token)):
            w.writerow([r.token, r.total_count, r.universality,
                        int(r.is_propn), int(r.is_name_cased), r.zipf])


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    root = _HERE.parent.parent
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--lexicon", type=Path, default=root / "data" / "lexicon_db" / "lexicon_v2.db")
    ap.add_argument("--corpus-root", type=Path, default=root.parent / "esperanto-lexicon-corpus")
    ap.add_argument("--out-dir", type=Path, default=root / "data" / "analysis" / "unknown_inventory")
    ap.add_argument("--lang", default="en")
    args = ap.parse_args(argv)

    from wordfreq import zipf_frequency  # mandatory junk gate (installed)
    sys.path.insert(0, str(root / "src" / "lexicon"))
    from query_named_entities import resolve as ne_resolve  # read-only store

    tier1, tier2 = load_tier_words(args.lexicon, args.lang)
    tier3 = load_tier3_words(args.lexicon, args.lang)
    inflected = load_inflected_forms(args.lexicon, args.lang)
    known_words = set(tier1) | set(tier2) | set(tier3) | set(inflected.keys())
    nlp = _load_nlp(args.lang)
    print(f"lexicon: T1={len(tier1)} T2={len(tier2)} T3={len(tier3)} inflected={len(inflected)}")

    ne_conn = sqlite3.connect(f"file:{args.lexicon}?mode=ro", uri=True)

    def store_resolve(token: str) -> bool:
        try:
            return ne_resolve(ne_conn, token) is not None
        except Exception:
            return False

    per_corpus: dict[str, dict[str, _Feat]] = {}
    per_corpus_totals: dict[str, int] = {}
    corpora = DEFAULT_CORPORA
    present: list[Corpus] = []
    for c in corpora:
        cdir = (args.corpus_root / c.rel_path).expanduser()
        if not cdir.is_dir():
            print(f"  WARN: corpus dir missing, skipping: {cdir}")
            continue
        present.append(c)
        feats, total = scan_corpus(cdir, nlp, tier1, tier2, tier3, inflected)
        per_corpus[c.name] = feats
        per_corpus_totals[c.name] = total
        n_unknown = sum(f.count for f in feats.values())
        print(f"  {c.name:12} files ok | {len(feats):>5} distinct UNKNOWN | "
              f"{n_unknown:>6} UNKNOWN tokens | {total:>6} content tokens "
              f"({100*n_unknown/max(total,1):.1f}%)")
    corpora = tuple(present)
    ne_conn.close()

    records = build_records(per_corpus, corpora, known_words,
                            lambda t: zipf_frequency(t, "en"), store_resolve)

    out = args.out_dir.expanduser()
    out.mkdir(parents=True, exist_ok=True)
    write_classified(records, corpora, out / "pooled_unknown_classified.tsv")
    write_true_residual(records, corpora, out / "true_residual.tsv")
    write_name_candidates(records, out / "name_candidates.tsv")

    _report(records, corpora, per_corpus_totals)
    print(f"\nwrote → {out}/  (pooled_unknown_classified.tsv, true_residual.tsv, name_candidates.tsv)")
    return 0


def _report(records, corpora, totals) -> None:
    buckets = summarise_buckets(records)
    print("\n" + "=" * 70)
    print("CLASSIFIED UNKNOWN — pooled across corpora")
    print("=" * 70)
    print(f"{'bucket':16} {'types':>7} {'tokens':>9}")
    for b, d in buckets.items():
        print(f"{b:16} {d['types']:>7} {d['tokens']:>9}")
    total_types = sum(d["types"] for d in buckets.values())
    total_tokens = sum(d["tokens"] for d in buckets.values())
    print(f"{'TOTAL':16} {total_types:>7} {total_tokens:>9}")
    grand_total = sum(totals.values())
    raw_unknown = total_tokens
    resid = buckets["true_residual"]["tokens"]
    print("-" * 70)
    print(f"raw UNKNOWN tokens (pooled)   : {raw_unknown}  "
          f"({100*raw_unknown/max(grand_total,1):.2f}% of {grand_total} content tokens)")
    print(f"  − junk                      : {buckets['junk']['tokens']}")
    print(f"  − named_entity              : {buckets['named_entity']['tokens']}")
    print(f"  − inflection_miss           : {buckets['inflection_miss']['tokens']}")
    print(f"  − domain_term               : {buckets['domain_term']['tokens']}")
    print(f"  − common_gap                : {buckets['common_gap']['tokens']}")
    print(f"  − local (single-corpus)     : {buckets['local']['tokens']}")
    print(f"  = TRUE RESIDUAL             : {resid}  "
          f"→ true-residual UNKNOWN % = {true_residual_pct(totals, records):.3f}%")
    print("-" * 70)
    print("true-residual % by corpus:")
    for c in corpora:
        print(f"  {c.name:12} {true_residual_pct(totals, records, c.name):.3f}%")


if __name__ == "__main__":
    sys.exit(main())
