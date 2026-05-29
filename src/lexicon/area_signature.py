"""Derive the per-area expertise signature for a Tier 4 term.

The signature is a compact, human-readable summary of WHICH canonical customs
areas a term is attested in and HOW STRONGLY. It is a derived display
affordance computed from raw attestation rows — never primary storage. Raw
doc_count + frequency live in mwe_area_attestation; weights are derived here so
the bucketing scheme can change without a schema migration.

Signature semantics (do not invert polarity):
  * 7 hex digits, one per canonical area in CANONICAL_AREAS order.
  * Each digit is an INDEPENDENT strength score, not a probability weight
    (digits do not sum to anything).
  * '0' = absent, 'F' = dominant. HIGH digit = HIGH relevance.
  * Bucketing: weight = area_doc_count / max_doc_count_across_areas;
    digit = min(15, floor(weight * 16)), rendered uppercase hex.
"""

from __future__ import annotations

import math

# Canonical customs areas, in signature digit order. Do not reorder — the
# position of each area in this list IS its position in the 7-digit signature.
CANONICAL_AREAS: list[str] = [
    "law",
    "tariff_regulation",
    "non_tariff_regulation",
    "customs_procedures",
    "origin",
    "classification",
    "valuation",
]

# Tag for cross-cutting / overlay corpora (compliance, sustainability, tech,
# other). Not a peer-level area; ignored for signature/specificity purposes.
CROSS_CUTTING = "cross_cutting"


def _doc_counts_by_canonical_area(attestation_rows: list[dict]) -> dict[str, int]:
    """Sum doc_count per canonical area, dropping cross-cutting rows."""
    sums: dict[str, int] = {area: 0 for area in CANONICAL_AREAS}
    for row in attestation_rows:
        area = row.get("area")
        if area in sums:
            sums[area] += int(row.get("doc_count") or 0)
    return sums


def compute_signature(attestation_rows: list[dict]) -> str:
    """Compute the 7-digit area signature from attestation rows.

    Args:
        attestation_rows: list of {area, doc_count, frequency} dicts
            for one mwe_id. Cross-cutting rows are IGNORED for
            signature purposes (signature represents canonical areas only).

    Returns:
        A 7-character string of hex digits in canonical area order:
        law, tariff_regulation, non_tariff_regulation, customs_procedures,
        origin, classification, valuation
        '0' = no attestation, 'F' = dominant.
    """
    sums = _doc_counts_by_canonical_area(attestation_rows)
    max_count = max(sums.values()) if sums else 0
    if max_count <= 0:
        return "0000000"

    digits: list[str] = []
    for area in CANONICAL_AREAS:
        weight = sums[area] / max_count
        digit = min(15, math.floor(weight * 16))
        digits.append(format(digit, "X"))
    return "".join(digits)


def compute_specificity(attestation_rows: list[dict]) -> float:
    """Return how area-specific a term is, from canonical attestation only.

    area_specificity = max(area_doc_count) / sum(area_doc_count) over canonical
    areas. 1.0 = perfectly area-specific; 1/7 ≈ 0.143 = perfectly uniform.
    Cross-cutting rows are excluded. Returns 0.0 when there is no canonical
    attestation (e.g. a cross-cutting-only term).
    """
    sums = _doc_counts_by_canonical_area(attestation_rows)
    total = sum(sums.values())
    if total <= 0:
        return 0.0
    return max(sums.values()) / total
