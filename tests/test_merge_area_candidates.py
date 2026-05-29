"""Tests for src/extractor/merge_area_candidates.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from extractor.merge_area_candidates import (
    _parse_area_pair,
    merge,
    run,
)


def _write_jsonl(path: Path, records: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _cand(
    phrase: str,
    doc_count: int,
    frequency: int,
    source_file: str,
    pos_pattern: str = "ADJ NOUN",
    sample_context: str = "",
) -> dict:
    return {
        "phrase": phrase,
        "phrase_normalized": phrase,
        "phrase_inflected": None,
        "lang": "en",
        "pos_pattern": pos_pattern,
        "frequency": frequency,
        "doc_count": doc_count,
        "source_file": source_file,
        "sample_context": sample_context,
    }


# ---------------------------------------------------------------------------
# _parse_area_pair
# ---------------------------------------------------------------------------


def test_parse_area_pair_basic() -> None:
    area, path = _parse_area_pair("origin:data/domain_db/candidates_origin.jsonl")
    assert area == "origin"
    assert path == Path("data/domain_db/candidates_origin.jsonl")


def test_parse_area_pair_missing_colon() -> None:
    import argparse

    with pytest.raises(argparse.ArgumentTypeError):
        _parse_area_pair("origin")


# ---------------------------------------------------------------------------
# merge
# ---------------------------------------------------------------------------


def test_merge_single_area(tmp_path: Path) -> None:
    f = tmp_path / "origin.jsonl"
    _write_jsonl(f, [_cand("preferential origin", 40, 210, "mine-A5-origin.txt")])
    merged = merge([("origin", f)], [])
    assert len(merged) == 1
    rec = merged[0]
    assert rec["phrase_normalized"] == "preferential origin"
    assert rec["area_signature"] == "0000F00"
    assert rec["area_specificity"] == 1.0
    assert rec["total_doc_count"] == 40
    assert rec["total_frequency"] == 210
    assert rec["attestation"] == [
        {
            "area": "origin",
            "doc_count": 40,
            "frequency": 210,
            "source_file": "mine-A5-origin.txt",
        }
    ]


def test_merge_phrase_across_areas(tmp_path: Path) -> None:
    f_origin = tmp_path / "origin.jsonl"
    f_law = tmp_path / "law.jsonl"
    _write_jsonl(
        f_origin, [_cand("preferential origin", 40, 210, "mine-A5-origin.txt")]
    )
    _write_jsonl(f_law, [_cand("preferential origin", 20, 28, "mine-A1-law.txt")])
    merged = merge([("origin", f_origin), ("law", f_law)], [])
    assert len(merged) == 1
    rec = merged[0]
    # origin 40 dominant, law 20 → law weight 0.5 → digit 8
    assert rec["area_signature"] == "8000F00"
    assert rec["total_doc_count"] == 60
    assert {r["area"] for r in rec["attestation"]} == {"origin", "law"}
    # specificity = 40 / 60
    assert abs(rec["area_specificity"] - 40 / 60) < 1e-3


def test_cross_cutting_excluded_from_signature(tmp_path: Path) -> None:
    f_origin = tmp_path / "origin.jsonl"
    f_comp = tmp_path / "compliance.jsonl"
    _write_jsonl(f_origin, [_cand("preferential origin", 40, 210, "mine-A5-origin.txt")])
    _write_jsonl(
        f_comp, [_cand("preferential origin", 100, 500, "mine-compliance.txt")]
    )
    merged = merge([("origin", f_origin)], [("cross_cutting", f_comp)])
    rec = merged[0]
    # cross_cutting larger but excluded → still pure origin
    assert rec["area_signature"] == "0000F00"
    assert rec["area_specificity"] == 1.0
    # total counts include cross_cutting
    assert rec["total_doc_count"] == 140
    assert rec["total_frequency"] == 710
    areas = {r["area"] for r in rec["attestation"]}
    assert areas == {"origin", "cross_cutting"}


def test_cross_cutting_only_phrase(tmp_path: Path) -> None:
    f_comp = tmp_path / "compliance.jsonl"
    _write_jsonl(f_comp, [_cand("due diligence", 30, 90, "mine-compliance.txt")])
    merged = merge([], [("cross_cutting", f_comp)])
    rec = merged[0]
    assert rec["area_signature"] == "0000000"
    assert rec["area_specificity"] == 0.0


def test_pos_pattern_inconsistency_flagged(tmp_path: Path) -> None:
    f1 = tmp_path / "a.jsonl"
    f2 = tmp_path / "b.jsonl"
    _write_jsonl(f1, [_cand("customs declaration", 50, 100, "mine-A1-law.txt", "NOUN NOUN")])
    _write_jsonl(
        f2, [_cand("customs declaration", 40, 80, "mine-A5-origin.txt", "PROPN NOUN")]
    )
    merged = merge([("law", f1), ("origin", f2)], [])
    rec = merged[0]
    assert rec.get("pos_pattern_inconsistent") is True
    # both appear once → most_common picks the first inserted (law / NOUN NOUN)
    assert rec["pos_pattern"] in {"NOUN NOUN", "PROPN NOUN"}


def test_pos_pattern_consistent_no_flag(tmp_path: Path) -> None:
    f1 = tmp_path / "a.jsonl"
    _write_jsonl(f1, [_cand("preferential origin", 40, 210, "mine-A5-origin.txt")])
    merged = merge([("origin", f1)], [])
    assert "pos_pattern_inconsistent" not in merged[0]
    assert merged[0]["pos_pattern"] == "ADJ NOUN"


def test_sample_context_longest_kept(tmp_path: Path) -> None:
    short_ctx = "short"
    long_ctx = "a much longer and more informative sample context sentence here"
    f1 = tmp_path / "a.jsonl"
    f2 = tmp_path / "b.jsonl"
    _write_jsonl(
        f1, [_cand("x phrase", 5, 5, "mine-A1-law.txt", sample_context=short_ctx)]
    )
    _write_jsonl(
        f2, [_cand("x phrase", 5, 5, "mine-A5-origin.txt", sample_context=long_ctx)]
    )
    merged = merge([("law", f1), ("origin", f2)], [])
    assert merged[0]["sample_context"] == long_ctx


def test_sample_context_capped_at_200(tmp_path: Path) -> None:
    long_ctx = "z" * 500
    f1 = tmp_path / "a.jsonl"
    _write_jsonl(f1, [_cand("x phrase", 5, 5, "mine-A1-law.txt", sample_context=long_ctx)])
    merged = merge([("law", f1)], [])
    assert len(merged[0]["sample_context"]) == 200


def test_output_sorted_by_specificity_then_doc_count(tmp_path: Path) -> None:
    f_origin = tmp_path / "origin.jsonl"
    f_law = tmp_path / "law.jsonl"
    # 'pure origin' only in origin (spec 1.0); 'general' in both (spec < 1.0)
    _write_jsonl(
        f_origin,
        [
            _cand("pure origin term", 10, 20, "mine-A5-origin.txt"),
            _cand("general term", 30, 60, "mine-A5-origin.txt"),
        ],
    )
    _write_jsonl(f_law, [_cand("general term", 30, 60, "mine-A1-law.txt")])
    merged = merge([("origin", f_origin), ("law", f_law)], [])
    assert merged[0]["phrase_normalized"] == "pure origin term"  # spec 1.0 first
    assert merged[1]["phrase_normalized"] == "general term"  # spec 0.5


def test_same_area_multiple_files_summed(tmp_path: Path) -> None:
    f1 = tmp_path / "a.jsonl"
    f2 = tmp_path / "b.jsonl"
    # Two files both mapped to origin → doc_counts add for signature, but
    # stored as separate attestation rows (distinct source_file).
    _write_jsonl(f1, [_cand("x", 20, 40, "fileA.txt")])
    _write_jsonl(f2, [_cand("x", 20, 40, "fileB.txt")])
    merged = merge([("origin", f1), ("origin", f2)], [])
    rec = merged[0]
    assert len(rec["attestation"]) == 2
    assert rec["total_doc_count"] == 40
    assert rec["area_signature"] == "0000F00"


def test_run_writes_output_and_returns(tmp_path: Path) -> None:
    f_origin = tmp_path / "origin.jsonl"
    _write_jsonl(f_origin, [_cand("preferential origin", 40, 210, "mine-A5-origin.txt")])
    out = tmp_path / "merged.jsonl"
    merged = run([("origin", f_origin)], [], out)
    assert out.exists()
    lines = out.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["area_signature"] == "0000F00"
    assert merged[0]["phrase_normalized"] == "preferential origin"
