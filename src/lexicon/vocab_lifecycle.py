#!/usr/bin/env python3
"""R9 vocabulary lifecycle — the no-loss partition + the conservative routing rule.

Two jobs, both *design + scaffold* (the full 22k sort is explicitly deferred):

1. **No-loss partition (B3).** Every ESPDIC root is always in exactly one
   lifecycle STATE. The states are derived from ground truth — never stored as a
   second source — so nothing can drift:

       covered_tier          root is a content root of a concept placed in T1-T3
       unplaced              root belongs to a concept staged `unplaced`
                             (rising/new; EXCLUDED from the metric)
       t4_domain             root is canonical in some domain DB, incl. philology
                             (fading/archaic philology-T4 is COUNTED like any T4)
       unclassified_obscure  everything else in the inventory (the honest default)

   :func:`partition_roots` is a *total* function over the inventory set, so the
   four state counts always sum to the full inventory (26,447) — before and
   after any move. Movement is a relabel (a status/domain assignment), never a
   delete: no root leaves the inventory.

2. **Routing rule (B2).** :func:`route_obscure_root` scores an obscure root by
   *direction of travel* — fading (→ philology-T4), rising (→ unplaced), or
   unknown (→ leave unclassified). It is deliberately **conservative**: static
   ESPDIC + wordfreq cannot reliably detect "rising", so the honest default is
   `unclassified`. Used to generate the ~200-root validation sample; the full
   sort is NOT run here.
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

# Canonical full-inventory count (eo_inventory.json `roots`), for reference in
# docs/tests. The code derives the real number from the file at runtime; this
# constant is the value the no-loss invariant is expected to reconcile to.
INVENTORY_TOTAL = 26_447

STATES = ("covered_tier", "unplaced", "t4_domain", "unclassified_obscure")


# --------------------------------------------------------------------------- #
# Ground-truth readers (thin; each tolerates absent DBs/tables)
# --------------------------------------------------------------------------- #
def load_inventory_roots(inventory_json: Path) -> set[str]:
    """Return the full set of ESPDIC roots from ``eo_inventory.json``."""
    if not inventory_json.exists():
        return set()
    data = json.loads(inventory_json.read_text(encoding="utf-8"))
    return {r for r in data.get("roots", [])}


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone()
        is not None
    )


def covered_roots(lexicon_db: Path) -> set[str]:
    """Roots of concepts placed in a common tier (T1-T3), excluding ``unplaced``.

    A concept is "placed" if it has any ``concept_lang.tier IN (1,2,3)`` row.
    Its roots come from ``concept_root`` (the decomposed content roots).
    """
    if not lexicon_db.exists():
        return set()
    conn = sqlite3.connect(lexicon_db)
    try:
        if not (_table_exists(conn, "concept_root") and _table_exists(conn, "concept_lang")):
            return set()
        unplaced = _unplaced_concept_ids(conn)
        placed = {
            cid
            for (cid,) in conn.execute(
                "SELECT DISTINCT concept_id FROM concept_lang WHERE tier IN (1,2,3)"
            )
        } - unplaced
        if not placed:
            return set()
        qmarks = ",".join("?" * len(placed))
        return {
            root
            for (root,) in conn.execute(
                f"SELECT DISTINCT root FROM concept_root WHERE concept_id IN ({qmarks})",
                tuple(placed),
            )
        }
    finally:
        conn.close()


def _unplaced_concept_ids(conn: sqlite3.Connection) -> set[int]:
    if not _table_exists(conn, "concept_lifecycle"):
        return set()
    return {
        cid
        for (cid,) in conn.execute(
            "SELECT concept_id FROM concept_lifecycle WHERE state = 'unplaced'"
        )
    }


def unplaced_roots(lexicon_db: Path) -> set[str]:
    """Roots belonging to concepts staged ``unplaced`` (rising/new; excluded)."""
    if not lexicon_db.exists():
        return set()
    conn = sqlite3.connect(lexicon_db)
    try:
        ids = _unplaced_concept_ids(conn)
        if not ids:
            return set()
        roots: set[str] = set()
        qmarks = ",".join("?" * len(ids))
        if _table_exists(conn, "concept_root"):
            roots |= {
                root
                for (root,) in conn.execute(
                    f"SELECT DISTINCT root FROM concept_root WHERE concept_id IN ({qmarks})",
                    tuple(ids),
                )
            }
        # Fall back to concept.eo_root for un-decomposed staged concepts.
        roots |= {
            r
            for (r,) in conn.execute(
                f"SELECT eo_root FROM concept WHERE id IN ({qmarks}) AND eo_root IS NOT NULL",
                tuple(ids),
            )
        }
        return {r for r in roots if r}
    finally:
        conn.close()


def domain_roots(domain_dbs: list[Path]) -> set[str]:
    """Canonical roots of every domain DB (incl. philology-T4). Counted as T4."""
    roots: set[str] = set()
    for db in domain_dbs:
        if not db.exists():
            continue
        conn = sqlite3.connect(db)
        try:
            if _table_exists(conn, "mwe"):
                roots |= {
                    r
                    for (r,) in conn.execute(
                        "SELECT eo_canonical FROM mwe WHERE eo_canonical IS NOT NULL"
                    )
                    if r
                }
        finally:
            conn.close()
    return roots


# --------------------------------------------------------------------------- #
# The no-loss partition (pure — operates on sets, so tests are hermetic)
# --------------------------------------------------------------------------- #
def partition_roots(
    inventory: set[str],
    covered: set[str],
    unplaced: set[str],
    t4: set[str],
) -> dict[str, str]:
    """Map every inventory root to exactly one lifecycle state.

    Precedence resolves *legitimate* overlaps: covered_tier > t4_domain >
    unplaced > unclassified_obscure. A root common today (covered) outranks a
    stale domain listing (promotion in progress). Only inventory roots are
    labelled — anything outside the inventory is ignored (it is not lost; it
    was never an ESPDIC root).

    Returns ``{root: state}``. Use :func:`reconcile` for counts and
    :func:`check_disjointness` for the R9 "never merge" guarantees.
    """
    label: dict[str, str] = {}
    for root in inventory:
        if root in covered:
            label[root] = "covered_tier"
        elif root in t4:
            label[root] = "t4_domain"
        elif root in unplaced:
            label[root] = "unplaced"
        else:
            label[root] = "unclassified_obscure"
    return label


def reconcile(label: dict[str, str]) -> dict[str, int]:
    """Return per-state counts plus a ``total``. The whole point of no-loss."""
    counts = {s: 0 for s in STATES}
    for state in label.values():
        counts[state] += 1
    counts["total"] = sum(counts[s] for s in STATES)
    return counts


def check_disjointness(
    covered: set[str], unplaced: set[str], t4: set[str]
) -> dict[str, set[str]]:
    """Return the R9 forbidden overlaps (should all be empty).

    ``unplaced`` (rising, excluded) must never intersect ``covered`` (a staged
    word has no tier) nor ``t4`` (the ``ampermetro`` trap — rising must not be
    counted as specialist). ``covered ∩ t4`` is *allowed* (a promotion in
    flight) and is resolved by precedence, so it is not reported here.
    """
    return {
        "unplaced_and_covered": unplaced & covered,
        "unplaced_and_t4": unplaced & t4,
    }


# --------------------------------------------------------------------------- #
# The conservative routing rule (B2) — direction of travel
# --------------------------------------------------------------------------- #
# Fading / backward-facing: an explicit historical-linguistic marker in the
# gloss is strong evidence of philology-T4 (a dead word scholars still study).
ARCHAIC_MARKERS = (
    "archaic",
    "obsolete",
    "poetic",
    "dialect",
    "dialectal",
    "ancient",
    "historical",
    "dated",
    "old-fashioned",
    "medieval",
)

# Rising / forward-facing: a clear modern-technology/culture referent whose
# root is not yet tiered. Kept SMALL and SPECIFIC and matched on **word
# boundaries** — over-routing to `unplaced` would let rising everyday words
# masquerade as inventory noise. (An earlier draft used the substring "app",
# which false-matched approach/apple/appeal/appreciate — hence word boundaries
# and multi-character terms only.)
MODERN_SIGNAL_KEYWORDS = (
    "internet",
    "online",
    "website",
    "software",
    "hardware",
    "computer",
    "smartphone",
    "cellphone",
    "digital",
    "download",
    "upload",
    "email",
    "e-mail",
    "blog",
    "weblog",
    "podcast",
    "streaming",
    "wifi",
    "wi-fi",
    "bluetooth",
    "webcam",
    "cyber",
)


def _has_word(gloss: str, phrase: str) -> bool:
    """True if *phrase* occurs in *gloss* on word boundaries (case-insensitive)."""
    return re.search(rf"(?<![a-z]){re.escape(phrase)}(?![a-z])", gloss) is not None


def route_obscure_root(
    gloss: str,
    gloss_zipf: float,
    *,
    inv_tier: str = "",
) -> tuple[str, str]:
    """Route one obscure root by direction of travel. Returns ``(route, signal)``.

    Conservative by design (see docs/design/vocab_lifecycle.md §B2):

    * **philology_t4** — an explicit archaic/historical marker in the gloss.
      That is the only *positive* fading signal reliable from static ESPDIC;
      frequency-absence alone (``gloss_zipf == 0``) is NOT enough, because most
      zero-zipf roots are merely technical/rare, not archaic.
    * **unplaced** — a clear modern-tech/culture referent (keyword hit) whose
      English gloss is actually in modern use (``gloss_zipf >= 3``) yet the root
      is untiered: plausibly rising, direction-unknown → stage it.
    * **unclassified** — the honest default for everything else. Not a failure:
      R9 says for most words the direction is genuinely unknown.
    """
    g = (gloss or "").lower()
    for marker in ARCHAIC_MARKERS:
        if _has_word(g, marker):
            return "philology_t4", f"archaic-marker:{marker}"
    if gloss_zipf >= 3.0:
        for kw in MODERN_SIGNAL_KEYWORDS:
            if _has_word(g, kw):
                return "unplaced", f"modern-referent:{kw};zipf={gloss_zipf:.2f}"
    return "unclassified", f"no-directional-signal;zipf={gloss_zipf:.2f}"
