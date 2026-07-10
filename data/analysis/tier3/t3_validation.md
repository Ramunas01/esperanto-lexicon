# Tier-3 AWL seed — Phase 5 validation (one-time)

Payoff check after the gated Phase-4 merge (2,605 AWL Tier-3 EN rows committed).
Honest before/after, run **once**, on the same corpus + domain DBs so the only
variable is the Tier-3 expansion.

## Method
- **Corpus:** the 29-text proficiency corpus,
  `esperanto-lexicon-corpus/proficiency_eval/` — strata `control` (5), `novice` (7),
  `expert` (17).
- **Tool:** `src/analyzer/batch_coverage_report.py --lang en --measures relational`.
- **Domain DBs (T4 detection):** `ucc_customs`, `cbam`, `dualuse`, `wco_intl`.
- **A/B:** BEFORE = the pre-merge DB backup (`lexicon_v2.db.bak-awl-20260711-004604`,
  **96** Tier-3 words); AFTER = the merged DB (**2,701** Tier-3 words). Identical
  corpus, language, domain DBs, and tool — the delta is purely the AWL seed.

## Result 1 — coverage win (unambiguous)
Across the 29 texts (21,477 tokens), the seed moves **802 tokens out of UNKNOWN
into Tier-3**:

| token class | before | after | Δ |
| --- | ---: | ---: | ---: |
| Tier-3 recognised | 958 (4.46%) | 1,760 (8.19%) | **+802** |
| UNKNOWN | 5,529 (25.74%) | 4,727 (22.01%) | **−802** |

The formal vocabulary the analyzer previously could not classify is now recognised.
This is the seed's intended job (stock the Tier-3 reservoir), and it delivers.

## Result 2 — `t3_anchor_density` (the target measure): the honest finding
`t3_anchor_density` = Tier-3 tokens that occur in sentences also carrying ≥1 Tier-4
token, per sentence. It **rose in every stratum** — but the expert-vs-control
**separation narrowed**:

| stratum | before | after | Δ |
| --- | ---: | ---: | ---: |
| control | 0.0633 | 0.2477 | +0.184 |
| novice | 0.1637 | 0.3092 | +0.146 |
| expert | 0.4608 | 0.8121 | +0.351 |
| **expert / control** | **7.3×** | **3.3×** | **separation ↓** |

**Interpretation (a valid, partly-null result).** The AWL is *domain-general by
construction*, so recognising it raises the Tier-3 signal for **everyone**, including
control (general-audience) texts — which pushed the control baseline up
proportionally more (3.9×) than expert (1.8×). So as a *discriminator*,
`t3_anchor_density` got **weaker**, not stronger, after the expansion. The seed's
value here is **coverage/recognition, not sharpening this particular expertise
separator.**

## Result 3 — robustness (the T4 measures are correctly unaffected)
A Tier-3-only edit must not move Tier-4 measures — confirmed, which validates the
merge touched nothing it shouldn't:

| measure | control | novice | expert | expert/control | moved? |
| --- | ---: | ---: | ---: | ---: | --- |
| `cooccur_density` (T4) | 0.000 → 0.000 | 0.270 → 0.270 | 0.687 → 0.687 | ∞ → ∞ | no ✓ |
| `t4_ratio` | 0.016 → 0.016 | 0.109 → 0.109 | 0.143 → 0.143 | 8.9× → 8.9× | no ✓ |
| `t3_anchor_rate` | 0.87 → 0.74 | 0.58 → 0.53 | 0.60 → 0.64 | 0.7× → 0.9× | slight |

The **T4-based measures remain the strong expertise discriminators**
(`cooccur_density` ∞, `t4_ratio` 8.9×) and are untouched by the Tier-3 work.

## Verdict
- **GO / kept.** The AWL Tier-3 seed is a clear **coverage** improvement (−802 UNKNOWN
  tokens, Tier-3 recognition 4.5% → 8.2% on this corpus) and populates the reservoir
  as intended.
- **On expertise discrimination it is neutral-to-slightly-negative for
  `t3_anchor_density`** (separation 7.3× → 3.3×): recognising domain-general academic
  vocabulary lifts the signal for all authors, so this measure is a weaker separator
  post-expansion. **This is a genuine finding, reported as-is — not a failure of the
  merge.** Expertise routing should continue to lean on the T4 measures
  (`cooccur_density`, `t4_ratio`), which are unaffected and still separate cleanly.

Artifacts: `data/analysis/tier3/t3_before.csv`, `t3_after.csv` (per-text rows).
