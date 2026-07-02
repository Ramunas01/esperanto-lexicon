"""Unit tests for tinystories_gap_triage triage logic.

These cover the pure logic (bucketing, ranking, tier-3 frequency counting,
pooled-file parsing, feature assembly) with small in-memory / tmp fixtures.
They do not depend on spaCy or the full corpus.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src" / "analyzer"))

from tinystories_gap_triage import (  # noqa: E402
    BUCKET_COMMON_GAP,
    BUCKET_INFLECTION_MISS,
    BUCKET_PROPER_NOUN,
    UnknownToken,
    build_unknown_tokens,
    classify_bucket,
    parse_pooled_unknowns,
    rank_unknowns,
    tier3_frequencies,
    write_tsv,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _u(
    token: str,
    *,
    frequency: int = 1,
    lemma: str | None = None,
    is_propn: bool = False,
    is_capitalized: bool = False,
) -> UnknownToken:
    return UnknownToken(
        token=token,
        frequency=frequency,
        lemma=lemma if lemma is not None else token,
        is_propn=is_propn,
        is_capitalized=is_capitalized,
    )


# ---------------------------------------------------------------------------
# classify_bucket
# ---------------------------------------------------------------------------


class TestClassifyBucket:
    LEXICON = {"hug", "run", "child", "number"}
    INFLECTED = {"is", "be", "are"}

    def test_lemma_resolving_in_lexicon_is_inflection_miss(self) -> None:
        # "hugged" is UNKNOWN in context, but its isolated lemma "hug" is known.
        u = _u("hugged", lemma="hug")
        assert (
            classify_bucket(u, self.LEXICON, self.INFLECTED)
            == BUCKET_INFLECTION_MISS
        )

    def test_token_itself_in_lexicon_is_inflection_miss(self) -> None:
        u = _u("number", lemma="number")
        assert (
            classify_bucket(u, self.LEXICON, self.INFLECTED)
            == BUCKET_INFLECTION_MISS
        )

    def test_token_in_inflected_forms_is_inflection_miss(self) -> None:
        u = _u("are", lemma="are")
        assert (
            classify_bucket(u, self.LEXICON, self.INFLECTED)
            == BUCKET_INFLECTION_MISS
        )

    def test_lemma_in_inflected_forms_is_inflection_miss(self) -> None:
        u = _u("isnt", lemma="be")
        assert (
            classify_bucket(u, self.LEXICON, self.INFLECTED)
            == BUCKET_INFLECTION_MISS
        )

    def test_propn_flag_is_proper_noun(self) -> None:
        u = _u("timmy", lemma="timmy", is_propn=True)
        assert (
            classify_bucket(u, self.LEXICON, self.INFLECTED) == BUCKET_PROPER_NOUN
        )

    def test_capitalized_flag_is_proper_noun(self) -> None:
        u = _u("lily", lemma="lily", is_capitalized=True)
        assert (
            classify_bucket(u, self.LEXICON, self.INFLECTED) == BUCKET_PROPER_NOUN
        )

    def test_inflection_miss_takes_priority_over_proper_noun(self) -> None:
        # Even if capitalised, a lexicon-resolving lemma is an inflection miss.
        u = _u("Number", lemma="number", is_propn=True, is_capitalized=True)
        assert (
            classify_bucket(u, self.LEXICON, self.INFLECTED)
            == BUCKET_INFLECTION_MISS
        )

    def test_unresolved_lowercase_is_common_gap(self) -> None:
        u = _u("nodded", lemma="nod")
        assert (
            classify_bucket(u, self.LEXICON, self.INFLECTED) == BUCKET_COMMON_GAP
        )

    def test_empty_lexicon_lowercase_noun_is_common_gap(self) -> None:
        u = _u("rabbit", lemma="rabbit")
        assert classify_bucket(u, set(), set()) == BUCKET_COMMON_GAP


# ---------------------------------------------------------------------------
# rank_unknowns
# ---------------------------------------------------------------------------


class TestRankUnknowns:
    def test_sorted_by_frequency_desc(self) -> None:
        counter = Counter({"a": 3, "b": 10, "c": 1})
        assert rank_unknowns(counter) == [("b", 10), ("a", 3), ("c", 1)]

    def test_ties_broken_alphabetically(self) -> None:
        counter = Counter({"zebra": 5, "apple": 5, "mango": 5})
        assert rank_unknowns(counter) == [
            ("apple", 5),
            ("mango", 5),
            ("zebra", 5),
        ]

    def test_empty(self) -> None:
        assert rank_unknowns(Counter()) == []


# ---------------------------------------------------------------------------
# tier3_frequencies
# ---------------------------------------------------------------------------


class TestTier3Frequencies:
    def test_counts_and_sorts_desc(self) -> None:
        tier3 = {"number", "revenue", "audit"}
        corpus = Counter({"number": 120, "revenue": 0, "audit": 3, "cat": 999})
        assert tier3_frequencies(tier3, corpus) == [
            ("number", 120),
            ("audit", 3),
            ("revenue", 0),
        ]

    def test_absent_word_reported_zero(self) -> None:
        tier3 = {"threshold"}
        corpus = Counter({"cat": 5})
        assert tier3_frequencies(tier3, corpus) == [("threshold", 0)]

    def test_zero_frequency_ties_alphabetical(self) -> None:
        tier3 = {"beta", "alpha"}
        corpus: Counter[str] = Counter()
        assert tier3_frequencies(tier3, corpus) == [("alpha", 0), ("beta", 0)]


# ---------------------------------------------------------------------------
# parse_pooled_unknowns
# ---------------------------------------------------------------------------


class TestParsePooledUnknowns:
    def test_parses_count_tab_token(self, tmp_path: Path) -> None:
        p = tmp_path / "pool.txt"
        p.write_text("10\tlily\n3\thugged\n1\tnodded\n", encoding="utf-8")
        assert parse_pooled_unknowns(p) == Counter(
            {"lily": 10, "hugged": 3, "nodded": 1}
        )

    def test_skips_blank_and_malformed_lines(self, tmp_path: Path) -> None:
        p = tmp_path / "pool.txt"
        p.write_text(
            "5\tcat\n\nnotanumber\tdog\nnojustoneword\n7\tbird\n",
            encoding="utf-8",
        )
        assert parse_pooled_unknowns(p) == Counter({"cat": 5, "bird": 7})


# ---------------------------------------------------------------------------
# build_unknown_tokens
# ---------------------------------------------------------------------------


class TestBuildUnknownTokens:
    def test_majority_capitalised_sets_flag(self) -> None:
        counter = Counter({"lily": 10})
        lemmas = {"lily": "lily"}
        features = {"lily": {"caps": 9, "total": 10, "propn": 0}}
        [u] = build_unknown_tokens(counter, lemmas, features)
        assert u.is_capitalized is True
        assert u.is_propn is False
        assert u.frequency == 10
        assert u.lemma == "lily"

    def test_minority_capitalised_not_flagged(self) -> None:
        counter = Counter({"spring": 10})
        lemmas = {"spring": "spring"}
        features = {"spring": {"caps": 2, "total": 10, "propn": 0}}
        [u] = build_unknown_tokens(counter, lemmas, features)
        assert u.is_capitalized is False

    def test_propn_flag_when_ever_tagged(self) -> None:
        counter = Counter({"max": 4})
        lemmas = {"max": "max"}
        features = {"max": {"caps": 2, "total": 4, "propn": 1}}
        [u] = build_unknown_tokens(counter, lemmas, features)
        assert u.is_propn is True

    def test_missing_features_default_to_lowercase_common(self) -> None:
        counter = Counter({"blorp": 2})
        lemmas: dict[str, str] = {}
        features: dict[str, dict[str, int]] = {}
        [u] = build_unknown_tokens(counter, lemmas, features)
        assert u.is_propn is False
        assert u.is_capitalized is False
        assert u.lemma == "blorp"


# ---------------------------------------------------------------------------
# write_tsv
# ---------------------------------------------------------------------------


class TestWriteTsv:
    def test_writes_header_and_ranked_rows(self, tmp_path: Path) -> None:
        ranked = [("lily", 10), ("hugged", 3)]
        buckets = {"lily": BUCKET_PROPER_NOUN, "hugged": BUCKET_INFLECTION_MISS}
        out = tmp_path / "sub" / "triaged.tsv"
        write_tsv(ranked, buckets, out)
        lines = out.read_text(encoding="utf-8").splitlines()
        assert lines[0] == "token\tfrequency\tbucket"
        assert lines[1] == "lily\t10\tproper_noun"
        assert lines[2] == "hugged\t3\tinflection_miss"

    def test_diagnostic_columns_when_index_supplied(self, tmp_path: Path) -> None:
        ranked = [("lily", 10), ("hugged", 3)]
        buckets = {"lily": BUCKET_PROPER_NOUN, "hugged": BUCKET_INFLECTION_MISS}
        index = {
            "lily": _u("lily", lemma="lily", is_capitalized=True),
            "hugged": _u("hugged", lemma="hug"),
        }
        out = tmp_path / "triaged.tsv"
        write_tsv(ranked, buckets, out, index)
        lines = out.read_text(encoding="utf-8").splitlines()
        assert lines[0] == "token\tfrequency\tbucket\tis_propn\tcaps_majority\tlemma"
        # lily: capitalisation-only proper_noun (is_propn=0, caps=1)
        assert lines[1] == "lily\t10\tproper_noun\t0\t1\tlily"
        assert lines[2] == "hugged\t3\tinflection_miss\t0\t0\thug"


# ---------------------------------------------------------------------------
# Integration of pure pieces: end-to-end bucketing over a mixed sample
# ---------------------------------------------------------------------------


class TestBucketingIntegration:
    def test_mixed_sample_bucket_counts(self) -> None:
        lexicon = {"hug", "number"}
        inflected = {"are", "be"}
        unknowns = [
            _u("hugged", lemma="hug"),  # inflection_miss
            _u("are", lemma="are"),  # inflection_miss
            _u("timmy", lemma="timmy", is_propn=True),  # proper_noun
            _u("lily", lemma="lily", is_capitalized=True),  # proper_noun
            _u("nodded", lemma="nod"),  # common_gap
            _u("giggled", lemma="giggle"),  # common_gap
        ]
        counts = Counter(
            classify_bucket(u, lexicon, inflected) for u in unknowns
        )
        assert counts[BUCKET_INFLECTION_MISS] == 2
        assert counts[BUCKET_PROPER_NOUN] == 2
        assert counts[BUCKET_COMMON_GAP] == 2


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
