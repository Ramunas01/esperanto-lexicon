# CLAUDE.md — Esperanto Lexicon Knowledge Analysis

This file is the primary briefing for Claude Code sessions working on this project.
Read it fully before taking any action. It supersedes any assumptions from training data.

\---

## What this project is

A multilingual lexicon analysis system that estimates an author's domain expertise from
their text. The core hypothesis: the ratio of common vocabulary to domain-specific
terminology in a piece of writing is a proxy for the author's knowledge level.

A second hypothesis for future development: the structure of concept relationships in a
text — compared against a normalised "concept map" for a given knowledge domain — can
reveal gaps or misconceptions in the author's understanding, going beyond vocabulary
counting to knowledge-graph-level analysis.

### Planned applications (in rough priority order)

1. **Expertise routing** — analyse questions submitted to a chatbot and adapt or route
responses based on the user's apparent proficiency level
2. **Domain lexicon construction** — build specialist vocabulary databases for multiple
knowledge domains (side effect: refinement and validation of Tier 1–3 common lexicons)
3. **Proficiency evaluation** — estimate the expertise level of any input text author,
including automated evaluation of exam or assignment answers against a domain model
4. **World model (Tier 1–3)** — a self-consistent knowledge graph of concepts and
relations accessible to general adult speakers; language- and geography-aware
5. **Domain knowledge graph (Tier 4)** — a specialist knowledge graph per domain,
encoding how Tier 4 concepts relate to each other and to the common lexicon
6. **Cross-domain consistency** — a unified world model spanning multiple Tier 4 domains,
tracking concept relationships and resolving conflicts across jurisdictions and fields
(long-term research direction; considered a prerequisite step toward AGI-level reasoning)

### Known gaps to address

* Named entity handling for Tier 1–3 users is not yet designed. Named entities
(people, places, organisations, events) are language-, geography-, and
historically-dependent and do not fit cleanly into the current tier model.
This requires a separate design decision before Tier 3 is built.

\---

## Repository layout

```
esperanto-lexicon/               ← this repo (code)
├── CLAUDE.md                    ← you are here
├── AGENTS.md                    ← pointer to CLAUDE.md for other agents
├── README.md
├── LICENSING.md
├── requirements.txt
├── .gitignore
├── src/
│   ├── lexicon/                 ← Tier 1–3 common lexicon code and schema
│   ├── extractor/               ← Tier 4 domain MWE extraction pipeline
│   └── analyzer/                ← text analysis and expertise estimation
├── data/
│   ├── lexicon\_db/              ← lexicon.db lives here (not committed, regenerated)
│   └── domain\_db/               ← per-domain SQLite files (not committed)
├── tests/
└── docs/                        ← architecture notes, decision log
```

```
esperanto-lexicon-corpus/        ← separate repo (data)
├── tax\_law/
│   ├── lt.txt                   ← Lithuanian original
│   ├── en.txt                   ← English translation
│   └── eo.txt                   ← Esperanto translation (future)
└── <other\_domains>/
```

Database files (`\*.db`) are gitignored. The code that creates and populates them is
in the repo; databases are regenerated locally by running the migration/build scripts.

\---

## Language architecture (critical — read carefully)

**Esperanto is the primary canonical anchor for all lexicon entries.**

Every concept in the system has an Esperanto root as its identity. Other languages
(English, Lithuanian, and future European languages) are "language packs" — optional
extensions that map onto Esperanto-keyed entries.

Rationale: Esperanto's systematically constructed roots provide a normalised
cross-linguistic foundation. \~92% of the existing common vocabulary already has
Esperanto mappings.

Fallback hierarchy for entries without an Esperanto equivalent yet:
`eo → en → source\_language`

Mark entries without Esperanto coverage as `eo\_status: 'pending'`, never omit them.

Language pack codes used throughout: `'eo'` (Esperanto), `'en'` (English),
`'lt'` (Lithuanian). Add others as needed using ISO 639-1 codes.

Language packs are optional and independently deployable. A real-world application
in Lithuanian does not require the English pack to be present — it links directly
from Esperanto roots to Lithuanian forms.

\---

## Tier model

|Tier|Audience|CEFR|Approx. size|Notes|
|-|-|-|-|-|
|1|Child (\~age 5)|A1|\~1,080 words|Dolch list + Oxford 3000 A1|
|2|Adolescent (\~10)|A2–B2|\~2,713 words|Oxford 3000 remainder|
|3|Adult (general)|C1+|TBD|Generic MWEs; named entities pending design|
|4|Domain expert|—|Per domain|See Tier 4 section below|

Tiers 1 and 2 are populated in `lexicon.db` (v1). Tier 3 is not yet built.
Tier 4 lives in per-domain SQLite files under `data/domain\_db/`.

\---

## Tier 4 — the "living language" model

Tier 4 entries are **not static**. They follow a lifecycle:

```
emerging → established → crystallized → promoted
```

* `emerging`: term appears in one or few documents; not yet widely recognised
* `established`: term is consistently used across multiple documents in the domain
* `crystallized`: term has a stable, agreed definition within the domain
* `promoted`: term has migrated into general use (Tier 3 or lower); e.g. "WiFi"

Each Tier 4 entry tracks:

* Where it was first seen (`first\_seen\_source`, `first\_seen\_date`)
* All subsequent occurrences (`seen\_in` — list of source refs and dates)
* Its current lifecycle status and tier
* Promotion history (if it has moved tiers)
* Conflicts: the same MWE can mean different things across domains or jurisdictions;
these are recorded explicitly with `mwe\_conflict` entries, never silently merged

A term is a candidate for promotion when it appears frequently across unrelated
documents and its meaning has stabilised. Promotion requires human review.

\---

## Database schema (v2 — target)

### Common lexicon: `lexicon.db`

```
concept
  id, eo\_root, eo\_word, eo\_pos, eo\_prefix, eo\_suffix, eo\_status
  wordnet\_synset, wordnet\_definition, hypernym\_chain, immediate\_hypernym

concept\_lang
  concept\_id, lang, word, pos, cefr\_level, tier, source

inflected\_forms
  inflected\_word, lemma, lang, form\_description, tier
```

### Domain lexicon: `data/domain\_db/<domain>.db`

```
mwe
  id, eo\_canonical, status, first\_seen\_source, first\_seen\_date,
  current\_tier, domain, jurisdiction

mwe\_lang
  mwe\_id, lang, phrase, definition, source\_ref, pos\_pattern

mwe\_occurrence
  mwe\_id, source\_doc, date, context\_snippet

mwe\_conflict
  mwe\_id\_a, mwe\_id\_b, conflict\_description, resolution\_status
```

The v1 `lexicon.db` (English-primary, single flat table) is the migration source.
Migration script: `src/lexicon/migrate\_v1\_to\_v2.py`.

\---

## Extraction pipeline (Tier 4)

The extractor is a standalone process. It reads cleaned plain-text corpus files
and writes/updates a domain DB. It does not depend on the chatbot or analyzer.

Stages:

1. **Definition parser** — regex + spaCy to extract `Term – definition` patterns
(e.g. Article 2 of a legal act). Output: `article2\_terms.jsonl`
2. **Statistical MWE detector** — noun-chunk + bigram/trigram collocation
(PMI, log-likelihood) over full text, filtered against common lexicon.
Output: `mwe\_candidates.jsonl`
3. **Human review** — CLI or simple UI to classify candidates as Tier 3, Tier 4,
or reject
4. **Domain DB writer** — commits reviewed entries to the domain SQLite file

Input format: `corpus/<domain>/<lang>.txt` — one clean plain-text file per language.
NLP engine: **spaCy** primary; Stanza as fallback for Lithuanian.

\---

## Collaboration model

This project is developed by a small research team (multiple humans, AIs + Claude Code).

**Workflow:**

1. Design decisions and architecture discussions happen in Claude.ai chat (not here).
2. Implementation work happens via Claude Code (this environment) against the GitHub repo.
3. Every code change goes through a Pull Request — including AI-generated changes.
4. Colleagues can invoke Claude via `@claude` in GitHub issues or PR comments.

**What Claude Code may do autonomously:**

* Read any file in the repository
* Write and edit code files
* Run tests (`pytest`)
* Run migration/build scripts against local DB files
* Commit to a working branch and open a PR

**What Claude Code must not do without explicit human instruction:**

* Merge a PR
* Delete or rename database files
* Change the tier of any existing lexicon entry
* Modify `CLAUDE.md` or `AGENTS.md` without being asked

\---

## Known limitations

### Lithuanian lemmatisation (lt\_core\_news\_sm)

The spaCy `lt\_core\_news\_sm` model mislemmatises some adjective inflections,
causing MWE lookup misses in the coverage report. Confirmed example:

```
"individualia" → spaCy lemma: "individualias"   (wrong)
expected base form: "individuali"
```

The stored `phrase\_normalized` for clause 7 is `"individuali veikla"`. Neither
the inflected text form `"individualia veikla"` nor the wrong lemma form
`"individualias veikla"` matches exactly. A **prefix partial-match fallback**
(Phase 2 in `classify\_tokens`) compensates: it detects that `"individualia"`
starts with `"individuali"` and the remaining word `"veikla"` matches, and
classifies the bigram as TIER4.

Workaround: Phase 2 prefix matching in `src/analyzer/coverage\_report.py`.
Proper fix: integrate Stanza `lt` model for better lemmatisation.
Tracked in: GitHub issue (to be created)

### Lithuanian common lexicon coverage

`src/lexicon/build\_lt\_lexicon.py` has been run against `lexicon\_v2.db` and
inserted **896 LT entries** via EN→LT translation pairs. LT Tier 1/2 lookup now
works without `--fallback-lang`. Coverage: 896 of 3,793 EN concepts mapped;
remainder have no known LT equivalent yet.

Known gap: proper Lithuanian wordnet or frequency-list import would extend
coverage further. `--fallback-lang en` remains available as a stopgap for
languages with no primary entries.

\---

## Conventions

**Python:**

* Python 3.10+
* Black formatting (line length 88)
* Type hints on all function signatures
* Docstrings on all public functions
* Tests in `tests/` mirroring `src/` structure

**SQL / SQLite:**

* Schema definitions in `src/lexicon/schema.py` (single source of truth)
* All queries use parameterised statements (never f-string SQL)
* Migrations are versioned scripts, never destructive in-place edits

**Commits:**

* Conventional commit format: `feat:`, `fix:`, `refactor:`, `docs:`, `test:`
* One logical change per commit
* Never commit `.db` files

**Languages in code:**

* Code, comments, docstrings, and commit messages: English
* Variable/function names reflecting domain concepts may use Esperanto roots
where they match the schema (e.g. `eo\_root`, `concept\_lang`)

**Test fixtures:**

* HTML fixtures for parser tests must be copied verbatim from a real source
  document, never hand-written. A minimal subset of the real document is fine —
  the smallest fragment that exercises the code path — but no element may be
  omitted, reformatted, or simplified. Real-world HTML includes structures that
  hand-written fixtures routinely miss (implicit `<tbody>`, `<colgroup>`,
  whitespace text nodes, attribute order, entity references), and parsers that
  pass tests on simplified fixtures will silently fail on real input.
* Document the source URL and retrieval date alongside each fixture file
  (e.g. as an HTML comment at the top of the fixture).
* This rule cost a full debugging cycle on the UCC LT extractor — see git
  history for the regression class.

\---

## Current state (update this section after each work session)



* \[x] src/ingestion/docx\_to\_corpus.py — docx to clean text ingestion
* \[x] src/extractor/extract\_definitions.py — Article 2 definition parser (\*\* markers, em-dash only)
* \[x] src/extractor/review\_cli.py — bilingual review CLI
* \[x] src/extractor/domain\_db\_writer.py — domain DB writer; dedup requires phrase+definition match; cross-phrase collision (e.g. shared EO translation) creates new mwe + conflict record
* \[x] src/extractor/statistical\_mwe\_detector.py — PMI/log-likelihood; splits into --output (MWE) and --output-ne (NE candidates)
* \[x] src/analyzer/coverage\_report.py — greedy MWE matching; expertise signal ratio T4/(T1+T2); --fallback-lang; prefix partial-match for inflected LT adjectives
* \[x] src/extractor/bulk\_approve.py — bulk-approve .jsonl records by language
* \[x] First domain corpus GPMI — 38 concepts × 3 langs (lt+eo+en) = 114 mwe\_lang rows in gpmi\_lt\_tax.db
* \[x] Clean ingestion from docx — 637 LT amendments stripped, tables handled
* \[x] First coverage report run — three test sentences validated with spaCy (see Known limitations)
* \[x] src/lexicon/build\_lt\_lexicon.py — 896 LT entries inserted into lexicon\_v2.db; LT T1/T2 matching working without --fallback-lang
* \[x] src/analyzer/conflict\_report.py — single-DB and cross-DB conflict report; 25 tests passing
* \[x] src/ingestion/ingest\_document.py — pipeline wrapper (Pass 1: extract; Pass 2: commit)
* \[x] docs/adding\_new\_domain.md — step-by-step guide for onboarding a new domain
* \[x] src/extractor/extract\_eurlex\_definitions.py — EUR-Lex consolidated HTML parser; EurLexExtractor class; emits definition/article\_metadata/footnote records; amendment cursor tracking; annex/recital skipping
* \[x] tests/fixtures/eurlex/ucc\_en\_article5\_fragment.html — 41-definition Article 5 fixture with sub-items, three-level nesting, M4 amendment marker, single-quote variant, footnotes, annex (skipped)
* \[x] tests/test\_extract\_eurlex\_definitions.py — 19 tests passing (1 slow integration test skipped)
* \[x] domain\_db\_writer.py — updated to accept EUR-Lex definition records (record\_type=definition with celex\_id); article\_metadata and footnote records skipped
* \[x] domain\_db\_writer.py — EUR-Lex cross-language grouping fixed; join key is (celex\_id, article\_number, list\_path), excluding language-dependent structural\_path. Regression test added.
* \[x] review\_cli.py — updated to display EUR-Lex records with amendment info, list\_path, and article rubric
* \[x] src/ingestion/ingest\_eurlex.py — two-phase EUR-Lex ingestion pipeline wrapper; Phase 1 extracts definitions + corpus text per language and combines to \_combined.jsonl; Phase 2 commits approved records and optionally runs statistical MWE detection
* \[x] docs/eurlex\_pipeline.md — end-to-end guide: downloading EUR-Lex HTML, directory layout, running Phase 1 and Phase 2, HTML layout variants, cross-language pairing, cross-domain conflict detection, standalone stat MWE detection
* \[x] docs/coverage\_report\_examples.md — three annotated coverage report runs (general, specialist, mixed); includes threshold reference table and note on short Tier 4 terms inflating specialist score
* \[x] src/extractor/candidate\_quality\_report.py — MWE candidate quality tiers (HIGH/MEDIUM/LOW by freq+PMI), NE overlap, cross-domain match detection, --auto-approve-high flag; 34 tests passing in tests/test\_candidate\_quality\_report.py
* \[x] tests/test\_ingest\_eurlex.py — 10 tests for \_count\_records and \_combine\_jsonl; Phase 1 combined JSONL count and Phase 2 no-approved-records guard
* \[x] CBAM definitions (02023R0956-20251020) — EN and LT both produce 34 definitions; LT uses divlayout\_numbered variant (N) term – definition em-dash style); FR uses guillemet+colon style (still 0 — different variant, not yet handled)
* \[x] extract\_eurlex\_definitions.py — added --list-articles dry-run flag; --auto-article=definitions flag; DEFINITION\_RUBRICS per-language keyword map; 0-definition sanity warning; divlayout\_numbered variant handler (\_article\_uses\_numbered\_items, \_match\_definition\_numbered) for LT-style em-dash definitions
* \[x] tests/fixtures/eurlex/cbam\_lt\_article3\_fragment.html — 4-item LT CBAM Article 3 fixture (items 1, 2, 19, 34); real HTML verbatim; exercises simple, chapeau+sub-items, and numbered list\_path cases
* \[x] tests/test\_extract\_eurlex\_definitions.py — 17 new TestDivlayoutNumbered tests + 3 chapter-rubric fallback tests (400 total passing)
* \[x] extract\_eurlex\_definitions.py — \_get\_article\_rubric() fallback to chapter title-division-2 when article has no stitle-article-norm; --list-articles marks inherited chapter rubrics with "← rubric (chapter)"; --auto-article=definitions resolves via chapter rubric with multi-article warning; article\_metadata record now includes article\_rubric\_source field
* \[x] Dual Use (02021R0821-20251115) — EN 22 definitions, LT 22 definitions extracted via --article 2; --list-articles now shows all 32 articles with chapter rubrics; --auto-article=definitions warns that art\_1 and art\_2 share chapter "SUBJECT AND DEFINITIONS" and selects art\_1
* \[x] review\_cli.py — sub\_items displayed when definition is empty/trivial (colon/dash placeholder); \_eurlex\_def\_lines() helper; max 5 items + overflow count; two-language display updated; 11 new tests in tests/test\_review\_cli.py
* \[x] domain\_db\_writer.py — EUR-Lex records with empty/trivial definition joined from sub\_items as "(a) text; (b) text; ..." before DB write; \_join\_sub\_items() helper; 10 new tests
* \[x] ucc\_customs.db — 41 concepts EN+LT committed
* \[x] cbam.db — 32 concepts EN+LT committed
* \[x] dualuse.db — 22 concepts EN+LT, lifecycle working
* \[x] extract\_eurlex\_definitions.py — fix LT term extraction for divlayout\_numbered Sub-case B chapeau: strip from first en/em-dash after removing trailing colon so "eksportas – tai:" → "eksportas"; same fix for tablelayout Shape B \_parse\_table\_row(); truncation warning added for chapaeu terms > 5 words; 3 new unit tests
* \[x] Sub-items display in review\_cli.py — \_eurlex\_def\_lines() helper; empty/trivial definition shows sub\_items; max 5 items + overflow count
* \[x] Cross-domain conflict detection working — 5 conflicts found across 4 domains (UCC/CBAM/DualUse/GPMI)
* \[x] Living language lifecycle validated: LT terms promoted emerging → established on second source appearance
* \[x] French definition extraction — French uses «term», definition or «term»: list (comma or colon separator depending on whether the definition is a noun phrase or a sub-list). Added FRENCH\_DEFINITION\_PATTERN with language dispatch via \_get\_definition\_pattern(lang). Handles guillemets (CBAM FR, DualUse FR), ASCII double-quotes (UCC FR), optional "ou ABBREV" suffix, and parenthesised abbreviation (numéro EORI) variant. UCC FR 41/41, CBAM FR 34/34, DualUse FR 22/22, 0 warnings. 4 new tests. UCC/CBAM/DualUse domain DBs now have 3 language packs (EN, FR, LT).
* \[x] src/extractor/extract\_wco\_glossary.py — PDF extractor for WCO Glossary of International Customs Terms (2024-06 edition). Parses 182 bilingual EN+FR entries with notes and cross-references. Uses pdfplumber native table extraction; handles nested French parens, page-break continuations, right-cell overflow rows, French-paren-on-next-row split (RESILIENCE), and mixed-case headwords. 31 tests passing.
* \[x] wco\_intl.db — new domain DB, EN+FR (LT and EO pending). 182 concepts × 2 langs = 364 mwe\_lang rows. Cross-language grouping key (source, edition, entry\_id) added to domain\_db\_writer.py as second source-specific grouping strategy alongside EUR-Lex. 10 cross-domain conflicts found vs ucc\_customs.db.
* \[ ] Statistical candidates review — pending human review
* \[ ] Named entity layer — design deferred
* \[ ] Tier 3 — not yet designed

