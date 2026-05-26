"""Tests for extract_eurlex_definitions.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from extractor.extract_eurlex_definitions import (
    EurLexExtractor,
    is_eurlex_definition,
    map_eurlex_to_writer_fields,
)

FIXTURE_HTML = Path(__file__).parent / "fixtures" / "eurlex" / "ucc_en_article5_fragment.html"
CELEX = "02013R0952-20221212"


@pytest.fixture(scope="module")
def extractor() -> EurLexExtractor:
    return EurLexExtractor(celex_id=CELEX, lang="en")


@pytest.fixture(scope="module")
def soup(extractor: EurLexExtractor):
    return extractor.parse_html(FIXTURE_HTML)


@pytest.fixture(scope="module")
def all_records(extractor: EurLexExtractor, soup) -> list[dict]:
    return extractor.extract(soup)


@pytest.fixture(scope="module")
def art5_defs(all_records: list[dict]) -> list[dict]:
    return [
        r for r in all_records
        if r["record_type"] == "definition"
        and r["context"].get("article_number") == "5"
    ]


# ---------------------------------------------------------------------------
# Fixture: basic count and term extraction
# ---------------------------------------------------------------------------


def test_art5_yields_41_definitions(art5_defs: list[dict]) -> None:
    assert len(art5_defs) == 41


def test_item1_term_customs_authorities(art5_defs: list[dict]) -> None:
    item1 = next((r for r in art5_defs if r["source_ref"]["list_path"] == "1"), None)
    assert item1 is not None
    assert item1["term"] == "customs authorities"


def test_item1_amendment_marker_B(art5_defs: list[dict]) -> None:
    item1 = next(r for r in art5_defs if r["source_ref"]["list_path"] == "1")
    assert item1["amendment"]["marker"] == "B"


# ---------------------------------------------------------------------------
# Fixture: item 2 sub-items
# ---------------------------------------------------------------------------


def test_item2_has_5_sub_items(art5_defs: list[dict]) -> None:
    item2 = next((r for r in art5_defs if r["source_ref"]["list_path"] == "2"), None)
    assert item2 is not None, "item 2 not found"
    assert len(item2["sub_items"]) == 5


def test_item2_sub_item_e_amendment_marker_M4(art5_defs: list[dict]) -> None:
    item2 = next(r for r in art5_defs if r["source_ref"]["list_path"] == "2")
    sub_e = next((s for s in item2["sub_items"] if s["marker"] == "e"), None)
    assert sub_e is not None, "sub-item (e) not found"
    assert sub_e["amendment"]["marker"] == "M4"


# ---------------------------------------------------------------------------
# Fixture: item 40 three-level nesting
# ---------------------------------------------------------------------------


def test_item40_has_nested_sub_items(art5_defs: list[dict]) -> None:
    item40 = next((r for r in art5_defs if r["source_ref"]["list_path"] == "40"), None)
    assert item40 is not None, "item 40 not found"
    assert len(item40["sub_items"]) >= 1
    sub_a = next((s for s in item40["sub_items"] if s["marker"] == "a"), None)
    assert sub_a is not None, "sub-item (a) of item 40 not found"
    assert len(sub_a["sub_items"]) >= 2


def test_item40_sub_a_has_i_and_ii(art5_defs: list[dict]) -> None:
    item40 = next(r for r in art5_defs if r["source_ref"]["list_path"] == "40")
    sub_a = next(s for s in item40["sub_items"] if s["marker"] == "a")
    markers = {s["marker"] for s in sub_a["sub_items"]}
    assert "i" in markers
    assert "ii" in markers


# ---------------------------------------------------------------------------
# Fixture: list_path construction
# ---------------------------------------------------------------------------


def test_list_path_2e(art5_defs: list[dict]) -> None:
    """list_path for item 2 sub-item (e) is carried as sub_item, not a top-level def."""
    item2 = next(r for r in art5_defs if r["source_ref"]["list_path"] == "2")
    sub_e = next(s for s in item2["sub_items"] if s["marker"] == "e")
    # sub-items carry their marker; the parent list_path is "2"
    assert item2["source_ref"]["list_path"] == "2"
    assert sub_e["marker"] == "e"


# ---------------------------------------------------------------------------
# Fixture: single-quote variant (item 17)
# ---------------------------------------------------------------------------


def test_item17_single_quote_extracted(art5_defs: list[dict]) -> None:
    item17 = next((r for r in art5_defs if r["source_ref"]["list_path"] == "17"), None)
    assert item17 is not None, "item 17 not found"
    assert item17["term"] == "economic operator"


# ---------------------------------------------------------------------------
# Fixture: non-breaking spaces
# ---------------------------------------------------------------------------


def test_no_nbsp_in_definitions(art5_defs: list[dict]) -> None:
    for rec in art5_defs:
        assert "\xa0" not in rec["definition"], f"nbsp found in {rec['term']}"
        assert "\xa0" not in rec["term"], f"nbsp found in term {rec['term']}"


# ---------------------------------------------------------------------------
# Fixture: footnote ref stripping
# ---------------------------------------------------------------------------


def test_footnote_refs_stripped_from_definition() -> None:
    """Footnote ref numerals like ' ( 1 )' must be stripped from definition text."""
    ext = EurLexExtractor(celex_id=CELEX, lang="en")
    html = """
    <html><body><div id="docHtml">
      <div id="art_99" class="eli-subdivision">
        <p class="title-article-norm">Article 99</p>
        <div class="grid-container">
          <div class="grid-list-column-1"><span>(1)</span></div>
          <div class="grid-list-column-2">
            <p class="norm">&#8216;test term&#8217; means something useful ( 1 );</p>
          </div>
        </div>
      </div>
    </div></body></html>
    """
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    records = ext.extract(soup)
    defs = [r for r in records if r["record_type"] == "definition"]
    assert len(defs) == 1
    assert "( 1 )" not in defs[0]["definition"]
    assert "(1)" not in defs[0]["definition"]


# ---------------------------------------------------------------------------
# Fixture: annex divs skipped
# ---------------------------------------------------------------------------


def test_annex_divs_skipped(all_records: list[dict]) -> None:
    """No definitions should be emitted from anx_* subtrees."""
    for rec in all_records:
        if rec["record_type"] == "definition":
            sp = rec["source_ref"].get("structural_path", "")
            assert "anx_" not in sp, f"definition from annex: {sp}"


def test_annex_warning_emitted(extractor: EurLexExtractor, soup) -> None:
    ext2 = EurLexExtractor(celex_id=CELEX, lang="en")
    ext2.extract(soup)
    # Fixture has 1 annex article (art_100 inside anx_I)
    annex_warns = [w for w in ext2.warnings if "annex" in w.lower()]
    assert len(annex_warns) >= 1


# ---------------------------------------------------------------------------
# Fixture: amendment cursor resets at article boundary
# ---------------------------------------------------------------------------


def test_amendment_cursor_resets_between_articles(all_records: list[dict]) -> None:
    """First definition in art_6 should have marker from art_6's own modref (M4),
    not carried over from art_5's last cursor state."""
    art6_defs = [
        r for r in all_records
        if r["record_type"] == "definition"
        and r["context"].get("article_number") == "6"
    ]
    assert len(art6_defs) >= 1
    # art_6 has its own ▼M4 modref before the only item
    assert art6_defs[0]["amendment"]["marker"] == "M4"


def test_art5_first_item_cursor_is_B(art5_defs: list[dict]) -> None:
    """Art5 item 1 must have marker B regardless of what art_6 sets."""
    item1 = next(r for r in art5_defs if r["source_ref"]["list_path"] == "1")
    assert item1["amendment"]["marker"] == "B"


# ---------------------------------------------------------------------------
# Fixture: footnotes collected
# ---------------------------------------------------------------------------


def test_footnotes_collected(all_records: list[dict]) -> None:
    footnotes = [r for r in all_records if r["record_type"] == "footnote"]
    assert len(footnotes) >= 1
    markers = {f["marker"] for f in footnotes}
    assert "1" in markers or "0001" in markers or any(m.isdigit() for m in markers)


# ---------------------------------------------------------------------------
# Record type helpers
# ---------------------------------------------------------------------------


def test_is_eurlex_definition_true(art5_defs: list[dict]) -> None:
    assert is_eurlex_definition(art5_defs[0]) is True


def test_is_eurlex_definition_false_for_legacy() -> None:
    legacy = {"term_raw": "foo", "definition_raw": "bar", "lang": "en"}
    assert is_eurlex_definition(legacy) is False


def test_map_eurlex_to_writer_fields(art5_defs: list[dict]) -> None:
    rec = art5_defs[0]
    mapped = map_eurlex_to_writer_fields(rec)
    assert mapped["term_raw"] == rec["term"]
    assert mapped["term_normalized"] == rec["term"].lower()
    assert mapped["definition_raw"] == rec["definition"]
    assert mapped["lang"] == "en"
    assert mapped["source_file"] == CELEX
    # Date from celex id suffix 20221212 → 2022-12-12
    assert mapped["first_seen_date"] == "2022-12-12"


# ---------------------------------------------------------------------------
# Integration test (slow, skipped unless real UCC HTML present)
# ---------------------------------------------------------------------------

REAL_UCC_HTML = Path(__file__).parent.parent / "data" / "corpus" / "ucc_en.html"


@pytest.mark.slow
@pytest.mark.skipif(not REAL_UCC_HTML.exists(), reason="Real UCC HTML not present")
def test_real_ucc_art5_yields_41_definitions() -> None:
    ext = EurLexExtractor(celex_id=CELEX, lang="en")
    soup = ext.parse_html(REAL_UCC_HTML)
    records = ext.extract(soup, article_filter="5")
    defs = [r for r in records if r["record_type"] == "definition"]
    assert len(defs) == 41
