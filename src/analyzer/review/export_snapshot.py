#!/usr/bin/env python3
"""Setup step (brief Part D): snapshot the review workbook, seed decisions.

Reads the reviewer's ``gapfill_review.xlsx`` **once, while Excel is closed**
(refuses to run if the ``~$`` lock file is present) and:

  1. writes ``worksheet_export.tsv`` — a full snapshot of the ``worksheet`` tab
     that every other harness tool reads (the agent never touches the live
     ``.xlsx`` again);
  2. seeds ``review_decisions.tsv`` from column I (``decision``), so the ~300
     rows the reviewer already did are skipped when the session resumes.

Column-I mapping: ``1`` → accept, ``0`` → reject, ``postpone`` → postpone,
blank → left pending. ``source=human``. Existing ``review_decisions.tsv`` rows
are preserved (append-only; last write per lemma wins downstream).
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (  # noqa: E402
    DECISION_FIELDS,
    append_decision,
    default_paths,
    load_decisions,
)
from xlsx_lite import read_sheet  # noqa: E402

# xlsx column I values -> canonical decisions.
_COL_I_MAP = {"1": "accept", "0": "reject", "postpone": "postpone", "hold": "hold"}


def _excel_lock_present(xlsx: Path) -> bool:
    return (xlsx.parent / f"~${xlsx.name}").exists()


def export(xlsx: Path, snapshot: Path, decisions: Path, sheet: str = "worksheet") -> dict:
    """Write the snapshot TSV and seed decisions from column I.

    Returns a summary dict. Rows already present in ``review_decisions.tsv`` are
    not re-seeded.
    """
    header, rows = read_sheet(xlsx, sheet)

    snapshot.parent.mkdir(parents=True, exist_ok=True)
    with snapshot.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=header, delimiter="\t")
        w.writeheader()
        for r in rows:
            w.writerow(r)

    already = set(load_decisions(decisions))
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    seeded = 0
    counts: dict[str, int] = {}
    for r in rows:
        lemma = r.get("en_lemma", "").strip().lower()
        raw = (r.get("decision") or "").strip()
        decision = _COL_I_MAP.get(raw)
        if not lemma or decision is None or lemma in already:
            continue
        append_decision(
            decisions,
            {
                "en_lemma": lemma,
                "decision": decision,
                "note": r.get("reviewer_note", ""),
                "eo_root_override": "",
                "eo_word_override": "",
                "source": "human",
                "reason": "imported from xlsx column I",
                "ts": ts,
            },
        )
        already.add(lemma)
        seeded += 1
        counts[decision] = counts.get(decision, 0) + 1
    return {"rows": len(rows), "seeded": seeded, "by_decision": counts}


def main(argv: list[str] | None = None) -> None:
    p = default_paths()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--xlsx", type=Path, default=p["xlsx"])
    ap.add_argument("--snapshot", type=Path, default=p["snapshot"])
    ap.add_argument("--decisions", type=Path, default=p["decisions"])
    ap.add_argument("--sheet", default="worksheet")
    ap.add_argument(
        "--force", action="store_true", help="proceed even if the Excel lock is present"
    )
    args = ap.parse_args(argv)

    if _excel_lock_present(args.xlsx) and not args.force:
        print(
            f"REFUSING: Excel appears to have {args.xlsx.name} open "
            f"(~${args.xlsx.name} lock present). Close Excel and retry, or --force.",
            file=sys.stderr,
        )
        sys.exit(2)

    summary = export(args.xlsx, args.snapshot, args.decisions, args.sheet)
    print(f"snapshot   : {args.snapshot}  ({summary['rows']} rows)")
    print(f"decisions  : {args.decisions}")
    print(f"seeded     : {summary['seeded']} new  {summary['by_decision']}")
    print(f"fields     : {', '.join(DECISION_FIELDS)}")


if __name__ == "__main__":
    main()
