"""Unit tests for the pure UNKNOWN classifier logic (no network, no models)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "analyzer"))

from unknown_classifier import (  # noqa: E402
    COMMON_ZIPF,
    JUNK_ZIPF,
    TokenFeatures,
    TokenRecord,
    classify_token,
    is_structural_junk,
    summarise_buckets,
    true_residual_pct,
)


def feat(token="word", *, universality=1, n_domain=0, n_nondomain=None, zipf=4.0,
         is_propn=False, is_name_cased=False, lemma_resolves=False, store_match=False):
    if n_nondomain is None:
        n_nondomain = universality - n_domain
    return TokenFeatures(
        token=token, universality=universality, n_domain_corpora=n_domain,
        n_nondomain_corpora=n_nondomain, zipf=zipf, is_propn=is_propn,
        is_name_cased=is_name_cased, lemma_resolves=lemma_resolves, store_match=store_match,
    )


# --- is_structural_junk -----------------------------------------------------


@pytest.mark.parametrize("tok", ["x", "3", "19", "covid19", "http://a.b", "e-mail@x", "a/b", "'", "??"])
def test_structural_junk_true(tok):
    assert is_structural_junk(tok) is True


@pytest.mark.parametrize("tok", ["embargo", "co-operate", "hippopotamus", "lily", "tariff"])
def test_structural_junk_false(tok):
    assert is_structural_junk(tok) is False


# --- bucket 1: junk ---------------------------------------------------------


def test_junk_structural_wins_first():
    # digits present -> junk even if it looks name-ish / high zipf.
    assert classify_token(feat("abc123", zipf=5.0, is_propn=True)).bucket == "junk"


def test_junk_low_freq_nonword():
    assert classify_token(feat("xqzptr", zipf=0.0)).bucket == "junk"


def test_low_freq_but_name_is_not_junk():
    # a rare real name with low zipf must survive the junk gate (store match).
    c = classify_token(feat("zzyzx", zipf=0.0, store_match=True))
    assert c.bucket == "named_entity" and c.subtype == "confirmed"


def test_low_freq_but_propn_is_not_junk():
    c = classify_token(feat("kayleigh", zipf=JUNK_ZIPF - 0.5, is_propn=True))
    assert c.bucket == "named_entity" and c.subtype == "candidate"


# --- bucket 2: named_entity -------------------------------------------------


def test_named_entity_confirmed_beats_candidate():
    c = classify_token(feat("paris", zipf=5.0, store_match=True, is_propn=True))
    assert c.bucket == "named_entity" and c.subtype == "confirmed"


def test_named_entity_candidate_when_absent_from_store():
    c = classify_token(feat("timmy", zipf=3.3, is_propn=True, store_match=False))
    assert c.bucket == "named_entity" and c.subtype == "candidate"


def test_name_cased_alone_is_candidate():
    c = classify_token(feat("lyra", zipf=2.0, is_name_cased=True))
    assert c.bucket == "named_entity" and c.subtype == "candidate"


def test_name_cased_beats_spurious_lemma_resolve():
    # 'peter' proper-cased mid-sentence stays a name even if a crude de-inflection
    # (peter→pet) made lemma_resolves true — casing is the stronger signal.
    c = classify_token(feat("peter", zipf=4.0, is_name_cased=True, lemma_resolves=True))
    assert c.bucket == "named_entity" and c.subtype == "candidate"


# --- bucket 3: inflection_miss ----------------------------------------------


def test_inflection_miss():
    c = classify_token(feat("running", zipf=4.5, lemma_resolves=True))
    assert c.bucket == "inflection_miss"


def test_store_confirmed_beats_inflection_miss():
    # A store hit is authoritative even if a lemma also resolves.
    c = classify_token(feat("holmes", zipf=4.0, store_match=True, lemma_resolves=True))
    assert c.bucket == "named_entity" and c.subtype == "confirmed"


def test_propn_inflection_is_not_a_name_candidate():
    # 'loved' — spaCy mis-tags sentence-initial as PROPN, but its lemma 'love'
    # resolves, so it must be inflection_miss, not a name candidate.
    c = classify_token(feat("loved", zipf=5.0, is_propn=True, lemma_resolves=True))
    assert c.bucket == "inflection_miss"


# --- bucket 4: domain_term --------------------------------------------------


def test_domain_term_only_in_domain_corpora():
    c = classify_token(feat("countervailing", universality=2, n_domain=2, zipf=2.5))
    assert c.bucket == "domain_term"


def test_domain_term_needs_zero_nondomain():
    # UNKNOWN in one domain + one general corpus -> NOT domain_term
    c = classify_token(feat("countervailing", universality=2, n_domain=1, n_nondomain=1, zipf=2.5))
    assert c.bucket != "domain_term"


def test_single_domain_corpus_is_domain_term():
    c = classify_token(feat("dumping", universality=1, n_domain=1, n_nondomain=0, zipf=2.0))
    assert c.bucket == "domain_term"


# --- bucket 5/6: common_gap vs true_residual --------------------------------


def test_common_gap_high_zipf_cross_corpus():
    c = classify_token(feat("perhaps", universality=3, zipf=COMMON_ZIPF + 1.0))
    assert c.bucket == "common_gap"


def test_true_residual_midfreq_cross_corpus():
    c = classify_token(feat("wistful", universality=2, zipf=COMMON_ZIPF - 1.0))
    assert c.bucket == "true_residual"


def test_true_residual_needs_two_corpora():
    # midfreq word UNKNOWN in only one non-domain corpus -> local, not residual
    c = classify_token(feat("wistful", universality=1, n_domain=0, zipf=COMMON_ZIPF - 1.0))
    assert c.bucket == "local"


def test_common_gap_needs_two_corpora():
    c = classify_token(feat("perhaps", universality=1, n_domain=0, zipf=5.0))
    assert c.bucket == "local"


def test_order_junk_before_everything():
    # zipf below junk threshold, not a name -> junk regardless of universality
    c = classify_token(feat("qwx", universality=4, zipf=0.0))
    assert c.bucket == "junk"


# --- aggregation helpers ----------------------------------------------------


def _rec(token, bucket, counts, **kw):
    return TokenRecord(
        token=token, per_corpus_counts=counts, universality=len(counts),
        total_count=sum(counts.values()), zipf=kw.get("zipf", 3.0),
        is_propn=False, is_name_cased=False, lemma="", lemma_resolves=False,
        store_match=False, bucket=bucket, subtype=kw.get("subtype", ""),
    )


def test_summarise_buckets():
    recs = [
        _rec("a", "junk", {"x": 5}),
        _rec("b", "true_residual", {"x": 2, "y": 3}),
        _rec("c", "true_residual", {"y": 1}),
    ]
    s = summarise_buckets(recs)
    assert s["junk"] == {"types": 1, "tokens": 5}
    assert s["true_residual"] == {"types": 2, "tokens": 6}
    assert s["named_entity"] == {"types": 0, "tokens": 0}


def test_true_residual_pct_pooled_and_per_corpus():
    recs = [
        _rec("b", "true_residual", {"x": 2, "y": 3}),
        _rec("n", "named_entity", {"x": 100}),  # excluded from residual
    ]
    totals = {"x": 1000, "y": 500}
    # pooled: 5 residual / 1500 total
    assert true_residual_pct(totals, recs) == pytest.approx(100 * 5 / 1500, abs=1e-3)
    # per corpus x: 2 / 1000
    assert true_residual_pct(totals, recs, "x") == pytest.approx(0.2, abs=1e-3)
