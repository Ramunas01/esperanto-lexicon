"""End-to-end integration tests for EUR-Lex extraction on real HTML files.

All tests are skipped when the real HTML files are not present on disk.
These tests catch structural regressions that synthetic fixtures cannot:
the real EUR-Lex LT HTML wraps tables inside intermediate container
elements that are NOT direct children of docHtml.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))
from extractor.extract_eurlex_definitions import (
    EurLexExtractor,
    detect_layout,
)

CELEX = "02013R0952-20221212"

REAL_UCC_LT_HTML = Path(__file__).parent.parent.parent / "data" / "corpus" / "ucc_lt.html"
REAL_UCC_EN_HTML = Path(__file__).parent.parent.parent / "data" / "corpus" / "ucc_en.html"


# ---------------------------------------------------------------------------
# Lithuanian real-file tests
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def ext_lt() -> EurLexExtractor:
    return EurLexExtractor(celex_id=CELEX, lang="lt")


@pytest.fixture(scope="module")
def soup_lt_real(ext_lt: EurLexExtractor):
    pytest.importorskip("bs4")
    if not REAL_UCC_LT_HTML.exists():
        pytest.skip(f"Real LT HTML not present: {REAL_UCC_LT_HTML}")
    return ext_lt.parse_html(REAL_UCC_LT_HTML)


@pytest.fixture(scope="module")
def records_lt_art5(ext_lt: EurLexExtractor, soup_lt_real) -> list[dict]:
    return ext_lt.extract(soup_lt_real, article_filter="5")


@pytest.mark.skipif(not REAL_UCC_LT_HTML.exists(), reason="Real LT HTML not present")
def test_lt_real_layout_is_tablelayout(soup_lt_real) -> None:
    assert detect_layout(soup_lt_real) == "tablelayout"


@pytest.mark.skipif(not REAL_UCC_LT_HTML.exists(), reason="Real LT HTML not present")
def test_lt_article_5_extracts_41_definitions(records_lt_art5: list[dict]) -> None:
    """The real LT UCC Article 5 contains exactly 41 defined terms."""
    defs = [r for r in records_lt_art5 if r["record_type"] == "definition"]
    assert len(defs) == 41, (
        f"Expected 41 definitions, got {len(defs)}. "
        "This likely means tables are still not found — check for intermediate "
        "container elements wrapping the <table> elements."
    )


@pytest.mark.skipif(not REAL_UCC_LT_HTML.exists(), reason="Real LT HTML not present")
def test_lt_article_5_no_warnings(ext_lt: EurLexExtractor, soup_lt_real) -> None:
    ext = EurLexExtractor(celex_id=CELEX, lang="lt")
    ext.extract(soup_lt_real, article_filter="5")
    assert ext.warnings == [], f"Unexpected warnings: {ext.warnings}"


@pytest.mark.skipif(not REAL_UCC_LT_HTML.exists(), reason="Real LT HTML not present")
def test_lt_article_5_list_paths_1_to_41(records_lt_art5: list[dict]) -> None:
    defs = [r for r in records_lt_art5 if r["record_type"] == "definition"]
    paths = sorted(r["source_ref"]["list_path"] for r in defs)
    expected = [str(n) for n in range(1, 42)]
    assert paths == expected


@pytest.mark.skipif(not REAL_UCC_LT_HTML.exists(), reason="Real LT HTML not present")
def test_lt_article_5_all_have_terms(records_lt_art5: list[dict]) -> None:
    defs = [r for r in records_lt_art5 if r["record_type"] == "definition"]
    for rec in defs:
        assert rec["term"], f"Empty term at list_path={rec['source_ref']['list_path']}"
        assert "►" not in rec["term"], f"Corrigendum marker in term: {rec['term']}"
        assert "◄" not in rec["term"], f"Corrigendum marker in term: {rec['term']}"


@pytest.mark.skipif(not REAL_UCC_LT_HTML.exists(), reason="Real LT HTML not present")
def test_lt_article_5_layout_field_in_source_ref(records_lt_art5: list[dict]) -> None:
    defs = [r for r in records_lt_art5 if r["record_type"] == "definition"]
    for rec in defs:
        assert rec["source_ref"]["layout"] == "tablelayout"


# ---------------------------------------------------------------------------
# English real-file tests (cross-check against known-good divlayout)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not REAL_UCC_EN_HTML.exists(), reason="Real EN HTML not present")
def test_en_real_layout_is_divlayout() -> None:
    ext = EurLexExtractor(celex_id=CELEX, lang="en")
    soup = ext.parse_html(REAL_UCC_EN_HTML)
    assert detect_layout(soup) == "divlayout"


@pytest.mark.skipif(not REAL_UCC_EN_HTML.exists(), reason="Real EN HTML not present")
def test_en_article_5_extracts_41_definitions() -> None:
    ext = EurLexExtractor(celex_id=CELEX, lang="en")
    soup = ext.parse_html(REAL_UCC_EN_HTML)
    records = ext.extract(soup, article_filter="5")
    defs = [r for r in records if r["record_type"] == "definition"]
    assert len(defs) == 41
