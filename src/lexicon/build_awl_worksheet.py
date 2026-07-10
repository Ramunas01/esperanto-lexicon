#!/usr/bin/env python3
"""Build the Tier-3 AWL anchor worksheet (Phases 1-2, NO DB writes).

Grows the near-empty Tier 3 by *assembly* of the **Academic Word List** (AWL,
Coxhead 2000) — a curated, domain-general formal vocabulary — rather than by
corpus discovery. This module reuses the common-lexicon gap-fill anchor logic
(``build_gapfill_worksheet.parse_espdic`` / ``propose_anchor`` /
``load_existing_roots`` and the shared ``eo_root_decomposer``); it does NOT fork
a second anchor pipeline and writes nothing to ``lexicon_v2.db``.

Efficiency model (the whole point): the reviewer approves ONE Esperanto anchor
per AWL **family head** (``analyse`` → ``analiz``); the family's member forms
(``analysis``, ``analytical``, ``analyst`` …) all attach to that one concept in
Phase 4. So ~570 review decisions cover ~3,000 English lemmas. The worksheet is
therefore **one row per family** (≈570 rows), with the member forms carried in
cells.

LOCKED design (PM ruling, implemented in Phase 4, previewed here):
  * A family = ONE ``concept`` carrying N EN ``concept_lang`` rows at ``tier=3``,
    ``source='awl_t3'`` — NOT N concepts.
  * Head: **LINK** to an existing concept when the EN head word already exists, or
    when the proposed ``eo_root`` already anchors a concept; else **NEW**.
  * Members: each an insert-only ``concept_lang`` row on the family concept; the
    ``(concept_id, lang, word, pos)`` UNIQUE key is the idempotency guard.
  * INVARIANT held in Phase 4 by ``apply_gapfill_merge.author_concept``:
    ``concept.eo_root`` == the ``concept_root`` head root (derived from the
    decomposition, never a stale stem).

Phase 1 (acquire & normalise): read the vendored, invariant-validated AWL
(``data/awl/awl_coxhead.json`` — 570 families / 10 sublists / 3,107 forms; see
``data/awl/SOURCE.md``). Produce, per family: head, sublist (1-10, a carried
frequency-priority signal), member lemmas, POS per form.

Phase 2 (anchor worksheet): reverse-ESPDIC-lookup each head → proposed
``eo_root`` / ``eo_word`` / ``eo_gloss``; mark LINK vs NEW; flag
``ok`` / ``compound`` / ``no_match``; list which member forms are new vs already
present (with their tier); run a junk sanity gate. Emit
``data/analysis/tier3/awl_worksheet.tsv`` and **STOP** — the worksheet is the
human review gate.

Usage::

    python3 src/lexicon/build_awl_worksheet.py \\
        --awl data/awl/awl_coxhead.json \\
        --lexicon data/lexicon_db/lexicon_v2.db \\
        --espdic data/lexicon_db/espdic.txt \\
        --inventory data/lexicon_db/eo_inventory.json \\
        --out data/analysis/tier3/awl_worksheet.tsv
"""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_gapfill_worksheet import (  # noqa: E402
    load_existing_roots,
    parse_espdic,
    propose_anchor,
    uk_to_us,
)
from eo_root_decomposer import Decomposer, load_inventory  # noqa: E402

# Insert-only provenance + tier defaults for every AWL row (reviewer may override).
SOURCE_TAG = "awl_t3"
DEFAULT_TIER = 3
DEFAULT_CEFR = "C1"  # academic/formal register; reviewer may down-flag to B2/T2

WORKSHEET_COLUMNS = [
    "sublist",         # 1-10 (frequency band; carried, not acted on)
    "family_head",     # AWL family head (en)
    "action",          # LINK | NEW | "" (needs manual anchor)
    "eo_root",         # proposed anchor stem
    "eo_word",         # proposed EO headword
    "eo_gloss",        # ESPDIC gloss of eo_word
    "flag",            # ok | compound | no_match
    "head_pos",        # POS of the head form
    "head_in_lexicon", # existing tier(s) of the EN head, or "no"
    "n_forms",         # head + members, after junk gate
    "n_new",           # forms not yet in the lexicon (will be inserted)
    "n_present",       # forms already present (will be skipped)
    "forms_new",       # "lemma:POS;..." — the rows Phase 4 will insert
    "forms_present",   # "lemma(tier);..." — already covered, skipped
    "component_roots", # for compounds: the decomposed roots
    "alt_candidates",  # other ESPDIC EO candidates for the head (sense check)
    "proposed_tier",   # 3
    "cefr",            # C1
    "decision",        # [Ramunas] approve | hold | reject
    "notes",
]

# ---------------------------------------------------------------------------
# POS tagging
#
# Isolated-word POS is hard: spaCy reliably tags bare roots (derive->VERB,
# area->NOUN) but mislabels many suffix-marked derived forms as PROPN
# (analyse->PROPN, analytical->PROPN). The AWL is overwhelmingly Latinate and
# heavily suffix-marked, so a small high-precision morphological tagger handles
# exactly the forms spaCy trips on, and spaCy is the fallback for the residue
# (bare roots), with NOUN as the last resort. POS is reviewer-checkable in the
# worksheet and not resolution-critical, so this pragmatic split is sufficient.
# ---------------------------------------------------------------------------

# Order: most specific first. Adverb suffixes are the *adverb-forming* ones only,
# so non-adverbs ending in -ly (supply, apply, rely, family, anomaly, assembly)
# are NOT caught and fall through to spaCy.
_ADV_SUFFIXES = ("ically", "ally", "antly", "ently", "ively", "ously",
                 "fully", "lessly", "ingly", "edly", "ibly", "ably")
_NOUN_SUFFIXES = (" isation", "ization", "tion", "sion", "ment", "ness", "ity",
                  "ance", "ence", "ency", "ancy", " ship", "ship", "ism", "ist",
                  "ure", "ee")
_VERB_SUFFIXES = ("ise", "ize", "ify", "yse", "yze")
# NB: '-ive' is deliberately NOT here — it is genuinely ambiguous (derive/survive
# are verbs; perspective/objective/initiative are nouns; effective/creative are
# adjectives). spaCy disambiguates these from lexical stats far better than a
# blanket rule, so -ive words fall through to the spaCy fallback.
_ADJ_SUFFIXES = ("ical", "ous", "able", "ible", "ful", "less")


def morphological_pos(word: str) -> Optional[str]:
    """High-precision POS from an English derivational suffix, or ``None``.

    Only suffixes with low noun/verb/adj ambiguity are used; ambiguous endings
    (``-al``, ``-ate``, ``-ic``, ``-ary``, ``-ant``, ``-ent``) are deliberately
    left to the spaCy fallback. Returns a coarse UD tag (NOUN/VERB/ADJ/ADV).
    """
    w = word.lower()
    if len(w) < 4:
        return None
    for suf in _ADV_SUFFIXES:
        if w.endswith(suf.strip()):
            return "ADV"
    for suf in _NOUN_SUFFIXES:
        if w.endswith(suf.strip()):
            return "NOUN"
    for suf in _VERB_SUFFIXES:
        if w.endswith(suf):
            return "VERB"
    for suf in _ADJ_SUFFIXES:
        if w.endswith(suf):
            return "ADJ"
    return None


PosTagger = Callable[[str], str]


def make_pos_tagger(spacy_model: object | None = None) -> PosTagger:
    """Return a POS tagger: morphology first, then spaCy, then NOUN.

    ``spacy_model`` is an optional preloaded spaCy pipeline (injected so callers
    and tests control model loading). When ``None``, the tagger uses morphology
    only and defaults the residue to NOUN — no spaCy dependency at import time.
    """

    def tag(word: str) -> str:
        pos = morphological_pos(word)
        if pos:
            return pos
        if spacy_model is not None:
            doc = spacy_model(word)
            if doc and doc[0].pos_ not in ("PROPN", "X", "SPACE", "NUM"):
                return doc[0].pos_
        return "NOUN"

    return tag


def load_spacy_tagger() -> PosTagger:
    """Production tagger: morphology + ``en_core_web_sm`` fallback."""
    import spacy  # local import; not needed for the pure logic or tests

    nlp = spacy.load("en_core_web_sm", disable=["parser", "ner", "lemmatizer"])
    return make_pos_tagger(nlp)


# ---------------------------------------------------------------------------
# Phase 1 — acquire & normalise the AWL
# ---------------------------------------------------------------------------


@dataclass
class Family:
    """One AWL word family: a head, its sublist, and its member forms."""

    head: str
    sublist: int
    members: tuple[str, ...]  # excludes the head; lowercased, deduped, sorted

    @property
    def forms(self) -> tuple[str, ...]:
        """All forms (head first, then members) — the lemmas that gain T3 rows."""
        return (self.head, *self.members)


# Unicode hyphens/dashes the AWL source uses in place of ASCII '-'
# (e.g. U+2011 non-breaking hyphen in ``co‑ordinate``, ``co‑operate``). These are
# real words, not junk — fold them to ASCII '-' before the gate so the family and
# its members survive.
_HYPHENS = ("‐", "‑", "‒", "–", "—", "−")


def normalize_form(word: str) -> str:
    """Lowercase, strip, and fold Unicode hyphens/dashes to ASCII '-'."""
    w = word.strip().lower()
    for h in _HYPHENS:
        w = w.replace(h, "-")
    return w


def _is_clean_form(word: str) -> bool:
    """Junk gate: keep only real alphabetic lemmas (drop artifacts/fragments).

    Assumes *word* is already ``normalize_form``-ed. Allows internal hyphens
    (``co-operate``) but requires ≥2 alphabetic characters and no digits/symbols.
    Single letters and empty strings are rejected.
    """
    w = word
    if len(w) < 2:
        return False
    core = w.replace("-", "")
    return core.isalpha() and len(core) >= 2


def load_awl_families(path: Path) -> tuple[list[Family], dict[str, int]]:
    """Parse the vendored AWL JSON into families; apply the junk gate.

    Returns ``(families, dropped)`` where ``families`` is sorted by
    ``(sublist, head)`` and ``dropped`` maps any rejected raw form to its family
    head (empty when the source is clean, as the vetted AWL is). The head is
    removed from its own member list; members are lowercased, deduped, sorted.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    families: list[Family] = []
    dropped: dict[str, int] = {}
    for sl_key, fams in data.items():
        # keys look like "sublist_1" .. "sublist_10"
        sublist = int(str(sl_key).split("_")[-1])
        for head, obj in fams.items():
            head_l = normalize_form(head)
            if not _is_clean_form(head_l):
                dropped[head] = sublist
                continue
            raw_members = (obj or {}).get("subwords") or []
            members: list[str] = []
            for m in raw_members:
                ml = normalize_form(str(m))
                if not _is_clean_form(ml):
                    dropped[m] = sublist
                    continue
                if ml != head_l and ml not in members:
                    members.append(ml)
            families.append(
                Family(head=head_l, sublist=sublist, members=tuple(sorted(members)))
            )
    families.sort(key=lambda f: (f.sublist, f.head))
    return families, dropped


# ---------------------------------------------------------------------------
# Lexicon loading (READ-ONLY) — tiers for de-dupe/LINK-vs-NEW
# ---------------------------------------------------------------------------


def load_en_word_tiers(lexicon_db: Path) -> dict[str, list[int]]:
    """Map each lowercased EN ``concept_lang.word`` to its sorted distinct tiers.

    A word already carrying a tier is 'present'; the LINK/NEW classifier and the
    per-member skip logic read this. ``NULL`` tiers are recorded as ``-1`` so a
    present-but-untiered row is still distinguishable from absent.
    """
    conn = sqlite3.connect(lexicon_db)
    try:
        tiers: dict[str, set[int]] = {}
        for word, tier in conn.execute(
            "SELECT LOWER(word), tier FROM concept_lang WHERE lang='en'"
        ):
            tiers.setdefault(word, set()).add(tier if tier is not None else -1)
        return {w: sorted(t) for w, t in tiers.items()}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Phase 2 — build the worksheet (one row per family)
# ---------------------------------------------------------------------------


# British spelling folds the gap-fill's uk_to_us does not cover, but which block
# an ESPDIC anchor: bare -ise/-yse verb infinitives, -isation, and -nce nouns.
# Applied ONLY to find an anchor — the stored EN words keep their AWL spelling and
# the family already carries the US variants as members.
_EXTRA_UK_US = (
    ("isation", "ization"), ("ise", "ize"), ("ised", "ized"), ("ising", "izing"),
    ("yse", "yze"), ("ysed", "yzed"), ("ysing", "yzing"), ("nce", "nse"),
)


def us_spelling_variants(word: str) -> list[str]:
    """Candidate US spellings to try for anchor lookup (original first, deduped).

    Over-generation is safe: a variant is only used if it actually resolves to an
    ESPDIC anchor, so a spurious candidate simply fails and is discarded.
    """
    cands = [word]
    folded = uk_to_us(word)  # gap-fill folds: -our/-ising/-ised/-tre/explicit
    if folded != word:
        cands.append(folded)
    for uk, us in _EXTRA_UK_US:
        if word.endswith(uk) and len(word) > len(uk):
            cand = word[: -len(uk)] + us
            if cand not in cands:
                cands.append(cand)
    return cands


@dataclass
class FamilyRow:
    """The computed worksheet row for one family (mirrors WORKSHEET_COLUMNS)."""

    family: Family
    action: str
    eo_root: str
    eo_word: str
    eo_gloss: str
    flag: str
    head_pos: str
    head_tiers: list[int]  # existing tiers of the EN head ([] if absent)
    forms_new: list[tuple[str, str]]  # (lemma, pos) not yet present
    forms_present: list[tuple[str, list[int]]]  # (lemma, tiers) already present
    component_roots: list[str] = field(default_factory=list)
    alt_candidates: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _fmt_tiers(tiers: list[int]) -> str:
    """Render a tier list for display (``-1`` = present but untiered)."""
    return "/".join("∅" if t == -1 else str(t) for t in tiers)


def classify_family(
    family: Family,
    reverse_index: dict[str, list[str]],
    forward_gloss: dict[str, str],
    decomposer: Decomposer,
    existing_roots: set[str],
    en_tiers: dict[str, list[int]],
    pos_tagger: PosTagger,
) -> FamilyRow:
    """Compute the worksheet row for one family (pure; no I/O).

    The Esperanto anchor comes from the shared ``propose_anchor`` (reverse-ESPDIC,
    sense-quality ranked). Action is **LINK** when the EN head already exists or
    the proposed root already anchors a concept, else **NEW**; a head with no
    ESPDIC anchor and not already in the lexicon is left blank (``no_match`` —
    needs a manual anchor). Members are split into new vs already-present (with
    their tiers) so Phase 4 skips what exists.
    """
    # Try the head, then US-spelling variants, and keep the first that anchors
    # (British -ise/-yse/-our/-nce spellings otherwise miss the ESPDIC index).
    variants = us_spelling_variants(family.head)
    a = propose_anchor(
        family.head, reverse_index, forward_gloss, decomposer, existing_roots
    )
    anchored_via = ""
    if a.flag == "no_match":
        for cand in variants[1:]:
            alt = propose_anchor(
                cand, reverse_index, forward_gloss, decomposer, existing_roots
            )
            if alt.flag != "no_match":
                a, anchored_via = alt, cand
                break
    head_tiers = en_tiers.get(family.head, [])
    eo_root_exists = bool(a.eo_root) and a.eo_root in existing_roots

    if head_tiers or eo_root_exists:
        action = "LINK"
    elif a.flag == "no_match":
        action = ""  # no anchor and not present — reviewer must anchor manually
    else:
        action = "NEW"

    forms_new: list[tuple[str, str]] = []
    forms_present: list[tuple[str, list[int]]] = []
    for form in family.forms:
        tiers = en_tiers.get(form)
        if tiers:
            forms_present.append((form, tiers))
        else:
            forms_new.append((form, pos_tagger(form)))

    notes: list[str] = []
    if anchored_via:
        notes.append(f"anchored via US spelling ({family.head}→{anchored_via})")
    if action == "LINK" and head_tiers:
        notes.append(f"head already in lexicon (tier {_fmt_tiers(head_tiers)})")
    if a.flag == "ok" and len(a.alt_candidates) >= 3:
        notes.append("multiple EO senses — verify anchor")
    if not family.members:
        notes.append("single-form family (head only)")

    head_pos = next((p for f, p in forms_new if f == family.head), "")
    if not head_pos:  # head already present -> still show a POS guess for review
        head_pos = pos_tagger(family.head)

    return FamilyRow(
        family=family,
        action=action,
        eo_root=a.eo_root,
        eo_word=a.eo_word,
        eo_gloss=a.eo_gloss,
        flag=a.flag,
        head_pos=head_pos,
        head_tiers=head_tiers,
        forms_new=forms_new,
        forms_present=forms_present,
        component_roots=a.component_roots,
        alt_candidates=a.alt_candidates,
        notes=notes,
    )


def row_to_cells(row: FamilyRow) -> list[object]:
    """Render a :class:`FamilyRow` to worksheet cells (order = WORKSHEET_COLUMNS)."""
    f = row.family
    return [
        f.sublist,
        f.head,
        row.action,
        row.eo_root,
        row.eo_word,
        row.eo_gloss,
        row.flag,
        row.head_pos,
        _fmt_tiers(row.head_tiers) if row.head_tiers else "no",
        len(f.forms),
        len(row.forms_new),
        len(row.forms_present),
        ";".join(f"{w}:{p}" for w, p in row.forms_new),
        ";".join(f"{w}({_fmt_tiers(t)})" for w, t in row.forms_present),
        "+".join(row.component_roots),
        ", ".join(row.alt_candidates),
        DEFAULT_TIER,
        DEFAULT_CEFR,
        "",  # decision — for Ramunas
        "; ".join(row.notes),
    ]


def build_rows(
    families: list[Family],
    reverse_index: dict[str, list[str]],
    forward_gloss: dict[str, str],
    decomposer: Decomposer,
    existing_roots: set[str],
    en_tiers: dict[str, list[int]],
    pos_tagger: PosTagger,
) -> list[FamilyRow]:
    """Compute all family rows (sublist-ordered, as ``families`` arrives)."""
    return [
        classify_family(
            fam, reverse_index, forward_gloss, decomposer,
            existing_roots, en_tiers, pos_tagger,
        )
        for fam in families
    ]


def write_worksheet(rows: list[FamilyRow], path: Path) -> None:
    """Write the worksheet TSV (emit a fresh file the reviewer copies to .xlsx)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow(WORKSHEET_COLUMNS)
        for r in rows:
            w.writerow(row_to_cells(r))


def summarise(rows: list[FamilyRow]) -> dict[str, object]:
    """Report counts for the memo: actions, flags, recall, forms covered."""
    from collections import Counter

    actions = Counter(r.action or "(manual)" for r in rows)
    flags = Counter(r.flag for r in rows)
    n_families = len(rows)
    anchored = sum(1 for r in rows if r.flag != "no_match")
    forms_new = sum(len(r.forms_new) for r in rows)
    forms_present = sum(len(r.forms_present) for r in rows)
    return {
        "families": n_families,
        "actions": dict(actions),
        "flags": dict(flags),
        "espdic_recall_pct": round(100.0 * anchored / n_families, 1) if n_families else 0.0,
        "forms_total": forms_new + forms_present,
        "forms_new": forms_new,
        "forms_present": forms_present,
    }


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parents[2]
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--awl", type=Path, default=root / "data" / "awl" / "awl_coxhead.json")
    ap.add_argument("--lexicon", type=Path, default=root / "data" / "lexicon_db" / "lexicon_v2.db")
    ap.add_argument("--espdic", type=Path, default=root / "data" / "lexicon_db" / "espdic.txt")
    ap.add_argument("--inventory", type=Path, default=root / "data" / "lexicon_db" / "eo_inventory.json")
    ap.add_argument("--out", type=Path, default=root / "data" / "analysis" / "tier3" / "awl_worksheet.tsv")
    ap.add_argument("--no-spacy", action="store_true", help="morphology-only POS (skip spaCy fallback)")
    args = ap.parse_args(argv)

    families, dropped = load_awl_families(args.awl.expanduser())
    reverse_index, forward_gloss = parse_espdic(
        args.espdic.expanduser().read_text(encoding="utf-8")
    )
    existing_roots = load_existing_roots(args.lexicon.expanduser())
    en_tiers = load_en_word_tiers(args.lexicon.expanduser())
    decomposer = Decomposer(load_inventory(args.inventory.expanduser()))
    pos_tagger = make_pos_tagger(None) if args.no_spacy else load_spacy_tagger()

    rows = build_rows(
        families, reverse_index, forward_gloss, decomposer,
        existing_roots, en_tiers, pos_tagger,
    )
    write_worksheet(rows, args.out.expanduser())

    s = summarise(rows)
    print(f"AWL families            : {s['families']}")
    print(f"  actions               : {s['actions']}")
    print(f"  flags                 : {s['flags']}")
    print(f"  ESPDIC recall         : {s['espdic_recall_pct']}%  (anchored / families)")
    print(f"forms (head+members)    : {s['forms_total']}  "
          f"(new {s['forms_new']} / already present {s['forms_present']})")
    if dropped:
        print(f"junk-gate dropped       : {len(dropped)} -> {dict(list(dropped.items())[:8])}")
    print(f"\nwrote {args.out}  ({len(rows)} rows) — STOP: human review gate (Phase 3).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
