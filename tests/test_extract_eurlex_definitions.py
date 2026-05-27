"""Tests for extract_eurlex_definitions.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from extractor.extract_eurlex_definitions import (
    NUMBERED_ITEM_PATTERN,
    EurLexExtractor,
    _extract_article_number_from_text,
    _record_key,
    detect_layout,
    is_eurlex_definition,
    map_eurlex_to_writer_fields,
    write_records,
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
# write_records / --append
# ---------------------------------------------------------------------------


def test_write_records_overwrite(tmp_path: Path, art5_defs: list[dict]) -> None:
    out = tmp_path / "out.jsonl"
    # Write once, then overwrite — result should contain only second batch
    write_records(art5_defs[:3], out)
    write_records(art5_defs[3:6], out)  # overwrite
    lines = [l for l in out.read_text().splitlines() if l.strip()]
    assert len(lines) == 3


def test_write_records_append_adds_new(tmp_path: Path, art5_defs: list[dict]) -> None:
    out = tmp_path / "out.jsonl"
    written1 = write_records(art5_defs[:3], out)
    written2 = write_records(art5_defs[3:6], out, append=True)
    lines = [l for l in out.read_text().splitlines() if l.strip()]
    assert written1 == 3
    assert written2 == 3
    assert len(lines) == 6


def test_write_records_append_skips_duplicates(tmp_path: Path, art5_defs: list[dict]) -> None:
    out = tmp_path / "out.jsonl"
    write_records(art5_defs[:5], out)
    # Re-append the same 5 records — all should be skipped
    written = write_records(art5_defs[:5], out, append=True)
    lines = [l for l in out.read_text().splitlines() if l.strip()]
    assert written == 0
    assert len(lines) == 5


def test_write_records_append_partial_overlap(tmp_path: Path, art5_defs: list[dict]) -> None:
    out = tmp_path / "out.jsonl"
    write_records(art5_defs[:4], out)
    # Append 2 already-present + 2 new
    written = write_records(art5_defs[2:6], out, append=True)
    lines = [l for l in out.read_text().splitlines() if l.strip()]
    assert written == 2
    assert len(lines) == 6


def test_write_records_append_to_nonexistent_file(tmp_path: Path, art5_defs: list[dict]) -> None:
    out = tmp_path / "new.jsonl"
    written = write_records(art5_defs[:2], out, append=True)
    assert written == 2
    assert out.exists()


def test_record_key_definition(art5_defs: list[dict]) -> None:
    rec = art5_defs[0]
    key = _record_key(rec)
    assert key == (
        CELEX,
        rec["source_ref"]["structural_path"],
        rec["source_ref"]["list_path"],
        "en",
    )


def test_record_key_article_metadata(all_records: list[dict]) -> None:
    meta = next(r for r in all_records if r["record_type"] == "article_metadata")
    key = _record_key(meta)
    assert key[0] == CELEX
    assert key[2] == "article_metadata"
    assert key[3] == "en"


def test_record_key_footnote(all_records: list[dict]) -> None:
    fn = next(r for r in all_records if r["record_type"] == "footnote")
    key = _record_key(fn)
    assert key[0] == CELEX
    assert key[2] == "footnote"
    assert key[3] == "en"


def test_write_records_mixed_types_dedup(tmp_path: Path, all_records: list[dict]) -> None:
    """Append with all three record types; re-appending the same set writes nothing."""
    out = tmp_path / "mixed.jsonl"
    written1 = write_records(all_records, out)
    written2 = write_records(all_records, out, append=True)
    assert written1 == len(all_records)
    assert written2 == 0


# ---------------------------------------------------------------------------
# Variant B — Lithuanian flat structure
# ---------------------------------------------------------------------------

FIXTURE_LT_HTML = Path(__file__).parent / "fixtures" / "eurlex" / "ucc_lt_article5_fragment.html"


@pytest.fixture(scope="module")
def extractor_lt() -> EurLexExtractor:
    return EurLexExtractor(celex_id=CELEX, lang="lt")


@pytest.fixture(scope="module")
def soup_lt(extractor_lt: EurLexExtractor):
    return extractor_lt.parse_html(FIXTURE_LT_HTML)


@pytest.fixture(scope="module")
def all_records_lt(extractor_lt: EurLexExtractor, soup_lt) -> list[dict]:
    return extractor_lt.extract(soup_lt)


@pytest.fixture(scope="module")
def art5_defs_lt(all_records_lt: list[dict]) -> list[dict]:
    return [
        r for r in all_records_lt
        if r["record_type"] == "definition"
        and r["context"].get("article_number") == "5"
    ]


def test_variant_b_detected_when_no_eli_subdivision(soup_lt) -> None:
    """LT fixture has no eli-subdivision divs — Variant B path is taken."""
    doc_div = soup_lt.find("div", id="docHtml")
    assert doc_div is not None
    assert len(doc_div.find_all("div", class_="eli-subdivision")) == 0


def test_variant_a_detected_when_eli_subdivision_present(soup) -> None:
    """EN fixture has eli-subdivision divs — Variant A path is taken."""
    doc_div = soup.find("div", id="docHtml")
    assert len(doc_div.find_all("div", class_="eli-subdivision")) > 0


def test_extract_article_number_nominative() -> None:
    assert _extract_article_number_from_text("5 straipsnis") == "5"


def test_extract_article_number_genitive() -> None:
    assert _extract_article_number_from_text("6 straipsnio") == "6"


def test_extract_article_number_english() -> None:
    assert _extract_article_number_from_text("Article 5") == "5"


def test_extract_article_number_bare_digit() -> None:
    assert _extract_article_number_from_text("5") == "5"


def test_variant_b_art5_yields_41_definitions(art5_defs_lt: list[dict]) -> None:
    assert len(art5_defs_lt) == 41


def test_variant_b_structural_path_is_art_5(art5_defs_lt: list[dict]) -> None:
    assert all(r["source_ref"]["structural_path"] == "art_5" for r in art5_defs_lt)


def test_variant_b_list_paths_match_variant_a(
    art5_defs: list[dict], art5_defs_lt: list[dict]
) -> None:
    """Both variants emit the same list_path values for Article 5."""
    paths_en = sorted(r["source_ref"]["list_path"] for r in art5_defs)
    paths_lt = sorted(r["source_ref"]["list_path"] for r in art5_defs_lt)
    assert paths_en == paths_lt


def test_variant_b_structural_path_ends_with_art_5(art5_defs: list[dict]) -> None:
    """Variant A structural path contains 'art_5'; Variant B IS 'art_5'."""
    assert all("art_5" in r["source_ref"]["structural_path"] for r in art5_defs)


def test_variant_b_context_has_title_and_chapter(art5_defs_lt: list[dict]) -> None:
    ctx = art5_defs_lt[0]["context"]
    assert ctx["title_label"] == "I ANTRAŠTINĖ DALIS"
    assert ctx["chapter_label"] == "1 SKYRIUS"
    assert ctx["title_rubric"] == "BENDROSIOS NUOSTATOS"
    assert ctx["chapter_rubric"] == "Taikymo sritis, misija ir apibrėžtys"


def test_variant_b_article_rubric(art5_defs_lt: list[dict]) -> None:
    assert art5_defs_lt[0]["context"]["article_rubric"] == "Apibrėžtys"


def test_variant_b_cursor_resets_at_article_boundary(all_records_lt: list[dict]) -> None:
    """Art 5 item 1 has marker B; art 6 item 1 has marker M4 from its own modref."""
    art5_item1 = next(
        r for r in all_records_lt
        if r["record_type"] == "definition"
        and r["context"].get("article_number") == "5"
        and r["source_ref"]["list_path"] == "1"
    )
    assert art5_item1["amendment"]["marker"] == "B"

    art6_defs = [
        r for r in all_records_lt
        if r["record_type"] == "definition"
        and r["context"].get("article_number") == "6"
    ]
    assert len(art6_defs) >= 1
    assert art6_defs[0]["amendment"]["marker"] == "M4"


def test_variant_b_article_filter(soup_lt, extractor_lt: EurLexExtractor) -> None:
    """--article 5 should return only art 5 definitions, not art 6."""
    ext = EurLexExtractor(celex_id=CELEX, lang="lt")
    records = ext.extract(soup_lt, article_filter="5")
    defs = [r for r in records if r["record_type"] == "definition"]
    assert len(defs) == 41
    assert all(r["context"].get("article_number") == "5" for r in defs)


def test_variant_b_genitive_article_number(all_records_lt: list[dict]) -> None:
    """Article 6 uses 'straipsnio' (genitive) in the fixture — must still parse as '6'."""
    art6_defs = [
        r for r in all_records_lt
        if r["record_type"] == "definition"
        and r["context"].get("article_number") == "6"
    ]
    assert len(art6_defs) >= 1


def test_variant_b_footnotes_collected(all_records_lt: list[dict]) -> None:
    footnotes = [r for r in all_records_lt if r["record_type"] == "footnote"]
    assert len(footnotes) >= 1


# ---------------------------------------------------------------------------
# divlayout_numbered variant — CBAM LT Article 3 fixture
# ---------------------------------------------------------------------------

CBAM_LT_FIXTURE = (
    Path(__file__).parent / "fixtures" / "eurlex" / "cbam_lt_article3_fragment.html"
)
CBAM_CELEX = "02023R0956-20251020"


@pytest.fixture(scope="module")
def extractor_cbam_lt() -> EurLexExtractor:
    return EurLexExtractor(celex_id=CBAM_CELEX, lang="lt")


@pytest.fixture(scope="module")
def soup_cbam_lt(extractor_cbam_lt: EurLexExtractor):
    return extractor_cbam_lt.parse_html(CBAM_LT_FIXTURE)


@pytest.fixture(scope="module")
def cbam_lt_defs(extractor_cbam_lt: EurLexExtractor, soup_cbam_lt) -> list[dict]:
    records = extractor_cbam_lt.extract(soup_cbam_lt, article_filter="3")
    return [r for r in records if r["record_type"] == "definition"]


class TestDivlayoutNumbered:
    """Numbered-item divlayout variant (CBAM LT and similar non-EN translations)."""

    def test_layout_detected_as_divlayout(self, soup_cbam_lt) -> None:
        assert detect_layout(soup_cbam_lt) == "divlayout"

    def test_numbered_item_pattern_matches_first_item(self, soup_cbam_lt) -> None:
        """NUMBERED_ITEM_PATTERN matches '1) ' style but not '(1) ' style."""
        assert NUMBERED_ITEM_PATTERN.match("1) prekės – I priede")
        assert not NUMBERED_ITEM_PATTERN.match("(1) 'goods' means")

    def test_article_uses_numbered_items_true_for_cbam_lt(
        self, extractor_cbam_lt: EurLexExtractor, soup_cbam_lt
    ) -> None:
        from bs4 import BeautifulSoup
        art3 = soup_cbam_lt.find(id="art_3")
        assert extractor_cbam_lt._article_uses_numbered_items(art3) is True

    def test_fixture_yields_four_definitions(self, cbam_lt_defs: list[dict]) -> None:
        """Fixture contains items 1, 2, 19, 34 — four definitions expected."""
        assert len(cbam_lt_defs) == 4

    def test_first_item_term_and_definition(self, cbam_lt_defs: list[dict]) -> None:
        """Item 1: 'prekės – I priede išvardytos prekės;' → correct split."""
        rec = cbam_lt_defs[0]
        assert rec["term"] == "prekės"
        assert rec["definition"] == "I priede išvardytos prekės"

    def test_first_item_list_path_is_one(self, cbam_lt_defs: list[dict]) -> None:
        assert cbam_lt_defs[0]["source_ref"]["list_path"] == "1"

    def test_second_item_list_path_is_two(self, cbam_lt_defs: list[dict]) -> None:
        assert cbam_lt_defs[1]["source_ref"]["list_path"] == "2"

    def test_second_item_term_split_on_endash(self, cbam_lt_defs: list[dict]) -> None:
        """Item 2 has en-dash in definition text — term must be left of dash only."""
        rec = cbam_lt_defs[1]
        assert rec["term"] == "šiltnamio efektą sukeliančios dujos"
        assert "–" not in rec["term"]

    def test_chapeau_item_list_path(self, cbam_lt_defs: list[dict]) -> None:
        """Item 19 is a chapeau (ends with colon); list_path must be '19'."""
        rec = cbam_lt_defs[2]
        assert rec["source_ref"]["list_path"] == "19"

    def test_chapeau_item_term_no_colon(self, cbam_lt_defs: list[dict]) -> None:
        rec = cbam_lt_defs[2]
        assert rec["term"] == "valstybėje narėje įsisteigęs asmuo"
        assert not rec["term"].endswith(":")

    def test_chapeau_item_has_sub_items(self, cbam_lt_defs: list[dict]) -> None:
        rec = cbam_lt_defs[2]
        assert len(rec["sub_items"]) == 2
        assert rec["sub_items"][0]["marker"] == "a"
        assert rec["sub_items"][1]["marker"] == "b"

    def test_chapeau_item_definition_empty(self, cbam_lt_defs: list[dict]) -> None:
        """Chapeau items have an empty definition string; content is in sub_items."""
        assert cbam_lt_defs[2]["definition"] == ""

    def test_last_item_list_path(self, cbam_lt_defs: list[dict]) -> None:
        assert cbam_lt_defs[3]["source_ref"]["list_path"] == "34"

    def test_article_rubric_detected(self, cbam_lt_defs: list[dict]) -> None:
        """Article rubric 'Terminų apibrėžtys' must be captured in context."""
        assert cbam_lt_defs[0]["context"]["article_rubric"] == "Terminų apibrėžtys"

    def test_article_number_detected(self, cbam_lt_defs: list[dict]) -> None:
        assert cbam_lt_defs[0]["context"]["article_number"] == "3"

    def test_amendment_markers_detected(
        self, extractor_cbam_lt: EurLexExtractor, soup_cbam_lt
    ) -> None:
        """Amendment markers (modref) between items 2 and 19 must be consumed."""
        records = extractor_cbam_lt.extract(soup_cbam_lt, article_filter="3")
        assert len(getattr(extractor_cbam_lt, "_amendments_detected", set())) >= 1

    def test_layout_string_in_source_ref(self, cbam_lt_defs: list[dict]) -> None:
        assert cbam_lt_defs[0]["source_ref"]["layout"] == "divlayout"


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
