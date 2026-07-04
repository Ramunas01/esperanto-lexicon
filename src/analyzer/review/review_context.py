#!/usr/bin/env python3
"""Assemble all review evidence for one gap-fill row (brief Part A).

``review_context.py <en_lemma>`` prints, for the review agent to read:
  * the worksheet row (freq, flag, priority, gloss, proposed anchor, alts, note);
  * corpus usage — sense-diverse example sentences from TinyStories + match count;
  * the anchor round-trip — the proposed ``eo_word``'s ESPDIC gloss(es) and
    whether they contain the English lemma (replaces a translate lookup), plus
    each alternative candidate's gloss so a better sense can be picked;
  * a name signal — capitalisation majority, PROPN, lowercase common use;
  * a one-line recommendation: ACCEPT / REJECT(name) / ASK(reason).

Read-only. Verbose by design — evidence over brevity.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (  # noqa: E402
    add_repo_src_to_path,
    default_paths,
    load_decisions,
    load_surface_map,
    matching_sentences,
    name_signal,
    read_corpus,
    recommend,
    roundtrip_glosses,
    roundtrip_matches,
    select_diverse,
)
from xlsx_lite import read_sheet  # noqa: E402


def _load_snapshot_row(snapshot: Path, lemma: str) -> dict[str, str] | None:
    import csv

    if not snapshot.exists():
        return None
    with snapshot.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh, delimiter="\t"):
            if r.get("en_lemma", "").strip().lower() == lemma:
                return r
    return None


def build_report(lemma: str, paths: dict, n_examples: int = 6) -> str:
    """Return the full evidence block for *lemma* as a printable string."""
    add_repo_src_to_path()
    from build_gapfill_worksheet import parse_espdic  # noqa: E402

    lemma = lemma.strip().lower()
    row = _load_snapshot_row(paths["snapshot"], lemma)
    if row is None:
        # Fall back to the live xlsx only if no snapshot exists yet.
        if paths["xlsx"].exists() and not paths["snapshot"].exists():
            _, rows = read_sheet(paths["xlsx"], "worksheet")
            row = next(
                (r for r in rows if r.get("en_lemma", "").strip().lower() == lemma),
                None,
            )
    if row is None:
        return f"[no worksheet row for {lemma!r} — run export_snapshot.py first]"

    surfaces = load_surface_map(paths["triaged"]).get(lemma, [])
    tokens = [str(s["token"]) for s in surfaces] or [lemma]
    corpus = read_corpus(paths["chunks"])
    sents = matching_sentences(corpus, tokens)
    examples = select_diverse(sents, tokens, n_examples)
    sig = name_signal(surfaces) if surfaces else {
        "caps_majority": 0.0, "ever_propn": False,
        "lowercase_common_freq": 0, "total_freq": 0,
    }

    _, forward = parse_espdic(paths["espdic"].read_text(encoding="utf-8"))
    glosses = roundtrip_glosses(row.get("eo_word", ""), forward)
    rt_ok = roundtrip_matches(lemma, glosses)
    alts = [a.strip() for a in (row.get("alt_candidates") or "").split(",") if a.strip()]
    alt_glosses = {a: roundtrip_glosses(a, forward) for a in alts}

    verdict, reason = recommend(row, sig, glosses, alt_glosses, len(sents))
    decided = load_decisions(paths["decisions"]).get(lemma)

    L = []
    L.append("=" * 72)
    L.append(f"  {lemma!r}   freq={row.get('total_freq','?')}   "
             f"priority={row.get('priority','?')}   flag={row.get('flag','?')}")
    L.append("=" * 72)
    if decided:
        L.append(f"⚠ ALREADY DECIDED: {decided['decision']} "
                 f"(source={decided.get('source')}) — skip unless revisiting.")
    L.append(f"action     : {row.get('action','')}")
    L.append(f"proposed   : eo_root={row.get('eo_root','')!r}  "
             f"eo_word={row.get('eo_word','')!r}  tier={row.get('proposed_tier','')}"
             f"/{row.get('cefr','')}")
    if row.get("component_roots"):
        L.append(f"components : {row['component_roots']}")
    L.append(f"eo_gloss   : {row.get('eo_gloss','')}")
    if row.get("notes"):
        L.append(f"notes      : {row['notes']}")

    L.append("")
    L.append(f"CORPUS USAGE ({len(sents)} sentences; showing {len(examples)}):")
    if examples:
        for s in examples:
            L.append(f"  • {s}")
    else:
        L.append("  (no corpus sentences found for surface forms "
                 f"{tokens[:6]})")

    L.append("")
    L.append("ANCHOR ROUND-TRIP:")
    if glosses:
        mark = "✓ matches" if rt_ok else "✗ MISMATCH"
        L.append(f"  {row.get('eo_word','')} → {', '.join(glosses)}   [{mark} '{lemma}']")
    else:
        L.append(f"  {row.get('eo_word','')!r} not found in ESPDIC — verify the anchor")
    if alts:
        L.append("  alternatives:")
        for a in alts[:6]:
            ag = alt_glosses.get(a, [])
            L.append(f"    - {a} → {', '.join(ag) if ag else '(no gloss)'}")

    L.append("")
    L.append("NAME SIGNAL:")
    L.append(f"  caps-majority={sig['caps_majority']:.0%}  "
             f"ever_PROPN={sig['ever_propn']}  "
             f"lowercase_common_uses={sig['lowercase_common_freq']}")

    L.append("")
    L.append(f"RECOMMENDATION: {verdict} — {reason}")
    L.append("")
    L.append("record with:")
    dec = {"ACCEPT": "accept", "REJECT(name)": "reject"}.get(verdict, "<accept|reject|hold>")
    L.append(f"  python3 src/analyzer/review/review_record.py {lemma} {dec} "
             f"--source {'auto' if verdict in ('ACCEPT','REJECT(name)') else 'human'} "
             f"--reason \"{reason}\"")
    return "\n".join(L)


def main(argv: list[str] | None = None) -> None:
    p = default_paths()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("en_lemma")
    ap.add_argument("--examples", type=int, default=6)
    ap.add_argument("--snapshot", type=Path, default=p["snapshot"])
    ap.add_argument("--triaged", type=Path, default=p["triaged"])
    ap.add_argument("--espdic", type=Path, default=p["espdic"])
    ap.add_argument("--chunks", type=Path, default=p["chunks"])
    ap.add_argument("--decisions", type=Path, default=p["decisions"])
    ap.add_argument("--xlsx", type=Path, default=p["xlsx"])
    args = ap.parse_args(argv)
    paths = {**p, "snapshot": args.snapshot, "triaged": args.triaged,
             "espdic": args.espdic, "chunks": args.chunks,
             "decisions": args.decisions, "xlsx": args.xlsx}
    print(build_report(args.en_lemma, paths, args.examples))


if __name__ == "__main__":
    main()
