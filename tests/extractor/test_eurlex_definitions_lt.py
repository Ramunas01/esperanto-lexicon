"""Smoke tests for EUR-Lex tablelayout extraction (Lithuanian HTML)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))
from extractor.extract_eurlex_definitions import (
    EurLexExtractor,
    detect_layout,
)

FIXTURE = Path(__file__).parent.parent / "fixtures" / "eurlex" / "ucc_lt_article_5.html"
CELEX = "02013R0952-20221212"


@pytest.fixture(scope="module")
def ext() -> EurLexExtractor:
    return EurLexExtractor(celex_id=CELEX, lang="lt")


@pytest.fixture(scope="module")
def soup(ext: EurLexExtractor):
    return ext.parse_html(FIXTURE)


@pytest.fixture(scope="module")
def all_records(ext: EurLexExtractor, soup) -> list[dict]:
    return ext.extract(soup)


@pytest.fixture(scope="module")
def art5_defs(all_records: list[dict]) -> list[dict]:
    return [
        r for r in all_records
        if r["record_type"] == "definition"
        and r["context"].get("article_number") == "5"
    ]


def test_lt_layout_is_tablelayout(soup) -> None:
    """detect_layout must return 'tablelayout' for the LT fixture."""
    assert detect_layout(soup) == "tablelayout"


def test_lt_art5_yields_5_definitions(art5_defs: list[dict]) -> None:
    assert len(art5_defs) == 5


def test_lt_shape_a_term_and_definition(art5_defs: list[dict]) -> None:
    """Shape A: term extracted from text before en-dash; definition after."""
    item1 = next(r for r in art5_defs if r["source_ref"]["list_path"] == "1")
    assert item1["term"] == "muitinė"
    assert item1["definition"].startswith("valstybių narių")


def test_lt_shape_b_sub_items(art5_defs: list[dict]) -> None:
    """Shape B (p.normal + grid sub-items): 5 sub-items collected for item 2."""
    item2 = next(r for r in art5_defs if r["source_ref"]["list_path"] == "2")
    assert item2["term"] == "muitų teisės aktai"
    assert len(item2["sub_items"]) == 5
    sub_e = next((s for s in item2["sub_items"] if s["marker"] == "e"), None)
    assert sub_e is not None
    assert sub_e["amendment"]["marker"] == "M4"


def test_lt_shape_a_item3(art5_defs: list[dict]) -> None:
    """Item 3 is Shape A: term and definition split on en-dash."""
    item3 = next(r for r in art5_defs if r["source_ref"]["list_path"] == "3")
    assert item3["term"] == "muitinis tikrinimas"
    assert "►" not in item3["term"]
    assert "◄" not in item3["term"]


def test_lt_amendment_cursor_from_modref(art5_defs: list[dict]) -> None:
    """p.modref inside definition cell updates amendment cursor for subsequent sub-items."""
    item2 = next(r for r in art5_defs if r["source_ref"]["list_path"] == "2")
    sub_e = next((s for s in item2["sub_items"] if s["marker"] == "e"), None)
    assert sub_e is not None, "sub-item (e) must be collected"
    assert sub_e["amendment"]["marker"] == "M4"
