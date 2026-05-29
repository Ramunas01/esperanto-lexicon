#!/usr/bin/env python3
"""Seed Tier 3 formal-English vocabulary from the UNKNOWN token pool.

Reads data/analysis/unknown_tokens_pooled.txt, applies four layers of
filters to exclude noise, named entities, and domain-specific Tier 4
vocabulary, then inserts genuine C1+ formal-English candidates into
concept_lang at tier=3.

Filtering stages:
  A1 — structural (frequency, character class, already-in-lexicon)
  A2a — Tier 4 stem prefix match (stoplist)
  A2b — Named entities and country/org names
  A2c — Fragment artefacts and prefix fragments
  A3  — Manual second-pass: additional T4 and noise words the
         primary stoplist missed (prints as REVIEW list, excludes)

Usage:
    python3 src/lexicon/seed_tier3.py [--dry-run]

    --dry-run   Print all filter counts and samples without writing to DB.
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from datetime import date
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

POOL_PATH = Path("data/analysis/unknown_tokens_pooled.txt")
LEXICON_DB = Path("data/lexicon_db/lexicon_v2.db")
DOMAIN_DBS = [
    Path("data/domain_db/ucc_customs.db"),
    Path("data/domain_db/wco_intl.db"),
    Path("data/domain_db/cbam.db"),
    Path("data/domain_db/dualuse.db"),
]

SOURCE_TAG = "tier3_unknown_pool_2026_05_29"
TIER = 3
CEFR = "C1"
LANG = "en"

MIN_FREQ = 5
MIN_LEN = 3  # inclusive

# A2a — Tier 4 domain stem prefixes (case-insensitive; startswith match)
_TIER4_STEMS = [
    "tariff", "customs", "duty", "duties", "tax", "taxes", "import", "export",
    "declaration", "declarant", "valuation", "classif", "valuat", "origin",
    "territory", "territorial", "compliance", "complian", "preferenti",
    "transit", "warehous", "aeo", "ucc", "hs", "wco", "eu", "ec", "oj",
    "tradesm", "trader", "shipment", "consignment", "broker",
    "incoter", "freight", "exporter", "importer", "sanction", "restrict",
    "quota", "license", "licens", "certifi", "manifest", "harmonis", "harmoniz",
    "nomenclat", "ratific", "accession", "treaty", "conventi", "regulat",
    "directiv", "implement", "dual-use", "controll", "exemption", "deroga",
    "embargo", "tariffic", "duty-free", "drawback", "refund", "reimburs",
    "rebate", "levy", "levied", "dumping", "countervail", "valoric", "ad-valor",
    "duty-paid", "transhipment", "smuggl", "contraband", "ncts", "vat",
    "originating", "annex", "transitional", "cn",
]

# A2b — Named entities: countries, regions, organisations (lowercased)
_NE_WORDS = {
    "albania", "algeria", "andorra", "angola", "antigua", "argentina", "armenia",
    "australia", "austria", "azerbaijan", "bahamas", "bahrain", "bangladesh",
    "barbados", "belarus", "belgium", "belize", "benin", "bhutan", "bolivia",
    "bosnia", "botswana", "brazil", "brunei", "bulgaria", "burkina", "burundi",
    "cambodia", "cameroon", "canada", "chile", "china", "colombia", "congo",
    "croatia", "cuba", "cyprus", "czechia", "denmark", "ecuador", "egypt",
    "estonia", "ethiopia", "finland", "france", "georgia", "germany", "ghana",
    "greece", "guatemala", "guinea", "haiti", "honduras", "hungary", "iceland",
    "india", "indonesia", "iran", "iraq", "ireland", "israel", "italy", "jamaica",
    "japan", "jordan", "kazakhstan", "kenya", "korea", "kosovo", "kuwait",
    "latvia", "lebanon", "lesotho", "liberia", "libya", "liechtenstein",
    "lithuania", "luxembourg", "madagascar", "malawi", "malaysia", "maldives",
    "mali", "malta", "mauritania", "mauritius", "mexico", "moldova", "monaco",
    "mongolia", "montenegro", "morocco", "mozambique", "myanmar", "namibia",
    "nepal", "netherlands", "nicaragua", "niger", "nigeria", "norway",
    "oman", "pakistan", "panama", "papua", "paraguay", "peru", "philippines",
    "poland", "portugal", "qatar", "romania", "russia", "rwanda", "senegal",
    "serbia", "singapore", "slovakia", "slovenia", "somalia", "spain",
    "srilanka", "sudan", "sweden", "switzerland", "syria", "taiwan",
    "tajikistan", "tanzania", "thailand", "togo", "trinidad", "tunisia",
    "turkey", "turkmenistan", "uganda", "ukraine", "emirates", "kingdom",
    "states", "america", "africa", "europe", "european", "african", "asian",
    "american", "pacific", "atlantic", "union", "republic", "federal",
    "uruguay", "uzbekistan", "venezuela", "vietnam", "yemen", "zambia",
    "zimbabwe",
    # organisations and trade agreements
    "afcfta", "ecowas", "caricom", "mercosur", "ceta", "nafta", "cjeu",
    "efta", "asean", "apec", "nato", "wto",
}

# A2c — Prefix fragments (standalone tokens that are actually word-parts)
_PREFIX_FRAGMENTS = {"non", "pre", "re", "anti", "sub", "co", "mis", "de"}

# A3 — Second-pass manual exclusions: T4 words the primary stoplist missed
_MANUAL_T4 = {
    # logistics and transport
    "logistics", "shipping", "cargo", "hub",
    # customs procedures and instruments
    "ruling", "rulings", "processing", "circulation", "facilitation",
    "facilitations", "simplifications", "simplification", "simplified",
    "authorisation", "authorisations", "authorised", "authorized", "accredited",
    # duties and taxes
    "excise", "allowance", "allowances", "consumption",
    # origin rules
    "tolerance", "wholly",
    # HS classification
    "heading", "subheading", "digit",
    # customs valuation
    "resale", "purchaser", "invoice",
    # Incoterms
    "cif", "fob",
    # trade actors / acronyms
    "suppliers", "trading", "roo", "smes", "input",
    # customs-specific verification
    "verification",
    # AEO-specific financial criterion
    "solvency",
    # corpus artefact (appears because "stratum" is in our own output files)
    "stratum", "domain",
}

# A3 — Second-pass: noise, foreign words, person names, commodities, abbreviations
_MANUAL_NOISE = {
    # unit of measure
    "litres", "litre",
    # commodities
    "tobacco", "fertiliser", "fertilisers", "wheat", "dairy", "cigars",
    "sparkling", "fortified",
    # national adjectives (NE-adjacent, not lexical)
    "ukrainian", "canadian", "irish", "israeli", "british", "baltic",
    "lithuanian", "continental",
    # NE-adjacent institutional terms
    "supreme", "parliament",
    # organisation / treaty acronyms
    "evfta", "ets", "tca", "ccrm",
    # company names / company type suffixes
    "dhl", "gmbh", "sia",
    # person names
    "georgi", "goranov", "omer", "michael", "momchil", "jason", "enrika",
    # foreign-language words (Latvian)
    "valsts", "dienests",
    # place name
    "riverside", "hauptzollamt",
    # abbreviations and shorthand
    "vol", "lux", "ils", "arts", "para", "etc", "minimis",
    # informal / ambiguous
    "cookies", "toolkit", "sized", "splitting",
    # uncommon / corpus-specific
    "peculiarities",
    # past-participle verb forms (not lexical nouns/adjs)
    "abolished", "formulated",
    # notes: too common (likely T1/T2 inflected form of "note")
    "notes",
    # trade-adjacent general terms that are better T4
    "representation",  # "customs representation" is T4
    # NE-adjacent: "WCO Secretariat", "UN Secretariat" etc.
    "secretariat",
    # conjugated verb form (not a lemma)
    "corresponds",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_pool() -> list[tuple[int, str]]:
    """Return [(count, token), ...] sorted by count descending."""
    rows = []
    with POOL_PATH.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            parts = line.split("\t", 1)
            if len(parts) == 2:
                rows.append((int(parts[0]), parts[1]))
    return sorted(rows, key=lambda x: -x[0])


def _load_existing_en(conn: sqlite3.Connection) -> set[str]:
    return {r[0].lower() for r in conn.execute(
        "SELECT LOWER(word) FROM concept_lang WHERE lang = ?", (LANG,)
    )}


def _load_domain_mwe_en() -> set[str]:
    phrases: set[str] = set()
    for db in DOMAIN_DBS:
        if not db.exists():
            continue
        c = sqlite3.connect(db)
        for (p,) in c.execute(
            "SELECT LOWER(phrase_normalized) FROM mwe_lang WHERE lang = ?", (LANG,)
        ):
            phrases.add(p)
        c.close()
    return phrases


def _is_alpha_hyphen(token: str) -> bool:
    """Token must be 2+ alpha chars, optionally separated by a single internal hyphen."""
    return bool(re.match(r"^[a-z][a-z-]*[a-z]$", token))


def _matches_t4_stem(token: str) -> bool:
    tl = token.lower()
    return any(tl.startswith(s.lower()) for s in _TIER4_STEMS)


# ---------------------------------------------------------------------------
# Main filter pipeline
# ---------------------------------------------------------------------------


def run_filters(
    pool: list[tuple[int, str]],
    existing_en: set[str],
    domain_mwe: set[str],
) -> dict:
    """Apply all filter stages; return a dict with survivor lists and rejected sets."""
    rejected_a1_freq: list[tuple[int, str]] = []
    rejected_a1_char: list[tuple[int, str]] = []
    rejected_a1_short: list[tuple[int, str]] = []
    rejected_a1_existing: list[tuple[int, str]] = []
    rejected_a1_mwe: list[tuple[int, str]] = []
    survivors_a1: list[tuple[int, str]] = []

    for count, token in pool:
        tl = token.lower()
        if count < MIN_FREQ:
            rejected_a1_freq.append((count, tl))
            continue
        if len(tl) < MIN_LEN:
            rejected_a1_short.append((count, tl))
            continue
        if not _is_alpha_hyphen(tl):
            rejected_a1_char.append((count, tl))
            continue
        if tl in existing_en:
            rejected_a1_existing.append((count, tl))
            continue
        if tl in domain_mwe:
            rejected_a1_mwe.append((count, tl))
            continue
        survivors_a1.append((count, tl))

    # A2a — Tier 4 stem exclusion
    rejected_a2a: list[tuple[int, str]] = []
    survivors_a2a: list[tuple[int, str]] = []
    for count, tl in survivors_a1:
        if _matches_t4_stem(tl):
            rejected_a2a.append((count, tl))
        else:
            survivors_a2a.append((count, tl))

    # A2b — Named entities
    rejected_a2b: list[tuple[int, str]] = []
    survivors_a2b: list[tuple[int, str]] = []
    for count, tl in survivors_a2a:
        if tl in _NE_WORDS:
            rejected_a2b.append((count, tl))
        else:
            survivors_a2b.append((count, tl))

    # A2c — Fragment artefacts
    rejected_a2c: list[tuple[int, str]] = []
    survivors_a2c: list[tuple[int, str]] = []
    for count, tl in survivors_a2b:
        if len(tl) <= 2:
            rejected_a2c.append((count, tl))
        elif tl.endswith("-"):
            rejected_a2c.append((count, tl))
        elif tl in _PREFIX_FRAGMENTS:
            rejected_a2c.append((count, tl))
        else:
            survivors_a2c.append((count, tl))

    # A3 — Manual second-pass: additional T4 + noise
    review_t4: list[tuple[int, str]] = []
    review_noise: list[tuple[int, str]] = []
    survivors_a3: list[tuple[int, str]] = []
    for count, tl in survivors_a2c:
        if tl in _MANUAL_T4:
            review_t4.append((count, tl))
        elif tl in _MANUAL_NOISE:
            review_noise.append((count, tl))
        else:
            survivors_a3.append((count, tl))

    return {
        "pool_total": len(pool),
        "rejected_a1_freq": rejected_a1_freq,
        "rejected_a1_char": rejected_a1_char,
        "rejected_a1_short": rejected_a1_short,
        "rejected_a1_existing": rejected_a1_existing,
        "rejected_a1_mwe": rejected_a1_mwe,
        "survivors_a1": survivors_a1,
        "rejected_a2a": rejected_a2a,
        "survivors_a2a": survivors_a2a,
        "rejected_a2b": rejected_a2b,
        "survivors_a2b": survivors_a2b,
        "rejected_a2c": rejected_a2c,
        "survivors_a2c": survivors_a2c,
        "review_t4": review_t4,
        "review_noise": review_noise,
        "survivors": survivors_a3,
    }


# ---------------------------------------------------------------------------
# Insertion
# ---------------------------------------------------------------------------


def _tag_pos(words: list[str]) -> dict[str, str]:
    """Return {word → spaCy UPOS tag} for each word using en_core_web_sm."""
    import spacy
    try:
        nlp = spacy.load("en_core_web_sm", disable=["ner", "parser"])
    except OSError:
        return {}
    result: dict[str, str] = {}
    for word in words:
        doc = nlp(word)
        if doc:
            result[word] = doc[0].pos_
    return result


def insert_tier3(conn: sqlite3.Connection, candidates: list[tuple[int, str]]) -> int:
    """Insert each candidate as a new concept + concept_lang row. Return insert count."""
    words = [w for _, w in candidates]
    pos_map = _tag_pos(words)

    inserted = 0
    for _count, word in candidates:
        # Check if already present at any tier (double-guard)
        existing = conn.execute(
            "SELECT id FROM concept_lang WHERE lang = ? AND LOWER(word) = ?",
            (LANG, word),
        ).fetchone()
        if existing:
            continue
        pos = pos_map.get(word, "NOUN")  # NOUN is the safest fallback
        # Create a minimal concept row (eo_status='pending')
        cur = conn.execute(
            "INSERT INTO concept (eo_status) VALUES ('pending')"
        )
        concept_id = cur.lastrowid
        conn.execute(
            "INSERT INTO concept_lang"
            " (concept_id, lang, word, pos, tier, cefr_level, source)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (concept_id, LANG, word, pos, TIER, CEFR, SOURCE_TAG),
        )
        inserted += 1
    conn.commit()
    return inserted


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _sample(lst: list, n: int = 20) -> list:
    return [t for _, t in lst[:n]]


def print_report(result: dict, dry_run: bool) -> None:
    print("=" * 72)
    print("TASK A — Tier 3 seeding from UNKNOWN pool")
    print("=" * 72)
    print(f"Source pool total tokens:           {result['pool_total']:>6,}")
    a1_total = (
        len(result["rejected_a1_freq"])
        + len(result["rejected_a1_char"])
        + len(result["rejected_a1_short"])
        + len(result["rejected_a1_existing"])
        + len(result["rejected_a1_mwe"])
    )
    print(f"  Rejected (freq < {MIN_FREQ}):             "
          f"{len(result['rejected_a1_freq']):>6,}")
    print(f"  Rejected (non-alpha/char noise):  {len(result['rejected_a1_char']):>6,}")
    print(f"  Rejected (len < {MIN_LEN}):              "
          f"{len(result['rejected_a1_short']):>6,}")
    print(f"  Rejected (already in lexicon):   {len(result['rejected_a1_existing']):>6,}")
    print(f"  Rejected (in domain MWE):        {len(result['rejected_a1_mwe']):>6,}")
    print(f"Survived A1 structural:             {len(result['survivors_a1']):>6,}")
    print()
    print(f"  Rejected A2a (T4 stem prefix):   {len(result['rejected_a2a']):>6,}")
    print(f"Survived A2a:                       {len(result['survivors_a2a']):>6,}")
    print()
    print(f"  Rejected A2b (named entities):   {len(result['rejected_a2b']):>6,}")
    print(f"Survived A2b:                       {len(result['survivors_a2b']):>6,}")
    print()
    print(f"  Rejected A2c (fragments):        {len(result['rejected_a2c']):>6,}")
    print(f"Survived A2c:                       {len(result['survivors_a2c']):>6,}")
    print()
    print(f"  Removed A3 (possible T4):        {len(result['review_t4']):>6,}")
    print(f"  Removed A3 (noise/NE/artefact):  {len(result['review_noise']):>6,}")
    print(f"Survived all filters (to insert):   {len(result['survivors']):>6,}")
    print()

    print("─" * 60)
    print(f"Top 10 A1 sample (freq≥{MIN_FREQ}, alpha, new):")
    print(" ", _sample(result["survivors_a1"], 10))

    print()
    print("─" * 60)
    print("REVIEW — possible Tier 4 missed by stoplist (excluded from T3):")
    for count, t in result["review_t4"]:
        print(f"  {count:4d}  {t}")

    print()
    print("─" * 60)
    print("REVIEW — noise / NE / artefacts excluded in A3:")
    for count, t in result["review_noise"]:
        print(f"  {count:4d}  {t}")

    print()
    print("─" * 60)
    n = len(result["survivors"])
    print(f"Tier 3 CANDIDATES ({n} words):  "
          f"{'(DRY-RUN — not inserted)' if dry_run else '(inserted)'}")
    for count, t in result["survivors"]:
        print(f"  {count:4d}  {t}")

    print()
    print("Top 20 rejected A2a (T4 stems):", _sample(result["rejected_a2a"], 20))
    print("Top 20 rejected A2b (NE):",       _sample(result["rejected_a2b"], 20))
    print("Top 20 rejected A2c (frags):",    _sample(result["rejected_a2c"], 20))
    print("=" * 72)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Seed Tier 3 vocabulary from UNKNOWN token pool."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print filter results without inserting into the lexicon DB."
    )
    args = parser.parse_args(argv)

    if not POOL_PATH.exists():
        print(f"ERROR: pool file not found: {POOL_PATH}", file=sys.stderr)
        sys.exit(1)
    if not LEXICON_DB.exists():
        print(f"ERROR: lexicon DB not found: {LEXICON_DB}", file=sys.stderr)
        sys.exit(1)

    pool = _load_pool()
    conn = sqlite3.connect(LEXICON_DB)
    existing_en = _load_existing_en(conn)
    domain_mwe = _load_domain_mwe_en()

    result = run_filters(pool, existing_en, domain_mwe)
    candidates = result["survivors"]

    n = len(candidates)
    if n < 20:
        print_report(result, dry_run=True)
        print(f"\nSTOP: only {n} candidates survived (< 20). Review filters before inserting.",
              file=sys.stderr)
        conn.close()
        sys.exit(2)
    if n > 200:
        print_report(result, dry_run=True)
        print(f"\nSTOP: {n} candidates survived (> 200). Filters may be too permissive.",
              file=sys.stderr)
        conn.close()
        sys.exit(2)

    print_report(result, dry_run=args.dry_run)

    if not args.dry_run:
        inserted = insert_tier3(conn, candidates)
        print(f"\nInserted {inserted} Tier 3 entries into {LEXICON_DB}")
        tier3_count = conn.execute(
            "SELECT COUNT(*) FROM concept_lang WHERE tier = 3 AND lang = ?", (LANG,)
        ).fetchone()[0]
        print(f"Tier 3 total (lang='en') after insertion: {tier3_count}")
    conn.close()


if __name__ == "__main__":
    main()
