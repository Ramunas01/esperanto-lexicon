#!/usr/bin/env python3
"""A1 — consolidate the 666 candidate_gaps into a distinct-concept review worksheet.

Turns the raw per-root `candidate_gaps.tsv` (PR #14) into a per-*concept* worksheet
for the human gate: dedupe multiple roots that gloss one English word, mark derived
`-ic/-al` adjectives (whose noun is the anchor), and flag each concept by its likely
**R9 direction of travel** so the reviewer's attention goes to the held subset, not
the clearly-common bulk. **No DB writes** — this emits the worksheet and stops.

R9 direction flags (roadmap R9 — direction, not raw commonness, is the sorting key):
  * ``common``          — everyday, general-adult → place into T1–T3.
  * ``domain-adjacent`` — recognised but leans T4 (military ranks, `naval`,
                          `genetic`, `agriculture`) → hold for domain review.
  * ``register-marked`` — frequent but not neutral (`damn`, `gay`) → hold.
  * ``archaic``         — backward-facing → philology-T4 when Effort B builds it.
The flags are **heuristic proposals** (curated whole-word lists + gloss cues); the
human review confirms/fixes them. `common` is the near-auto-approve bulk.

Anchor + tier proposal per concept:
  * anchor root = the collapsed roots' best (ESPDIC core over extended, higher
    productivity, then shorter); all collapsed roots are shown for review.
  * eo_word = anchor root + a POS ending from the gloss (verb→i, adjective→a,
    noun→o). The A3 merge derives ``concept.eo_root`` from the decomposition head of
    this eo_word, so the ending never breaks the invariant.
  * tier = T2 when the gloss zipf ≥ 4.5, else T3-general (held rows get no tier).
"""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

# --- R9 flag heuristics (curated; whole-word matches against the gloss) ------

# Vulgar / sexual / identity / expletive — frequent but not register-neutral.
REGISTER_MARKED = frozenset({
    "damn", "fuck", "shit", "ass", "arse", "bitch", "whore", "slut", "gigolo",
    "prostitute", "penis", "vagina", "dick", "cock", "piss", "gay", "homosexual",
    "queer", "lesbian", "erotic", "obscene", "vulgar", "bastard", "crap", "fart",
    "horny", "nude", "randy", "lewd",
})

# Recognised by a general adult but leaning Tier-4 (military / hard-science /
# political-institutional). Held for domain review.
DOMAIN_ADJACENT = frozenset({
    # military / naval
    "colonel", "lieutenant", "admiral", "corporal", "sergeant", "brigadier",
    "cadet", "marshal", "commodore", "ensign", "regiment", "battalion",
    "artillery", "cavalry", "infantry", "garrison", "naval", "nautical",
    "military", "musketeer", "grenadier", "bayonet",
    # hard science
    "molecular", "genetic", "atomic", "isotope", "magnetic", "anatomical",
    "chromosome", "enzyme", "protein", "voltage",
    # political / institutional
    "parliamentary", "senatorial", "diplomatic", "imperial", "ecclesiastical",
    "agronomy", "agriculture", "agricultural",
})

# Gloss cues that a root is backward-facing / scholarly.
ARCHAIC_MARKERS = frozenset({"archaic", "obsolete", "dated", "poetic", "dialectal"})

_ADJ_SUFFIXES = ("ical", "ic", "ial", "ian", "ary", "ous", "ive", "al", "ary")


_LEADING_FUNCTION = ("to", "a", "an", "the", "of", "be", "one's", "someone", "something")


def gloss_tokens(gloss: str) -> list[str]:
    """Lowercased alphabetic word tokens of a gloss (for whole-word matching)."""
    out: list[str] = []
    for raw in gloss.replace("/", " ").replace(",", " ").replace(";", " ").split():
        w = raw.strip(".!?\"'()").lower()
        if w.isalpha():
            out.append(w)
    return out


def gloss_head(gloss: str) -> str:
    """First *content* word of a gloss (leading `to`/articles stripped)."""
    toks = gloss_tokens(gloss)
    i = 0
    while i < len(toks) and toks[i] in _LEADING_FUNCTION:
        i += 1
    if i < len(toks):
        return toks[i]
    return toks[0] if toks else ""


def flag_direction(gloss_head: str, gloss: str) -> str:
    """Propose an R9 direction flag for a concept (heuristic; human confirms)."""
    toks = set(gloss_tokens(gloss)) | {gloss_head.lower()}
    if toks & ARCHAIC_MARKERS:
        return "archaic"
    if toks & REGISTER_MARKED:
        return "register-marked"
    if toks & DOMAIN_ADJACENT:
        return "domain-adjacent"
    return "common"


def is_derived_adjective(head: str) -> bool:
    """True if the English head looks like a derived `-ic/-al/...` adjective.

    Requires ≥3 chars of stem before the suffix, so `naval`/`toxic` count while
    short false hits (`gal`, `mic`) do not.
    """
    h = head.lower()
    return any(h.endswith(s) and len(h) - len(s) >= 3 for s in _ADJ_SUFFIXES)


def pos_and_ending(gloss_head: str, gloss: str) -> tuple[str, str]:
    """Coarse EO POS + word ending from the gloss (verb→i, adjective→a, noun→o)."""
    if gloss.strip().lower().startswith("to "):
        return "VERB", "i"
    h = gloss_head.lower()
    if is_derived_adjective(h) or h.endswith(("ful", "less", "ed", "ing")):
        return "ADJ", "a"
    return "NOUN", "o"


def select_anchor(rows: list[dict]) -> tuple[str, list[str]]:
    """Pick the anchor root for a concept and return (anchor, all_roots_ranked).

    Preference: ESPDIC ``core`` over ``extended``, then higher productivity, then
    shorter root, then alphabetical. All collapsed roots are surfaced for review.
    """
    def key(r: dict):
        return (0 if r["inv_tier"] == "core" else 1,
                -int(r["prod"] or 0), len(r["root"]), r["root"])

    ranked = sorted(rows, key=key)
    return ranked[0]["root"], [r["root"] for r in ranked]


def propose_tier(gloss_zipf: float, flag: str) -> str:
    """Tier for a `common` concept (T2 if very common, else T3); held rows blank."""
    if flag != "common":
        return ""
    return "2" if gloss_zipf >= 4.5 else "3"


@dataclass
class ConceptRow:
    en_word: str
    anchor_root: str
    all_roots: list[str]
    eo_word: str
    eo_pos: str
    flag: str
    fold: str          # standalone | derived_adj
    proposed_tier: str
    gloss_zipf: float
    inv_tier: str
    prod: int
    gloss: str
    note: str = ""


WORKSHEET_COLUMNS = [
    "decision", "flag", "fold", "en_word", "anchor_root", "all_roots",
    "eo_word", "eo_pos", "proposed_tier", "gloss_zipf", "inv_tier", "prod",
    "gloss", "note",
]


def consolidate(rows: list[dict]) -> list[ConceptRow]:
    """Collapse per-root rows into per-concept rows (deduped, flagged, anchored)."""
    by_head: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_head[r["gloss_head"].strip().lower()].append(r)

    out: list[ConceptRow] = []
    for head, group in by_head.items():
        anchor, all_roots = select_anchor(group)
        # Use the anchor row's gloss/zipf/inv_tier for the concept.
        arow = next(r for r in group if r["root"] == anchor)
        gloss = arow["gloss"]
        zipf = float(arow["gloss_zipf"])
        flag = flag_direction(head, gloss)
        pos, ending = pos_and_ending(head, gloss)
        eo_word = anchor + ending
        fold = "derived_adj" if is_derived_adjective(head) else "standalone"
        notes: list[str] = []
        if len(all_roots) > 1:
            notes.append(f"{len(all_roots)} roots collapsed: {', '.join(all_roots)}")
        if fold == "derived_adj":
            notes.append("derived adjective — confirm noun anchor / eo_word")
        out.append(ConceptRow(
            en_word=head, anchor_root=anchor, all_roots=all_roots,
            eo_word=eo_word, eo_pos=pos, flag=flag, fold=fold,
            proposed_tier=propose_tier(zipf, flag), gloss_zipf=zipf,
            inv_tier=arow["inv_tier"], prod=int(arow["prod"] or 0),
            gloss=gloss, note="; ".join(notes),
        ))
    # Order: common first (the placeable bulk), then by commonness.
    flag_order = {"common": 0, "domain-adjacent": 1, "register-marked": 2, "archaic": 3}
    out.sort(key=lambda c: (flag_order.get(c.flag, 9), -c.gloss_zipf, c.en_word))
    return out


def write_worksheet(concepts: list[ConceptRow], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow(WORKSHEET_COLUMNS)
        for c in concepts:
            w.writerow([
                "", c.flag, c.fold, c.en_word, c.anchor_root, ",".join(c.all_roots),
                c.eo_word, c.eo_pos, c.proposed_tier, c.gloss_zipf, c.inv_tier,
                c.prod, c.gloss, c.note,
            ])


def summarise(concepts: list[ConceptRow]) -> dict:
    from collections import Counter

    flags = Counter(c.flag for c in concepts)
    common = [c for c in concepts if c.flag == "common"]
    common_tier = Counter(c.proposed_tier for c in common)
    return {
        "distinct_concepts": len(concepts),
        "by_flag": dict(flags),
        "common_by_proposed_tier": {t: common_tier.get(t, 0) for t in ("2", "3")},
        "derived_adj": sum(1 for c in concepts if c.fold == "derived_adj"),
    }


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parents[2]
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--candidate-gaps", type=Path,
                    default=root / "data" / "analysis" / "root_coverage" / "candidate_gaps.tsv")
    ap.add_argument("--out", type=Path,
                    default=root / "data" / "analysis" / "tier3_general" / "general_gap_worksheet.tsv")
    args = ap.parse_args(argv)

    with args.candidate_gaps.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh, delimiter="\t"))
    concepts = consolidate(rows)
    write_worksheet(concepts, args.out)

    s = summarise(concepts)
    print(f"raw candidate_gap rows      : {len(rows)}")
    print(f"distinct concepts (deduped) : {s['distinct_concepts']}")
    print(f"  by R9 flag                : {s['by_flag']}")
    print(f"  common by proposed tier   : {s['common_by_proposed_tier']}")
    print(f"  derived-adjective concepts: {s['derived_adj']}")
    print(f"\nwrote worksheet -> {args.out}  — STOP: human review gate (A2).")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
