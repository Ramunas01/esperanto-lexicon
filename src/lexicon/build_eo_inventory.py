#!/usr/bin/env python3
"""
build_eo_inventory.py  --  build the Esperanto root inventory from ESPDIC alone.

WHY THIS REPLACES build_root_inventory.py
  The previous inventory drew roots from parseo (GPL-3.0). This builder derives the
  full root inventory from ESPDIC (Paul Denisowski, CC-BY-3.0) instead, plus the
  standard Esperanto affix/correlative tables hardcoded below (those are public-domain
  grammatical facts of the language, not copyrightable). Net effect: a single,
  permissively-licensed inventory with no GPL entanglement -- safe for a public repo
  and for commercial routing applications -- AND far broader coverage than the BRO
  core (BRO ~4.6k roots vs ESPDIC ~25k), which is what Tier 3/4 specialist vocabulary
  needs.

METHOD (attested-primitive root extraction)
  ESPDIC lists word FORMS, not bare roots. For each single-word common headword we
  strip the grammatical ending to a stem, then reduce the stem to its primitive root
  by peeling derivational affixes -- but ONLY when the remainder is itself an attested
  ESPDIC stem. So `konceptado` -> `koncept` (because `koncepto` exists), while
  `kompil`-type roots stay whole (no shorter attested base exists). This avoids
  inventing fragment "roots" like `tel` out of `telefono`.

CONFIDENCE TIERS (a root's productivity = how many distinct forms reduce to it)
  core      prod >= 3   workhorse set (~2.7k); load always
  extended  prod == 2   (~2.4k); load for Tier 2+
  tail      prod == 1   (~20k) rare/scientific/borrowed; load for Tier 3/4 specialist
                        coverage, treat as candidate roots pending review

LICENSE / PROVENANCE  (record in LICENSING.md)
  Roots + glosses: ESPDIC, (c) Paul Denisowski, CC-BY-3.0 -- attribute the source.
  Affix/correlative/ending tables: standard Esperanto grammar (public domain).
  Data is fetched at build time, not vendored.

USAGE
  python build_eo_inventory.py --out data/lexicon_db/
  python build_eo_inventory.py --espdic /path/to/espdic.txt   # use a local/newer file
"""
import argparse, json, re, sys, urllib.request, datetime, pathlib
from collections import Counter

ESPDIC_URL = "https://raw.githubusercontent.com/drandre2014/ESPDIC/master/espdic.txt"

# --- standard Esperanto morphology (public-domain grammatical facts) -------------
SUFFIXES = ["aĉ","ad","aĵ","an","ant","ar","at","ĉj","ebl","ec","eg","ej","em","end",
            "er","estr","et","id","ig","iĝ","il","in","ind","ing","int","ism","ist",
            "it","nj","obl","on","ont","op","ot","uj","ul","um"]
PREFIXES = ["bo","ĉef","dis","ek","eks","fi","ge","mal","mem","mis","pra","re","vic",
            "ekster","kontraŭ","sen","sub","super","trans"]
NUMBER_ROOTS = ["nul","unu","du","tri","kvar","kvin","ses","sep","ok","naŭ","dek","cent","mil"]
VERB_END = ["as","is","os","us","u","i"]
NOMINAL_END = ["o","a","e"]
CORRELATIVES = [a+b for a in ["ki","ti","i","ĉi","neni"]
                    for b in ["o","u","a","e","es","am","al","el","om"]]
OTHER = ["al","ankaŭ","ankoraŭ","almenaŭ","ambaŭ","anstataŭ","antaŭ","apenaŭ","apud",
         "aŭ","baldaŭ","ĉar","ĉe","ĉi","ĉirkaŭ","da","de","do","dum","eĉ","el","en",
         "for","ĝis","hieraŭ","hodiaŭ","ja","jam","je","jen","jes","ĵus","kaj",
         "kontraŭ","krom","kun","kvankam","kvazaŭ","la","laŭ","malgraŭ","mem","mi",
         "morgaŭ","ne","nek","ni","nu","nun","nur","ol","oni","per","plej","pli","plu",
         "por","post","preter","pri","pro","se","sed","sen","si","sub","super","sur",
         "ŝi","li","ĝi","ili","tamen","tra","trans","tre","tro","tuj","vi"]

_SUF = sorted(SUFFIXES, key=len, reverse=True)
_PRE = sorted(PREFIXES, key=len, reverse=True)

def strip_flexion(s):
    if s.endswith("n"): s = s[:-1]
    if s.endswith("j"): s = s[:-1]
    for e in VERB_END + NOMINAL_END:
        if s.endswith(e) and len(s) > len(e): return s[:-len(e)]
    return s

def parse_espdic(text):
    stems, gloss = set(), {}
    for line in text.splitlines():
        if " : " not in line: continue
        head, g = line.split(" : ", 1)
        head = head.strip()
        if (not head or head.startswith("-") or head.endswith("-")
                or " " in head or head[:1].isupper()): continue
        if not re.fullmatch(r"[a-zĉĝĥĵŝŭ]+", head.lower()): continue
        st = strip_flexion(head.lower())
        stems.add(st); gloss.setdefault(st, g.strip())
    return stems, gloss

def extract_roots(stems):
    attested = stems | set(NUMBER_ROOTS)
    def reduce_once(x):
        for suf in _SUF:
            if x.endswith(suf) and len(x)-len(suf) >= 3 and x[:-len(suf)] in attested:
                return x[:-len(suf)]
        for pre in _PRE:
            if x.startswith(pre) and len(x)-len(pre) >= 3 and x[len(pre):] in attested:
                return x[len(pre):]
        return None
    memo = {}
    def primitive(x):
        seen, cur = set(), x
        while cur not in memo:
            if cur in seen: break
            seen.add(cur); y = reduce_once(cur)
            if not y or y == cur: break
            cur = y
        res = memo.get(cur, cur)
        for s in seen: memo[s] = res
        return res
    prod = Counter(primitive(s) for s in stems)
    for n in NUMBER_ROOTS: prod[n] = max(prod[n], 1)
    return prod

def tier(p): return "core" if p >= 3 else ("extended" if p == 2 else "tail")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--espdic", help="local ESPDIC .txt (else fetch CC-BY mirror)")
    ap.add_argument("--out", default=".")
    args = ap.parse_args()

    if args.espdic:
        text = pathlib.Path(args.espdic).read_text(encoding="utf-8")
        src = args.espdic
    else:
        try:
            with urllib.request.urlopen(ESPDIC_URL, timeout=60) as r:
                text = r.read().decode("utf-8")
            src = ESPDIC_URL
        except Exception as e:
            sys.exit(f"ESPDIC fetch failed: {e}")

    stems, gloss = parse_espdic(text)
    prod = extract_roots(stems)
    roots = {r: {"gloss": gloss.get(r, ""), "prod": prod[r], "tier": tier(prod[r])}
             for r in sorted(prod)}
    inv = {
        "meta": {
            "source": "ESPDIC (Paul Denisowski), CC-BY-3.0; affix tables = public-domain grammar",
            "built": datetime.date.today().isoformat(),
            "espdic_src": src,
            "root_count": len(roots),
            "by_tier": {t: sum(1 for v in roots.values() if v["tier"] == t)
                        for t in ("core", "extended", "tail")},
        },
        "roots": roots,
        "suffixes": SUFFIXES, "prefixes": PREFIXES, "number_roots": NUMBER_ROOTS,
        "correlatives": CORRELATIVES, "other": OTHER,
        "verb_endings": VERB_END, "nominal_endings": NOMINAL_END,
    }
    out = pathlib.Path(args.out); out.mkdir(parents=True, exist_ok=True)
    (out / "eo_inventory.json").write_text(
        json.dumps(inv, ensure_ascii=False), encoding="utf-8")
    (out / "akademio_roots.txt").write_text(   # flat list kept for compatibility
        f"# Esperanto roots from {src} (CC-BY-3.0); built {inv['meta']['built']}; "
        f"{len(roots)} roots\n" + "\n".join(roots) + "\n", encoding="utf-8")
    m = inv["meta"]
    print(f"roots: {m['root_count']}  (core {m['by_tier']['core']}, "
          f"extended {m['by_tier']['extended']}, tail {m['by_tier']['tail']})")
    print(f"wrote {out/'eo_inventory.json'} and {out/'akademio_roots.txt'}")

if __name__ == "__main__":
    main()
