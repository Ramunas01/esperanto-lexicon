# Inventory-vs-tier root coverage — which Esperanto roots do our Tiers miss?

Read-only, corpus-free cross-source consistency check: the ESPDIC root inventory
(`eo_inventory.json`, 26,447 roots + English glosses) laid over `lexicon_v2.db`
(concepts + pedagogical tiers). The tiers were built from **English** sources
(Oxford, Dolch, AWL, TinyStories); the inventory came from **ESPDIC**
independently — so the mismatches are concepts one source treats as common that the
other missed, surfaced **without any corpus**. **Authors nothing** — the TSVs are
review material; each hit needs a human glance.

## Headline
- **candidate_gap = 666 roots (621 distinct English words)** — uncovered, common,
  single-word, non-name glosses whose word is not yet a concept. **T3-weighted**:
  suggested T1 = 1, T2 = 107, **T3 = 558**. Dominated by **Latinate / formal /
  academic vocabulary** — exactly the Advisor's prediction.
- **shade_mismatch = 480 roots** — granularity splits where Esperanto carves a sense
  English blurs (`lepor`="hare" while `kunikl`="rabbit" is covered). The richer read.
- **The bet: the Advisor was right, decisively.** Gaps concentrate at the *top* of
  the stack (T3), are negligible at T1, single-digit at T2. Ramunas's uniform
  1/5–1/4 gap fractions at T1/T2 are contradicted by the numbers.

## Method (four traps + a tail prior, all measured)
Each root is scored on its ESPDIC gloss with `wordfreq`, guarded against:
1. **`"to "` / article prefixes** (trap #1) — a naive scorer scores `to` (zipf 7.4)
   for *every* verb. We strip leading function words and score the content head.
   (Proven by a unit test.)
2. **Common head ≠ common concept** (trap #2) — `incens`="to burn incense" has a
   common head (`burn`) but an obscure concept. We require the first sense to reduce
   to a **single** common content word; phrasal / multi-word / parenthetical → obscure.
3. **Derived-form glosses** (trap #3) — `abrad`="abrasive". Before deciding a gloss
   word is "not a concept" we normalize it (spaCy lemma + `inflected_forms` + the
   British `uk_to_us` fold) against the concept `en` words.
4. **Proper nouns / demonyms** (added — they dominated a naive run) — `American`,
   `Google`, `Louis` are capitalised in the gloss; names are a *separate layer*, out
   of scope here → obscure. Also excludes hyphenated compounds (`e-book`) and
   closed-class **stopword** glosses (`mi`=my, `sed`=but — grammatical morphemes).
- **Tail prior:** a common single-word gloss on a `tail`-confidence ESPDIC root is
  far more often an obscure concept ESPDIC glossed with a common word than a real
  missing common concept, so tail roots are not eligible for `candidate_gap` (they
  *are* eligible for `shade_mismatch` — the canonical `lepor` is tail).

## Buckets (26,447 roots)
| bucket | count | meaning |
| --- | ---: | --- |
| `covered_T1_3` | 2,648 | a T1/T2/T3 en concept anchors this root |
| `obscure_root` | 22,653 | uncovered + gloss fails the commonness gate (or tail prior / primary-sense already covered) — counted, not listed |
| **`candidate_gap`** | **666** | uncovered, common single non-name word, word not a concept — **the prize** |
| **`shade_mismatch`** | **480** | uncovered, primary sense distinct but a later sense overlaps a covered word — granularity split |

### Coverage by ESPDIC confidence tier
| ESPDIC tier | covered / total | % |
| --- | --- | ---: |
| core | 1,632 / 2,626 | **62.1%** |
| extended | 438 / 2,402 | 18.2% |
| tail | 573 / 21,414 | 2.7% |
| modern | 5 / 5 | 100% |

Our tiers cover ~62% of ESPDIC's *core* (everyday-confidence) roots. The uncovered
core remainder is mostly obscure-with-common-gloss or covered-under-another-root;
only **262 core roots** are genuine `candidate_gap`s.

## The bet — settled with numbers
Covered roots by pedagogical tier (a root's lowest covered tier / any covered tier):

| tier | covered (min) | covered (any) | candidate_gap (suggested this tier) | gap ÷ covered |
| --- | ---: | ---: | ---: | --- |
| T1 | 764 | 764 | **1** | **~0%** |
| T2 | 1,824 | 2,338 | **107** | **5–6%** |
| T3 | 64 | 447 | **558** | **1.25× (any) – 8.7× (min)** |

- **Ramunas:** gaps ≈ 1/5 of T1 (20%), 1/4 of T2 (25%), ~3× of T3. → T1 and T2 are
  **way off** (actual ~0% and 5–6%); T3 is only in range under the min-tier denominator.
- **Advisor:** <5% at T1, single-digit % at T2, large at T3. → **T1 ✓ (~0%), T2 ✓
  (5–6%), T3 ✓ (large).** All three hold.

**The Advisor was closer, decisively.** Coverage completeness tracks *source
agreement*: near-total for universal concepts (T1) and weakest for freshly-seeded
formal vocabulary (T3, seeded largely from the single AWL source). The gaps sit where
that agreement is thinnest — the top of the stack.

**Red-flag check (passed):** the brief warned a *large* T1 gap would signal English
lexicalizing via phrases rather than a real hole. The T1 gap is **1 root** (`damn`,
informal) — not large, no red flag.

## The shape of `candidate_gap` — a Latinate / formal cluster
Ranked by commonness, the distinct missing words are overwhelmingly **formal,
academic, and institutional Latinate vocabulary**: `carbon`, `circuit`, `agriculture`,
`faculty`, `petition`, `collective`, `auction`, `census`, `charter`, `pension`,
`copyright`, `genetic`, `chronic`, `naval`, `imperial`, `civilian`, `amateur`,
`lieutenant`, `colonel`, `retail`, `toxic`, `graphic`, `bronze`, `tobacco`… This is
the T3 register — the AWL seed reached a slice of it, but ESPDIC treats a much larger
formal core as common that our tiers do not yet carry.

Three sub-populations a reviewer should expect (honest caveats):
- **Derivational adjectives** (`democratic`, `republican`, `presidential`,
  `agricultural`, `mechanical`, `racial`, `naval`) — the `-al`/`-ic`/`-ial` adjective
  of a noun that may already be covered (`democracy`, `agriculture`). In Esperanto
  these are one concept + a productive ending, not separate roots. The trap-#3
  normalization is inflectional, not derivational, so these survive as apparent gaps
  — a known residual for human review, not a hard hole.
- **Informal register** (`damn`, `gay`, `suck`, `virgin`) — genuinely common, but a
  register the tiers deliberately may not carry. Reviewer's call.
- **Borderline names** (`ford`, `khan`, `rugby`) — lowercased in the gloss so they
  passed the proper-noun gate; a few names still leak.

Each `candidate_gap` row carries a **suggested pedagogical tier** from its commonness
(zipf ≥ 5 → T1, 4–5 → T2, 3–4 → T3) for review triage.

## The shape of `shade_mismatch` — granularity splits
The interesting read: Esperanto roots whose *primary* sense is distinct and uncovered
while a *secondary* sense overlaps a covered English word — English blurs, Esperanto
splits. `lepor`→(rabbit) [hare vs rabbit], `sake`→(rice) [rice wine], `bay`→(bark/howl)
[animal cry], `avenue`→(passage), `bureau`→(office), `premier`→(prime), `aged`→(elderly),
`railway`→(railroad). These are not gaps — they are meaning-shade differences worth a
linguist's eye. (The filter that isolates them — primary head uncovered, a later sense
covered — removes the large noise class of derivatives/compounds whose *primary* gloss
is already covered, e.g. `kronometr`="to time", `uzad`="to use".)

## Go-forward
- The `candidate_gap` list (esp. the ~262 core-tier, non-derivational, non-informal
  entries) is the reviewable set of formal common concepts the tiers miss; a pass
  authoring the clean ones would extend T3 beyond the AWL slice.
- `shade_mismatch` is a linguist-review artifact (granularity), not an authoring queue.
- Derivational adjectives suggest a future refinement: recognise `-a`-form Esperanto
  adjectives as the productive form of a covered noun root rather than separate gaps.
- This is the one coverage check that is complete (whole root space), cross-source
  (ESPDIC vs English), and corpus-free — finding what no text sieving could.

## Artifacts
- `data/analysis/root_coverage/root_tier_coverage.tsv` — every root: bucket, covered
  tiers, gloss, gloss-zipf, inventory tier, prod.
- `data/analysis/root_coverage/candidate_gaps.tsv` — commonness-ranked, with suggested tier.
- `data/analysis/root_coverage/shade_mismatches.tsv` — the granularity candidates.
- Code: `src/analyzer/root_tier_coverage.py` (pure scorer/classifier, 26 tests) +
  `build_root_coverage.py` (driver). Read-only; `wordfreq` + spaCy lemma; no corpus.
