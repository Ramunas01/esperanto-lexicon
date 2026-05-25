# Adding a New Domain

This guide walks through adding a new knowledge domain to the lexicon system.
A "domain" is a subject area (e.g. personal income tax, corporate law, medical terminology)
represented as a SQLite database under `data/domain_db/`.

---

## Prerequisites

- [ ] Source document(s) in `.docx` format, one file per language
- [ ] `lexicon_v2.db` built and in `data/lexicon_db/` (run `src/lexicon/migrate_v1_to_v2.py` if absent)
- [ ] spaCy model installed for your language (e.g. `python -m spacy download lt_core_news_sm`)
- [ ] A short domain label with underscores, e.g. `corporate_income_tax`
- [ ] A jurisdiction code (ISO 3166-1 alpha-2), e.g. `LT`

---

## Directory layout you will create

```
data/
├── corpus/<domain>/
│   ├── lt.txt                 ← cleaned plain text (produced by ingest_document.py)
│   └── lt_amendments.txt      ← stripped amendment records
└── domain_db/
    └── <domain>.db            ← the target SQLite domain database
data/ingestion/<domain>_lt/    ← intermediate work files for each language
    ├── corpus.txt
    ├── amendments.txt
    ├── definitions.jsonl      ← Article 2 definition candidates
    ├── mwe_candidates.jsonl   ← statistical MWE candidates
    └── ne_candidates.jsonl    ← named-entity candidates
```

---

## Step-by-step

### 1. Run Pass 1 (extract)

For each language, run `ingest_document.py` in Pass 1 mode.  This converts the docx,
extracts Article 2 definitions, and detects statistical MWE candidates.

```bash
python3 src/ingestion/ingest_document.py \
    --docx    path/to/law_lt.docx \
    --lang    lt \
    --domain  corporate_income_tax \
    --jurisdiction LT \
    --lexicon data/lexicon_db/lexicon_v2.db \
    --work-dir data/ingestion/corporate_income_tax_lt
```

If your document uses a different article for definitions, pass `--article 3` (or whichever).

Repeat for each language (swap `--lang` and `--docx`):

```bash
python3 src/ingestion/ingest_document.py \
    --docx    path/to/law_en.docx \
    --lang    en \
    --work-dir data/ingestion/corporate_income_tax_en \
    --lexicon data/lexicon_db/lexicon_v2.db
```

**Tip:** If you already have a plain-text corpus, pass `--skip-docx` and place it at
`<work-dir>/corpus.txt` before running.

---

### 2. Review definition candidates

Open the interactive review CLI for each language:

```bash
python3 src/extractor/review_cli.py \
    --input data/ingestion/corporate_income_tax_lt/definitions.jsonl \
    --lang lt
```

Keys: `[a]` approve, `[r]` reject, `[s]` skip, `[q]` quit.

For side-by-side bilingual review (e.g. LT + EO):

```bash
python3 src/extractor/review_cli.py \
    --input data/ingestion/corporate_income_tax_lt/definitions.jsonl \
    --lang lt eo
```

---

### 3. Review statistical MWE candidates

```bash
python3 src/extractor/review_cli.py \
    --input data/ingestion/corporate_income_tax_lt/mwe_candidates.jsonl \
    --lang lt
```

Statistical records show PHRASE, FREQ, PMI, and novelty components.
Approve candidates that are genuine domain terms; reject common collocations.

---

### 4. (Optional) Bulk-approve

If all records for a language look good and you want to skip manual review:

```bash
python3 src/extractor/bulk_approve.py \
    --input data/ingestion/corporate_income_tax_lt/definitions.jsonl \
    --lang lt eo
```

---

### 5. Run Pass 2 (commit to domain DB)

After review, commit approved records to the domain database:

```bash
python3 src/ingestion/ingest_document.py \
    --work-dir    data/ingestion/corporate_income_tax_lt \
    --domain      corporate_income_tax \
    --jurisdiction LT \
    --db          data/domain_db/corporate_income_tax.db \
    --post-review
```

The domain DB is created automatically if it does not exist.
Run Pass 2 separately for each language's work directory.

---

### 6. Check for conflicts

Within a single DB (same phrase, different definitions across documents):

```bash
python3 src/analyzer/conflict_report.py \
    --db data/domain_db/corporate_income_tax.db
```

Across two domain DBs (shared terms, diverging definitions):

```bash
python3 src/analyzer/conflict_report.py \
    --db       data/domain_db/corporate_income_tax.db \
    --cross-db data/domain_db/personal_income_tax.db \
    --lang     lt
```

---

### 7. Run a coverage report

Verify the domain DB with a sample text:

```bash
echo "Mokesčių mokėtojas privalo deklaruoti pelno mokestį." > /tmp/sample.txt

python3 src/analyzer/coverage_report.py \
    --lexicon   data/lexicon_db/lexicon_v2.db \
    --domain-db data/domain_db/corporate_income_tax.db \
    --lang      lt \
    --input     /tmp/sample.txt
```

---

## Troubleshooting

**"no definitions found"** — Check that Article 2 uses the `**Term** – definition` pattern
with a double-asterisk bold marker (as in Lithuanian GPMI law).  Other formatting patterns
require extending `extract_definitions.py`.

**"individualia" not matching "individuali veikla"** — Known issue: Lithuanian spaCy model
sometimes mislemmatises inflected adjectives.  Phase 2 prefix matching compensates for the
first token; subsequent tokens must match exactly.  See code comment in `coverage_report.py`.

**LT Tier 1/2 coverage is 0** — The LT lexicon is built from English translations via
`build_lt_lexicon.py`.  Run it against `lexicon_v2.db` if LT entries are absent:

```bash
python3 src/lexicon/build_lt_lexicon.py --db data/lexicon_db/lexicon_v2.db
```

**Conflict detected for shared EO phrase** — Normal behaviour.  Two Lithuanian terms may
share the same Esperanto canonical form (e.g. "Rilataj personoj" for both "Susiję asmenys"
and "Asocijuoti asmenys").  The system creates two separate `mwe` rows and a `mwe_conflict`
record linking them.  Resolve via `conflict_report.py`.

---

## Adding a second language to an existing domain

Run Pass 1 with the second-language docx and a new work-dir:

```bash
python3 src/ingestion/ingest_document.py \
    --docx     path/to/law_en.docx \
    --lang     en \
    --lexicon  data/lexicon_db/lexicon_v2.db \
    --work-dir data/ingestion/corporate_income_tax_en
```

Then Pass 2 pointing at the same domain DB:

```bash
python3 src/ingestion/ingest_document.py \
    --work-dir    data/ingestion/corporate_income_tax_en \
    --domain      corporate_income_tax \
    --jurisdiction LT \
    --db          data/domain_db/corporate_income_tax.db \
    --post-review
```

The writer deduplicates by phrase + definition and links new `mwe_lang` rows to existing
`mwe` entries where possible.
