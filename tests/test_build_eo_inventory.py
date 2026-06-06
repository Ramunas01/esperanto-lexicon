"""Tests for ``src.lexicon.build_eo_inventory`` — specifically the
supplement merging and reduce-exception machinery added in this PR.

These tests exercise the loaders and ``extract_roots``/``apply_supplement``
in isolation. A full ESPDIC fetch is not required.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.lexicon.build_eo_inventory import (
    apply_supplement,
    extract_roots,
    load_reduce_exceptions,
    load_supplement,
    parse_espdic,
)


# ---------------------------------------------------------------------------
# Supplement loader + merger (Part A)
# ---------------------------------------------------------------------------


def test_supplement_loader_parses_tsv(tmp_path: Path) -> None:
    """Skips comments / blank lines; reads root/gloss/note."""
    p = tmp_path / "sup.tsv"
    p.write_text(
        "# header\n"
        "\n"
        "dvd\tDVD\tcontemporary tech acronym\n"
        "kampus\tcampus\tcommon borrowing\n"
        "noresult\n"        # 1 column — ignored
        "\t\t\n"             # all empty — ignored
        "bus\tbus\n",        # 2 columns — gloss present, no note
        encoding="utf-8",
    )
    entries = load_supplement(p)
    assert set(entries) == {"dvd", "kampus", "bus"}
    assert entries["dvd"]["gloss"] == "DVD"
    assert entries["dvd"]["note"].startswith("contemporary")
    assert entries["bus"]["gloss"] == "bus"
    assert entries["bus"]["note"] == ""


def test_supplement_loader_missing_file_returns_empty(tmp_path: Path) -> None:
    assert load_supplement(tmp_path / "absent.tsv") == {}


def test_apply_supplement_adds_modern_entries() -> None:
    """``dvd`` joins ``roots`` with tier='modern' and prod=-1."""
    roots: dict[str, dict] = {
        "patr": {"gloss": "father", "prod": 22, "tier": "core"},
    }
    supplement = {
        "dvd":    {"gloss": "DVD", "note": ""},
        "kampus": {"gloss": "campus", "note": ""},
    }
    added = apply_supplement(roots, supplement)
    assert added == 2
    assert roots["dvd"] == {"gloss": "DVD", "prod": -1, "tier": "modern"}
    assert roots["kampus"]["tier"] == "modern"
    assert roots["kampus"]["prod"] == -1


def test_apply_supplement_never_overwrites_existing_espdic_root() -> None:
    """An ESPDIC root with the same key wins — supplement is silently
    ignored. (Concrete case: ``blog`` is in ESPDIC as core/prod=5.)"""
    roots = {
        "blog": {"gloss": "to blog", "prod": 5, "tier": "core"},
    }
    supplement = {
        "blog": {"gloss": "internet diary (supplement)", "note": "doc"},
    }
    added = apply_supplement(roots, supplement)
    assert added == 0
    assert roots["blog"] == {
        "gloss": "to blog", "prod": 5, "tier": "core",
    }


# ---------------------------------------------------------------------------
# Reduce-exceptions loader + extract_roots short-circuit (Part B)
# ---------------------------------------------------------------------------


def test_reduce_exceptions_loader_skips_comments_and_blanks(
    tmp_path: Path,
) -> None:
    p = tmp_path / "ex.txt"
    p.write_text(
        "# header line\n"
        "\n"
        "prezid\n"
        "   \n"
        "# another comment\n"
        "OtherStem\n",  # case-folded on load
        encoding="utf-8",
    )
    assert load_reduce_exceptions(p) == {"prezid", "otherstem"}


def test_reduce_exceptions_loader_missing_file_returns_empty(
    tmp_path: Path,
) -> None:
    assert load_reduce_exceptions(tmp_path / "absent.txt") == set()


def test_extract_roots_without_exceptions_collapses_prezid() -> None:
    """Sanity check: without the exception, ``prezid`` is orthographically
    reducible to ``prez`` (because ``prez`` is independently attested) and
    therefore gets absorbed."""
    stems = {"prez", "prezid"}
    prod = extract_roots(stems)
    # prezid was peeled into prez — prezid no longer a primitive.
    assert prod.get("prezid", 0) == 0
    # prez took the prezid count on top of its own.
    assert prod["prez"] == 2


def test_extract_roots_honors_reduce_exception_for_prezid() -> None:
    """With ``prezid`` in the exceptions set, both ``prez`` and ``prezid``
    stay primitive: each receives only its own attestation. No row maps
    prezid→prez."""
    stems = {"prez", "prezid"}
    prod = extract_roots(stems, reduce_exceptions={"prezid"})
    assert prod["prezid"] == 1
    assert prod["prez"] == 1


def test_parse_espdic_basic_handling() -> None:
    """Minimal ESPDIC parse: ``prezido`` and ``prezo`` both reduce to
    their endingless stems."""
    text = (
        "prezido : to preside\n"
        "prezo : price\n"
        "# a comment line that won't match the ' : ' separator\n"
        "-suffix- : skipped (affix entry)\n"
    )
    stems, gloss = parse_espdic(text)
    assert "prezid" in stems
    assert "prez" in stems
    assert gloss["prezid"] == "to preside"
    assert gloss["prez"] == "price"
