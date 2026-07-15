"""Tests for the R9 vocabulary lifecycle (Effort B).

Three concerns:

* **B3 no-loss invariant** — every inventory root in exactly one state; counts
  reconcile to the full inventory before and after a relabel; nothing deleted.
* **Metric exclusion** — an ``unplaced`` concept counts on neither the common
  nor the specialist side, and the wiring is a strict no-op on pre-migration
  DBs and while the table is empty.
* **Routing rule** — conservative direction-of-travel routing, incl. a
  regression guard for the ``app``/``apple`` substring false-positive.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from analyzer.coverage_report import load_tier3_words, load_tier_words  # noqa: E402
from lexicon.schema import (  # noqa: E402
    create_common_lexicon_schema,
    create_domain_schema,
    create_lifecycle_schema,
)
from lexicon.vocab_lifecycle import (  # noqa: E402
    INVENTORY_TOTAL,
    STATES,
    check_disjointness,
    covered_roots,
    domain_roots,
    load_inventory_roots,
    partition_roots,
    reconcile,
    route_obscure_root,
    unplaced_roots,
)

REPO = Path(__file__).resolve().parent.parent
LEXICON = REPO / "data" / "lexicon_db" / "lexicon_v2.db"
INVENTORY = REPO / "data" / "lexicon_db" / "eo_inventory.json"
DOMAIN_DIR = REPO / "data" / "domain_db"


# --------------------------------------------------------------------------- #
# B3 — the no-loss partition (pure, hermetic)
# --------------------------------------------------------------------------- #
class TestNoLossPartition:
    def _inv(self) -> set[str]:
        return {f"root{i}" for i in range(100)}

    def test_partition_is_total_and_single_valued(self) -> None:
        inv = self._inv()
        covered = {"root0", "root1"}
        unplaced = {"root2"}
        t4 = {"root3", "root4"}
        label = partition_roots(inv, covered, unplaced, t4)
        # every inventory root labelled exactly once, with a known state
        assert set(label) == inv
        assert all(v in STATES for v in label.values())

    def test_counts_reconcile_to_inventory(self) -> None:
        inv = self._inv()
        label = partition_roots(inv, {"root0"}, {"root1"}, {"root2"})
        counts = reconcile(label)
        assert counts["total"] == len(inv) == 100
        assert counts["covered_tier"] == 1
        assert counts["unplaced"] == 1
        assert counts["t4_domain"] == 1
        assert counts["unclassified_obscure"] == 97

    def test_relabel_only_conserves_the_inventory(self) -> None:
        """Moving a root obscure→unplaced conserves the total and loses nothing."""
        inv = self._inv()
        before = partition_roots(inv, set(), set(), set())
        assert reconcile(before)["total"] == 100
        assert before["root7"] == "unclassified_obscure"

        # A move is a relabel: stage root7 as unplaced. Nothing is deleted.
        after = partition_roots(inv, set(), {"root7"}, set())
        assert reconcile(after)["total"] == 100
        assert set(after) == set(before)  # identical root set — no loss
        assert after["root7"] == "unplaced"  # only this root's label changed
        changed = {r for r in inv if before[r] != after[r]}
        assert changed == {"root7"}

    def test_precedence_covered_outranks_t4(self) -> None:
        # a promoted root (both covered and in a domain) labels as covered_tier
        inv = {"volt"}
        label = partition_roots(inv, {"volt"}, set(), {"volt"})
        assert label["volt"] == "covered_tier"

    def test_roots_outside_inventory_are_ignored_not_lost(self) -> None:
        inv = {"a", "b"}
        # a covered root not in inventory must not appear (it is not an ESPDIC root)
        label = partition_roots(inv, {"a", "ghost"}, set(), set())
        assert set(label) == {"a", "b"}

    def test_disjointness_flags_the_ampermetro_trap(self) -> None:
        # unplaced must never intersect covered or t4 (opposite scoring)
        clean = check_disjointness({"a"}, {"b"}, {"c"})
        assert clean["unplaced_and_covered"] == set()
        assert clean["unplaced_and_t4"] == set()

        violation = check_disjointness(covered={"a"}, unplaced={"a", "b"}, t4={"b"})
        assert violation["unplaced_and_covered"] == {"a"}
        assert violation["unplaced_and_t4"] == {"b"}


# --------------------------------------------------------------------------- #
# B3 — real-data reconciliation (skips if the regenerable data is absent)
# --------------------------------------------------------------------------- #
class TestRealInventoryReconciles:
    @pytest.mark.skipif(not INVENTORY.exists(), reason="eo_inventory.json absent")
    def test_partition_of_real_inventory_sums_to_total(self) -> None:
        inv = load_inventory_roots(INVENTORY)
        assert len(inv) == INVENTORY_TOTAL  # 26,447

        covered = covered_roots(LEXICON) if LEXICON.exists() else set()
        unplaced = unplaced_roots(LEXICON) if LEXICON.exists() else set()
        t4 = domain_roots(sorted(DOMAIN_DIR.glob("*.db"))) if DOMAIN_DIR.exists() else set()

        label = partition_roots(inv, covered, unplaced, t4)
        counts = reconcile(label)
        # The whole point: the partition conserves the full inventory exactly.
        assert counts["total"] == INVENTORY_TOTAL
        # And the R9 "never merge" guarantee holds on real data.
        viol = check_disjointness(covered, unplaced, t4)
        assert viol["unplaced_and_covered"] == set()
        assert viol["unplaced_and_t4"] == set()


# --------------------------------------------------------------------------- #
# Metric exclusion — an unplaced concept counts on neither side
# --------------------------------------------------------------------------- #
class TestMetricExclusion:
    def _lexicon(self, tmp_path: Path, *, with_lifecycle: bool) -> Path:
        db = tmp_path / "lex.db"
        conn = sqlite3.connect(db)
        create_common_lexicon_schema(conn)
        if with_lifecycle:
            create_lifecycle_schema(conn)
        # two concepts: one normal (placed), one we will stage unplaced
        conn.execute(
            "INSERT INTO concept (id, eo_root, eo_word) VALUES (1, 'dom', 'domo')"
        )
        conn.execute(
            "INSERT INTO concept (id, eo_root, eo_word) VALUES (2, 'blog', 'blogo')"
        )
        conn.executemany(
            "INSERT INTO concept_lang (concept_id, lang, word, tier) VALUES (?,?,?,?)",
            [
                (1, "en", "house", 1),
                (1, "en", "home", 2),
                (2, "en", "blog", 1),  # a rising word, tier-1 word row present
                (2, "en", "weblog", 3),
            ],
        )
        conn.commit()
        conn.close()
        return db

    def test_unplaced_concept_excluded_from_common_side(self, tmp_path: Path) -> None:
        db = self._lexicon(tmp_path, with_lifecycle=True)
        # before staging: blog is visible on the common side
        t1, t2 = load_tier_words(db, "en")
        assert "blog" in t1 and "house" in t1
        assert "weblog" in load_tier3_words(db, "en")

        # stage concept 2 (blog) as unplaced
        conn = sqlite3.connect(db)
        conn.execute(
            "INSERT INTO concept_lifecycle (concept_id, state, source, asof) "
            "VALUES (2, 'unplaced', 'test', '2026-07-13')"
        )
        conn.commit()
        conn.close()

        # after: blog/weblog vanish from BOTH common loaders; house/home stay
        t1, t2 = load_tier_words(db, "en")
        assert "blog" not in t1 and "blog" not in t2
        assert "house" in t1 and "home" in t2  # untouched — no default shift
        assert "weblog" not in load_tier3_words(db, "en")

    def test_unplaced_absent_from_specialist_side_by_construction(
        self, tmp_path: Path
    ) -> None:
        # An unplaced concept lives only in the common lexicon; it is never an
        # mwe in a domain DB, so it cannot count on the specialist (T4) side.
        from src.analyzer.coverage_report import load_mwe_phrases

        domain = tmp_path / "philology.db"
        conn = sqlite3.connect(domain)
        create_domain_schema(conn)
        conn.commit()
        conn.close()
        assert load_mwe_phrases(domain, "en") == set()  # empty domain → no T4

    def test_noop_on_pre_migration_db(self, tmp_path: Path) -> None:
        # A DB with no concept_lifecycle table must behave exactly as before.
        db = self._lexicon(tmp_path, with_lifecycle=False)
        t1, t2 = load_tier_words(db, "en")
        assert "blog" in t1 and "house" in t1  # no error, no exclusion
        assert "weblog" in load_tier3_words(db, "en")

    def test_empty_lifecycle_table_is_a_noop(self, tmp_path: Path) -> None:
        db = self._lexicon(tmp_path, with_lifecycle=True)  # table present, empty
        t1, _ = load_tier_words(db, "en")
        assert {"blog", "house"} <= t1  # identical to pre-migration behaviour


# --------------------------------------------------------------------------- #
# Routing rule — conservative direction of travel
# --------------------------------------------------------------------------- #
class TestRoutingRule:
    def test_archaic_marker_routes_to_philology(self) -> None:
        route, signal = route_obscure_root("archaic, obsolete form", 3.3)
        assert route == "philology_t4"
        assert "archaic" in signal

    def test_zero_zipf_alone_is_not_philology(self) -> None:
        # frequency-absence without an archaic marker stays unclassified
        route, _ = route_obscure_root("a rare technical chemistry term", 0.0)
        assert route == "unclassified"

    def test_modern_referent_routes_to_unplaced(self) -> None:
        route, signal = route_obscure_root("software, computer program", 4.5)
        assert route == "unplaced"
        assert "software" in signal

    def test_modern_referent_below_zipf_gate_stays_unclassified(self) -> None:
        # a modern keyword but no modern frequency → not confidently rising
        route, _ = route_obscure_root("obscure software-ish sense", 1.0)
        assert route == "unclassified"

    def test_app_substring_false_positive_regression(self) -> None:
        # "approach"/"apple"/"appeal" must NOT trigger the modern-referent rule
        for gloss in ("to approach, deal with", "Adam's apple", "to appeal"):
            route, _ = route_obscure_root(gloss, 4.8)
            assert route == "unclassified", f"false positive on {gloss!r}"

    def test_default_is_unclassified(self) -> None:
        route, signal = route_obscure_root("a squirrel", 4.0)
        assert route == "unclassified"
        assert "no-directional-signal" in signal
