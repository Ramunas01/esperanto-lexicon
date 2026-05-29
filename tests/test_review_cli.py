"""Tests for review_cli.py helper functions."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from extractor.review_cli import _eurlex_def_lines, _handle_review_key


def _make_rec(definition: str, sub_items: list[dict] | None = None) -> dict:
    return {
        "record_type": "definition",
        "lang": "en",
        "term": "export",
        "definition": definition,
        "sub_items": sub_items or [],
    }


class TestEurlexDefLines:
    def test_non_empty_definition_returned_as_single_line(self) -> None:
        rec = _make_rec("departure of dual-use items from the customs territory")
        lines = _eurlex_def_lines(rec)
        assert lines == ["departure of dual-use items from the customs territory"]

    def test_empty_definition_with_sub_items_shows_sub_items(self) -> None:
        rec = _make_rec("", [
            {"marker": "a", "text": "departure of dual-use items"},
            {"marker": "b", "text": "re-export of dual-use items"},
        ])
        lines = _eurlex_def_lines(rec)
        assert lines == ["(a) departure of dual-use items", "(b) re-export of dual-use items"]

    def test_colon_definition_shows_sub_items(self) -> None:
        rec = _make_rec(":", [{"marker": "a", "text": "first option"}])
        lines = _eurlex_def_lines(rec)
        assert lines == ["(a) first option"]

    def test_dash_definition_shows_sub_items(self) -> None:
        rec = _make_rec("–", [{"marker": "a", "text": "dash case"}])
        lines = _eurlex_def_lines(rec)
        assert lines == ["(a) dash case"]

    def test_empty_definition_no_sub_items_returns_question_mark(self) -> None:
        rec = _make_rec("")
        lines = _eurlex_def_lines(rec)
        assert lines == ["?"]

    def test_sub_item_text_truncated_at_80_chars(self) -> None:
        long_text = "x" * 100
        rec = _make_rec("", [{"marker": "a", "text": long_text}])
        lines = _eurlex_def_lines(rec)
        assert len(lines[0]) <= len("(a) ") + 80

    def test_maximum_five_sub_items_shown(self) -> None:
        sub_items = [{"marker": str(i), "text": f"item {i}"} for i in range(8)]
        rec = _make_rec("", sub_items)
        lines = _eurlex_def_lines(rec)
        assert len(lines) == 6  # 5 items + "... (3 more)"
        assert lines[-1] == "... (3 more)"

    def test_exactly_five_sub_items_no_overflow_line(self) -> None:
        sub_items = [{"marker": str(i), "text": f"item {i}"} for i in range(5)]
        rec = _make_rec("", sub_items)
        lines = _eurlex_def_lines(rec)
        assert len(lines) == 5
        assert not any("more" in line for line in lines)

    def test_non_trivial_definition_with_sub_items_uses_definition(self) -> None:
        rec = _make_rec("the customs territory of the Union", [
            {"marker": "a", "text": "should be ignored"},
        ])
        lines = _eurlex_def_lines(rec)
        assert lines == ["the customs territory of the Union"]

    def test_no_marker_sub_item_omits_parentheses(self) -> None:
        rec = _make_rec("", [{"marker": "", "text": "plain content"}])
        lines = _eurlex_def_lines(rec)
        assert lines == ["plain content"]

    def test_whitespace_only_definition_treated_as_trivial(self) -> None:
        rec = _make_rec("   ", [{"marker": "a", "text": "content"}])
        lines = _eurlex_def_lines(rec)
        assert lines == ["(a) content"]


class TestReviewNavigation:
    @staticmethod
    def _fresh():
        records = [{"lang": "en", "approved": None} for _ in range(3)]
        pending = [0, 1, 2]
        counts = {"approved": 0, "rejected": 0, "skipped": 0, "reviewed_again": 0}
        history: list[tuple[int, object, str]] = []
        return records, pending, counts, history

    def test_back_navigation_restores_previous_state(self) -> None:
        records, pending, counts, history = self._fresh()

        # Approve the first record, advancing to position 1.
        pos, quit_, save = _handle_review_key("a", records, pending, 0, history, counts)
        assert pos == 1 and not quit_ and save
        assert records[0]["approved"] is True
        assert counts["approved"] == 1

        # Back: undo the approve, restore prior state, return to position 0.
        pos, quit_, save = _handle_review_key("-", records, pending, 1, history, counts)
        assert pos == 0 and not quit_ and save
        assert records[0]["approved"] is None  # restored to pre-action value
        assert counts["approved"] == 0
        assert counts["reviewed_again"] == 1
        assert history == []

    def test_back_at_first_record_stays_put(self, capsys) -> None:
        records, pending, counts, history = self._fresh()

        pos, quit_, save = _handle_review_key("-", records, pending, 0, history, counts)

        assert pos == 0 and not quit_ and not save
        assert history == []
        assert counts["reviewed_again"] == 0
        assert "Already at first record" in capsys.readouterr().out

    def test_plus_same_as_skip(self) -> None:
        # Run the same starting state through 's' and through '+'.
        recs_s, pend_s, counts_s, hist_s = self._fresh()
        recs_p, pend_p, counts_p, hist_p = self._fresh()

        res_s = _handle_review_key("s", recs_s, pend_s, 0, hist_s, counts_s)
        res_p = _handle_review_key("+", recs_p, pend_p, 0, hist_p, counts_p)

        assert res_s == res_p == (1, False, False)
        assert recs_s[0]["approved"] is None  # skip leaves value unchanged
        assert recs_p[0]["approved"] is None
        assert counts_s == counts_p
        assert counts_p["skipped"] == 1
        assert hist_s == hist_p == [(0, None, "skip")]
