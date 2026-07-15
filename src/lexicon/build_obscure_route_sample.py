#!/usr/bin/env python3
"""Generate the ~200-root labelled validation sample for the R9 routing rule (B2).

Reads the obscure_root rows from ``root_tier_coverage.tsv`` (PR #14), applies
:func:`vocab_lifecycle.route_obscure_root` to each, and writes a stratified
~200-root sample that exhibits all three routes so the rule can be validated by
eye. **This is NOT the full 22k sort** — it is the validation sample only.

Deterministic (no randomness): every archaic-marker and modern-referent hit is
included, then the remainder is filled by an even stride across zipf bands.

Usage:
    python3 src/lexicon/build_obscure_route_sample.py \\
        --coverage data/analysis/root_coverage/root_tier_coverage.tsv \\
        --out data/analysis/lifecycle/obscure_route_sample.tsv --n 200
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lexicon.vocab_lifecycle import route_obscure_root  # noqa: E402

OUT_HEADER = [
    "root",
    "route",
    "signal",
    "inv_tier",
    "gloss_zipf",
    "gloss_head",
    "gloss",
]


def _zipf(row: dict) -> float:
    try:
        return float(row.get("gloss_zipf") or 0)
    except ValueError:
        return 0.0


def build_sample(coverage_tsv: Path, n: int = 200) -> list[dict]:
    rows = [
        r
        for r in csv.DictReader(coverage_tsv.open(encoding="utf-8"), delimiter="\t")
        if r.get("bucket") == "obscure_root"
    ]
    routed = []
    for r in rows:
        route, signal = route_obscure_root(
            r.get("gloss", ""), _zipf(r), inv_tier=r.get("inv_tier", "")
        )
        routed.append({**r, "_route": route, "_signal": signal, "_zipf": _zipf(r)})

    # Every positive-signal hit is included; they validate the rule's precision.
    positives = [r for r in routed if r["_route"] in ("philology_t4", "unplaced")]
    unclassified = [r for r in routed if r["_route"] == "unclassified"]

    # Fill the rest with an even stride across zipf-sorted unclassified roots, so
    # the sample spans the frequency space (fading tail → modern gloss).
    unclassified.sort(key=lambda r: (r["_zipf"], r["root"]))
    fill_n = max(0, n - len(positives))
    if unclassified and fill_n:
        stride = max(1, len(unclassified) // fill_n)
        filled = unclassified[::stride][:fill_n]
    else:
        filled = []

    sample = positives + filled
    sample.sort(key=lambda r: (r["_route"], -r["_zipf"], r["root"]))
    return sample


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--coverage",
        type=Path,
        default=Path("data/analysis/root_coverage/root_tier_coverage.tsv"),
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=Path("data/analysis/lifecycle/obscure_route_sample.tsv"),
    )
    ap.add_argument("--n", type=int, default=200)
    args = ap.parse_args(argv)

    if not args.coverage.exists():
        print(f"Error: {args.coverage} not found.", file=sys.stderr)
        sys.exit(1)

    sample = build_sample(args.coverage, args.n)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow(OUT_HEADER)
        for r in sample:
            w.writerow(
                [
                    r["root"],
                    r["_route"],
                    r["_signal"],
                    r.get("inv_tier", ""),
                    f"{r['_zipf']:.2f}",
                    r.get("gloss_head", ""),
                    r.get("gloss", ""),
                ]
            )

    from collections import Counter

    dist = Counter(r["_route"] for r in sample)
    print(f"wrote {args.out} ({len(sample)} roots)")
    print("route distribution:", dict(dist))


if __name__ == "__main__":
    main()
