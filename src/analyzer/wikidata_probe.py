#!/usr/bin/env python3
"""D7 Wikidata feasibility probe for the names gazetteer (READ-ONLY).

Answers one decision question with numbers: **how far down the salience curve
does Esperanto-label coverage hold on Wikidata?** The "seed the physically-
anchored names core from Wikidata instead of translating one-by-one" plan
rests on Wikidata already carrying ``eo`` labels for salient entities. This
probe measures that: per closed set, EO-label coverage % at salience depths
top-50 / top-200 / top-1000 (by sitelinks), plus salience usability, a
P31->coarse-type mapping, alias availability, and CC0 licensing.

Scope bounds (this is a *probe*, not a build):
  * No writes to ``lexicon_v2.db``, no ``named_entity`` schema, no gazetteer.
  * Only reads from the public Wikidata SPARQL endpoint (CC0 data).

Operating reality (2026-07): the programmatic endpoint
``https://query.wikidata.org/sparql`` is throttled to ~1 request/minute during
an active WDQS outage. This module therefore:
  * paces API calls at <= 1/min and backs off exponentially on HTTP 429,
  * caches every response on disk under ``_cache/`` (re-runs hit cache),
  * prefers a human-provided ``manual_pulls/<set_key>.json`` (Wikidata GUI
    "Download -> JSON") over the network, since the GUI is not throttled.

Human-in-the-loop contract: ``emit_query_files()`` writes one ``.rq`` per set
plus ``MANUAL_PULL_README.md`` so a human can run the queries in the browser
and drop the JSON at ``manual_pulls/<set_key>.json``. The SPARQL JSON the GUI
downloads is byte-identical in shape to the API response, so ``parse_rows()``
handles both. The probe still completes fully standalone (just slower).

Pure logic (query builder, row parsing, coverage %, coarse-type mapper, TSV
writer) is import-safe and unit-tested with fixture JSON; nothing here touches
the network at import time.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SPARQL_ENDPOINT = "https://query.wikidata.org/sparql"
USER_AGENT = "esperanto-lexicon-probe/0.1 (research; contact team@customsclear.net)"
GUI_URL = "https://query.wikidata.org"

# Repo-relative default locations (data/analysis/names/...).
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
NAMES_DIR = _REPO_ROOT / "data" / "analysis" / "names"

MIN_REQUEST_INTERVAL_S = 60.0  # <= 1 request / minute while WDQS is throttled
MAX_BACKOFF_S = 300.0  # cap exponential backoff at ~5 min per the brief
MAX_RETRIES = 5

SALIENCE_DEPTHS = (50, 200, 1000)


# ---------------------------------------------------------------------------
# Coarse-type mapping: P31 (instance-of) QID -> our four coarse buckets.
#
# This is the *messiness* instrument, not the authoritative label. Each set
# already declares its own coarse_type (see SETS), which is what the sample TSV
# uses. This mapper independently classifies each raw P31 QID an entity carries,
# so the memo can report how cleanly P31 maps to coarse types and where it does
# not (multi-P31 entities, unmapped classes). QIDs with no mapping return the
# sentinel "unmapped" -- that is a finding, not an error.
# ---------------------------------------------------------------------------

COARSE_CELESTIAL = "celestial"
COARSE_PHYSICAL = "physical_geographic"
COARSE_INSTITUTIONAL = "institutional"
COARSE_SETTLEMENT = "settlement"
COARSE_UNMAPPED = "unmapped"

# Known class QIDs -> coarse type. Deliberately a curated core; anything not
# here surfaces as "unmapped" and is reported as P31 messiness.
P31_COARSE_TYPE: dict[str, str] = {
    # celestial
    "Q634": COARSE_CELESTIAL,  # planet
    "Q30014": COARSE_CELESTIAL,  # dwarf planet
    "Q3504248": COARSE_CELESTIAL,  # inner planet of the Solar System
    "Q30060419": COARSE_CELESTIAL,  # outer planet of the Solar System
    "Q128207": COARSE_CELESTIAL,  # terrestrial planet
    "Q128944": COARSE_CELESTIAL,  # gas giant
    "Q523": COARSE_CELESTIAL,  # star
    "Q5864": COARSE_CELESTIAL,  # G-type main-sequence star
    "Q2537": COARSE_CELESTIAL,  # natural satellite (moon)
    "Q3323914": COARSE_CELESTIAL,  # S-type asteroid (defensive)
    # physical geography
    "Q9430": COARSE_PHYSICAL,  # ocean
    "Q5107": COARSE_PHYSICAL,  # continent
    "Q165": COARSE_PHYSICAL,  # sea
    "Q4022": COARSE_PHYSICAL,  # river
    "Q8502": COARSE_PHYSICAL,  # mountain
    "Q8514": COARSE_PHYSICAL,  # desert
    "Q46831": COARSE_PHYSICAL,  # mountain range
    "Q23442": COARSE_PHYSICAL,  # island
    "Q23397": COARSE_PHYSICAL,  # lake
    "Q37901": COARSE_PHYSICAL,  # strait
    "Q39594": COARSE_PHYSICAL,  # cape (defensive)
    "Q9430430": COARSE_PHYSICAL,  # body of water (defensive)
    # institutional
    "Q3624078": COARSE_INSTITUTIONAL,  # sovereign state
    "Q6256": COARSE_INSTITUTIONAL,  # country
    "Q7275": COARSE_INSTITUTIONAL,  # state
    "Q1335818": COARSE_INSTITUTIONAL,  # supranational union
    "Q484652": COARSE_INSTITUTIONAL,  # international organization
    "Q245065": COARSE_INSTITUTIONAL,  # intergovernmental organization
    "Q1050501": COARSE_INSTITUTIONAL,  # military alliance
    "Q43229": COARSE_INSTITUTIONAL,  # organization (defensive)
    # settlement
    "Q515": COARSE_SETTLEMENT,  # city
    "Q1549591": COARSE_SETTLEMENT,  # big city
    "Q486972": COARSE_SETTLEMENT,  # human settlement
    "Q5119": COARSE_SETTLEMENT,  # capital city
    "Q1637706": COARSE_SETTLEMENT,  # city with millions of inhabitants
    "Q200250": COARSE_SETTLEMENT,  # metropolis
}


def coarse_type_for(type_qids: Iterable[str]) -> str:
    """Map a set of raw P31 QIDs to a single coarse type.

    Returns the coarse type of the first QID (in iteration order) that has a
    known mapping. If several map to *different* coarse types, returns a
    ``"mixed:a+b"`` marker (sorted, deduped) so the caller can count genuine
    cross-type entities. Returns ``"unmapped"`` if none map.
    """
    seen: list[str] = []
    for qid in type_qids:
        coarse = P31_COARSE_TYPE.get(qid)
        if coarse and coarse not in seen:
            seen.append(coarse)
    if not seen:
        return COARSE_UNMAPPED
    if len(seen) == 1:
        return seen[0]
    return "mixed:" + "+".join(sorted(seen))


# ---------------------------------------------------------------------------
# Target set registry
# ---------------------------------------------------------------------------


@dataclass
class SetDef:
    """One closed target set to pull.

    Exactly one of ``p31`` (class filter, top-N by sitelinks) or ``qids``
    (curated VALUES list) drives the query. ``coarse_type`` is the
    authoritative coarse bucket for the sample TSV (the set's *intent*).
    """

    key: str
    title: str
    coarse_type: str
    limit: int
    p31: Optional[str] = None  # e.g. "Q4022" -> instance of river
    qids: tuple[str, ...] = ()  # curated VALUES list (celestial small sets)
    note: str = ""

    def __post_init__(self) -> None:
        if bool(self.p31) == bool(self.qids):
            raise ValueError(
                f"set {self.key!r} must set exactly one of p31 / qids"
            )


# Curated celestial QIDs (P31 filters are messy for these; brief permits
# curated lists and asks that we note it).
_PLANET_QIDS = (
    "Q308",  # Mercury
    "Q313",  # Venus
    "Q2",  # Earth
    "Q111",  # Mars
    "Q319",  # Jupiter
    "Q193",  # Saturn
    "Q324",  # Uranus
    "Q332",  # Neptune
)
_SUN_QID = ("Q525",)  # the Sun
# Nearest / brightest stars named in the brief.
_STAR_QIDS = (
    "Q14001",  # Proxima Centauri
    "Q12176",  # Alpha Centauri
    "Q3037",  # Sirius
    "Q11002",  # Barnard's Star
    "Q3033",  # Betelgeuse (bright, well-known control)
    "Q12167",  # Vega
)
# Major institutional orgs (curated; P31 supranational-union is too narrow for
# NATO/UN which are not "unions"). Note this in the memo.
_ORG_QIDS = (
    "Q458",  # European Union
    "Q1065",  # United Nations
    "Q7184",  # NATO
    "Q7768",  # ASEAN
    "Q7159",  # African Union
    "Q37230",  # World Trade Organization
    "Q7817",  # World Health Organization
    "Q1132",  # International Monetary Fund
    "Q7164",  # World Bank
    "Q8908",  # Council of Europe
    "Q41550",  # OECD
    "Q1043527",  # OPEC
)

SETS: tuple[SetDef, ...] = (
    # --- celestial (curated) ---
    SetDef("planets", "Planets of the Solar System", COARSE_CELESTIAL, 10,
           qids=_PLANET_QIDS, note="curated 8-planet QID list"),
    SetDef("sun", "The Sun", COARSE_CELESTIAL, 5,
           qids=_SUN_QID, note="curated single QID"),
    SetDef("moons", "Major natural satellites", COARSE_CELESTIAL, 30,
           p31="Q2537", note="P31 natural satellite, top-N by sitelinks"),
    SetDef("stars", "Nearest / brightest named stars", COARSE_CELESTIAL, 10,
           qids=_STAR_QIDS, note="curated near-star list from the brief"),
    # --- physical geography (class filters) ---
    SetDef("oceans", "Oceans", COARSE_PHYSICAL, 10, p31="Q9430"),
    SetDef("continents", "Continents", COARSE_PHYSICAL, 12, p31="Q5107"),
    SetDef("seas", "Seas", COARSE_PHYSICAL, 40, p31="Q165"),
    SetDef("rivers", "Rivers", COARSE_PHYSICAL, 50, p31="Q4022"),
    SetDef("mountains", "Mountains", COARSE_PHYSICAL, 30, p31="Q8502"),
    SetDef("deserts", "Deserts", COARSE_PHYSICAL, 20, p31="Q8514"),
    SetDef("ranges", "Mountain ranges", COARSE_PHYSICAL, 20, p31="Q46831"),
    SetDef("islands", "Largest islands", COARSE_PHYSICAL, 30, p31="Q23442"),
    SetDef("lakes", "Lakes", COARSE_PHYSICAL, 20, p31="Q23397"),
    SetDef("straits", "Straits", COARSE_PHYSICAL, 15, p31="Q37901"),
    # --- institutional ---
    SetDef("orgs", "Supranational unions / major orgs", COARSE_INSTITUTIONAL,
           15, qids=_ORG_QIDS,
           note="curated; P31 supranational-union too narrow for UN/NATO"),
    SetDef("sovereign_states", "Sovereign states", COARSE_INSTITUTIONAL, 200,
           p31="Q3624078"),
    # --- settlements ---
    SetDef("cities", "Cities by sitelinks", COARSE_SETTLEMENT, 300,
           p31="Q515"),
)


def set_by_key(key: str) -> SetDef:
    for s in SETS:
        if s.key == key:
            return s
    raise KeyError(key)


# ---------------------------------------------------------------------------
# Query builder (pure)
# ---------------------------------------------------------------------------


def build_query(s: SetDef) -> str:
    """Build the SPARQL query string for a target set.

    Two shapes, both selecting item/en/eo/sitelinks plus grouped P31 types and
    en/eo altLabels:
      * ``p31`` sets: an inner subquery grabs the top-N items by sitelinks for
        the class first (keeps the join small), then labels/types/aliases are
        attached and grouped. EO label is OPTIONAL -- its absence is the
        measurement.
      * ``qids`` sets: a ``VALUES ?item { ... }`` curated list.
    """
    select = (
        "SELECT ?item ?en ?eo ?sitelinks\n"
        '  (GROUP_CONCAT(DISTINCT ?typeQid; SEPARATOR="|") AS ?types)\n'
        '  (GROUP_CONCAT(DISTINCT ?enAlias; SEPARATOR="|") AS ?enAliases)\n'
        '  (GROUP_CONCAT(DISTINCT ?eoAlias; SEPARATOR="|") AS ?eoAliases)\n'
    )
    optionals = (
        '  OPTIONAL { ?item rdfs:label ?en FILTER(LANG(?en)="en") }\n'
        '  OPTIONAL { ?item rdfs:label ?eo FILTER(LANG(?eo)="eo") }\n'
        "  OPTIONAL { ?item wdt:P31 ?type .\n"
        '    BIND(STRAFTER(STR(?type), "entity/") AS ?typeQid) }\n'
        '  OPTIONAL { ?item skos:altLabel ?enAlias FILTER(LANG(?enAlias)="en") }\n'
        '  OPTIONAL { ?item skos:altLabel ?eoAlias FILTER(LANG(?eoAlias)="eo") }\n'
    )
    tail = (
        "}\n"
        "GROUP BY ?item ?en ?eo ?sitelinks\n"
        "ORDER BY DESC(?sitelinks)\n"
    )

    if s.p31:
        core = (
            "  {\n"
            "    SELECT ?item ?sitelinks WHERE {\n"
            f"      ?item wdt:P31 wd:{s.p31} .\n"
            "      ?item wikibase:sitelinks ?sitelinks .\n"
            f"    }} ORDER BY DESC(?sitelinks) LIMIT {s.limit}\n"
            "  }\n"
        )
    else:
        values = " ".join(f"wd:{q}" for q in s.qids)
        core = (
            f"  VALUES ?item {{ {values} }}\n"
            "  ?item wikibase:sitelinks ?sitelinks .\n"
        )

    header = (
        f"# {s.title} ({s.key}) -- coarse_type={s.coarse_type}\n"
        f"# {s.note or 'P31 class filter, top-N by sitelinks'}\n"
        f"# EO label is OPTIONAL: its absence is the coverage measurement.\n"
    )
    return header + select + "WHERE {\n" + core + optionals + tail


# ---------------------------------------------------------------------------
# Row parsing (pure) -- one parser for API JSON and GUI-downloaded JSON.
# ---------------------------------------------------------------------------


@dataclass
class Row:
    """One parsed entity row from a SPARQL result."""

    qid: str
    label_en: str
    label_eo: str  # "" when Wikidata has no eo label -- the coverage signal
    sitelinks: int
    type_qids: tuple[str, ...]
    en_aliases: tuple[str, ...]
    eo_aliases: tuple[str, ...]
    coarse_type_p31: str = field(default="")  # derived from type_qids

    @property
    def has_eo(self) -> bool:
        return bool(self.label_eo.strip())


def _qid_from_uri(uri: str) -> str:
    """Extract 'Q42' from a Wikidata entity URI (or pass through a bare QID)."""
    return uri.rsplit("/", 1)[-1] if "/" in uri else uri


def _split_concat(value: str) -> tuple[str, ...]:
    """Split a GROUP_CONCAT '|'-joined field into a deduped, ordered tuple."""
    if not value:
        return ()
    out: list[str] = []
    for part in value.split("|"):
        part = part.strip()
        if part and part not in out:
            out.append(part)
    return tuple(out)


def parse_rows(result_json: dict) -> list[Row]:
    """Parse a SPARQL JSON result (API or GUI download) into Row objects.

    Expects the standard ``{"results": {"bindings": [...]}}`` shape. Missing
    OPTIONAL bindings (notably ``eo``) simply produce empty strings. Rows are
    sorted by sitelinks descending so callers can slice salience depths without
    trusting the server's ORDER BY to survive a manual re-save.
    """
    bindings = result_json.get("results", {}).get("bindings", [])
    rows: list[Row] = []
    for b in bindings:
        item_uri = b.get("item", {}).get("value", "")
        if not item_uri:
            continue
        qid = _qid_from_uri(item_uri)
        label_en = b.get("en", {}).get("value", "")
        label_eo = b.get("eo", {}).get("value", "")
        sitelinks_raw = b.get("sitelinks", {}).get("value", "0")
        try:
            sitelinks = int(sitelinks_raw)
        except (TypeError, ValueError):
            sitelinks = 0
        type_qids = tuple(
            _qid_from_uri(t) for t in _split_concat(b.get("types", {}).get("value", ""))
        )
        en_aliases = _split_concat(b.get("enAliases", {}).get("value", ""))
        eo_aliases = _split_concat(b.get("eoAliases", {}).get("value", ""))
        rows.append(
            Row(
                qid=qid,
                label_en=label_en,
                label_eo=label_eo,
                sitelinks=sitelinks,
                type_qids=type_qids,
                en_aliases=en_aliases,
                eo_aliases=eo_aliases,
                coarse_type_p31=coarse_type_for(type_qids),
            )
        )
    rows.sort(key=lambda r: r.sitelinks, reverse=True)
    return rows


# ---------------------------------------------------------------------------
# Coverage computation (pure) -- the headline measurement.
# ---------------------------------------------------------------------------


@dataclass
class CoverageAtDepth:
    depth: int
    n: int  # entities actually considered (min(depth, set size))
    n_with_eo: int

    @property
    def pct(self) -> float:
        return 100.0 * self.n_with_eo / self.n if self.n else 0.0


def coverage_at_depths(
    rows: list[Row], depths: Iterable[int] = SALIENCE_DEPTHS
) -> list[CoverageAtDepth]:
    """EO-label coverage % at each salience depth.

    ``rows`` must be salience-sorted (``parse_rows`` guarantees this). At depth
    D we look at the top ``min(D, len(rows))`` rows and count how many carry a
    non-empty eo label. Depths larger than the set size collapse to the full
    set -- reported honestly via ``n``.
    """
    out: list[CoverageAtDepth] = []
    for d in depths:
        head = rows[:d]
        n_with_eo = sum(1 for r in head if r.has_eo)
        out.append(CoverageAtDepth(depth=d, n=len(head), n_with_eo=n_with_eo))
    return out


def alias_coverage(rows: list[Row]) -> tuple[float, float]:
    """Return (en_alias_%, eo_alias_%) -- share of rows with >=1 alias."""
    if not rows:
        return (0.0, 0.0)
    en = 100.0 * sum(1 for r in rows if r.en_aliases) / len(rows)
    eo = 100.0 * sum(1 for r in rows if r.eo_aliases) / len(rows)
    return (en, eo)


# ---------------------------------------------------------------------------
# TSV writer (pure)
# ---------------------------------------------------------------------------

TSV_HEADER = ("qid", "label_en", "label_eo", "coarse_type", "sitelinks", "aliases")


def _tsv_escape(value: str) -> str:
    """Make a value safe for a single TSV cell (no tabs/newlines)."""
    return value.replace("\t", " ").replace("\r", " ").replace("\n", " ")


def rows_to_tsv_lines(rows_with_type: Iterable[tuple[Row, str]]) -> list[str]:
    """Render (Row, authoritative_coarse_type) pairs to TSV lines.

    ``aliases`` column joins en+eo aliases with ';' (en first). The coarse_type
    passed in is the set's authoritative intent, not the P31-derived guess.
    """
    lines = ["\t".join(TSV_HEADER)]
    for row, coarse_type in rows_with_type:
        aliases = ";".join((*row.en_aliases, *row.eo_aliases))
        lines.append(
            "\t".join(
                (
                    _tsv_escape(row.qid),
                    _tsv_escape(row.label_en),
                    _tsv_escape(row.label_eo),
                    _tsv_escape(coarse_type),
                    str(row.sitelinks),
                    _tsv_escape(aliases),
                )
            )
        )
    return lines


def write_tsv(rows_with_type: Iterable[tuple[Row, str]], path: Path) -> None:
    lines = rows_to_tsv_lines(rows_with_type)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Query runner -- manual-pull-or-paced-API, on-disk cache, 429 backoff.
# (Network code; not exercised in tests.)
# ---------------------------------------------------------------------------


class QueryRunner:
    """Fetches SPARQL results with a manual-pull-first, cache-second, paced-
    API-third strategy.

    Source precedence per set_key:
      1. ``manual_pulls/<set_key>.json`` (human ran it in the GUI) -> "manual"
      2. ``_cache/<queryhash>.json`` (we fetched it before) -> "cache"
      3. paced API GET (<=1/min, 429 backoff) -> "api", then cached.
    """

    def __init__(
        self,
        names_dir: Path = NAMES_DIR,
        min_interval_s: float = MIN_REQUEST_INTERVAL_S,
    ) -> None:
        self.names_dir = names_dir
        self.cache_dir = names_dir / "_cache"
        self.manual_dir = names_dir / "manual_pulls"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.min_interval_s = min_interval_s
        self._last_request_ts: Optional[float] = None

    def _cache_path(self, query: str) -> Path:
        digest = hashlib.sha256(query.encode("utf-8")).hexdigest()[:16]
        return self.cache_dir / f"{digest}.json"

    def _pace(self) -> None:
        if self._last_request_ts is None:
            return
        elapsed = time.monotonic() - self._last_request_ts
        wait = self.min_interval_s - elapsed
        if wait > 0:
            print(f"    pacing: sleeping {wait:.0f}s (<=1 req/min)...", flush=True)
            time.sleep(wait)

    def _fetch_api(self, query: str) -> dict:
        """GET the endpoint with UA, pacing, and exponential 429 backoff."""
        params = urllib.parse.urlencode({"query": query, "format": "json"})
        url = f"{SPARQL_ENDPOINT}?{params}"
        backoff = self.min_interval_s
        for attempt in range(1, MAX_RETRIES + 1):
            self._pace()
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "application/sparql-results+json",
                },
            )
            self._last_request_ts = time.monotonic()
            try:
                with urllib.request.urlopen(req, timeout=90) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                if exc.code == 429:
                    print(
                        f"    HTTP 429 (attempt {attempt}/{MAX_RETRIES}); "
                        f"backing off {backoff:.0f}s",
                        flush=True,
                    )
                    time.sleep(backoff)
                    backoff = min(backoff * 2, MAX_BACKOFF_S)
                    continue
                raise
            except urllib.error.URLError as exc:
                print(f"    network error (attempt {attempt}): {exc}", flush=True)
                time.sleep(backoff)
                backoff = min(backoff * 2, MAX_BACKOFF_S)
        raise RuntimeError(
            f"endpoint unavailable after {MAX_RETRIES} attempts (WDQS outage?)"
        )

    def get(self, set_key: str, query: str) -> tuple[dict, str]:
        """Return (result_json, source) where source in manual/cache/api."""
        manual = self.manual_dir / f"{set_key}.json"
        if manual.exists():
            return json.loads(manual.read_text(encoding="utf-8")), "manual"
        cache = self._cache_path(query)
        if cache.exists():
            return json.loads(cache.read_text(encoding="utf-8")), "cache"
        result = self._fetch_api(query)
        cache.write_text(json.dumps(result), encoding="utf-8")
        return result, "api"


# ---------------------------------------------------------------------------
# P0: emit query files + human-pull README
# ---------------------------------------------------------------------------


def emit_query_files(names_dir: Path = NAMES_DIR) -> None:
    """Write per-set .rq files and MANUAL_PULL_README.md -- the human signal."""
    q_dir = names_dir / "queries"
    q_dir.mkdir(parents=True, exist_ok=True)
    for s in SETS:
        (q_dir / f"{s.key}.rq").write_text(build_query(s), encoding="utf-8")

    lines = [
        "# Manual pull instructions -- D7 Wikidata names probe",
        "",
        "The programmatic SPARQL endpoint is throttled to ~1 req/min (WDQS",
        "outage). The **web GUI is not throttled**. You can run any/all of the",
        "queries below in the browser to speed the probe up; the probe also",
        "completes standalone if you do nothing.",
        "",
        "## How to hand-pull a set",
        f"1. Open <{GUI_URL}>.",
        "2. Open the query file `data/analysis/names/queries/<set_key>.rq`,",
        "   paste its body into the editor (the leading `#` comment lines are",
        "   fine to include), and run it (Ctrl+Enter).",
        "3. Click **Download -> JSON**.",
        "4. Save it to `data/analysis/names/manual_pulls/<set_key>.json`",
        "   (exact set_key from the table below -- the filename is the contract).",
        "",
        "The probe checks `manual_pulls/<set_key>.json` first for every set; if",
        "present it uses your file, else it fetches via the paced API. Either",
        "way it logs the source per set.",
        "",
        "## Sets",
        "",
        "| set_key | what | limit | save as |",
        "| --- | --- | --- | --- |",
    ]
    for s in SETS:
        lines.append(
            f"| `{s.key}` | {s.title} | {s.limit} | "
            f"`manual_pulls/{s.key}.json` |"
        )
    lines.extend(
        [
            "",
            "All sets are salience-sorted `ORDER BY DESC(?sitelinks)`. EO label",
            "is OPTIONAL in every query -- its absence is exactly what we are",
            "measuring, so do not filter it out.",
            "",
        ]
    )
    (names_dir / "MANUAL_PULL_README.md").write_text(
        "\n".join(lines), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# QID verification probes (P0 step 3)
# ---------------------------------------------------------------------------

# Cheap anchor checks: QID -> expected English label substring (lowercased).
ANCHOR_QIDS: dict[str, str] = {
    "Q525": "sun",
    "Q2537": "satellite",
    "Q523": "star",
    "Q9430": "ocean",
    "Q5107": "continent",
    "Q165": "sea",
    "Q4022": "river",
    "Q8502": "mountain",
    "Q46831": "range",
    "Q8514": "desert",
    "Q23442": "island",
    "Q23397": "lake",
    "Q37901": "strait",
    "Q3624078": "state",
    "Q1335818": "union",
    "Q515": "city",
    "Q634": "planet",
}


def build_anchor_query(qids: Iterable[str]) -> str:
    """One VALUES query returning en labels for the anchor class QIDs."""
    values = " ".join(f"wd:{q}" for q in qids)
    return (
        "# anchor QID verification -- en labels for the class QIDs we filter on\n"
        "SELECT ?item ?en WHERE {\n"
        f"  VALUES ?item {{ {values} }}\n"
        '  OPTIONAL { ?item rdfs:label ?en FILTER(LANG(?en)="en") }\n'
        "}\n"
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cmd_emit_queries(args: argparse.Namespace) -> int:
    emit_query_files(NAMES_DIR)
    q_dir = NAMES_DIR / "queries"
    n = len(list(q_dir.glob("*.rq")))
    print("=" * 68)
    print("QUERIES READY.")
    print(f"  wrote {n} query files -> {q_dir}")
    print(f"  wrote {NAMES_DIR / 'MANUAL_PULL_README.md'}")
    print("")
    print("Ramunas: you can now hand-pull any set in the GUI")
    print(f"  ({GUI_URL} -> paste .rq -> Download -> JSON ->")
    print(f"   save to {NAMES_DIR / 'manual_pulls'}/<set_key>.json).")
    print("The probe will also run standalone under the 1/min throttle.")
    print("=" * 68)
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    runner = QueryRunner(NAMES_DIR)
    query = build_anchor_query(ANCHOR_QIDS.keys())
    try:
        result, source = runner.get("_anchors", query)
    except RuntimeError as exc:
        print(f"ANCHOR VERIFY BLOCKED: {exc}")
        return 2
    labels = {
        _qid_from_uri(b["item"]["value"]): b.get("en", {}).get("value", "")
        for b in result.get("results", {}).get("bindings", [])
    }
    print(f"anchor verification (source={source}):")
    ok = True
    for qid, expect in ANCHOR_QIDS.items():
        got = labels.get(qid, "<missing>")
        good = expect in got.lower()
        ok = ok and good
        print(f"  {qid:12} expect~{expect:12} got={got!r} {'OK' if good else 'CHECK'}")
    return 0 if ok else 1


def _cmd_run(args: argparse.Namespace) -> int:
    from statistics import mean  # local import; pure-logic import stays light

    runner = QueryRunner(NAMES_DIR)
    keys = args.sets or [s.key for s in SETS]
    report: dict[str, dict] = {}
    all_rows_for_tsv: list[tuple[Row, str]] = []
    for key in keys:
        s = set_by_key(key)
        query = build_query(s)
        print(f"[{key}] fetching (limit={s.limit})...", flush=True)
        try:
            result, source = runner.get(key, query)
        except RuntimeError as exc:
            print(f"  BLOCKED: {exc}")
            report[key] = {"error": str(exc)}
            continue
        rows = parse_rows(result)
        cov = coverage_at_depths(rows)
        en_alias, eo_alias = alias_coverage(rows)
        report[key] = {
            "source": source,
            "n": len(rows),
            "coverage": {c.depth: (c.n, c.n_with_eo, round(c.pct, 1)) for c in cov},
            "en_alias_pct": round(en_alias, 1),
            "eo_alias_pct": round(eo_alias, 1),
        }
        print(
            f"  source={source} n={len(rows)} "
            + " ".join(f"@{c.depth}={c.pct:.0f}%(n={c.n})" for c in cov)
        )
        for r in rows:
            all_rows_for_tsv.append((r, s.coarse_type))

    out = NAMES_DIR / "run_report.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nwrote {out}")
    if all_rows_for_tsv:
        tsv = NAMES_DIR / "gazetteer_sample.tsv"
        write_tsv(all_rows_for_tsv, tsv)
        print(f"wrote {tsv} ({len(all_rows_for_tsv)} rows)")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_emit = sub.add_parser("emit-queries", help="write .rq files + README (P0)")
    p_emit.set_defaults(func=_cmd_emit_queries)

    p_verify = sub.add_parser("verify", help="verify anchor QIDs (P0)")
    p_verify.set_defaults(func=_cmd_verify)

    p_run = sub.add_parser("run", help="pull sets, compute coverage (P1/P2)")
    p_run.add_argument("--sets", nargs="*", help="subset of set keys (default all)")
    p_run.set_defaults(func=_cmd_run)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
