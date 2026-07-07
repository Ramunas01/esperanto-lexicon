#!/usr/bin/env python3
"""Closed-set completeness audit (brief Part C).

The frequency queue only surfaces words TinyStories happened to use. Closed
categories (all fingers, all family terms, every colour) must be checked as
*wholes*. This enumerates canonical English members of curated closed sets,
checks presence in ``concept_lang(en)`` at Tier 1/2, and emits
``set_gaps.tsv`` (``set, member, in_lexicon, proposed_eo_anchor, eo_gloss``) so
the review agent can spot systematic holes ("siblings X, Y are also missing").

Read-only on the lexicon.
"""

from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import add_repo_src_to_path, default_paths  # noqa: E402

# Curated canonical members per closed set. Deliberately generous — a member
# absent from a child lexicon is exactly the finding we want.
SETS: dict[str, list[str]] = {
    "family": [
        "mother", "father", "mom", "dad", "mommy", "daddy", "parent", "sister",
        "brother", "sibling", "grandmother", "grandfather", "grandma", "grandpa",
        "aunt", "uncle", "cousin", "niece", "nephew", "son", "daughter", "child",
        "baby", "wife", "husband", "family",
    ],
    "body": [
        "head", "hair", "face", "eye", "ear", "nose", "mouth", "lip", "tooth",
        "tongue", "cheek", "chin", "neck", "shoulder", "arm", "elbow", "hand",
        "wrist", "finger", "thumb", "palm", "chest", "back", "stomach", "belly",
        "leg", "knee", "foot", "toe", "heel", "ankle", "hip", "skin", "bone",
        # the five fingers as a closed sub-set
        "forefinger", "pinky",
    ],
    "colours": [
        "red", "orange", "yellow", "green", "blue", "purple", "pink", "brown",
        "black", "white", "grey", "gray",
    ],
    "numbers": [
        "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
        "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
        "seventeen", "eighteen", "nineteen", "twenty", "thirty", "forty", "fifty",
        "sixty", "seventy", "eighty", "ninety", "hundred",
    ],
    "days": [
        "monday", "tuesday", "wednesday", "thursday", "friday", "saturday",
        "sunday",
    ],
    "months": [
        "january", "february", "march", "april", "may", "june", "july", "august",
        "september", "october", "november", "december",
    ],
    "weather": [
        "sun", "rain", "snow", "wind", "cloud", "storm", "fog", "ice", "sunny",
        "rainy", "cloudy", "windy", "hot", "cold", "warm", "wet", "dry",
        "thunder", "lightning", "rainbow",
    ],
    "animals": [
        "dog", "cat", "cow", "horse", "pig", "sheep", "goat", "chicken", "duck",
        "goose", "rabbit", "mouse", "rat", "bird", "fish", "frog", "bee", "ant",
        "spider", "fox", "wolf", "bear", "lion", "tiger", "elephant", "monkey",
        "giraffe", "zebra", "deer", "squirrel", "owl", "snake", "turtle",
        "whale", "dolphin", "shark", "butterfly",
    ],
    "motion_verbs": [
        "go", "come", "run", "walk", "jump", "hop", "skip", "climb", "crawl",
        "fly", "swim", "fall", "sit", "stand", "turn", "roll", "slide", "spin",
        "dance", "march", "throw", "catch", "push", "pull", "carry", "kick",
        "ride",
    ],
    "emotions": [
        "happy", "sad", "angry", "mad", "scared", "afraid", "glad", "excited",
        "surprised", "worried", "proud", "jealous", "shy", "lonely", "calm",
        "upset", "cheerful", "curious", "bored", "nervous", "brave",
    ],
}


def load_tier12_en(lexicon_db: Path) -> set[str]:
    """Lowercased English words present in ``concept_lang`` at Tier 1 or 2."""
    conn = sqlite3.connect(lexicon_db)
    try:
        return {
            r[0].lower()
            for r in conn.execute(
                "SELECT word FROM concept_lang WHERE lang='en' AND tier IN (1,2)"
            )
        }
    finally:
        conn.close()


def audit(sets: dict[str, list[str]], covered: set[str], propose) -> list[dict[str, str]]:
    """Return one result row per (set, member); ``propose`` supplies an anchor."""
    out: list[dict[str, str]] = []
    for set_name, members in sets.items():
        for member in members:
            present = member.lower() in covered
            anchor, gloss = ("", "")
            if not present:
                anchor, gloss = propose(member)
            out.append(
                {
                    "set": set_name,
                    "member": member,
                    "in_lexicon": "Y" if present else "N",
                    "proposed_eo_anchor": anchor,
                    "eo_gloss": gloss,
                }
            )
    return out


def main(argv: list[str] | None = None) -> None:
    p = default_paths()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--lexicon", type=Path, default=p["lexicon"])
    ap.add_argument("--espdic", type=Path, default=p["espdic"])
    ap.add_argument("--inventory", type=Path, default=p["inventory"])
    ap.add_argument("--out", type=Path, default=p["set_gaps"])
    args = ap.parse_args(argv)

    add_repo_src_to_path()
    from build_gapfill_worksheet import (  # noqa: E402
        load_existing_roots,
        parse_espdic,
        propose_anchor,
    )
    from eo_root_decomposer import Decomposer, load_inventory  # noqa: E402

    covered = load_tier12_en(args.lexicon)
    reverse, forward = parse_espdic(args.espdic.read_text(encoding="utf-8"))
    decomposer = Decomposer(load_inventory(args.inventory))
    existing = load_existing_roots(args.lexicon)

    def propose(member: str) -> tuple[str, str]:
        a = propose_anchor(member.lower(), reverse, forward, decomposer, existing)
        anchor = f"{a.eo_root}/{a.eo_word}" if a.eo_word else ""
        return anchor, a.eo_gloss

    rows = audit(SETS, covered, propose)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(
            fh,
            fieldnames=["set", "member", "in_lexicon", "proposed_eo_anchor", "eo_gloss"],
            delimiter="\t",
        )
        w.writeheader()
        w.writerows(rows)

    gaps = sum(1 for r in rows if r["in_lexicon"] == "N")
    by_set: dict[str, tuple[int, int]] = {}
    for r in rows:
        present, total = by_set.get(r["set"], (0, 0))
        by_set[r["set"]] = (present + (r["in_lexicon"] == "Y"), total + 1)
    print(f"{args.out}: {len(rows)} members, {gaps} gaps")
    for s, (present, total) in by_set.items():
        print(f"  {s:<13} {present}/{total} present  ({total - present} missing)")


if __name__ == "__main__":
    main()
