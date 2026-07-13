# PM brief — place the 666 now; stand up the lifecycle sorting (no inventory lost)

Two efforts, sequenced. **Effort A (now):** place the 666 `candidate_gaps` into T1–T3 through
the normal human-gated pipeline — the general-adult vocabulary layer the AWL seed missed.
**Effort B (design + scaffold, execution later):** stand up the *vocabulary-lifecycle* homes
(R9) — the `unplaced` staging status and the T4 "philology" archive — and the sorting process
that routes the rest of the root space into them **without losing a single root from inventory.**

Governing principle (roadmap **R9**): sort by *direction of travel*, not raw commonness.
Rising/new → `unplaced` (scoring-EXCLUDED). Common → T1–T3. Fading/archaic → T4-philology
(scoring-COUNTED). `unplaced` and philology-T4 must never merge — opposite scoring treatment.

---

## Effort A — place the 666 into T1–T3 (now, human-gated)

The `candidate_gaps.tsv` (666 roots) is a first draft of the missing **general-adult layer**.
Land the clearly-common ones; hold the rest.

**A1 — Consolidate [PROG] (no DB writes).**
- **Dedupe by concept:** multiple roots glossing to one English word collapse
  (`demokrat`/`demokrati`→democratic; `agrikultur`/`agrokultur`/`agronomi`→agricultural;
  `aŭtorrajt`/`kopirajt`→copyright). Report distinct-concept count (well under 666).
- **Fold derived forms:** many gaps are `-ic/-al` adjectives (`democratic`, `presidential`,
  `naval`) whose noun is (or should be) the anchor — attach as forms of one concept, don't
  author each separately.
- **Flag by direction (R9):** for each surviving concept, tag the *likely* route —
  `common` (everyday, → T1–T3), `domain-adjacent` (`colonel`, `naval`, `agriculture` — a
  general adult recognises it but it leans T4 → hold for domain review), `register-marked`
  (`damn`, `fik` — common by frequency, not neutral → hold), `archaic` (→ philology-T4 when
  that exists). Use `wordfreq` on the gloss as the commonness signal.
- Propose a tier per common concept (default **T3-general**; the very common, e.g. zipf ≥ 4.5,
  may be T2). Emit `data/analysis/tier3_general/awl_gap_worksheet.tsv`.

**A2 — Human review gate [RAMUNAS].** Same terse flow as prior worksheets: approve/hold/reject,
fix anchors, confirm tier. The Advisor can pre-triage this worksheet (validate anchors, pre-fill
decisions) exactly as done for `set_gaps`/`anchor_flags` — expect the real review to be ~the
domain-adjacent + register-marked + ambiguous subset, not all 666.

**A3 — Gated merge [PROG].** Back up; transaction; **insert-only**; `source='general_gap_v1'`;
approved tiers. Never modify existing rows. Post-write audit mandatory (0 eo_root mismatches,
resolution holds — the invariant gate stays on). Re-run the root-vs-tier join to confirm the
placed concepts leave `candidate_gap`. Report counts by tier.

---

## Effort B — the lifecycle homes + sorting scaffold (design now, sort later)

Goal: create the two out-of-band homes and a process that can eventually classify the ~22,653
`obscure_root` remainder by direction of travel — **without ever dropping a root from
inventory.** This effort is *scaffolding + design*; the full sort is a later, larger run.

**B1 — Schema for the two homes [PROG] (design + minimal DDL, human-reviewed before build).**
- **`unplaced` status:** a status a root/concept can carry (staging). MUST be **excluded from
  the expertise metric** — neither common denominator nor specialist numerator. Wire the metric
  to skip `unplaced` (additive flag, don't change existing scoring defaults).
- **T4 "philology / historical-linguistic" domain:** a genuine Tier-4 domain DB for
  obsolete/archaic/dialectal/scholarly roots. **Counted as expertise** like any T4 domain.
- Both must respect: no root leaves the inventory when it moves into a home; movement is a
  status/domain assignment, reversible, provenance-stamped (R8 derived-not-fixed).

**B2 — The sorting design (NOT the full run) [PROG + ADVISOR].** A written method for routing an
obscure root by direction of travel: what evidence sends a root to `unplaced` (recent coinage /
rising frequency / new borrowing) vs philology-T4 (attested-historical / archaic-marked / absent
from modern frequency lists) vs "leave as unclassified-inventory for now." Deliver as a memo +
a small labelled sample (e.g. 200 obscure roots hand-routed) to validate the rule *before*
committing to a 22k-root pass. **Explicitly do NOT run the full sort yet** — the point is to
prove the routing rule and the no-loss guarantee first.

**B3 — The no-loss invariant [PROG].** Assert and test that: every ESPDIC root is always in
exactly one state (covered-tier / unplaced / a T4 domain incl. philology / unclassified-obscure);
counts reconcile to the full inventory before and after any move; nothing is ever deleted, only
re-labelled. This invariant is the whole point of "don't lose inventory" — make it a test, not a
hope.

---

## Constraints (both efforts)
Insert-only / status-relabel-only; never delete a root or edit existing `tier`/`word`/`cefr`/
`source`; human-gated writes; back up + post-write audit (the invariant break from PR #8 must
not recur); `unplaced` excluded from scoring, philology-T4 counted; `wordfreq` gate on
commonness calls. Effort A: branch `analysis/general-gap-fill`. Effort B: branch
`design/vocab-lifecycle`. PRs; no merge without review.

## Success criteria
**A:** the clearly-common subset of the 666 (deduped, forms folded) merged into T1–T3, audit
clean, those concepts gone from `candidate_gap`; the held subset (domain-adjacent / register /
archaic) parked with reasons for Effort B. **B:** the `unplaced` status and philology-T4 domain
exist and are correctly wired into (excluded from / counted by) the metric; a validated sorting
rule + labelled sample; and a passing **no-loss invariant test** proving the full inventory
count is conserved across every state. The full 22k sort is deferred — this lands the homes,
the rule, and the guarantee.
