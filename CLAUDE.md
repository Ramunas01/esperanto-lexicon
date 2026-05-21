# CLAUDE.md — Esperanto Lexicon Knowledge Analysis

This file is the primary briefing for Claude Code sessions working on this project.
Read it fully before taking any action. It supersedes any assumptions from training data.

\---

## What this project is

A multilingual lexicon analysis system that estimates some entity's domain expertise from
their text. The core hypothesis: the ratio of common vocabulary to domain-specific
terminology in someone's writing is a proxy for their knowledge level (as a first approximation).

Possible further developments: detect the concepts relationships (in text) and compare them to the 

normalized "concept map" of a specific knowledge area to detect (the entity knowledge) discrepancies.

The system has several parts:

* A **common lexicon** (Tiers 1–3): words and concepts known by most adult speakers
* A **domain lexicon** (Tier 4): specialist terminology, multi-word expressions (MWEs),
abbreviations, and named entities introduced in specific domain documents,
* **Missing part**: data structure for named entities for Tiers 1-3 users (might depend on language, on geography, on historical period).

Several tool development applications expected:

&#x20;- creation of the domain lexicons for several (multiple) domains of knowledge (side effect -> refinement of Tier 1-3 lexicons);

&#x20;- creation of the "world models" (self-consistent knowledge graphs) for Tier 1-3 users;

&#x20;- creation of specific "domain knowledge" (knowledge graph) for specific Tier 4 vocabulary users;

&#x20;- evaluation of proficiency level or the author of some input text (e.g. estimation of some chatbot answer to a user question);

The first practical application is analysing questions asked to a chatbot, to route
or adapt responses based on the user's apparent expertise level.

Ultimate application: evaluation whether some input text matches the domain knowledge (e.g. evaluation of student's exam answer).

Future applications: consistent "world model" reflecting object/entity relations in multiple Tier 4 domains (pre-requisite to AGI).

\---

## Repository layout

```
esperanto-lexicon/          ← this repo (code)
├── CLAUDE.md               ← you are here
├── README.md
├── LICENSING.md
├── requirements.txt
├── .gitignore
├── src/
│   ├── lexicon/            ← Tier 1–3 common lexicon code and schema
│   ├── extractor/          ← Tier 4 domain MWE extraction pipeline
│   └── analyzer/           ← text analysis and expertise estimation
├── data/
│   ├── lexicon\_db/         ← lexicon.db lives here (not committed, regenerated)
│   └── domain\_db/          ← per-domain SQLite files (not committed)
├── tests/
└── docs/                   ← architecture notes, decision log
```

```
esperanto-lexicon-corpus/   ← separate repo (data)
├── tax\_law/
│   ├── lt.txt              ← Lithuanian original
│   ├── en.txt              ← English translation
│   └── eo.txt              ← Esperanto translation (future)
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

\---

## Tier model

|Tier|Audience|CEFR|Approx. size|Notes|
|-|-|-|-|-|
|1|Child (\~age 5)|A1|\~1,080 words|Dolch list + Oxford 3000 A1|
|2|Adolescent (\~10)|A2–B2|\~2,713 words|Oxford 3000 remainder|
|3|Adult (general)|C1+|TBD|Generic MWEs ("as a result of")|
|4|Domain expert|—|Per domain|See below|

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
* Conflicts: the same MWE can have different meanings across domains or jurisdictions;
these are recorded explicitly, never silently merged

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

This project is developed by a small research team (multiple humans + Claude Code).

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

\---

## Current state (update this section after each work session)

* \[x] v1 `lexicon.db` exists: 3,793 entries, Tiers 1–2, English-primary, \~92% Esperanto coverage
* \[x] Directory structure and repos created
* \[ ] `migrate\_v1\_to\_v2.py` — not yet written
* \[ ] v2 schema — not yet implemented
* \[ ] Tier 3 — not yet built
* \[ ] Extractor pipeline — not yet written
* \[ ] First domain corpus (Lithuanian tax law) — not yet added to corpus repo

