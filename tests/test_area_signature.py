"""Tests for src/lexicon/area_signature.py."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from lexicon.area_signature import (
    CANONICAL_AREAS,
    compute_signature,
    compute_specificity,
)


def _row(area: str, doc_count: int, frequency: int = 0) -> dict:
    return {"area": area, "doc_count": doc_count, "frequency": frequency}


# ---------------------------------------------------------------------------
# compute_signature
# ---------------------------------------------------------------------------


def test_empty_input_returns_all_zeros() -> None:
    assert compute_signature([]) == "0000000"


def test_only_cross_cutting_returns_all_zeros() -> None:
    rows = [_row("cross_cutting", 50, 200), _row("cross_cutting", 10, 30)]
    assert compute_signature(rows) == "0000000"


def test_single_area_dominance_law() -> None:
    # law is index 0
    assert compute_signature([_row("law", 40, 210)]) == "F000000"


def test_single_area_dominance_origin() -> None:
    # origin is index 4
    assert compute_signature([_row("origin", 297, 1000)]) == "0000F00"


def test_single_area_dominance_valuation() -> None:
    # valuation is index 6 (last)
    assert compute_signature([_row("valuation", 5, 9)]) == "000000F"


def test_equal_distribution_all_seven() -> None:
    rows = [_row(area, 10, 10) for area in CANONICAL_AREAS]
    # Every area has weight 1.0 → digit F.
    assert compute_signature(rows) == "FFFFFFF"


def test_cross_cutting_rows_ignored_in_signature() -> None:
    rows = [
        _row("origin", 40, 210),
        _row("cross_cutting", 100, 500),  # larger, but must not affect signature
    ]
    # max over canonical areas = 40 (origin) → origin = F, rest 0.
    assert compute_signature(rows) == "0000F00"


def test_mixed_realistic_case() -> None:
    # law dominant (40), origin moderate, classification weak.
    rows = [
        _row("law", 40, 100),
        _row("origin", 20, 50),  # weight 0.5 → floor(8) = 8
        _row("classification", 5, 12),  # weight 0.125 → floor(2) = 2
    ]
    sig = compute_signature(rows)
    # order: law, tariff_regulation, non_tariff_regulation, customs_procedures,
    #        origin, classification, valuation
    assert sig == "F000820"


def test_doc_count_summed_across_same_area_rows() -> None:
    # Same area mined from two files → doc_counts add up.
    rows = [
        _row("origin", 20, 100, ),
        _row("origin", 20, 100),
        _row("law", 10, 30),
    ]
    # origin total 40 (max), law 10 → law weight 0.25 → digit 4.
    assert compute_signature(rows) == "4000F00"


def test_digit_clamped_to_F() -> None:
    # weight exactly 1.0 → 1.0 * 16 = 16 → clamped to 15 = 'F'.
    assert compute_signature([_row("law", 1, 1)]) == "F000000"


# ---------------------------------------------------------------------------
# compute_specificity
# ---------------------------------------------------------------------------


def test_specificity_single_area_is_one() -> None:
    assert compute_specificity([_row("origin", 40, 210)]) == 1.0


def test_specificity_uniform_is_one_seventh() -> None:
    rows = [_row(area, 10, 10) for area in CANONICAL_AREAS]
    assert abs(compute_specificity(rows) - 1 / 7) < 1e-9


def test_specificity_cross_cutting_only_is_zero() -> None:
    assert compute_specificity([_row("cross_cutting", 100, 500)]) == 0.0


def test_specificity_excludes_cross_cutting() -> None:
    rows = [_row("origin", 40, 210), _row("cross_cutting", 60, 300)]
    # cross_cutting excluded → only origin → specificity 1.0
    assert compute_specificity(rows) == 1.0


def test_specificity_mixed() -> None:
    rows = [_row("law", 40, 100), _row("origin", 10, 50), _row("classification", 10, 20)]
    # max 40 / sum 60
    assert abs(compute_specificity(rows) - 40 / 60) < 1e-9
