"""Tests for ``src.lexicon.build_eo_inventory``.

Covers the SV-guarded reducer, the curated reduce-exceptions, the
modern-roots supplement, and the decode-prefix split — all in isolation
with hand-built fixtures so no network ESPDIC fetch is required.

Fixtures use realistic ESPDIC-style headword sets: when we want a stem
``X`` to be reducible, we attest enough headwords ``X + ending`` that the
successor-variety of ``X`` exceeds that of the longer stem. When we want
the longer stem ``XY`` preserved, we attest enough variety AT ``XY``
(``XYa``, ``XYe``, ``XYi``, ``XYo``, ``XYu``, ...) that SV(``XY``) >
SV(``X``).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.lexicon.build_eo_inventory import (
    DECODE_PREFIXES,
    PREFIXES,
    PREPOSITIONAL,
    apply_supplement,
    build_successor_index,
    extract_roots,
    load_reduce_exceptions,
    load_supplement,
    parse_espdic,
)


# ---------------------------------------------------------------------------
# Helpers — build heads + stems sets from a flat list of headwords
# ---------------------------------------------------------------------------


def _stems_from(heads: set[str]) -> set[str]:
    """Approximate the stems set without depending on the full strip_flexion
    chain. For the test fixtures every headword ends in one of {a,e,i,o,u}
    so chopping the last char is correct and avoids cross-coupling between
    these tests and strip_flexion's internals."""
    return {h[:-1] for h in heads if len(h) > 1}


# ---------------------------------------------------------------------------
# Successor-variety index
# ---------------------------------------------------------------------------


def test_successor_index_counts_unique_following_chars() -> None:
    """``succ[L]`` is the set of chars that can follow ``L`` over the
    headword vocabulary; ``len(succ[L])`` is the SV measure."""
    heads = {"rapida", "rapide", "rapidi", "rapido", "rapidu"}
    succ = build_successor_index(heads)
    assert succ["rapid"] == {"a", "e", "i", "o", "u"}
    assert len(succ["rapid"]) == 5
    # ``rap`` is followed only by 'i' across this headword set.
    assert succ["rap"] == {"i"}


# ---------------------------------------------------------------------------
# Reducer — SV-guard preserves monoradical roots
# ---------------------------------------------------------------------------


def _preserved_fixture() -> tuple[set[str], set[str]]:
    """Heads set engineered so the SV guard MUST preserve each of the
    `preserved` roots. Each preserved root has a wide ending set; each
    plausible reduction target has narrow SV."""
    heads = set()
    # rapid (monoradical, NOT rap+id)
    heads |= {"rapida", "rapide", "rapidi", "rapido", "rapidu"}
    heads |= {"rapo"}  # attest 'rap' so the reducer is tempted
    # decid (monoradical, NOT dec+id)
    heads |= {"decida", "decide", "decidi", "decido"}
    heads |= {"deco"}  # attest 'dec'
    # person (monoradical, NOT pers+on)
    heads |= {"persona", "persone", "personi", "persono", "personu"}
    heads |= {"perso"}  # attest 'pers'
    # kalkul (monoradical, NOT kalk+ul)
    heads |= {"kalkula", "kalkuli", "kalkulo", "kalkule"}
    heads |= {"kalko"}  # attest 'kalk'
    # ripet (monoradical, NOT rip+et)
    heads |= {"ripeta", "ripeti", "ripeto", "ripete"}
    heads |= {"ripo"}
    # rilat (monoradical, NOT ril+at)
    heads |= {"rilata", "rilati", "rilato", "rilate"}
    heads |= {"rilo"}
    return heads, _stems_from(heads)


@pytest.mark.parametrize("preserved", [
    "rapid", "decid", "person", "kalkul", "ripet", "rilat",
])
def test_sv_guard_preserves_monoradical_roots(preserved: str) -> None:
    """Under SV-guard the named monoradicals are NOT reduced — each ends in
    an affix-homograph (-id/-on/-ul/-et/-at) but its successor variety is
    higher than the would-be remainder's, so the suffix strip is rejected."""
    heads, stems = _preserved_fixture()
    prod = extract_roots(heads, stems)
    assert preserved in prod, (
        f"{preserved!r} was reduced — SV-guard didn't preserve it"
    )


def test_sv_guard_eliminates_greedy_collapse_to_short_homograph() -> None:
    """Under the old greedy reducer ``rapid`` was absorbed into ``rap``;
    the SV guard prevents that. Both stems land in ``prod`` as independent
    primitives (each with their own attestation count) rather than sharing
    a single productivity row."""
    heads, stems = _preserved_fixture()
    prod = extract_roots(heads, stems)
    assert prod["rap"] >= 1
    assert prod["rapid"] >= 1


# ---------------------------------------------------------------------------
# Reducer — correct reductions still happen (SV-guard isn't blanket-off)
# ---------------------------------------------------------------------------


def _reductive_fixture() -> tuple[set[str], set[str]]:
    """Heads set where the genuine -ad/-ist derivations SHOULD reduce
    correctly. The base stem (``kamp``, ``art``, ...) is attested with wide
    ending variety; the longer derivation has narrow SV."""
    heads = set()
    # kamp + ad (field + activity) — kamp is high-SV, kampad narrow
    heads |= {"kampo", "kampa", "kampe", "kampi", "kampu"}
    heads |= {"kampado", "kampada"}
    # koncept + ad
    heads |= {"koncepto", "koncepta", "koncepte", "koncepti"}
    heads |= {"konceptado"}
    # art + ist (high-SV art, narrow -ist)
    heads |= {"arto", "arta", "arte", "arti"}
    heads |= {"artisto", "artista", "artiste"}
    # danc + ist
    heads |= {"danco", "danca", "dance", "danci"}
    heads |= {"dancisto", "dancista"}
    # rapid + ad — note rapid still preserved as root (see fixture above);
    # rapidad reduces THROUGH rapid (Rule 4 SV would compare against rapid
    # not rap), but in this small fixture we need to attest rapid + endings.
    heads |= {"rapida", "rapidi", "rapide", "rapido", "rapidu"}
    heads |= {"rapidado", "rapidada"}
    return heads, _stems_from(heads)


@pytest.mark.parametrize("derived", [
    "kampad", "konceptad", "artist", "dancist", "rapidad",
])
def test_sv_guard_still_reduces_correct_derivations(derived: str) -> None:
    """SV-guard must not be a blanket off-switch — genuine derivations
    (``kampad``, ``artist``) still collapse onto their base because the
    base has higher SV than the derived form."""
    heads, stems = _reductive_fixture()
    prod = extract_roots(heads, stems)
    assert derived not in prod, (
        f"{derived!r} stayed a primitive — SV-guard is too conservative "
        "or the fixture's SV gap is too small"
    )


# ---------------------------------------------------------------------------
# Reducer — curated exceptions (short-collision residual SV cannot reach)
# ---------------------------------------------------------------------------


def _exception_fixture() -> tuple[set[str], set[str]]:
    """Short-collision scenarios: each of {koler, regul, disting} is a real
    root, but the would-be remainder (``kol``, ``reg``, ``dist``) has high
    SV from UNRELATED words, so the SV guard alone doesn't protect them.

    Concretely:
      * ``kol`` is inflated by ``kolo``/``koloro``/``kolono`` → SV >> SV(koler)
      * ``reg`` is inflated by ``rego``/``regi``/``regulo`` → SV >> SV(regul)
      * ``dist`` is inflated by ``disto``/``distanca``/``distri`` → SV >> SV(disting)
    """
    heads = {
        # Inflate kol's SV with unrelated kol-words. The SV measure counts
        # distinct chars that follow "kol" across heads, so we want a wide
        # set: {o,a,e,i,u,b,n,d} = 8 here, beating SV(koler)=4.
        "kolo", "kola", "kole", "koli", "kolu", "kolbo", "kolnja", "koldo",
        # The collision: koler is the anger root — would be lost without exception.
        "kolero", "kolera", "kolere", "koleri",
        # Inflate reg similarly: SV(reg) >> SV(regul).
        "rego", "rega", "rege", "regi", "regu", "regba", "regdo", "regfo",
        # The collision: regul is the rule root.
        "regulo", "regula", "regule", "reguli",
        # Inflate dist: SV(disting) needs to be < SV(dist).
        "disto", "dista", "diste", "disti", "distu", "distbo", "distco",
        # The collision: disting is "distinguish".
        "distinga", "distinge", "distingi", "distingo",
    }
    return heads, _stems_from(heads)


def test_exceptions_preserve_koler_regul_disting() -> None:
    """With the exception list active, all three short-collision roots are
    preserved despite their would-be remainders having higher SV."""
    heads, stems = _exception_fixture()
    prod = extract_roots(heads, stems, reduce_exceptions={"koler", "regul", "disting"})
    for exc in ("koler", "regul", "disting"):
        assert exc in prod, f"{exc!r} was reduced despite being in exceptions"


def test_without_exceptions_koler_collapses_into_kol() -> None:
    """Without the exception list, ``koler`` is exactly the short-collision
    case SV can't catch — it does reduce."""
    heads, stems = _exception_fixture()
    prod_no_exc = extract_roots(heads, stems)
    assert prod_no_exc.get("koler", 0) == 0


# ---------------------------------------------------------------------------
# Decode-prefix split — JSON emits the prepositional set but build-time
# peeling does NOT use it (would over-reduce ``periodo`` → ``per+iod``).
# ---------------------------------------------------------------------------


def test_emitted_decode_prefixes_include_prepositional() -> None:
    """The decomposer reads ``prefixes`` from the emitted JSON, so the
    prepositional prefixes (`inter`, `laŭ`, …) must be there."""
    assert "inter" in DECODE_PREFIXES
    assert "laŭ" in DECODE_PREFIXES
    assert "kun" in DECODE_PREFIXES
    # And the union is a superset of build-time PREFIXES.
    assert set(PREFIXES).issubset(set(DECODE_PREFIXES))


def test_prepositional_prefixes_excluded_from_build_time_peeling() -> None:
    """Build-time ``PREFIXES`` must NOT include the prepositional set —
    otherwise the reducer would over-collapse short words like ``periodo``."""
    overlap = set(PREFIXES) & set(PREPOSITIONAL)
    assert overlap == set(), (
        f"PREFIXES leaked prepositional prefixes: {overlap}"
    )


def test_build_time_reducer_keeps_period_and_interes_whole() -> None:
    """`period` doesn't get peeled to `iod` because `per` is not in the
    build-time PREFIXES; `interes` doesn't get peeled to `es` because
    `inter` is not in the build-time PREFIXES either."""
    heads = {
        "periodo", "perioda", "periode", "periodi",
        "interesa", "intereso", "interese", "interesi",
        # Provide enough ``per`` and ``inter`` attestations to ensure those
        # short fragments are themselves in the stems set, so the test is
        # honest: if PREFIXES contained these the reducer WOULD try to peel.
        "pero", "perono",
        "interna", "intere",
    }
    stems = _stems_from(heads)
    prod = extract_roots(heads, stems)
    assert "period" in prod
    assert "interes" in prod
    # And we did NOT manufacture ``iod`` or ``es`` as roots.
    assert "iod" not in prod
    assert "es" not in prod


# ---------------------------------------------------------------------------
# parse_espdic — the new (heads, stems, gloss) 3-tuple shape
# ---------------------------------------------------------------------------


def test_parse_espdic_returns_heads_stems_gloss() -> None:
    text = (
        "prezido : to preside\n"
        "prezo : price\n"
        "# a comment line that won't match the ' : ' separator\n"
        "-suffix- : skipped (affix entry)\n"
    )
    heads, stems, gloss = parse_espdic(text)
    assert {"prezido", "prezo"} <= heads
    assert {"prezid", "prez"} <= stems
    assert gloss["prezid"] == "to preside"
    assert gloss["prez"] == "price"


# ---------------------------------------------------------------------------
# Loader hygiene (unchanged behaviours from prior PRs)
# ---------------------------------------------------------------------------


def test_supplement_loader_parses_tsv(tmp_path: Path) -> None:
    p = tmp_path / "sup.tsv"
    p.write_text(
        "# header\n"
        "\n"
        "dvd\tDVD\tcontemporary tech acronym\n"
        "kampus\tcampus\tcommon borrowing\n"
        "noresult\n"
        "\t\t\n"
        "bus\tbus\n",
        encoding="utf-8",
    )
    entries = load_supplement(p)
    assert set(entries) == {"dvd", "kampus", "bus"}
    assert entries["dvd"]["gloss"] == "DVD"


def test_apply_supplement_never_overwrites_existing_root() -> None:
    roots = {"blog": {"gloss": "to blog", "prod": 5, "tier": "core"}}
    added = apply_supplement(roots, {"blog": {"gloss": "modern", "note": ""}})
    assert added == 0
    assert roots["blog"]["tier"] == "core"


def test_reduce_exceptions_loader_strips_inline_comments(tmp_path: Path) -> None:
    p = tmp_path / "ex.txt"
    p.write_text(
        "prezid\n"
        "koler    # kolero=anger\n"
        "regul    # regulo=rule\n",
        encoding="utf-8",
    )
    assert load_reduce_exceptions(p) == {"prezid", "koler", "regul"}
