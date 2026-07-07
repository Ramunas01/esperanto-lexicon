"""Unit tests for the D7 Wikidata probe pure logic.

Covers the query builder, SPARQL-JSON row parser, coverage-% computation,
P31->coarse-type mapper, and TSV writer. NONE of these tests hit the network:
the runner is exercised only through fixture JSON.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src" / "analyzer"))

from wikidata_probe import (  # noqa: E402
    COARSE_CELESTIAL,
    COARSE_PHYSICAL,
    COARSE_SETTLEMENT,
    COARSE_UNMAPPED,
    SALIENCE_DEPTHS,
    SETS,
    Row,
    SetDef,
    alias_coverage,
    build_anchor_query,
    build_query,
    coarse_type_for,
    coverage_at_depths,
    parse_rows,
    rows_to_tsv_lines,
    set_by_key,
    write_tsv,
)

_FIX_DIR = Path(__file__).resolve().parent / "fixtures" / "wikidata"
FIXTURE = _FIX_DIR / "sample_planets.json"  # SPARQL results-object shape
FIXTURE_GUI = _FIX_DIR / "sample_gui_download.json"  # GUI "Download -> JSON" array


@pytest.fixture
def planets_json() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture
def planets_gui_json() -> list:
    return json.loads(FIXTURE_GUI.read_text(encoding="utf-8"))


@pytest.fixture
def planets_rows(planets_json) -> list[Row]:
    return parse_rows(planets_json)


# ---------------------------------------------------------------------------
# coarse_type_for
# ---------------------------------------------------------------------------


def test_coarse_type_single_known():
    assert coarse_type_for(["Q515"]) == COARSE_SETTLEMENT
    assert coarse_type_for(["Q4022"]) == COARSE_PHYSICAL
    assert coarse_type_for(["Q634"]) == COARSE_CELESTIAL


def test_coarse_type_unmapped():
    assert coarse_type_for(["Q999999"]) == COARSE_UNMAPPED
    assert coarse_type_for([]) == COARSE_UNMAPPED


def test_coarse_type_multi_same_bucket_collapses():
    # Earth's two P31s are both celestial -> single bucket.
    assert coarse_type_for(["Q3504248", "Q128207"]) == COARSE_CELESTIAL


def test_coarse_type_mixed_buckets_marked():
    # a city that is also a country -> genuine cross-type entity.
    result = coarse_type_for(["Q515", "Q6256"])
    assert result.startswith("mixed:")
    assert "settlement" in result and "institutional" in result


def test_coarse_type_unknown_ignored_when_known_present():
    assert coarse_type_for(["Q999999", "Q515"]) == COARSE_SETTLEMENT


# ---------------------------------------------------------------------------
# build_query
# ---------------------------------------------------------------------------


def test_build_query_p31_uses_subquery_and_limit():
    q = build_query(set_by_key("cities"))
    assert "wdt:P31 wd:Q515" in q
    assert "LIMIT 300" in q
    assert "ORDER BY DESC(?sitelinks)" in q
    assert 'FILTER(LANG(?eo)="eo")' in q  # eo is measured, must be present


def test_build_query_values_shape_for_curated_set():
    q = build_query(set_by_key("planets"))
    assert "VALUES ?item {" in q
    assert "wd:Q2" in q  # Earth in the curated list
    assert "wdt:P31 wd:" not in q  # curated sets do not class-filter


def test_build_query_always_optional_eo():
    for s in SETS:
        q = build_query(s)
        assert 'OPTIONAL { ?item rdfs:label ?eo' in q, s.key


def test_build_anchor_query_has_all_qids():
    q = build_anchor_query(["Q525", "Q515"])
    assert "wd:Q525" in q and "wd:Q515" in q


def test_setdef_rejects_both_p31_and_qids():
    with pytest.raises(ValueError):
        SetDef("bad", "bad", COARSE_CELESTIAL, 10, p31="Q1", qids=("Q2",))


def test_setdef_rejects_neither():
    with pytest.raises(ValueError):
        SetDef("bad", "bad", COARSE_CELESTIAL, 10)


# ---------------------------------------------------------------------------
# parse_rows
# ---------------------------------------------------------------------------


def test_parse_rows_count_and_qids(planets_rows):
    assert len(planets_rows) == 3
    assert {r.qid for r in planets_rows} == {"Q2", "Q111", "Q319"}


def test_parse_rows_sorted_by_sitelinks_desc(planets_rows):
    sl = [r.sitelinks for r in planets_rows]
    assert sl == sorted(sl, reverse=True)
    assert planets_rows[0].qid == "Q2"  # Earth, 295


def test_parse_rows_missing_eo_binding_is_empty(planets_rows):
    jupiter = next(r for r in planets_rows if r.qid == "Q319")
    assert jupiter.label_eo == ""
    assert jupiter.has_eo is False


def test_parse_rows_present_eo(planets_rows):
    earth = next(r for r in planets_rows if r.qid == "Q2")
    assert earth.label_eo == "Tero"
    assert earth.has_eo is True


def test_parse_rows_aliases_split_and_deduped(planets_rows):
    earth = next(r for r in planets_rows if r.qid == "Q2")
    assert earth.en_aliases == ("Blue Planet", "Terra", "Sol III")
    assert earth.eo_aliases == ("Tero (planedo)",)


def test_parse_rows_empty_alias_string_yields_empty_tuple(planets_rows):
    mars = next(r for r in planets_rows if r.qid == "Q111")
    assert mars.eo_aliases == ()


def test_parse_rows_types_stripped_to_qids(planets_rows):
    earth = next(r for r in planets_rows if r.qid == "Q2")
    assert earth.type_qids == ("Q3504248", "Q128207")
    assert earth.coarse_type_p31 == COARSE_CELESTIAL


def test_parse_rows_bad_sitelinks_defaults_zero():
    rows = parse_rows(
        {
            "results": {
                "bindings": [
                    {
                        "item": {"value": "http://www.wikidata.org/entity/Q1"},
                        "sitelinks": {"value": "not-a-number"},
                    }
                ]
            }
        }
    )
    assert rows[0].sitelinks == 0


def test_parse_rows_empty_result():
    assert parse_rows({"results": {"bindings": []}}) == []


# ---------------------------------------------------------------------------
# parse_rows -- GUI "Download -> JSON" simplified array format (manual pulls).
# The two on-disk shapes must yield identical Row objects.
# ---------------------------------------------------------------------------


def test_parse_rows_gui_array_shape(planets_gui_json):
    rows = parse_rows(planets_gui_json)
    assert {r.qid for r in rows} == {"Q2", "Q111", "Q319"}
    earth = next(r for r in rows if r.qid == "Q2")
    assert earth.label_en == "Earth"
    assert earth.label_eo == "Tero"
    assert earth.en_aliases == ("The Blue Planet", "Mother Earth", "World")


def test_parse_rows_gui_missing_eo_key_is_empty(planets_gui_json):
    # Jupiter has no "eo" key at all in the GUI array (absent OPTIONAL).
    rows = parse_rows(planets_gui_json)
    jupiter = next(r for r in rows if r.qid == "Q319")
    assert jupiter.label_eo == ""
    assert jupiter.has_eo is False


def test_parse_rows_both_formats_equivalent(planets_json, planets_gui_json):
    # Same three planets expressed in each format -> matching coverage + eo.
    sparql_rows = parse_rows(planets_json)
    gui_rows = parse_rows(planets_gui_json)
    sparql_eo = {r.qid: r.has_eo for r in sparql_rows}
    gui_eo = {r.qid: r.has_eo for r in gui_rows}
    assert sparql_eo == gui_eo  # Q2/Q111 have eo, Q319 does not, in both


def test_parse_rows_rejects_bad_type():
    with pytest.raises(ValueError):
        parse_rows("not a result")
    with pytest.raises(ValueError):
        parse_rows(42)


# ---------------------------------------------------------------------------
# coverage_at_depths
# ---------------------------------------------------------------------------


def test_coverage_full_set(planets_rows):
    # 3 rows, 2 with eo (Earth, Mars); Jupiter has none.
    cov = {c.depth: c for c in coverage_at_depths(planets_rows, [50])}
    assert cov[50].n == 3
    assert cov[50].n_with_eo == 2
    assert cov[50].pct == pytest.approx(66.6, abs=0.1)


def test_coverage_depth_smaller_than_set(planets_rows):
    # top-2 by sitelinks = Earth(295, eo) + Jupiter(280, no eo) -> 1/2.
    cov = {c.depth: c for c in coverage_at_depths(planets_rows, [2])}
    assert cov[2].n == 2
    assert cov[2].n_with_eo == 1
    assert cov[2].pct == 50.0


def test_coverage_depth_collapses_to_set_size(planets_rows):
    cov = {c.depth: c for c in coverage_at_depths(planets_rows, [1000])}
    assert cov[1000].n == 3  # honestly reports actual size, not 1000


def test_coverage_default_depths(planets_rows):
    depths = [c.depth for c in coverage_at_depths(planets_rows)]
    assert depths == list(SALIENCE_DEPTHS)


def test_coverage_empty_rows_zero_pct():
    cov = coverage_at_depths([], [50])
    assert cov[0].n == 0
    assert cov[0].pct == 0.0


# ---------------------------------------------------------------------------
# alias_coverage
# ---------------------------------------------------------------------------


def test_alias_coverage(planets_rows):
    en_pct, eo_pct = alias_coverage(planets_rows)
    # en aliases: Earth + Mars (2/3); eo aliases: Earth only (1/3).
    assert en_pct == pytest.approx(66.6, abs=0.1)
    assert eo_pct == pytest.approx(33.3, abs=0.1)


def test_alias_coverage_empty():
    assert alias_coverage([]) == (0.0, 0.0)


# ---------------------------------------------------------------------------
# TSV writer
# ---------------------------------------------------------------------------


def test_tsv_header_and_row_shape(planets_rows):
    lines = rows_to_tsv_lines((r, "celestial") for r in planets_rows)
    assert lines[0] == "qid\tlabel_en\tlabel_eo\tcoarse_type\tsitelinks\taliases"
    earth_line = next(ln for ln in lines if ln.startswith("Q2\t"))
    cols = earth_line.split("\t")
    assert cols == [
        "Q2",
        "Earth",
        "Tero",
        "celestial",
        "295",
        "en:Blue Planet;en:Terra;en:Sol III;eo:Tero (planedo)",
    ]


def test_tsv_missing_eo_leaves_empty_cell(planets_rows):
    lines = rows_to_tsv_lines((r, "celestial") for r in planets_rows)
    jupiter_line = next(ln for ln in lines if ln.startswith("Q319\t"))
    cols = jupiter_line.split("\t")
    assert cols[2] == ""  # empty label_eo cell


def test_tsv_escapes_tabs_and_newlines():
    row = Row(
        qid="Q1",
        label_en="a\tb\nc",
        label_eo="",
        sitelinks=1,
        type_qids=(),
        en_aliases=(),
        eo_aliases=(),
    )
    lines = rows_to_tsv_lines([(row, "celestial")])
    assert "\t" not in lines[1].split("\t")[1]  # tab scrubbed inside cell
    assert "\n" not in lines[1]


def test_write_tsv_roundtrip(tmp_path, planets_rows):
    out = tmp_path / "sample.tsv"
    write_tsv(((r, "celestial") for r in planets_rows), out)
    text = out.read_text(encoding="utf-8")
    assert text.startswith("qid\tlabel_en")
    assert text.endswith("\n")
    assert len(text.strip().splitlines()) == 4  # header + 3 rows


# ---------------------------------------------------------------------------
# registry sanity
# ---------------------------------------------------------------------------


def test_all_set_keys_unique():
    keys = [s.key for s in SETS]
    assert len(keys) == len(set(keys))


def test_set_by_key_raises_on_unknown():
    with pytest.raises(KeyError):
        set_by_key("nope")
