# Loop-closure — did the cleaner denominator sharpen the metric? (Phase F)

**Date:** 2026-07-06. The 29-text English customs corpus (`proficiency\_eval/`: control 5 /
novice 7 / expert 17), 5 domain DBs (`ucc\_customs, cbam, dualuse, gpmi\_lt\_tax, wco\_intl`;
`customs\_expert\_vocab` excluded as it was mined from the expert corpus), run against the
lexicon **before** (pre-merge backup) and **after** the gap-fill merge.

## Results

|stratum|T4\_ratio before → after|UNKNOWN% before → after|
|-|-:|-:|
|control|0.0188 → **0.0166**|27.03% → **17.29%**|
|novice|0.1113 → **0.1082**|26.13% → **24.31%**|
|expert|0.1680 → **0.1650**|27.34% → **26.44%**|

|separation (T4\_ratio)|before|after|
|-|-:|-:|
|expert / control|8.91×|**9.96×**|
|expert / novice|1.51×|**1.53×**|

## Reading

* **UNKNOWN dropped on every stratum, most on control (−9.7 pts).** The gap-fill was
common (Tier-1/2) vocabulary, so it clears the most UNKNOWN from the general-vocabulary
control texts and less from the domain-dense novice/expert texts — exactly the expected
shape.
* **T4\_ratio dipped slightly everywhere** (\~2%). Mechanical and benign: filling common
vocabulary grows the `T1+T2` denominator while `T4` (domain hits) is unchanged, so the
ratio edges down uniformly. It does **not** weaken the signal.
* **Separation modestly sharpened.** Because control's denominator grew most, its T4\_ratio
fell most, widening **expert/control 8.91× → 9.96×**. The always-weak **expert/novice**
axis barely moved (1.51× → 1.53×) — consistent with prior findings that T4\_ratio is a
strong topic detector but only a partial expert/novice separator.

## Verdict

A **mildly positive, mostly-null** result, honestly reported: the cleaner denominator
did not distort the metric and slightly improved its topic-detection separation, while
substantially improving raw coverage (UNKNOWN). The core value delivered is a
**more reliable `T1+T2` denominator** (TinyStories UNKNOWN 19.5% → 8.3%), which was the
point of the exercise; it did not, and was not expected to, fix the expert/novice gap
(that needs the Tier-4 / relational features, not denominator hygiene).

*For Ramunas's review. May inform `CLAUDE.md`/roadmap only with his approval.*

