#!/usr/bin/env python3
"""
build_root_inventory.py  --  construct the Esperanto root inventory for the lexicon.

Produces two artifacts under data/lexicon_db/ :

  akademio_roots.txt   one validated Esperanto root per line (the canonical
                       inventory the migration/analyzer validates stems against)
  eo_inventory.json    richer form: {roots:{root:[glosses]}, suffixes, prefixes,
                       correlatives, other}  -- this is what the decomposer needs
                       to resolve stems -> true roots, fill eo_prefix/eo_suffix,
                       and recognise function words.

SOURCE / PROVENANCE
  Data is the Baza Radikaro Oficiala (BRO), the Akademio de Esperanto's
  frequency-ranked official root list, in the machine-readable form published by
  the `parseo` project (Rieselhilfe/parseo, vortaro.json).
    parseo is licensed GPL-3.0.  The underlying BRO roots are an Akademio
    publication; bare linguistic roots are factual data, but the compiled file
    and English glosses originate from a GPL-3.0 work.
  DECISION FOR THIS REPO: we do NOT vendor vortaro.json. This script downloads it
  at build time (like the .db files, the data is regenerated locally, not
  committed). Record the provenance in LICENSING.md. Pin --ref to a commit SHA
  for reproducible builds.

USAGE
  python build_root_inventory.py --out data/lexicon_db/
  python build_root_inventory.py --ref <commit-sha>   # reproducible pin
"""
import argparse, json, sys, urllib.request, datetime, pathlib

REPO = "Rieselhilfe/parseo"
RAW = "https://raw.githubusercontent.com/{repo}/{ref}/vortaro.json"

def fetch(ref):
    url = RAW.format(repo=REPO, ref=ref)
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.loads(r.read().decode("utf-8")), url

def build(d):
    roots = {}
    for bucket in d["radikoj"].values():        # bucketed by natural ending
        for root, glosses in bucket.items():
            roots[root] = glosses
    return {
        "roots": dict(sorted(roots.items())),
        "suffixes": sorted(d["sufiksoj"].keys()),
        "prefixes": sorted(d["prefiksoj"].keys()),
        "correlatives": sorted(d["correlatives"].keys()),
        "other": sorted(d["other"].keys()),
    }

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", default="main", help="git ref/commit SHA of parseo to pin")
    ap.add_argument("--out", default=".", help="output directory")
    args = ap.parse_args()

    try:
        raw, url = fetch(args.ref)
    except Exception as e:
        sys.exit(f"fetch failed ({url if 'url' in dir() else REPO}): {e}")

    inv = build(raw)
    out = pathlib.Path(args.out); out.mkdir(parents=True, exist_ok=True)
    today = datetime.date.today().isoformat()
    header = (f"# akademio_roots.txt -- Esperanto root inventory\n"
              f"# Source: Baza Radikaro Oficiala via {REPO} ({args.ref}), GPL-3.0\n"
              f"# Built: {today}  |  {len(inv['roots'])} roots\n"
              f"# Regenerate: python build_root_inventory.py --ref <sha>\n")
    (out / "akademio_roots.txt").write_text(
        header + "\n".join(inv["roots"].keys()) + "\n", encoding="utf-8")
    (out / "eo_inventory.json").write_text(
        json.dumps(inv, ensure_ascii=False, indent=0), encoding="utf-8")

    print(f"roots:        {len(inv['roots'])}")
    print(f"suffixes:     {len(inv['suffixes'])}")
    print(f"prefixes:     {len(inv['prefixes'])}")
    print(f"correlatives: {len(inv['correlatives'])}")
    print(f"other:        {len(inv['other'])}")
    print(f"wrote: {out/'akademio_roots.txt'}")
    print(f"wrote: {out/'eo_inventory.json'}")

if __name__ == "__main__":
    main()
