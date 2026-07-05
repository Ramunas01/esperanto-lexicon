#!/usr/bin/env python3
"""Phase A + B prep for the gap-fill merge (no DB writes).

Consumes the reviewed inventory and the systematic-set seed, and emits the
review packet Ramunas needs for the Phase-C human gate. Read-only on the
lexicon; writes only TSV/text artifacts under ``data/analysis/gapfill/``.

Phase A (from ``gapfill_review.reviewed.xlsx`` sheet ``reviewed``):
  A1  keep ``decision=accept``; drop any row with a blank ``final_eo_root``.
  A2  re-derive ``eo_gloss`` from ``final_eo_word`` via ESPDIC; flag any
      ``final_eo_word`` not found in ESPDIC (suspect/coined anchor).
  A3  propose a tier by frequency (freq>=THRESHOLD → Tier 1); everything
      ``freq<THRESHOLD`` → ``tier-triage-needed`` (the tail Ramunas rules on).

Phase B (from ``systematic_sets_seed.tsv``):
  B1  for each ``closed``/``semi-open`` member, test presence in
      ``concept_lang(en)``; for the missing, propose an ESPDIC anchor and carry
      the seed's proposed tier.
  B2  exclude ``names-straddle`` members from authoring; list them separately.

Outputs:
  accepts_clean.tsv, anchor_flags.tsv, tier_triage.tsv,
  set_gaps.tsv, names_straddle_note.txt
"""

from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from pathlib import Path

# freq < this → the tier-triage tail (rare-anchor flagged; the risky low-freq set).
TAIL_THRESHOLD = 5
# freq >= this (and not seed-tiered) → propose Tier 1, else Tier 2. Gap words are
# by construction absent from the original A1 core, so the bar for Tier 1 is high
# (Ramunas ruling 2026-07-06: seed + freq>=50). Note: T1-vs-T2 does not affect
# T4_ratio (both are the denominator) — this is tier-model correctness.
T1_FREQ_THRESHOLD = 50


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_reviewed(xlsx: Path) -> list[dict[str, str]]:
    sys.path.insert(0, str(_repo_root() / "src" / "analyzer" / "review"))
    from xlsx_lite import read_sheet  # noqa: E402

    _, rows = read_sheet(xlsx, "reviewed")
    return rows


def load_forward_gloss(espdic: Path) -> dict[str, str]:
    sys.path.insert(0, str(_repo_root() / "src" / "lexicon"))
    from build_gapfill_worksheet import parse_espdic  # noqa: E402

    _, forward = parse_espdic(espdic.read_text(encoding="utf-8"))
    return forward


def _int(s: str) -> int:
    s = (s or "").strip()
    return int(s) if s.lstrip("-").isdigit() else 0


# ---------------------------------------------------------------------------
# Phase A
# ---------------------------------------------------------------------------


def _head_root_tier(eo_word: str, decomposer) -> str | None:
    """Inventory tier (core/extended/tail) of *eo_word*'s head content root."""
    dec = decomposer.decompose_word(eo_word)
    if not dec.content_roots:
        return None
    return decomposer.root_tier(dec.content_roots[-1].root)


def propose_tier(
    en_lemma: str,
    base_word: str,
    freq: int,
    eo_word: str,
    seed_tiers: dict[str, str],
    decomposer,
    threshold: int,
) -> str:
    """Propose a tier for one accept.

    Priority: the Advisor seed (authoritative for set members) → frequency for
    the common head (freq>=20 Tier 1, else Tier 2) → the freq<threshold tail
    defaults to Tier 2 (safe: never blanket Tier 1). Whether a tail row is
    *flagged for closer review* is a separate signal (:func:`review_flag`), not
    a lower tier. ``en_lemma`` may be a sense-split key (``spoil#pamper``) — the
    base word before ``#`` is used for the seed lookup.
    """
    key = en_lemma.split("#", 1)[0].strip().lower()
    for k in (key, base_word.strip().lower()):
        if k and k in seed_tiers:
            return seed_tiers[k]
    if freq >= threshold:
        return "1" if freq >= T1_FREQ_THRESHOLD else "2"
    return "2"  # tail default — Tier 2, never blanket Tier 1


def review_flag(freq: int, eo_word: str, decomposer, threshold: int) -> str:
    """Flag a tail row whose EO anchor is a rare/compound root for closer review.

    Returns ``"rare-anchor"`` when a freq<threshold accept anchors on an
    inventory 'tail'/absent head root — this bucket concentrates the real
    adult-drift and junk (``inevitably``, ``beachs``) but also many fine
    compounds (``bubblegum``, ``rainstorm``), so it is a *review-priority* flag,
    not an auto-drop. Everything else → ``""`` (spot-check only).
    """
    if freq >= threshold:
        return ""
    inv = _head_root_tier(eo_word, decomposer)
    return "" if inv in ("core", "extended") else "rare-anchor"


def phase_a(
    rows: list[dict[str, str]],
    forward: dict[str, str],
    seed_tiers: dict[str, str],
    decomposer,
    threshold: int = TAIL_THRESHOLD,
) -> dict[str, list[dict]]:
    """Return ``{accepts, dropped, anchor_flags, tier_triage}`` row lists."""
    accepts, dropped, flags, triage = [], [], [], []
    for r in rows:
        if r.get("decision") != "accept":
            continue
        root = (r.get("final_eo_root") or "").strip()
        word = (r.get("final_eo_word") or "").strip()
        if not root:
            dropped.append(r)  # A1: defective, drop
            continue

        derived = forward.get(word, "")
        if not derived:
            flags.append(
                {
                    "en_lemma": r.get("en_lemma", ""),
                    "final_eo_root": root,
                    "final_eo_word": word,
                    "old_gloss": r.get("eo_gloss", ""),
                    "anchor_source": r.get("anchor_source", ""),
                    "reason": "final_eo_word not found in ESPDIC — verify anchor",
                }
            )

        freq = _int(r.get("total_freq", "0"))
        tier = propose_tier(
            r.get("en_lemma", ""), r.get("base_word", ""), freq, word,
            seed_tiers, decomposer, threshold,
        )
        rflag = review_flag(freq, word, decomposer, threshold)
        clean = {
            "en_lemma": r.get("en_lemma", ""),
            "base_word": r.get("base_word", ""),
            "total_freq": freq,
            "band": r.get("band", ""),
            "final_eo_root": root,
            "final_eo_word": word,
            "eo_gloss": derived or r.get("eo_gloss", ""),
            "gloss_source": "espdic" if derived else "kept_original",
            "anchor_source": r.get("anchor_source", ""),
            "tier_basis": "seed" if r.get("en_lemma", "").split("#")[0].lower() in seed_tiers
            or r.get("base_word", "").lower() in seed_tiers
            else ("freq" if freq >= threshold else "inventory"),
            "proposed_tier": tier,
            "review_flag": rflag,
            "note": r.get("note", ""),
        }
        accepts.append(clean)
        if freq < threshold:
            triage.append(
                {
                    "en_lemma": clean["en_lemma"],
                    "total_freq": freq,
                    "final_eo_root": root,
                    "final_eo_word": word,
                    "eo_gloss": clean["eo_gloss"],
                    "band": clean["band"],
                    "head_root_inventory_tier": _head_root_tier(word, decomposer) or "—",
                    "proposed_tier": tier,  # default '2'; Ramunas confirms/overrides (1/2/drop)
                    "review_flag": rflag,  # 'rare-anchor' → review closely; '' → spot-check
                }
            )
    return {
        "accepts": accepts,
        "dropped": dropped,
        "anchor_flags": flags,
        "tier_triage": triage,
    }


# ---------------------------------------------------------------------------
# Phase B
# ---------------------------------------------------------------------------


def load_en_lexicon(lexicon_db: Path) -> set[str]:
    conn = sqlite3.connect(lexicon_db)
    try:
        return {
            r[0].lower()
            for r in conn.execute("SELECT word FROM concept_lang WHERE lang='en'")
        }
    finally:
        conn.close()


def phase_b(
    seed_rows: list[dict[str, str]],
    covered: set[str],
    propose,
) -> tuple[list[dict], list[dict]]:
    """Return ``(set_gaps, names_straddle)``.

    ``set_gaps`` covers ``closed``/``semi-open`` members with presence flag and,
    for the missing, a proposed anchor + gloss (+ seed tier). ``names_straddle``
    members are listed separately (not for authoring).
    """
    set_gaps, straddle = [], []
    for r in seed_rows:
        member = (r.get("member_en") or "").strip().lower()
        category = (r.get("category") or "").strip()
        if not member:
            continue
        if category == "names-straddle":
            straddle.append(r)
            continue
        present = member in covered
        anchor, gloss = ("", "")
        if not present:
            anchor, gloss = propose(member)
        set_gaps.append(
            {
                "set_name": r.get("set_name", ""),
                "member_en": member,
                "category": category,
                "in_lexicon": "Y" if present else "N",
                "proposed_eo_anchor": anchor,
                "eo_gloss": gloss,
                "proposed_tier": r.get("proposed_tier", ""),
            }
        )
    return set_gaps, straddle


# ---------------------------------------------------------------------------
# IO
# ---------------------------------------------------------------------------


def _write_tsv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames, delimiter="\t", extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def main(argv: list[str] | None = None) -> None:
    root = _repo_root()
    gf = root / "data" / "analysis" / "gapfill"
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--reviewed", type=Path, default=gf / "gapfill_review.reviewed.xlsx")
    ap.add_argument("--seed", type=Path, default=root / "docs" / "systematic_sets_seed.tsv")
    ap.add_argument("--espdic", type=Path, default=root / "data" / "lexicon_db" / "espdic.txt")
    ap.add_argument("--inventory", type=Path, default=root / "data" / "lexicon_db" / "eo_inventory.json")
    ap.add_argument("--lexicon", type=Path, default=root / "data" / "lexicon_db" / "lexicon_v2.db")
    ap.add_argument("--out-dir", type=Path, default=gf)
    ap.add_argument("--threshold", type=int, default=TAIL_THRESHOLD)
    args = ap.parse_args(argv)

    # Shared loads.
    sys.path.insert(0, str(root / "src" / "lexicon"))
    from build_gapfill_worksheet import (  # noqa: E402
        load_existing_roots,
        parse_espdic,
        propose_anchor,
    )
    from eo_root_decomposer import Decomposer, load_inventory  # noqa: E402

    reverse, forward = parse_espdic(args.espdic.read_text(encoding="utf-8"))
    decomposer = Decomposer(load_inventory(args.inventory))
    existing = load_existing_roots(args.lexicon)
    covered = load_en_lexicon(args.lexicon)

    with args.seed.open(encoding="utf-8") as fh:
        seed_rows = list(csv.DictReader(fh, delimiter="\t"))
    seed_tiers = {
        (r.get("member_en") or "").strip().lower(): (r.get("proposed_tier") or "").strip()
        for r in seed_rows
        if (r.get("category") or "").strip() != "names-straddle"
        and (r.get("member_en") or "").strip()
    }

    rows = load_reviewed(args.reviewed)
    a = phase_a(rows, forward, seed_tiers, decomposer, args.threshold)

    _write_tsv(
        args.out_dir / "accepts_clean.tsv",
        ["en_lemma", "base_word", "total_freq", "band", "final_eo_root",
         "final_eo_word", "eo_gloss", "gloss_source", "anchor_source",
         "tier_basis", "proposed_tier", "review_flag", "note"],
        a["accepts"],
    )
    _write_tsv(
        args.out_dir / "anchor_flags.tsv",
        ["en_lemma", "final_eo_root", "final_eo_word", "old_gloss",
         "anchor_source", "reason"],
        a["anchor_flags"],
    )
    _write_tsv(
        args.out_dir / "tier_triage.tsv",
        ["en_lemma", "total_freq", "final_eo_root", "final_eo_word", "eo_gloss",
         "band", "head_root_inventory_tier", "proposed_tier", "review_flag"],
        a["tier_triage"],
    )

    def propose(member: str) -> tuple[str, str]:
        pa = propose_anchor(member, reverse, forward, decomposer, existing)
        anchor = f"{pa.eo_root}/{pa.eo_word}" if pa.eo_word else ""
        return anchor, pa.eo_gloss

    set_gaps, straddle = phase_b(seed_rows, covered, propose)

    _write_tsv(
        args.out_dir / "set_gaps.tsv",
        ["set_name", "member_en", "category", "in_lexicon",
         "proposed_eo_anchor", "eo_gloss", "proposed_tier"],
        set_gaps,
    )
    note = args.out_dir / "names_straddle_note.txt"
    lines = [
        "Names-straddle members — NOT authored into the common lexicon.",
        "Route to the future named-entity layer (per CLAUDE.md deferred NE design).",
        "",
    ]
    for r in straddle:
        lines.append(f"  {r.get('set_name',''):<22} {r.get('member_en','')}")
    note.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Summary
    gaps_missing = sum(1 for r in set_gaps if r["in_lexicon"] == "N")
    print("PHASE A")
    print(f"  accepts_clean : {len(a['accepts'])}  (dropped blank-root: {len(a['dropped'])})")
    print(f"  anchor_flags  : {len(a['anchor_flags'])}  (final_eo_word not in ESPDIC)")
    from collections import Counter
    flagged = sum(1 for r in a["tier_triage"] if r["review_flag"])
    print(f"  tier_triage   : {len(a['tier_triage'])} tail rows (freq<{args.threshold}), all default Tier 2; "
          f"{flagged} 'rare-anchor' flagged for close review, {len(a['tier_triage']) - flagged} spot-check")
    at = Counter(r["proposed_tier"] for r in a["accepts"])
    print(f"  accepts tier split (proposed): {dict(at)}")
    glossed = sum(1 for r in a["accepts"] if r["gloss_source"] == "espdic")
    print(f"  glosses re-derived from ESPDIC: {glossed}/{len(a['accepts'])}")
    print("PHASE B")
    print(f"  set_gaps      : {len(set_gaps)} members, {gaps_missing} missing from lexicon")
    print(f"  names_straddle: {len(straddle)} members excluded → {note.name}")
    print(f"\nWritten to {args.out_dir}/  — STOP, human review gate (Phase C). No DB writes.")


if __name__ == "__main__":
    main()
