#!/usr/bin/env python3
"""Fold recorded decisions into a fresh viewable workbook (brief Part C).

Reads the snapshot ``worksheet_export.tsv`` and ``review_decisions.tsv`` and
writes a **new** ``gapfill_review.reviewed.xlsx`` with the decision, note and any
corrected anchor merged in. Never overwrites the reviewer's live workbook — this
is a separate, viewing-only copy produced on request.

The merged sheet carries all snapshot columns plus (overwriting where present):
``decision``, ``reviewer_note``, and a new ``corrected_anchor`` column
(``eo_root/eo_word`` when the reviewer picked an override).
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import default_paths, load_decisions  # noqa: E402
from xlsx_lite import write_xlsx  # noqa: E402


def _read_snapshot(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8") as fh:
        r = csv.DictReader(fh, delimiter="\t")
        return list(r.fieldnames or []), list(r)


def merge(snapshot: Path, decisions: Path) -> tuple[list[str], list[list[str]]]:
    """Return ``(header, rows)`` for the reviewed workbook."""
    header, rows = _read_snapshot(snapshot)
    dmap = load_decisions(decisions)
    out_header = list(header)
    if "corrected_anchor" not in out_header:
        out_header.append("corrected_anchor")

    out_rows: list[list[str]] = []
    for r in rows:
        lemma = r.get("en_lemma", "").strip().lower()
        d = dmap.get(lemma)
        if d:
            r = dict(r)
            r["decision"] = d["decision"]
            if d.get("note"):
                r["reviewer_note"] = d["note"]
            root, word = d.get("eo_root_override", ""), d.get("eo_word_override", "")
            r["corrected_anchor"] = f"{root}/{word}" if (root or word) else ""
        out_rows.append([r.get(c, "") for c in out_header])
    return out_header, out_rows


def main(argv: list[str] | None = None) -> None:
    p = default_paths()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--snapshot", type=Path, default=p["snapshot"])
    ap.add_argument("--decisions", type=Path, default=p["decisions"])
    ap.add_argument("--out", type=Path, default=p["reviewed"])
    args = ap.parse_args(argv)

    if not args.snapshot.exists():
        print(f"missing snapshot {args.snapshot} — run export_snapshot.py first",
              file=sys.stderr)
        sys.exit(1)

    header, rows = merge(args.snapshot, args.decisions)
    write_xlsx(args.out, header, rows)
    decided = sum(1 for r in rows if r[header.index("decision")])
    print(f"wrote {args.out}  ({len(rows)} rows, {decided} with a decision)")


if __name__ == "__main__":
    main()
