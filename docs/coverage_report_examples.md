# Coverage Report Examples

Three sentences tested against `ucc_customs.db` (41 UCC Article 5 definitions, EN + LT).

Command used:

```bash
echo "<sentence>" | python3 src/analyzer/coverage_report.py \
    --domain-db data/domain_db/ucc_customs.db \
    --lang en
```

---

## Sentence 1 — General audience text

**Input:** `The company submitted its annual report to the board of directors last week.`

```
COVERAGE REPORT
Lang: en   Domain: ucc_customs
Token breakdown:
  The — TIER1
  company — TIER1
  submitted — UNKNOWN
  its — TIER1
  annual — TIER2
  report — TIER1
  to — TIER1
  the — TIER1
  board — TIER2
  of — TIER1
  directors — UNKNOWN
  last — TIER1
  week — TIER1
Summary: T1=9(69.2%)  T2=2(15.4%)  T4=0(0.0%)  Unknown=2(15.4%)  Skipped=1
Ratio T4/common: 0.00 → GENERAL AUDIENCE
```

**Interpretation:** No domain terminology detected. The text is entirely common vocabulary
(Tier 1 and Tier 2), as expected for a business-English sentence with no customs context.
"submitted" and "directors" fall outside the common lexicon at this DB state.

---

## Sentence 2 — Specialist customs text

**Input:** `The declarant must present the customs declaration to the customs authorities before the release of goods from temporary storage.`

```
COVERAGE REPORT
Lang: en   Domain: ucc_customs
Token breakdown:
  The — TIER1
  declarant — TIER4  (UCC Art.5 item 15)
  must — TIER1
  present — TIER1
  the — TIER1
  customs declaration — TIER4  (UCC Art.5 item 12)
  to — TIER1
  the — TIER1
  customs authorities — TIER4  (UCC Art.5 item 1)
  before — TIER1
  the — TIER1
  release of goods — TIER4  (UCC Art.5 item 26)
  from — TIER1
  temporary storage — TIER4  (UCC Art.5 item 17)
Summary: T1=9(64.3%)  T2=0(0.0%)  T4=5(35.7%)  Unknown=0(0.0%)  Skipped=0
Ratio T4/common: 0.56 → SPECIALIST
```

**Interpretation:** Five multi-word UCC terms identified by greedy MWE matching. The
35.7 % Tier 4 density and 0.56 ratio place the author firmly in the specialist band.
All tokens accounted for — no unknowns — because the sentence was constructed from
UCC Article 5 vocabulary.

---

## Sentence 3 — Mixed text (surprising result)

**Input:** `The person submitted a declaration for imported goods and paid the import duty.`

```
COVERAGE REPORT
Lang: en   Domain: ucc_customs
Token breakdown:
  The — TIER1
  person — TIER4  (UCC Art.5 item 4)
  submitted — UNKNOWN
  a — TIER1
  declaration — UNKNOWN
  for — TIER1
  imported goods — UNKNOWN
  and — TIER1
  paid — UNKNOWN
  the — TIER1
  import duty — TIER4  (UCC Art.5 item 20)
Summary: T1=5(41.7%)  T2=1(8.3%)  T4=2(16.7%)  Unknown=4(33.3%)  Skipped=0
Ratio T4/common: 0.33 → SPECIALIST
```

**Interpretation:** This sentence looks general but scores as SPECIALIST because the UCC
gives "person" a precise legal definition (Art.5 item 4: any natural or legal person, or
any association of persons) and "import duty" is an Art.5 item 20 defined term. The
standalone word "declaration" does not match the MWE "customs declaration" (greedy
matching requires the full phrase), so it falls through to UNKNOWN along with "imported
goods" and "submitted".

This illustrates a known calibration issue: the ratio signal is sensitive to how many
short, legally-redefined common words appear in the UCC definition list. Sentences that
incidentally contain "person" will be over-scored for customs expertise. Mitigation
options: weight Tier 4 matches by MWE length (longer phrases = stronger signal), or
mark single-token Tier 4 entries as a weaker sub-tier.

---

## Threshold reference

| Ratio T4/common | Label |
|---|---|
| ≥ 0.30 | SPECIALIST |
| 0.10 – 0.29 | INTERMEDIATE |
| < 0.10 | GENERAL AUDIENCE |

Thresholds are provisional and will be tuned once coverage data from multiple domains
and human-labelled test texts is available.
