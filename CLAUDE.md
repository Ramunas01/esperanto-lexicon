# CLAUDE.md — Esperanto Lexicon Knowledge Analysis

This file is the primary briefing for Claude Code sessions working on this project.
Read it fully before taking any action. It supersedes any assumptions from training data.

---

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

- Named entity handling for Tier 1–3 users is not yet designed. Named entities
  (people, places, organisations, events) are language-, geography-, and
  historically-dependent and do not fit cleanly into the current tier model.
  This requires a separate design decision before Tier 3 is built.

---

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
│   ├── lexicon_db/              ← lexicon.db lives here (not committed, regenerated)
│   └── domain_db/               ← per-domain SQLite files (not committed)
├── tests/
└── docs/                        ← architecture notes, decision log
```

```
esperanto-lexicon-corpus/        ← separate repo (data)
├── tax_law/
│   ├── lt.txt                   ← Lithuanian original
│   ├── en.txt                   ← English translation
│   └── eo.txt                   ← Esperanto translation (future)
└── <other_domains>/
```

Database files (`*.db`) are gitignored. The code that creates and populates them is
in the repo; databases are regenerated locally by running the migration/build scripts.

---

## Language architecture (critical — read carefully)

**Esperanto is the primary canonical anchor for all lexicon entries.**

Every concept in the system has an Esperanto root as its identity. Other languages
(English, Lithuanian, and future European languages) are "language packs" — optional
extensions that map onto Esperanto-keyed entries.

Rationale: Esperanto's systematically constructed roots provide a normalised
cross-linguistic foundation. ~92% of the existing common vocabulary already has
Esperanto mappings.

Fallback hierarchy for entries without an Esperanto equivalent yet:
`eo → en → source_language`

Mark entries without Esperanto coverage as `eo_status: 'pending'`, never omit them.

Language pack codes used throughout: `'eo'` (Esperanto), `'en'` (English),
`'lt'` (Lithuanian). Add others as needed using ISO 639-1 codes.

Language packs are optional and independently deployable. A real-world application
in Lithuanian does not require the English pack to be present — it links directly
from Esperanto roots to Lithuanian forms.

---

## Tier model

| Tier | Audience         | CEFR | Approx. size | Notes                           |
|------|-----------------|------|--------------|-------------------------------|
| 1    | Child (~age 5)   | A1   | ~1,080 words | Dolch list + Oxford 3000 A1    |
| 2    | Adolescent (~10) | A2–B2| ~2,713 words | Oxford 3000 remainder          |
| 3    | Adult (general)  | C1+  | TBD          | Generic MWEs; named entities pending design |
| 4    | Domain expert    | —    | Per domain   | See Tier 4 section below       |

Tiers 1 and 2 are populated in `lexicon.db` (v1). Tier 3 is not yet built.
Tier 4 lives in per-domain SQLite files under `data/domain_db/`.

---

## Tier 4 — the "living language" model

Tier 4 entries are **not static**. They follow a lifecycle:

```
emerging → established → crystallized → promoted
```

- `emerging`: term appears in one or few documents; not yet widely recognised
- `established`: term is consistently used across multiple documents in the domain
- `crystallized`: term has a stable, agreed definition within the domain
- `promoted`: term has migrated into general use (Tier 3 or lower); e.g. "WiFi"

Each Tier 4 entry tracks:

- Where it was first seen (`first_seen_source`, `first_seen_date`)
- All subsequent occurrences (`seen_in` — list of source refs and dates)
- Its current lifecycle status and tier
- Promotion history (if it has moved tiers)
- Conflicts: the same MWE can mean different things across domains or jurisdictions;
  these are recorded explicitly with `mwe_conflict` entries, never silently merged

A term is a candidate for promotion when it appears frequently across unrelated
documents and its meaning has stabilised. Promotion requires human review.

---

## Database schema (v2 — target)

### Common lexicon: `lexicon.db`

```
concept
  id, eo_root, eo_word, eo_pos, eo_prefix, eo_suffix, eo_status
  wordnet_synset, wordnet_definition, hypernym_chain, immediate_hypernym

concept_lang
  concept_id, lang, word, pos, cefr_level, tier, source

inflected_forms
  inflected_word, lemma, lang, form_description, tier
```

### Domain lexicon: `data/domain_db/<domain>.db`

```
mwe
  id, eo_canonical, status, first_seen_source, first_seen_date,
  current_tier, domain, jurisdiction

mwe_lang
  mwe_id, lang, phrase, definition, source_ref, pos_pattern

mwe_occurrence
  mwe_id, source_doc, date, context_snippet

mwe_conflict
  mwe_id_a, mwe_id_b, conflict_description, resolution_status
```

The v1 `lexicon.db` (English-primary, single flat table) is the migration source.
Migration script: `src/lexicon/migrate_v1_to_v2.py`.

---

## Extraction pipeline (Tier 4)

The extractor is a standalone process. It reads cleaned plain-text corpus files
and writes/updates a domain DB. It does not depend on the chatbot or analyzer.

Stages:

1. **Definition parser** — regex + spaCy to extract `Term – definition` patterns
   (e.g. Article 2 of a legal act). Output: `article2_terms.jsonl`
2. **Statistical MWE detector** — noun-chunk + bigram/trigram collocation
   (PMI, log-likelihood) over full text, filtered against common lexicon.
   Output: `mwe_candidates.jsonl`
3. **Human review** — CLI or simple UI to classify candidates as Tier 3, Tier 4,
   or reject
4. **Domain DB writer** — commits reviewed entries to the domain SQLite file

Input format: `corpus/<domain>/<lang>.txt` — one clean plain-text file per language.
NLP engine: **spaCy** primary; Stanza as fallback for Lithuanian.

---

## Collaboration model

This project is developed by a small research team (multiple humans + Claude Code).

**Workflow:**

1. Design decisions and architecture discussions happen in Claude.ai chat (not here).
2. Implementation work happens via Claude Code (this environment) against the GitHub repo.
3. Every code change goes through a Pull Request — including AI-generated changes.
4. Colleagues can invoke Claude via `@claude` in GitHub issues or PR comments.

**What Claude Code may do autonomously:**

- Read any file in the repository
- Write and edit code files
- Run tests (`pytest`)
- Run migration/build scripts against local DB files
- Commit to a working branch and open a PR

**What Claude Code must not do without explicit human instruction:**

- Merge a PR
- Delete or rename database files
- Change the tier of any existing lexicon entry
- Modify `CLAUDE.md` or `AGENTS.md` without being asked

---

## Conventions

**Python:**

- Python 3.10+
- Black formatting (line length 88)
- Type hints on all function signatures
- Docstrings on all public functions
- Tests in `tests/` mirroring `src/` structure

**SQL / SQLite:**

- Schema definitions in `src/lexicon/schema.py` (single source of truth)
- All queries use parameterised statements (never f-string SQL)
- Migrations are versioned scripts, never destructive in-place edits

**Commits:**

- Conventional commit format: `feat:`, `fix:`, `refactor:`, `docs:`, `test:`
- One logical change per commit
- Never commit `.db` files

**Languages in code:**

- Code, comments, docstrings, and commit messages: English
- Variable/function names reflecting domain concepts may use Esperanto roots
  where they match the schema (e.g. `eo_root`, `concept_lang`)

---

## Current state (update this section after each work session)


- [x] src/ingestion/docx_to_corpus.py — docx to clean text ingestion
- [x] src/extractor/extract_definitions.py — Article 2 definition parser (** markers, em-dash only)
- [x] src/extractor/review_cli.py — bilingual review CLI
- [x] src/extractor/domain_db_writer.py — domain DB writer; dedup requires phrase+definition match; cross-phrase collision (e.g. shared EO translation) creates new mwe + conflict record
- [x] src/extractor/statistical_mwe_detector.py — PMI/log-likelihood; splits into --output (MWE) and --output-ne (NE candidates)
- [x] src/analyzer/coverage_report.py — greedy MWE matching; expertise signal ratio T4/(T1+T2)
- [x] First domain corpus GPMI — 38 concepts × 3 langs (lt+eo+en) = 114 mwe_lang rows in gpmi_lt_tax.db
- [x] Clean ingestion from docx — 637 LT amendments stripped, tables handled
- [ ] Statistical candidates review — pending human review
- [ ] First coverage report run — sentences not yet tested end-to-end with spaCy
- [ ] Named entity layer — design deferred
- [ ] Tier 3 — not yet designed
