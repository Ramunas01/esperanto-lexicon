"""Tests for extract_wco_glossary.py.

Uses the real PDF as the fixture (single-document extractor; copying
the PDF into the tests directory is acceptable per the conventions in CLAUDE.md).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from extractor.extract_wco_glossary import (
    _collect_raw_rows,
    _entry_id,
    _extract_cross_refs,
    _parse_left,
    _parse_right,
    extract_entries,
)

PDF_PATH = (
    Path(__file__).parent.parent.parent
    / "esperanto-lexicon-corpus"
    / "customs"
    / "WCO"
    / "glossary-of-international-customs-terms.pdf"
)

pytestmark = pytest.mark.skipif(
    not PDF_PATH.exists(),
    reason="WCO PDF not found at expected path; skipping integration tests",
)


# ---------------------------------------------------------------------------
# Unit tests — no PDF needed
# ---------------------------------------------------------------------------


class TestParseLeft:
    def test_simple_entry(self):
        left = "ADVANCE RULINGS\n(Décision anticipée)"
        en, fr, warn = _parse_left(left)
        assert en == "ADVANCE RULINGS"
        assert fr == "Décision anticipée"
        assert warn is None

    def test_multi_line_en_term(self):
        left = "ADMINISTRATIVE\nSETTLEMENT OF A CUSTOMS\nOFFENCE\n(Règlement administratif d'une\ninfraction douanière)"
        en, fr, warn = _parse_left(left)
        assert en == "ADMINISTRATIVE SETTLEMENT OF A CUSTOMS OFFENCE"
        assert "Règlement administratif" in fr
        assert warn is None

    def test_nested_parens_in_french(self):
        """HARMONIZED SYSTEM CONVENTION has nested parens — French must include '(SH)'."""
        left = "HARMONIZED SYSTEM\nCONVENTION (HS)\n(Convention sur le Système\nharmonisé (SH))"
        en, fr, warn = _parse_left(left)
        assert en == "HARMONIZED SYSTEM CONVENTION (HS)"
        assert fr == "Convention sur le Système harmonisé (SH)", f"Got: {fr!r}"

    def test_mixed_case_headword_perishable_goods(self):
        """'Perishable goods' is not ALL CAPS but is a valid headword."""
        left = "Perishable goods\n(Marchandises périssables)"
        en, fr, warn = _parse_left(left)
        assert en == "Perishable goods"
        assert fr == "Marchandises périssables"

    def test_en_abbreviation_inline(self):
        """Time Release Study(TRS) — abbreviation attached directly to term."""
        left = "Time Release Study(TRS)\n(Étude sur le temps nécessaire\npour la mainlevée)"
        en, fr, warn = _parse_left(left)
        assert en == "Time Release Study(TRS)"
        assert "Étude" in fr

    def test_national_customs_enforcement_network_non_standard(self):
        """NATIONAL CUSTOMS ENFORCEMENT NETWORK has French NOT in outer parens."""
        left = (
            "NATIONAL CUSTOMS\nENFORCEMENT NETWORK\n(nCEN)\n"
            "Réseau douanier national de\nlutte contre la fraude (nCEN)"
        )
        en, fr, warn = _parse_left(left)
        assert "NATIONAL CUSTOMS ENFORCEMENT NETWORK" in en
        assert "(nCEN)" in en  # abbreviation stays in EN term
        assert fr is not None
        assert "Réseau douanier" in fr
        assert warn is not None  # should warn about non-standard format

    def test_truncated_french_paren(self):
        """STORES FOR CONSUMPTION has a truncated closing paren — handle gracefully."""
        left = "STORES FOR CONSUMPTION\n(Produits d'avitaillement à\nconsommer"
        en, fr, warn = _parse_left(left)
        assert en == "STORES FOR CONSUMPTION"
        assert fr is not None
        assert "consommer" in fr  # partial term extracted


class TestParseRight:
    def test_definition_only(self):
        right = "Duties and taxes which are calculated on the basis of value."
        body, notes = _parse_right(right)
        assert body == right
        assert notes == []

    def test_definition_with_note_singular(self):
        right = (
            "The procedure laid down by national legislation.\n"
            "Note\n"
            "Administrative settlement is dealt with in Annex H.2 to the Kyoto Convention."
        )
        body, notes = _parse_right(right)
        assert "national legislation" in body
        assert "Note" not in body
        assert len(notes) == 1
        assert "Kyoto" in notes[0]

    def test_definition_with_notes_plural_colon(self):
        right = (
            "A written decision.\n"
            "Notes:\n"
            "1. Advance rulings are dealt with in Article 3.\n"
            "2. Advance rulings are provided for under the revised Kyoto Convention."
        )
        body, notes = _parse_right(right)
        assert body == "A written decision."
        assert len(notes) == 2
        assert "Article 3" in notes[0]
        assert "Kyoto" in notes[1]

    def test_no_notes_prefix_variation(self):
        right = (
            "A definition here.\n"
            "Notes\n"
            "This is a note paragraph without numbering."
        )
        body, notes = _parse_right(right)
        assert body == "A definition here."
        assert len(notes) == 1


class TestEntryId:
    def test_all_caps(self):
        assert _entry_id("ADVANCE RULINGS") == "advance-rulings"

    def test_with_abbreviation(self):
        assert _entry_id("AUTHORIZED ECONOMIC OPERATOR (AEO)") == "authorized-economic-operator"

    def test_mixed_case(self):
        assert _entry_id("Perishable goods") == "perishable-goods"

    def test_slash(self):
        assert _entry_id("IMPORT/EXPORT LICENCE") == "import-export-licence"

    def test_time_release_study(self):
        result = _entry_id("Time Release Study(TRS)")
        assert result == "time-release-study"

    def test_intellectual_property_rights(self):
        assert _entry_id("INTELLECTUAL PROPERTY RIGHTS") == "intellectual-property-rights"


class TestExtractCrossRefs:
    def test_kyoto_convention_reference(self):
        text = "Administrative settlement is dealt with in Annex H.2 to the Kyoto Convention of 1974."
        refs = _extract_cross_refs(text)
        assert any("Kyoto" in r for r in refs)

    def test_wto_agreement_reference(self):
        text = "Advance rulings are dealt with in Article 3 of the WTO Agreement on Trade Facilitation."
        refs = _extract_cross_refs(text)
        assert any("WTO" in r or "Trade Facilitation" in r for r in refs)

    def test_no_refs(self):
        text = "Duties and taxes calculated on the basis of value."
        refs = _extract_cross_refs(text)
        assert refs == []

    def test_multiple_refs(self):
        text = (
            "See General Annex, Chapter 2 of the revised Kyoto Convention. "
            "Also Article 3 of the WTO Agreement on Trade Facilitation."
        )
        refs = _extract_cross_refs(text)
        assert len(refs) >= 2


# ---------------------------------------------------------------------------
# Integration tests — require the real PDF
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def all_records():
    """Extract all records from the WCO PDF (module-scoped, loaded once)."""
    import pdfplumber

    records, stats = extract_entries(PDF_PATH)
    return records, stats


class TestBasicEntry:
    def test_advance_rulings_en(self, all_records):
        """First sampled entry parses correctly with EN + FR + notes + cross-refs."""
        records, _ = all_records
        en = next(r for r in records if r["source_ref"]["entry_id"] == "advance-rulings" and r["lang"] == "en")
        assert en["term"] == "advance rulings"
        assert en["term_original"] == "ADVANCE RULINGS"
        assert "competent authority" in en["definition"]
        assert len(en["notes"]) >= 1
        assert len(en["cross_references"]) >= 1

    def test_advance_rulings_fr(self, all_records):
        """FR record for advance rulings has null definition."""
        records, _ = all_records
        fr = next(r for r in records if r["source_ref"]["entry_id"] == "advance-rulings" and r["lang"] == "fr")
        assert fr["term_original"] == "Décision anticipée"
        assert fr["definition"] is None
        assert fr["notes"] == []
        assert fr["cross_references"] == []


class TestNestedParensInFrench:
    def test_harmonized_system_convention(self, all_records):
        """HARMONIZED SYSTEM CONVENTION has nested parens — French is 'Convention sur le Système harmonisé (SH)'."""
        records, _ = all_records
        fr = next(
            r for r in records
            if "harmonized-system-convention" in r["source_ref"]["entry_id"] and r["lang"] == "fr"
        )
        assert fr["term_original"] == "Convention sur le Système harmonisé (SH)", (
            f"Got: {fr['term_original']!r} — nested '(SH)' must not be truncated"
        )


class TestPageBreakContinuation:
    def test_intellectual_property_rights_spans_pages(self, all_records):
        """INTELLECTUAL PROPERTY RIGHTS spans pages 22–23 — both halves merged into one entry."""
        records, stats = all_records
        assert stats["page_break_joins"] >= 1

        en = next(
            r for r in records
            if r["source_ref"]["entry_id"] == "intellectual-property-rights" and r["lang"] == "en"
        )
        fr = next(
            r for r in records
            if r["source_ref"]["entry_id"] == "intellectual-property-rights" and r["lang"] == "fr"
        )

        assert en["term_original"] == "INTELLECTUAL PROPERTY RIGHTS"
        assert fr["term_original"] == "Droits de propriété intellectuelle"
        # Definition must include content from both pages
        assert "trademarks" in en["definition"].lower() or "Copyright" in en["definition"]
        assert fr["definition"] is None


class TestMixedCaseHeadword:
    def test_perishable_goods(self, all_records):
        """'Perishable goods' is not ALL CAPS but is a valid headword."""
        records, _ = all_records
        en = next(r for r in records if r["source_ref"]["entry_id"] == "perishable-goods" and r["lang"] == "en")
        assert en["term_original"] == "Perishable goods"
        assert "rapidly decay" in en["definition"]


class TestNoFrenchDefinition:
    def test_fr_records_always_have_null_definition(self, all_records):
        """FR records always have definition = None; no fake French prose."""
        records, _ = all_records
        fr_with_def = [r for r in records if r["lang"] == "fr" and r["definition"] is not None]
        assert fr_with_def == [], (
            f"Found {len(fr_with_def)} FR records with non-null definition: "
            + ", ".join(r["term_original"] for r in fr_with_def[:5])
        )


class TestEntryIdUniqueness:
    def test_entry_ids_unique(self, all_records):
        """Every entry_id in the output is unique."""
        records, _ = all_records
        en_records = [r for r in records if r["lang"] == "en"]
        ids = [r["source_ref"]["entry_id"] for r in en_records]
        dupes = sorted(set(i for i in ids if ids.count(i) > 1))
        assert dupes == [], f"Duplicate entry_ids: {dupes}"

    def test_each_entry_has_en_and_fr(self, all_records):
        """Every entry_id has exactly one EN and one FR record."""
        records, _ = all_records
        from collections import Counter
        by_id: dict[str, Counter] = {}
        for r in records:
            eid = r["source_ref"]["entry_id"]
            if eid not in by_id:
                by_id[eid] = Counter()
            by_id[eid][r["lang"]] += 1

        bad = {eid: counts for eid, counts in by_id.items() if counts["en"] != 1 or counts["fr"] != 1}
        assert not bad, f"Entries with wrong language counts: {bad}"

    def test_entry_count_reasonable(self, all_records):
        """Total entry count is in the expected range for this glossary edition."""
        records, stats = all_records
        assert 160 <= stats["entries_extracted"] <= 220, (
            f"Got {stats['entries_extracted']} entries; expected 160–220"
        )


class TestResilienceEntry:
    def test_resilience_merged_correctly(self, all_records):
        """RESILIENCE has its French term on a separate row — must be merged."""
        records, _ = all_records
        en = next(r for r in records if r["source_ref"]["entry_id"] == "resilience" and r["lang"] == "en")
        fr = next(r for r in records if r["source_ref"]["entry_id"] == "resilience" and r["lang"] == "fr")
        assert en["term_original"] == "RESILIENCE"
        assert fr["term_original"] == "Résilience"
        assert en["definition"] is not None and len(en["definition"]) > 50
