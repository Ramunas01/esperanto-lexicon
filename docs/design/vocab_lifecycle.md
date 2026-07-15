# R9 vocabulary lifecycle — the two out-of-band homes + the no-loss partition

**Status:** design + scaffold (Effort B). The two homes, the routing rule, and the
no-loss guarantee are landed and tested. **The full 22,653-root sort is explicitly
deferred.** DDL is human-review-gated: reviewed *before* it is applied to the real DBs.

Source model: **R9** in `docs/ROADMAP.md`. Programmer brief:
`docs/pm/programmer/vocab-lifecycle.md`.

---

## 1. The R9 scoring treatment (the crux)

A term's tier is *time-relative*: words travel through a lifecycle, and the metric
must have a home for every stage — including the two that sit *outside* the common
T1–T3 band. **Direction of travel, not raw commonness, is the sorting key.** The two
out-of-band homes both hold "uncommon" words but get **opposite** scoring treatment:

| Home | Direction | In the expertise metric | Mechanism |
|---|---|---|---|
| `unplaced` | rising / new (coinage, fresh borrowing; direction unknown) | **EXCLUDED** — neither common denominator nor specialist numerator | `concept_lifecycle` status row |
| T1–T3 | common (saturated everyday) | denominator (common) | `concept_lang.tier IN (1,2,3)` |
| philology-T4 | fading / archaic (dead but scholar-studied) | **COUNTED** as expertise, like any T4 | a domain DB (`philology.db`) |
| unclassified-obscure | unknown / not yet examined | not counted (no tier, no domain) | the derived default |

`unplaced` and philology-T4 **must never merge.** Collapsing them would either let
rising everyday words inflate expertise (the `ampermetro` trap — a fresh coinage
scored as specialist) or erase genuine scholarly vocabulary from the signal. This
design keeps them in **two different mechanisms** (a status row vs a domain DB) so
they cannot be collapsed by accident.

---

## 2. B1 — schema for the two homes

### 2a. `unplaced` — an additive status table (not a column, not `eo_status`)

`concept_lifecycle` (see `src/lexicon/schema.py:create_lifecycle_schema`):

```sql
CREATE TABLE concept_lifecycle (
    concept_id INTEGER PRIMARY KEY REFERENCES concept(id),
    state      TEXT NOT NULL DEFAULT 'unplaced' CHECK (state IN ('unplaced')),
    source     TEXT,   -- provenance tag, e.g. 'r9_unplaced_v1'
    asof       TEXT,   -- ISO date the state was assigned
    note       TEXT
);
```

Design choices and why:

- **A separate table, not a column on `concept`.** Per R8 (derived-not-fixed),
  lifecycle is a reversible, provenance-stamped *assignment*, not part of the
  concept's identity. Keeping it beside `concept` means the 5,101 existing rows are
  never rewritten (zero migration risk) and un-staging is a single `DELETE`.
- **Not `eo_status`.** That column is `complete`/`pending` — a data-quality axis,
  orthogonal to lifecycle. Overloading it would conflate "we finished authoring
  this" with "this is rising vocabulary." The brief forbids it; so do we.
- **Absence of a row is the default.** A concept with no `concept_lifecycle` row is
  on the normal placed/derived path. This is what makes the wiring *additive*: with
  an empty table, every existing analysis is byte-identical.
- **`CHECK (state IN ('unplaced'))`** guards typos while only one state is defined.
  *Review point:* relax to a wider enum (or drop the CHECK) when a second staging
  state is actually needed — that is a one-line migration, deliberately deferred.

**Metric wiring (additive, no-op until used).** The common-side loaders
`load_tier_words` / `load_tier3_words` gain an anti-join
(`_unplaced_exclusion`) that removes `unplaced` concepts:

```sql
... AND concept_id NOT IN
    (SELECT concept_id FROM concept_lifecycle WHERE state = 'unplaced')
```

It is a strict no-op in two ways, so **no existing analysis shifts**: on a DB with no
`concept_lifecycle` table the fragment is empty (byte-identical query); while the
table is empty the anti-join matches nothing. The exclusion only bites once a concept
is explicitly staged. (Proven by `TestMetricExclusion`.) The specialist side needs no
change: an `unplaced` concept lives only in the common lexicon and is never an `mwe`
in a domain DB, so it cannot count as T4 by construction.

### 2b. philology-T4 — a genuine Tier-4 domain DB

`data/domain_db/philology.db`, built with the shared
`create_domain_schema` (identical shape to `ucc_customs.db` et al.). Because the
batch metric loads **all** `data/domain_db/*.db`, philology roots are **counted as
expertise like any T4** the moment they are routed there — no analyzer change needed.
Domain convention: `mwe.domain = 'philology'`, `current_tier = 4`.

Both homes: **movement is a relabel** (a status row or a domain assignment),
reversible and provenance-stamped. **No root ever leaves the inventory.**

---

## 3. B2 — the sorting rule (direction of travel)

`src/lexicon/vocab_lifecycle.py:route_obscure_root`. Routes one obscure root by
asking *"which way is it heading?"* — and is **deliberately conservative**, because
static ESPDIC + `wordfreq` cannot reliably detect "rising." R9 itself says that for a
brand-new word the honest answer is "unknown" — which is exactly what the
`unclassified` default is for.

| Route | Positive signal | Rationale |
|---|---|---|
| **philology_t4** (fading) | an explicit archaic/historical marker in the gloss (`archaic`, `obsolete`, `poetic`, `dialect`, `ancient`, `historical`, `dated`, `medieval`…) matched on **word boundaries** | The only *positive* fading signal reliable from a static dictionary. |
| **unplaced** (rising) | a specific modern-tech/culture referent (`software`, `computer`, `online`, `download`, `email`, `blog`, `webcam`…) **and** `gloss_zipf ≥ 3` (the English concept is in modern use) yet the root is untiered | Modern concept + unsettled EO form ⇒ plausibly rising, direction unknown ⇒ stage it. |
| **unclassified** (unknown) | everything else | The honest majority. Not a failure state. |

Two deliberate non-rules, learned from the data probe:

- **Frequency-absence alone is NOT philology.** ~10.9k obscure roots have
  `gloss_zipf == 0`, but most are merely technical/rare (chemistry, taxonomy), not
  archaic — and a technical term used by a living specialist community belongs to
  *that* domain, not to philology. So philology fires only on an explicit
  historical-linguistic marker.
- **Word-boundary matching is mandatory.** An early draft matched the substring
  `app`, which false-matched *approach / apple / appeal / appreciate*. Fixed;
  guarded by `test_app_substring_false_positive_regression`.

### The ~200-root validation sample

`data/analysis/lifecycle/obscure_route_sample.tsv` (generated by
`build_obscure_route_sample.py`, deterministic). Distribution:
**14 philology_t4 / 21 unplaced / 165 unclassified.** That honest skew *is* the
validation — the rule does not over-route. Highlights:

- **philology_t4** is precise: `arkaj/arĥaj` (archaic), `neaktual/troantikv`
  (obsolete), `dialekt`, `parnas` (poetic), `antaŭdiluv` (antediluvian), `arŝin`
  (obsolete Russian unit), `spes/spesmil` (the obsolete Esperanto *speso* currency).
- **unplaced** catches genuinely unsettled modern coinages — and the tell that they
  are *unsettled* is visible in the sample itself: `subenŝarg`/`subenŝarĝ` and three
  competing "upload" forms (`suprenŝarg`/`suprenŝarĝ`/`surinterretig`).
- **Known false-positive class for the Advisor:** a *productive living affix* whose
  gloss mentions antiquity — e.g. `pra-` ("ancient, primal") is routed philology by
  the marker rule but is in fact a live prefix (`praavo` = great-grandfather). The
  memo flags this: **marker-based philology routing needs human/Advisor confirmation
  before any real assignment.** The sorting rule is a *proposer*, not the gate.

**The full 22k sort is not run here** — the rule + the sample validate the method;
the run is deferred.

---

## 4. B3 — the no-loss invariant

`src/lexicon/vocab_lifecycle.py:partition_roots` maps **every** inventory root to
**exactly one** state, derived from ground truth (never stored as a second source, so
it cannot drift):

```
covered_tier          root is a content root of a concept placed in T1–T3
unplaced              root belongs to a concept staged `unplaced`
t4_domain             root is canonical in some domain DB (incl. philology)
unclassified_obscure  everything else in the inventory (the default)
```

- **Precedence** resolves legitimate overlaps: `covered_tier > t4_domain > unplaced >
  unclassified`. A root common *today* (covered) outranks a stale domain listing — a
  promotion in flight.
- **Disjointness guarantees** (`check_disjointness`): `unplaced` must never intersect
  `covered` (a staged word has no tier) nor `t4` (the `ampermetro` trap).
  `covered ∩ t4` is *allowed* (promotion) and resolved by precedence.
- **Conservation.** Because `partition_roots` is a *total function* over the
  inventory set, the four state counts always sum to the full inventory. Verified on
  the real data: `len(roots) == 26,447` and the partition total `== 26,447`
  (`TestRealInventoryReconciles`). A move (obscure → `unplaced`, or obscure →
  philology-T4) is a **relabel**: the root set before equals the root set after, only
  the moved root's label changes, and the total is invariant
  (`test_relabel_only_conserves_the_inventory`). **Nothing is ever deleted.**

Inventory reconciliation (the numbers the invariant reconciles to):

| bucket (PR #14 `root_tier_coverage.tsv`) | count |
|---|---|
| covered_T1_3 | 2,648 |
| candidate_gap (Effort A places these) | 666 |
| shade_mismatch | 480 |
| obscure_root (the R9 homes carve from here) | 22,653 |
| **total** | **26,447** |

---

## 5. Apply / rollback

- **Apply (after human review of the DDL):**
  `python3 src/lexicon/migrate_vocab_lifecycle.py` (dry-run available with
  `--dry-run`). Idempotent and additive: `CREATE TABLE IF NOT EXISTS`, no existing
  row touched. Proven idempotent on a copy of the real DB.
- **Rollback of a staging assignment:** `DELETE FROM concept_lifecycle WHERE
  concept_id = ?` (un-stage), or remove the `mwe` row from `philology.db` (un-route).
  The concept/root is never deleted.

## 6. Deliverables in this branch

- `src/lexicon/schema.py` — `create_lifecycle_schema` (concept_lifecycle).
- `src/lexicon/migrate_vocab_lifecycle.py` — idempotent migration (unplaced table +
  philology.db scaffold); **human-review-gated, not applied to real DBs here.**
- `src/analyzer/coverage_report.py` — additive `_unplaced_exclusion` in the tier
  loaders.
- `src/lexicon/vocab_lifecycle.py` — the partition + the routing rule.
- `src/lexicon/build_obscure_route_sample.py` +
  `data/analysis/lifecycle/obscure_route_sample.tsv` — the ~200-root sample.
- `tests/test_vocab_lifecycle.py` — no-loss invariant + metric-exclusion + routing
  (17 tests).
