"""Tests for src/extractor/bucket_candidates.py — enrichment + bucketing."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from extractor.bucket_candidates import (  # noqa: E402
    assign_buckets,
    compute_ne_risk,
    find_low_scorers,
    normalise,
)


def _rec(**kw):
    """Build a minimal enriched candidate record with sensible defaults."""
    base = {
        "phrase_normalized": "phrase",
        "phrase_inflected": None,
        "pos_pattern": "NOUN NOUN",
        "total_doc_count": 10,
        "total_frequency": 20,
        "attestation": [],
        "area_signature": "0000000",
        "area_specificity": 0.0,
        "ne_risk": 0.0,
        "appears_in_low_scorers": [],
    }
    base.update(kw)
    return base


def _att(area, doc_count):
    return {"area": area, "doc_count": doc_count, "frequency": doc_count}


def test_ne_risk_country_name():
    rec = _rec(phrase_normalized="northern ireland", pos_pattern="NOUN NOUN")
    assert compute_ne_risk(rec) >= 0.3


def test_ne_risk_acronym():
    rec = _rec(phrase_normalized="afcfta agreement", pos_pattern="NOUN NOUN")
    assert compute_ne_risk(rec) >= 0.3


def test_ne_risk_clean_vocabulary():
    rec = _rec(
        phrase_normalized="diagonal cumulation",
        pos_pattern="ADJ NOUN",
        area_specificity=0.5,
    )
    assert compute_ne_risk(rec) < 0.2


def test_low_scorer_match():
    texts = {
        "expert_04": normalise("Rules of origin and preferential origin in EU-UK trade."),
        "expert_06": normalise("Machinery sector under the PEM Convention."),
    }
    assert find_low_scorers("preferential origin", texts) == ["expert_04"]
    assert find_low_scorers("nonexistent phrase", texts) == []


def test_bucket_assignment():
    b1 = _rec(
        phrase_normalized="customs declaration",
        attestation=[
            _att("law", 5), _att("origin", 4),
            _att("valuation", 3), _att("classification", 2),
        ],
    )
    b2 = _rec(
        phrase_normalized="preferential origin",
        attestation=[_att("origin", 8)],
        area_specificity=1.0,
        appears_in_low_scorers=["expert_04"],
    )
    b3 = _rec(
        phrase_normalized="tariff measures",
        attestation=[_att("tariff_regulation", 9)],
        area_specificity=1.0,
        ne_risk=0.0,
    )
    b4_cross = _rec(
        phrase_normalized="risk management",
        attestation=[_att("cross_cutting", 12)],
    )

    buckets = assign_buckets([b1, b2, b3, b4_cross], skip_phrases=set())
    assert b1 in buckets["bucket_1"]
    assert b2 in buckets["bucket_2"]
    assert b3 in buckets["bucket_3"]
    assert b4_cross in buckets["bucket_4"]


def test_skip_already_in_db():
    rec = _rec(phrase_normalized="customs debt", attestation=[_att("law", 9)],
               area_specificity=1.0)
    buckets = assign_buckets([rec], skip_phrases={normalise("customs debt")})
    total = sum(len(v) for v in buckets.values())
    assert total == 0


def test_bucket3_top_n_per_area_spills_to_bucket4():
    recs = [
        _rec(
            phrase_normalized=f"origin term {i}",
            attestation=[_att("origin", 50 - i)],
            area_specificity=1.0,
            total_doc_count=50 - i,
        )
        for i in range(35)
    ]
    buckets = assign_buckets(recs, skip_phrases=set())
    assert len(buckets["bucket_3"]) == 30
    assert len(buckets["bucket_4"]) == 5
