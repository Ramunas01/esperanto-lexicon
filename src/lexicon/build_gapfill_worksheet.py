#!/usr/bin/env python3
"""Build the common-lexicon gap-fill review worksheet (Phases 1-2, NO DB writes).

Turns the frequency-ranked ``common_gap`` queue from the TinyStories coverage
probe (``tinystories_unknown_triaged.tsv``) into a reviewable authoring
worksheet that proposes an **Esperanto anchor** for each gap word. This is the
input to a human review gate — nothing here writes to ``lexicon_v2.db`` or
changes any tier/word/cefr_level/source.

Esperanto-anchored, not English-first: "add ``hug``" means ensuring the concept
anchored on an Esperanto root (``brakum``, from ESPDIC ``brakumi : to embrace,
hug``) carries an English form. Two safe, insert-only outcomes per word:

* **LINK** — a ``concept`` with that ``eo_root`` already exists; the fix is one
  ``concept_lang`` row (add the English form).
* **NEW** — no concept exists for that meaning; author a ``concept`` +
  ``concept_lang`` + ``concept_root`` row(s).

Phase 1 (consolidate): collapse surface forms to lemmas (using the analyzer's
lemma column), reclaim common words hiding in the ``proper_noun`` bucket, and
split off British spellings (handled downstream as a spelling map, not new
concepts).

Phase 2 (propose anchors): reverse-look-up each lemma against the full ESPDIC
(EN sense -> EO headword), reduce the headword to the lexicon's root form with
the shared :class:`Decomposer`, and mark LINK vs NEW. Ambiguous / no-match /
compound cases are flagged for closer human attention.

Outputs (under ``data/analysis/gapfill/``):
  * ``consolidated_gap_lemmas.tsv`` — lemma, total_freq, origin, has_anchor
  * ``authoring_worksheet.tsv``     — the review worksheet (see COLUMNS)
  * ``british_spellings.tsv``       — uk_form, us_form, total_freq, us_in_lexicon

Usage::

    python3 src/lexicon/build_gapfill_worksheet.py \\
        --triaged data/analysis/tinystories_unknown_triaged.tsv \\
        --lexicon data/lexicon_db/lexicon_v2.db \\
        --espdic  data/lexicon_db/espdic.txt \\
        --inventory data/lexicon_db/eo_inventory.json \\
        --out-dir data/analysis/gapfill
"""

from __future__ import annotations

import argparse
import csv
import re
import sqlite3
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

# The shared decomposer is pure (no spaCy); import it at module load so the
# anchor logic can reduce Esperanto headwords to their stem form.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from eo_root_decomposer import (  # noqa: E402
    Decomposer,
    load_inventory,
    strip_flexion,
)

# Proposed provenance for every row (reviewer may override). Insert-only tag.
SOURCE_TAG = "tinystories_gap_v1"
DEFAULT_TIER = 1
DEFAULT_CEFR = "A1"

WORKSHEET_COLUMNS = [
    "en_lemma",
    "total_freq",
    "action",  # LINK | NEW | (blank for no_match)
    "eo_root",
    "eo_word",
    "eo_gloss",
    "component_roots",
    "proposed_tier",
    "cefr",
    "alt_candidates",
    "flag",  # ok | ambiguous | compound | no_match | reclaimed
    "notes",
]

# British -> American spelling folds. Applied to the whole surface form; a fold
# only counts as a "spelling variant" (routed out of the concept queue) when it
# actually changes the word. Entries are (uk_suffix, us_suffix, min_stem_len),
# tried longest-suffix-first; ``min_stem_len`` is the minimum number of chars that
# must precede the suffix (guards short-word false folds, e.g. ``pre``->``per``,
# ``tore``->``toer`` under the generic ``-re``->``-er`` rule). This is a *candidate
# generator*: it may over-produce (``surprise``->``surprize``); every caller must
# guard the result against the lexicon/ESPDIC before trusting it.
_UK_US_SUFFIX = [
    # -our family (colour, favour, honour, ...)
    ("ourite", "orite", 1),  # favourite -> favorite
    ("ourful", "orful", 1),  # colourful -> colorful
    ("ouring", "oring", 1),  # colouring -> coloring
    ("oured", "ored", 1),    # coloured -> colored
    ("ours", "ors", 1),      # colours -> colors
    ("our", "or", 1),        # colour -> color, favour -> favor
    # -ise / -ize family (organise, recognise, apologise, ...)
    ("isations", "izations", 1),
    ("isation", "ization", 1),  # organisation -> organization
    ("isers", "izers", 1),
    ("iser", "izer", 1),     # organiser -> organizer
    ("ising", "izing", 1),   # realising -> realizing
    ("ised", "ized", 1),     # realised -> realized
    ("ises", "izes", 1),
    ("ise", "ize", 1),       # recognise -> recognize
    # -yse / -yze family (analyse, paralyse, ...)
    ("ysing", "yzing", 1),
    ("ysed", "yzed", 1),
    ("yses", "yzes", 1),
    ("yser", "yzer", 1),
    ("yse", "yze", 1),       # analyse -> analyze
    # -tre / -ter and the generic -re / -er (centre, theatre, metre, fibre, ...)
    ("tres", "ters", 1),     # centres -> centers
    ("tre", "ter", 1),       # centre -> center, metre -> meter
    ("res", "ers", 4),       # centres -> centers (non -tre); stem >= 4 (guards cares->caers)
    ("re", "er", 3),         # theatre -> theater, fibre -> fiber; stem >= 3 (guards pre/tore/acre)
]
_UK_US_EXPLICIT = {
    "grey": "gray",
    "greyish": "grayish",
    "mum": "mom",
    "mummy": "mommy",
    "pyjamas": "pajamas",
    "plough": "plow",
    "aeroplane": "airplane",
}


# ---------------------------------------------------------------------------
# ESPDIC reverse index (EN sense -> [EO headwords]) + forward gloss
# ---------------------------------------------------------------------------


def normalise_sense(sense: str) -> str:
    """Normalise one English gloss sense for reverse-index keying.

    Strips parentheticals/brackets, a leading article or infinitive ``to``,
    surrounding punctuation and whitespace, and lowercases. Returns ``""`` for
    a sense that reduces to nothing.
    """
    s = re.sub(r"\(.*?\)|\[.*?\]", "", sense)
    s = s.strip().lower()
    s = re.sub(r"^(to|a|an|the)\s+", "", s)
    s = s.strip(" .!?\"'")
    return s.strip()


def parse_espdic(text: str) -> tuple[dict[str, list[str]], dict[str, str]]:
    """Parse ESPDIC into a reverse index and a forward gloss map.

    Returns ``(reverse, forward)`` where ``reverse[en_sense]`` is the list of
    Esperanto headwords whose gloss carries that sense (insertion-ordered,
    de-duplicated) and ``forward[eo_headword]`` is the headword's first full
    gloss line (for display). Affix entries (headword starting/ending with
    ``-``) are skipped; **capitalised headwords are skipped** — they are
    Esperanto proper names (``Benedikto : Ben``, ``Ĝon : John``) whose
    inclusion otherwise anchors English names to garbage roots. Multi-word EO
    headwords are kept (they surface compounds and MWEs).
    """
    reverse: dict[str, list[str]] = defaultdict(list)
    forward: dict[str, str] = {}
    for line in text.splitlines():
        if " : " not in line:
            continue
        head, gloss = line.split(" : ", 1)
        head = head.strip()
        gloss = gloss.strip()
        if not head or head.startswith("-") or head.endswith("-"):
            continue
        if head[:1].isupper():  # Esperanto proper name — not a common-word anchor
            continue
        forward.setdefault(head, gloss)
        for sense in re.split(r"[,;]", gloss):
            key = normalise_sense(sense)
            if key and head not in reverse[key]:
                reverse[key].append(head)
    return dict(reverse), forward


# ---------------------------------------------------------------------------
# Phase 1 — consolidate the queue
# ---------------------------------------------------------------------------


def read_triaged(path: Path) -> list[dict[str, str]]:
    """Read the triaged TSV into a list of dict rows (header-keyed)."""
    with path.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def consolidate_common_gap(rows: list[dict[str, str]]) -> dict[str, int]:
    """Collapse ``common_gap`` surface forms to lemmas, summing frequency.

    Uses the analyzer's ``lemma`` column (isolated spaCy lemma) so ``hugged`` /
    ``hopping`` collapse onto ``hug`` / ``hop``. Falls back to the surface token
    when the lemma cell is empty.
    """
    lemmas: dict[str, int] = defaultdict(int)
    for r in rows:
        if r.get("bucket") != "common_gap":
            continue
        lemma = (r.get("lemma") or r["token"]).strip().lower()
        lemmas[lemma] += int(r["frequency"])
    return dict(lemmas)


def reclaim_proper_nouns(
    rows: list[dict[str, str]], reverse_index: dict[str, list[str]]
) -> dict[str, int]:
    """Reclaim common words mis-bucketed as ``proper_noun``.

    spaCy PROPN-tags capitalised common words, so kinship terms (``mommy``),
    personified animals (``rabbit``) and interjections hide among the names. A
    ``proper_noun`` lemma is reclaimed iff it has an ESPDIC anchor (i.e. it is a
    translatable common word); true names (``timmy``, ``ben``) have none. Return
    ``{lemma: summed_frequency}``.
    """
    reclaimed: dict[str, int] = defaultdict(int)
    for r in rows:
        if r.get("bucket") != "proper_noun":
            continue
        lemma = (r.get("lemma") or r["token"]).strip().lower()
        if lemma in reverse_index:
            reclaimed[lemma] += int(r["frequency"])
    return dict(reclaimed)


def uk_to_us(word: str) -> str:
    """Fold a British spelling to its American form (unchanged if not British).

    A surface-only candidate generator (no lexicon knowledge): it may over-produce
    non-words (``surprise``->``surprize``, ``genre``->``gener``); callers must guard
    the result against the lexicon/ESPDIC. The ``min_stem_len`` on each rule blocks
    the shortest false folds (``pre``, ``tore``, ``acre`` under ``-re``->``-er``).
    """
    if word in _UK_US_EXPLICIT:
        return _UK_US_EXPLICIT[word]
    for uk, us, min_stem in _UK_US_SUFFIX:
        if word.endswith(uk) and len(word) - len(uk) >= min_stem:
            return word[: -len(uk)] + us
    return word


def split_british_spellings(
    lemmas: dict[str, int],
    en_words: set[str],
    reverse_index: dict[str, list[str]],
) -> tuple[dict[str, int], list[dict[str, object]]]:
    """Separate British-spelling variants from the genuine-gap lemmas.

    Returns ``(remaining, british)`` where *remaining* is the lemma->freq map
    with British variants removed and their US form folded in (so the concept is
    authored under the US spelling), and *british* is a list of dicts
    ``{uk_form, us_form, total_freq, us_in_lexicon}`` for the spelling map.
    """
    remaining: dict[str, int] = dict(lemmas)
    british: list[dict[str, object]] = []
    for lemma, freq in list(lemmas.items()):
        us = uk_to_us(lemma)
        if us == lemma:
            continue
        # Guard against over-eager folds: the -our->-or rule would otherwise
        # mangle plain words (sour->sor, detour->detor) and silently drop them.
        # Only a fold whose US form is a real word (covered or in ESPDIC) is a
        # genuine British variant; anything else stays a normal gap lemma.
        if us not in en_words and us not in reverse_index:
            continue
        us_in_lexicon = us in en_words
        british.append(
            {
                "uk_form": lemma,
                "us_form": us,
                "total_freq": freq,
                "us_in_lexicon": us_in_lexicon,
            }
        )
        remaining.pop(lemma, None)
        # If the US form is neither already covered nor separately in the queue,
        # fold this frequency onto it so the underlying concept still gets a row.
        if not us_in_lexicon and us not in remaining and us in reverse_index:
            remaining[us] = remaining.get(us, 0) + freq
    return remaining, british


# ---------------------------------------------------------------------------
# Phase 2 — propose an Esperanto anchor
# ---------------------------------------------------------------------------


@dataclass
class AnchorProposal:
    """A proposed Esperanto anchor for one English gap lemma."""

    action: str = ""  # LINK | NEW | "" (no_match)
    eo_root: str = ""
    eo_word: str = ""
    eo_gloss: str = ""
    component_roots: list[str] = field(default_factory=list)
    alt_candidates: list[str] = field(default_factory=list)
    flag: str = "no_match"


def propose_anchor(
    lemma: str,
    reverse_index: dict[str, list[str]],
    forward_gloss: dict[str, str],
    decomposer,
    existing_roots: set[str],
) -> AnchorProposal:
    """Choose the best Esperanto anchor for *lemma* and mark LINK vs NEW.

    Selection is by **sense quality, not link-bias**: candidates are ranked
    non-compound-first then shortest headword. (Preferring a candidate merely
    because its root already exists picks the wrong sense — ``hop`` would link
    to ``danc`` "dance" instead of anchoring on ``hopi``.) The anchor stem is
    ``strip_flexion(headword)`` — the meaning-bearing derived stem
    (``brakumi``→``brakum``), never the over-reduced bare root (``brak`` "arm").

    ``action`` is LINK iff that stem already exists as a ``concept.eo_root``,
    else NEW. Flags: ``no_match`` (only multi-word / no candidates — needs
    manual anchoring), ``compound`` (decomposer sees ≥2 roots — verify the
    component split), else ``ok``. Alternative senses are NOT flagged (that
    fired on benign synonymy for half the queue); the ``alt_candidates`` column
    carries them so the reviewer can sense-check the pick directly.
    """
    heads = reverse_index.get(lemma, [])
    single = [h for h in heads if " " not in h]
    multi = [h for h in heads if " " in h]

    if not single:
        return AnchorProposal(
            flag="no_match",
            alt_candidates=multi[:5],
            eo_gloss=forward_gloss.get(multi[0], "") if multi else "",
        )

    decs = [(h, decomposer.decompose_word(h)) for h in single]
    decs.sort(key=lambda hd: (hd[1].is_compound, len(hd[0]), hd[0]))

    h, d = decs[0]
    stem = strip_flexion(h)
    is_comp = d.is_compound
    return AnchorProposal(
        action="LINK" if stem in existing_roots else "NEW",
        eo_root=stem,
        eo_word=h,
        eo_gloss=forward_gloss.get(h, ""),
        component_roots=[cr.root for cr in d.content_roots] if is_comp else [],
        alt_candidates=[x for x in single if x != h][:5],
        flag="compound" if is_comp else "ok",
    )


# ---------------------------------------------------------------------------
# Lexicon loading (READ-ONLY)
# ---------------------------------------------------------------------------


def load_existing_roots(lexicon_db: Path) -> set[str]:
    """Return the set of distinct non-null ``concept.eo_root`` stems."""
    conn = sqlite3.connect(lexicon_db)
    try:
        return {
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT eo_root FROM concept WHERE eo_root IS NOT NULL"
            )
        }
    finally:
        conn.close()


def load_en_words(lexicon_db: Path) -> set[str]:
    """Return every lowercased English ``concept_lang.word``."""
    conn = sqlite3.connect(lexicon_db)
    try:
        return {
            r[0].lower()
            for r in conn.execute(
                "SELECT word FROM concept_lang WHERE lang = 'en'"
            )
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def _write_tsv(path: Path, header: list[str], rows: list[list[object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow(header)
        w.writerows(rows)


def build_worksheet_rows(
    consolidated: dict[str, int],
    reclaimed: set[str],
    reverse_index: dict[str, list[str]],
    forward_gloss: dict[str, str],
    decomposer,
    existing_roots: set[str],
) -> list[list[object]]:
    """Assemble the authoring-worksheet rows, ranked by frequency descending."""
    rows: list[list[object]] = []
    for lemma, freq in sorted(consolidated.items(), key=lambda kv: (-kv[1], kv[0])):
        a = propose_anchor(
            lemma, reverse_index, forward_gloss, decomposer, existing_roots
        )
        notes = []
        if lemma in reclaimed:
            notes.append("reclaimed from proper_noun — confirm not a name")
        rows.append(
            [
                lemma,
                freq,
                a.action,
                a.eo_root,
                a.eo_word,
                a.eo_gloss,
                "+".join(a.component_roots),
                DEFAULT_TIER,
                DEFAULT_CEFR,
                ", ".join(a.alt_candidates),
                a.flag,
                "; ".join(notes),
            ]
        )
    return rows


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--triaged", required=True, type=Path)
    parser.add_argument("--lexicon", required=True, type=Path)
    parser.add_argument("--espdic", required=True, type=Path)
    parser.add_argument("--inventory", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args(argv)

    rows = read_triaged(args.triaged.expanduser())
    reverse_index, forward_gloss = parse_espdic(
        args.espdic.expanduser().read_text(encoding="utf-8")
    )
    existing_roots = load_existing_roots(args.lexicon.expanduser())
    en_words = load_en_words(args.lexicon.expanduser())
    decomposer = Decomposer(load_inventory(args.inventory.expanduser()))

    # Phase 1 -----------------------------------------------------------------
    gap = consolidate_common_gap(rows)
    reclaimed = reclaim_proper_nouns(rows, reverse_index)
    for lemma, freq in reclaimed.items():
        gap[lemma] = gap.get(lemma, 0) + freq
    consolidated, british = split_british_spellings(gap, en_words, reverse_index)

    out = args.out_dir.expanduser()

    _write_tsv(
        out / "consolidated_gap_lemmas.tsv",
        ["lemma", "total_freq", "origin", "has_anchor"],
        [
            [
                lemma,
                freq,
                "reclaimed" if lemma in reclaimed else "common_gap",
                "yes"
                if any(" " not in h for h in reverse_index.get(lemma, []))
                else "no",
            ]
            for lemma, freq in sorted(
                consolidated.items(), key=lambda kv: (-kv[1], kv[0])
            )
        ],
    )

    _write_tsv(
        out / "british_spellings.tsv",
        ["uk_form", "us_form", "total_freq", "us_in_lexicon"],
        [
            [b["uk_form"], b["us_form"], b["total_freq"],
             "yes" if b["us_in_lexicon"] else "no"]
            for b in sorted(british, key=lambda b: -int(b["total_freq"]))
        ],
    )

    worksheet = build_worksheet_rows(
        consolidated, set(reclaimed), reverse_index, forward_gloss,
        decomposer, existing_roots,
    )
    _write_tsv(out / "authoring_worksheet.tsv", WORKSHEET_COLUMNS, worksheet)

    # Summary -----------------------------------------------------------------
    from collections import Counter

    actions = Counter(r[2] or "no_match" for r in worksheet)
    flags = Counter(r[10] for r in worksheet)
    print(f"consolidated gap lemmas : {len(consolidated)}")
    print(f"  reclaimed from proper_noun: {len(reclaimed)}")
    print(f"  british spellings split off: {len(british)}")
    print(f"worksheet rows          : {len(worksheet)}")
    print(f"  actions: {dict(actions)}")
    print(f"  flags  : {dict(flags)}")
    print(f"\nWritten to {out}/:")
    for name in (
        "consolidated_gap_lemmas.tsv",
        "authoring_worksheet.tsv",
        "british_spellings.tsv",
    ):
        print(f"  {name}")
    print("\nSTOP — human review gate. No DB writes performed.")


if __name__ == "__main__":
    main()
