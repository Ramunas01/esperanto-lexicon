#!/usr/bin/env python3
"""Record one review decision to the sidecar TSV (brief Part A).

Appends to ``review_decisions.tsv``; idempotent in effect — the loader keeps the
last write per lemma, so re-deciding a row simply appends a newer line. Never
writes the lexicon or the live ``.xlsx``.

Usage::

    review_record.py <en_lemma> <decision> [--note ...] \\
        [--eo-root R --eo-word W] [--source human|auto] [--reason ...]

``decision`` ∈ {accept, reject, hold, postpone}. ``--eo-root/--eo-word`` carry a
corrected anchor (the agent proposes; the human confirms; it lands here for the
Phase-3 writer, so column K/L in the xlsx is never hand-edited).
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (  # noqa: E402
    VALID_DECISIONS,
    append_decision,
    default_paths,
    load_decisions,
)


def main(argv: list[str] | None = None) -> None:
    p = default_paths()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("en_lemma")
    ap.add_argument("decision", choices=sorted(VALID_DECISIONS))
    ap.add_argument("--note", default="")
    ap.add_argument("--eo-root", dest="eo_root", default="")
    ap.add_argument("--eo-word", dest="eo_word", default="")
    ap.add_argument("--source", choices=["human", "auto"], default="human")
    ap.add_argument("--reason", default="")
    ap.add_argument("--decisions", type=Path, default=p["decisions"])
    args = ap.parse_args(argv)

    lemma = args.en_lemma.strip().lower()
    prior = load_decisions(args.decisions).get(lemma)
    append_decision(
        args.decisions,
        {
            "en_lemma": lemma,
            "decision": args.decision,
            "note": args.note,
            "eo_root_override": args.eo_root,
            "eo_word_override": args.eo_word,
            "source": args.source,
            "reason": args.reason,
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        },
    )
    override = f"  anchor→{args.eo_root}/{args.eo_word}" if args.eo_root or args.eo_word else ""
    prior_note = f"  (was: {prior['decision']})" if prior else ""
    print(f"recorded: {lemma} = {args.decision} [{args.source}]{override}{prior_note}")


if __name__ == "__main__":
    main()
