"""Tests for src/ingestion/ingest_eurlex.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Make sure the project src is importable
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ingestion.ingest_eurlex import _combine_jsonl, _count_records


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_jsonl(path: Path, records: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _make_def(lang: str = "en", approved: bool | None = None) -> dict:
    rec: dict = {
        "record_type": "definition",
        "lang": lang,
        "term": "customs authorities",
        "definition": "the customs administrations of the Member States",
        "source_ref": {"celex_id": "02013R0952-20221212", "list_path": "1"},
        "context": {"article_number": "5"},
    }
    if approved is not None:
        rec["approved"] = approved
    return rec


# ---------------------------------------------------------------------------
# _count_records
# ---------------------------------------------------------------------------


class TestCountRecords:
    def test_empty_file(self, tmp_path: Path) -> None:
        p = tmp_path / "empty.jsonl"
        p.write_text("", encoding="utf-8")
        total, approved = _count_records(p)
        assert total == 0
        assert approved == 0

    def test_missing_file(self, tmp_path: Path) -> None:
        total, approved = _count_records(tmp_path / "missing.jsonl")
        assert total == 0
        assert approved == 0

    def test_counts_only_definition_records(self, tmp_path: Path) -> None:
        records = [
            _make_def("en"),
            {"record_type": "article_metadata", "article_number": "5"},
            {"record_type": "footnote", "text": "See Art.3"},
            _make_def("lt"),
        ]
        p = tmp_path / "mixed.jsonl"
        _write_jsonl(p, records)
        total, approved = _count_records(p)
        assert total == 2
        assert approved == 0

    def test_approved_count(self, tmp_path: Path) -> None:
        records = [
            _make_def("en", approved=True),
            _make_def("lt", approved=True),
            _make_def("en", approved=False),
            _make_def("lt"),
        ]
        p = tmp_path / "some_approved.jsonl"
        _write_jsonl(p, records)
        total, approved = _count_records(p)
        assert total == 4
        assert approved == 2

    def test_blank_lines_skipped(self, tmp_path: Path) -> None:
        p = tmp_path / "blanks.jsonl"
        lines = [
            json.dumps(_make_def("en", approved=True)),
            "",
            "   ",
            json.dumps(_make_def("lt", approved=True)),
        ]
        p.write_text("\n".join(lines), encoding="utf-8")
        total, approved = _count_records(p)
        assert total == 2
        assert approved == 2


# ---------------------------------------------------------------------------
# _combine_jsonl
# ---------------------------------------------------------------------------


class TestCombineJsonl:
    def test_combines_two_files(self, tmp_path: Path) -> None:
        src1 = tmp_path / "en.jsonl"
        src2 = tmp_path / "lt.jsonl"
        _write_jsonl(src1, [_make_def("en")])
        _write_jsonl(src2, [_make_def("lt")])
        dest = tmp_path / "combined.jsonl"
        _combine_jsonl([src1, src2], dest)
        lines = [ln for ln in dest.read_text(encoding="utf-8").splitlines() if ln.strip()]
        assert len(lines) == 2
        langs = {json.loads(ln)["lang"] for ln in lines}
        assert langs == {"en", "lt"}

    def test_missing_source_skipped(self, tmp_path: Path) -> None:
        src1 = tmp_path / "en.jsonl"
        _write_jsonl(src1, [_make_def("en")])
        missing = tmp_path / "nonexistent.jsonl"
        dest = tmp_path / "combined.jsonl"
        _combine_jsonl([src1, missing], dest)
        lines = [ln for ln in dest.read_text(encoding="utf-8").splitlines() if ln.strip()]
        assert len(lines) == 1

    def test_combined_record_count_matches_phase1_output(self, tmp_path: Path) -> None:
        """Phase 1 combined JSONL contains exactly EN + LT records."""
        en_records = [_make_def("en", approved=None) for _ in range(3)]
        lt_records = [_make_def("lt", approved=None) for _ in range(3)]
        src_en = tmp_path / "dom_definitions_en.jsonl"
        src_lt = tmp_path / "dom_definitions_lt.jsonl"
        _write_jsonl(src_en, en_records)
        _write_jsonl(src_lt, lt_records)

        combined = tmp_path / "dom_definitions_combined.jsonl"
        _combine_jsonl([src_en, src_lt], combined)

        total, _ = _count_records(combined)
        assert total == 6

    def test_blank_lines_not_written_to_dest(self, tmp_path: Path) -> None:
        src = tmp_path / "src.jsonl"
        src.write_text(
            json.dumps(_make_def("en")) + "\n\n   \n" + json.dumps(_make_def("lt")) + "\n",
            encoding="utf-8",
        )
        dest = tmp_path / "dest.jsonl"
        _combine_jsonl([src], dest)
        lines = dest.read_text(encoding="utf-8").splitlines()
        assert all(ln.strip() for ln in lines)

    def test_no_approved_records_returns_zero_approved(self, tmp_path: Path) -> None:
        """Phase 2 should fail gracefully when no records are approved."""
        records = [_make_def("en", approved=False), _make_def("lt", approved=False)]
        p = tmp_path / "combined.jsonl"
        _write_jsonl(p, records)
        total, approved = _count_records(p)
        assert total == 2
        assert approved == 0
