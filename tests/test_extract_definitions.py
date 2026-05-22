"""Tests for extract_definitions.py.

Uses the real GPMI-LT.txt and GPMI-EO.txt corpus files from the sibling
esperanto-lexicon-corpus repository.  All tests are skipped if the corpus
is absent so the test suite stays green in a checked-out-code-only environment.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.extractor.extract_definitions import (
    extract_definitions,
    write_records,
)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parent.parent
_CORPUS_DIR = _REPO_ROOT.parent / "esperanto-lexicon-corpus" / "tax_law"
_GPMI_LT = _CORPUS_DIR / "GPMI-LT.txt"
_GPMI_EO = _CORPUS_DIR / "GPMI-EO.txt"


def _skip_if_absent(path: Path) -> None:
    if not path.exists():
        pytest.skip(f"Corpus file not found: {path}")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def lt_lines() -> list[str]:
    _skip_if_absent(_GPMI_LT)
    return _GPMI_LT.read_text(encoding="utf-8").splitlines(keepends=True)


@pytest.fixture(scope="module")
def eo_lines() -> list[str]:
    _skip_if_absent(_GPMI_EO)
    return _GPMI_EO.read_text(encoding="utf-8").splitlines(keepends=True)


@pytest.fixture(scope="module")
def lt_defs(lt_lines: list[str]) -> list[dict]:
    return extract_definitions(lt_lines, "2", "lt", "GPMI-LT.txt")


@pytest.fixture(scope="module")
def eo_defs(eo_lines: list[str]) -> list[dict]:
    return extract_definitions(eo_lines, "2", "eo", "GPMI-EO.txt")


@pytest.fixture(scope="module")
def lt_by_clause(lt_defs: list[dict]) -> dict[str, dict]:
    return {r["clause_num"]: r for r in lt_defs}


@pytest.fixture(scope="module")
def eo_by_clause(eo_defs: list[dict]) -> dict[str, dict]:
    return {r["clause_num"]: r for r in eo_defs}


# ---------------------------------------------------------------------------
# 1. Count
# ---------------------------------------------------------------------------


def test_lt_article2_count(lt_defs: list[dict]) -> None:
    """All 38 numbered definitions from GPMI-LT.txt Article 2 are extracted."""
    assert len(lt_defs) == 38


def test_eo_article2_count(eo_defs: list[dict]) -> None:
    """All 38 numbered definitions from GPMI-EO.txt Article 2 are extracted."""
    assert len(eo_defs) == 38


# ---------------------------------------------------------------------------
# 2. Abbreviation clauses
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "clause_num, expected_abbrev",
    [
        ("1", "Lietuva"),                                  # (toliau – Lietuva) in term
        ("12", "Pelno mokesčio įstatymas"),                # (toliau – …) in definition
        ("13", "veikla"),                                  # (toliau šioje dalyje vadinama – veikla)
        ("27", "kontroliuojantis asmuo"),                  # (toliau – …) inside definition
        ("271", "kontroliuojamasis užsienio vienetas"),    # (toliau – …) in term
    ],
)
def test_lt_abbrev_populated(
    lt_by_clause: dict[str, dict], clause_num: str, expected_abbrev: str
) -> None:
    rec = lt_by_clause[clause_num]
    assert rec["abbrev"] == expected_abbrev


@pytest.mark.parametrize(
    "clause_num, expected_abbrev",
    [
        ("1", "Litovio"),                                                    # (ĉi-poste nomata – Litovio )
        ("12", "la Leĝo pri Kompanio-Enspezimposto"),                       # no dash form
        ("13", "agadoj"),                                                    # (ĉi-poste nomata en ĉi tiu parto – agadoj)
        ("27", "la kontrolanta persono"),                                    # no dash form
        ("271", "kontrolita eksterlanda ento"),                              # quoted form
    ],
)
def test_eo_abbrev_populated(
    eo_by_clause: dict[str, dict], clause_num: str, expected_abbrev: str
) -> None:
    rec = eo_by_clause[clause_num]
    assert rec["abbrev"] == expected_abbrev


def test_no_abbrev_is_none(lt_by_clause: dict[str, dict]) -> None:
    """Clauses without abbreviation clauses have abbrev=None."""
    for clause_num in ("2", "5", "8", "20", "23", "28"):
        assert lt_by_clause[clause_num]["abbrev"] is None


# ---------------------------------------------------------------------------
# 3. By-reference definitions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "clause_num",
    ["12", "21", "36", "37", "38"],
)
def test_lt_by_reference_type(lt_by_clause: dict[str, dict], clause_num: str) -> None:
    rec = lt_by_clause[clause_num]
    assert rec["definition_type"] == "by_reference"
    assert rec["by_reference_law"] is not None
    assert len(rec["by_reference_law"]) > 3


@pytest.mark.parametrize(
    "clause_num",
    ["12", "21", "36", "37", "38"],
)
def test_eo_by_reference_type(eo_by_clause: dict[str, dict], clause_num: str) -> None:
    rec = eo_by_clause[clause_num]
    assert rec["definition_type"] == "by_reference"
    assert rec["by_reference_law"] is not None


@pytest.mark.parametrize(
    "clause_num",
    ["1", "2", "5", "7", "15", "19", "27", "33"],
)
def test_direct_definitions(lt_by_clause: dict[str, dict], clause_num: str) -> None:
    rec = lt_by_clause[clause_num]
    assert rec["definition_type"] == "direct"
    assert rec["by_reference_law"] is None


# ---------------------------------------------------------------------------
# 4. Amendment lines are not extracted as terms
# ---------------------------------------------------------------------------


def test_amendment_lines_not_in_terms(lt_defs: list[dict]) -> None:
    """No term_raw should look like an amendment line."""
    bad_prefixes = ("Nr.", "Straipsnio", "Papildyta", "TAR pastaba")
    for rec in lt_defs:
        for prefix in bad_prefixes:
            assert not rec["term_raw"].startswith(prefix), (
                f"Amendment line leaked into term_raw: {rec['term_raw']!r}"
            )


def test_amendment_numbers_not_terms(lt_by_clause: dict[str, dict]) -> None:
    """Clause numbers like 16, 35, 39 (no separator) must not appear."""
    for excluded in ("16", "35", "39"):
        assert excluded not in lt_by_clause, (
            f"Clause {excluded} should be excluded but was extracted"
        )


def test_no_nr_in_clause_nums(lt_defs: list[dict]) -> None:
    """No record should have a clause_num that looks like an amendment reference."""
    for rec in lt_defs:
        assert rec["clause_num"].isdigit() or rec["clause_num"].isalnum(), (
            f"Unexpected clause_num: {rec['clause_num']!r}"
        )


# ---------------------------------------------------------------------------
# 5. Correct field structure on every record
# ---------------------------------------------------------------------------


REQUIRED_FIELDS = {
    "source_file",
    "lang",
    "article",
    "clause_num",
    "term_raw",
    "term_normalized",
    "abbrev",
    "definition_raw",
    "definition_type",
    "by_reference_law",
    "cross_lang_num",
    "approved",
}


def test_record_fields(lt_defs: list[dict]) -> None:
    for rec in lt_defs:
        assert REQUIRED_FIELDS == set(rec.keys()), (
            f"Field mismatch for clause {rec.get('clause_num')}"
        )
        assert rec["approved"] is False
        assert rec["lang"] == "lt"
        assert rec["article"] == "2"
        assert rec["source_file"] == "GPMI-LT.txt"
        assert rec["cross_lang_num"] == rec["clause_num"]
        assert rec["term_normalized"] == rec["term_raw"].lower()


# ---------------------------------------------------------------------------
# 6. --append adds to existing file without duplicating
# ---------------------------------------------------------------------------


def test_append_no_duplicates(lt_lines: list[str], tmp_path: Path) -> None:
    """Running with --append twice produces the same record count as once."""
    out = tmp_path / "out.jsonl"
    records = extract_definitions(lt_lines, "2", "lt", "GPMI-LT.txt")

    # First write
    written1 = write_records(records, out, append=False)
    assert written1 == 38

    # Second write with append — all keys already exist, nothing new
    written2 = write_records(records, out, append=True)
    assert written2 == 0

    # File still has exactly 38 lines
    lines = [ln for ln in out.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 38


def test_append_adds_new_records(lt_lines: list[str], tmp_path: Path) -> None:
    """Append mode does write genuinely new records."""
    out = tmp_path / "out.jsonl"
    records = extract_definitions(lt_lines, "2", "lt", "GPMI-LT.txt")

    # Write half the records first
    half = records[:19]
    write_records(half, out, append=False)

    # Append all 38 — only the other 19 should be new
    written = write_records(records, out, append=True)
    assert written == 19

    # Total in file: 38
    lines = [ln for ln in out.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 38


def test_append_records_are_valid_json(lt_lines: list[str], tmp_path: Path) -> None:
    """Each line in the output file is valid JSON with required fields."""
    out = tmp_path / "out.jsonl"
    records = extract_definitions(lt_lines, "2", "lt", "GPMI-LT.txt")
    write_records(records, out, append=False)

    with out.open(encoding="utf-8") as fh:
        for line in fh:
            rec = json.loads(line)
            assert REQUIRED_FIELDS == set(rec.keys())


# ---------------------------------------------------------------------------
# 7. Cross-language clause number alignment
# ---------------------------------------------------------------------------


def test_cross_lang_clause_nums_match(
    lt_by_clause: dict[str, dict], eo_by_clause: dict[str, dict]
) -> None:
    """LT and EO Article 2 define the same set of clause numbers."""
    assert set(lt_by_clause.keys()) == set(eo_by_clause.keys())


def test_compound_clause_numbers_present(
    lt_by_clause: dict[str, dict], eo_by_clause: dict[str, dict]
) -> None:
    """Compound numbers like 271 and 381 are present in both languages."""
    for compound in ("271", "381"):
        assert compound in lt_by_clause, f"LT missing compound clause {compound}"
        assert compound in eo_by_clause, f"EO missing compound clause {compound}"
