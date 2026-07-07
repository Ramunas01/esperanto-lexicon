# PM brief — common-lexicon gap-fill + customs re-measure (human-gated)

Follows the TinyStories coverage probe (PR #5). That probe produced a frequency-ranked
`common_gap` queue: ~2,960 UNKNOWN surface types (~8–10% of running tokens) that are
genuine Tier-1/2 coverage gaps in the English pack. This task turns that queue into
lexicon coverage **through a human review gate**, then re-measures the customs corpus to
see whether closing the gap sharpens the core expertise metric.

**Ramunas is the reviewer/approver.** Every write to the lexicon (new concepts, new
language links, any tier change) passes through him first. The agent's job is to
*prepare reviewable proposals and apply only what he approves* — never to author lexicon
entries autonomously. This is a two-phase task with a hard STOP in the middle.

Repo/conventions unchanged: `github.com/Ramunas01/esperanto-lexicon`, corpora in the
private `esperanto-lexicon-corpus`, WSL2, PRs with tests, no merge without review.
`CLAUDE.md` hard rule stands: **never modify an existing entry's `tier`/`word`/
`cefr_level`/`source`** (adding *new* rows is allowed; the one tier *change* below is
gated on explicit approval). Back up the DB before any write; wrap writes in a transaction.

---

## Key framing (convey to Claude Code — it changes the work)

This is an **Esperanto-anchored** lexicon. "Add `hug`" does NOT mean inserting an English
word — it means ensuring the concept anchored on the Esperanto root (`brakum`, from ESPDIC
`brakumi : to embrace, hug`) carries an English form tagged Tier 1. Crucially: **the EO
concept very likely already exists** (there are ~26k EO roots; English is a sparse pack).
So for most gap words the fix is **linking an English form to an existing EO concept**
(insert one `concept_lang` row), not authoring a new concept. Only create a new `concept`
when no EO concept for that meaning exists. Both are insert-only and safe.

---

## Phase 1 — consolidate the queue (no DB writes)

From `tinystories_unknown_triaged.tsv`:
1. **Collapse surface forms to lemmas.** `hugged/hopping/hopped` → `hug/hop`; `dolls`→
   `doll`. The 2,960 types collapse to far fewer target lemmas; rank by summed frequency.
2. **Reclaim `proper_noun` leaks.** spaCy PROPN-tags capitalized common words, so basic
   vocabulary is hiding in the names bucket. Pull the high-frequency common words back into
   the gap queue (`mommy` 1441, `mum` 633, `rabbit`, `daddy` 338, `bunny`, `hug`, `okay`,
   `curious`, …). Rule of thumb: a token with `is_propn=1` but that is a common noun/
   interjection in lowercase usage → reclaim. Leave true names (`lily`, `timmy`, `ben`).
3. **Split off British spellings** (`colour`, `favourite`, `behaviour`, `neighbour`) into a
   separate list — these are handled in Phase 3b as a spelling map, NOT as new concepts.
Output: `data/analysis/gapfill/consolidated_gap_lemmas.tsv` (lemma, total_freq, notes).

## Phase 2 — propose EO anchors → the review worksheet (no DB writes)

For each consolidated gap lemma:
- **Check for an existing EO concept.** Reverse-look-up the English lemma against ESPDIC
  (EO→EN glosses; CC-BY, already in the project) to find candidate EO headword(s) and their
  root(s); then check whether a `concept` with that `eo_root` already exists in
  `lexicon_v2.db`. Record whether the fix is **LINK** (concept exists, add en form) or
  **NEW** (author a concept).
- Handle **compounds**: some map to EO compounds (`rainbow`→`ĉielarko`=`ĉiel`+`ark`;
  `playground`→`ludejo`=`lud`+`ej`). Record the component roots (they become `concept_root`
  rows).
- **Flag** the hard cases for closer human attention: multiple plausible EO candidates
  (polysemy), no ESPDIC match, or culture-specific items.
- Propose `tier` (default **1** for this queue — age-5 vocabulary — with `cefr_level` A1/A2)
  and `source = "tinystories_gap_v1"`.

Emit a reviewable worksheet `data/analysis/gapfill/authoring_worksheet.tsv` with columns:
`en_lemma, total_freq, action(LINK|NEW), eo_root, eo_word, eo_gloss, component_roots,
proposed_tier, cefr, alt_candidates, flag(ok|ambiguous|no_match|compound), notes`.

**Then STOP and hand the worksheet to Ramunas.** Do not write to the lexicon.

---

### ⟦ HUMAN REVIEW GATE — Ramunas ⟧
Ramunas reviews the worksheet: confirms/edits each EO anchor, resolves `ambiguous`/
`no_match` rows, adjusts tiers, and marks each row `approved` / `hold` / `reject`. He also
rules on the **`number` Tier-3→Tier-1 demotion** flag from PR #5 (a *change* to an existing
entry — applied only if he approves it, and only in Phase 3c). The approved worksheet is the
sole input to Phase 3.

---

## Phase 3 — apply approved changes (gated writes, insert-only)

Only after the approved worksheet returns:
- **3a. LINK rows:** insert one `concept_lang` row (`lang='en'`, `word`, `tier`,
  `cefr_level`, `source='tinystories_gap_v1'`) on the existing concept. Never touch existing
  rows.
- **3b. NEW rows:** insert the `concept` (`eo_root`, `eo_word`, `eo_pos`, `eo_status`), its
  `concept_lang` en row, and `concept_root` row(s) (compounds → multiple, `is_head` on the
  final root). Source-tagged. Idempotent: skip if the en word already resolves.
- **3c. The `number` demotion** — ONLY if explicitly approved — as a separate, clearly-logged
  single-row `tier` update (the one sanctioned exception to the hard rule).
- **British-spelling normalization** (from Phase 1's split): add a small committed US/UK
  spelling map applied in the English resolver *before* lookup (`colour`→`color`), with
  tests. This is a pipeline change, not a lexicon change — no new concepts.
- **Validate:** back up DB first; run `audit_root_consistency.py` after; confirm 0
  truncations / 0 mismatches introduced and resolution stays ≈99.7%. Report inserted/linked
  counts. PR, no merge.

## Phase 4 — close the loop (the point of all this)

Re-run the 29-text customs corpus before/after the gap-fill and report the effect on the
core metric:
```
python3 src/analyzer/batch_coverage_report.py --corpus <proficiency_eval> --lang en \
    --lexicon data/lexicon_db/lexicon_v2.db --domain-dbs data/domain_db/*.db \
    --output data/analysis/gapfill/customs_after_gapfill.csv
```
Short report `data/analysis/gapfill/loop_closure_report.md`: per-stratum `T4_ratio`,
`UNKNOWN%`, and expert/novice separation **before vs after**. The hypothesis: a better-
covered `T1+T2` denominator lowers UNKNOWN and may tighten/steady `T4_ratio` and its
expert-vs-novice separation. Whichever way it moves, report it plainly — a null result
(no change) is a valid, useful finding, not a failure. For Ramunas's review; may inform a
`CLAUDE.md` update **only** with his approval.

---

## Files
**Read:** `CLAUDE.md`; `tinystories_unknown_triaged.tsv`; ESPDIC source (EO→EN glosses);
`eo_inventory.json` (root/gloss lookup); `lexicon_v2.db` schema; `batch_coverage_report.py`
and `audit_root_consistency.py` interfaces.
**Write (Phase 1–2, no DB):** `data/analysis/gapfill/consolidated_gap_lemmas.tsv`,
`authoring_worksheet.tsv`. **Write (Phase 3, gated):** `lexicon_v2.db` inserts + the spelling
map + tests. **Write (Phase 4):** `customs_after_gapfill.csv`, `loop_closure_report.md`.
Branch `analysis/common-gapfill`; PR; no merge.

## Success criteria
Worksheet is complete and genuinely reviewable (every row actionable in one glance). After
approved apply: TinyStories UNKNOWN drops materially on a re-probe; audit still clean;
resolution ≈99.7%. Phase 4 produces a clear before/after on the customs metric.

## Do NOT
Author or insert any lexicon entry without an approved worksheet row; modify existing
`tier`/`word`/`cefr_level`/`source` (except the approved `number` demotion); edit `CLAUDE.md`;
add the British spellings as new concepts (use the map).
