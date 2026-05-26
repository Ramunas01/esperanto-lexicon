# Adding a New Domain

This guide walks through adding a new knowledge domain to the lexicon system.
A "domain" is a subject area (e.g. personal income tax, corporate law, customs)
represented as a SQLite database under `data/domain_db/`.

---

## Prerequisites

- [ ] Source document(s): `.docx` for national law, `.html` for EUR-Lex
- [ ] `lexicon_v2.db` in `data/lexicon_db/` (run `src/lexicon/migrate_v1_to_v2.py` if absent)
- [ ] spaCy model for your language: `python -m spacy download lt_core_news_sm`
- [ ] A short domain label with underscores, e.g. `corporate_income_tax`
- [ ] A jurisdiction code (ISO 3166-1 alpha-2 or `EU`), e.g. `LT`, `EU`

---

## Directory layout created by the pipeline

```
<corpus-dir>/<domain>/
    corpus.txt             ← clean plain text (docx source only)
    amendments.txt         ← stripped amendment records (docx source only)
    definitions.jsonl      ← extracted definition candidates (review here)
    mwe_candidates.jsonl   ← statistical MWE candidates (review here)
    ne_candidates.jsonl    ← named-entity candidates

data/domain_db/
    <domain>.db            ← the target SQLite domain database
    manual_overrides.jsonl ← committed corrections (hand-edited, never regenerated)
```

---

## Workflow A: National law (docx source)

### Phase 1 — Extract

```bash
python3 src/ingestion/ingest_document.py \
    --source docx \
    --input path/to/law_lt.docx \
    --lang lt \
    --domain corporate_tax \
    --jurisdiction LT \
    --primary-lang lt \
    --corpus-dir ~/projects/esperanto-lexicon-corpus/ \
    --db data/domain_db/corporate_tax.db \
    --lexicon data/lexicon_db/lexicon_v2.db
```

If your document uses a non-standard article for definitions, pass `--article 3`.

Repeat for each additional language (swap `--lang` and `--input`).

### Phase 2 — Review, then commit

```bash
# Review definitions (required before Phase 2)
python3 src/extractor/review_cli.py \
    --input ~/projects/esperanto-lexicon-corpus/corporate_tax/definitions.jsonl \
    --lang lt

# Commit approved records
python3 src/ingestion/ingest_document.py \
    --phase 2 \
    --lang lt \
    --domain corporate_tax \
    --jurisdiction LT \
    --corpus-dir ~/projects/esperanto-lexicon-corpus/ \
    --db data/domain_db/corporate_tax.db \
    --lexicon data/lexicon_db/lexicon_v2.db
```

---

## Workflow B: EU legislation (EUR-Lex HTML source)

```bash
python3 src/ingestion/ingest_document.py \
    --source eurlex \
    --input path/to/ucc_en.html \
    --celex 02013R0952-20221212 \
    --lang en \
    --domain customs_ucc \
    --jurisdiction EU \
    --primary-lang en \
    --corpus-dir ~/projects/esperanto-lexicon-corpus/ \
    --db data/domain_db/customs_ucc.db \
    --lexicon data/lexicon_db/lexicon_v2.db
```

Note: `extract_eurlex_definitions.py` handles EUR-Lex HTML directly and produces
`definitions.jsonl` without an intermediate corpus text step.

**Layout auto-detection**: The extractor calls `detect_layout()` internally:
- `divlayout` — EUR-Lex English and most languages with `eli-subdivision` wrappers
- `tablelayout` — Lithuanian and some other translations: flat article siblings with
  `<table><tr><td class="dlist-term">...</td><td class="dlist-definition">...</td></tr></table>`
  rows and en-dash–separated term/definition text

No `--layout` flag is needed; the right path is selected automatically.
If you see `0 definitions found` for a language that uses tables (check the raw HTML),
run `detect_layout` directly to confirm detection:
```python
from extractor.extract_eurlex_definitions import EurLexExtractor, detect_layout
ext = EurLexExtractor("...", "lt")
print(detect_layout(ext.parse_html(Path("path/to/lt.html"))))
```

---

## Manual review in detail

### Definition records

Keys: `[a]` approve, `[r]` reject, `[s]` skip, `[q]` quit.

For bilingual side-by-side review (e.g. LT + EO):

```bash
python3 src/extractor/review_cli.py \
    --input definitions.jsonl \
    --lang lt eo
```

### Statistical MWE candidates

Statistical records show PHRASE, FREQ, PMI, and component breakdown.
Approve genuine domain terms; reject common collocations.

```bash
python3 src/extractor/review_cli.py \
    --input mwe_candidates.jsonl \
    --lang lt
```

### Bulk-approve (skip manual review)

If all records look correct and you want to approve a language in bulk:

```bash
python3 src/extractor/bulk_approve.py \
    --input definitions.jsonl \
    --lang lt eo
```

---

## Manual overrides

If the extractor produces incorrect values (wrong Esperanto translation,
typo in definition), add a correction to `data/domain_db/manual_overrides.jsonl`
rather than re-running from scratch:

```json
{
  "match_on": {"phrase_normalized": "rilataj personoj", "lang": "eo"},
  "override": {"phrase": "Asociitaj personoj", "phrase_normalized": "asociitaj personoj"},
  "reason": "Incorrect EO translation — 'rilataj' means 'related', correct is 'asociitaj'",
  "overridden_by": "ramunas",
  "override_date": "2026-05-26"
}
```

The override is applied automatically on the next pipeline run. To apply it to
an already-built DB without re-running the pipeline:

```bash
python3 src/extractor/apply_overrides.py \
    --db data/domain_db/gpmi_lt_tax.db
```

---

## Linking synonyms

When two phrases express the same concept, link them rather than deleting one:

```bash
python3 src/extractor/link_synonyms.py \
    --db data/domain_db/corporate_tax.db \
    --phrase-a "individualia veikla besiverčiantys" \
    --phrase-b "verčiasi individualia veikla" \
    --lang lt \
    --reason "participial vs verbal form of same concept"

# List all synonym pairs
python3 src/extractor/link_synonyms.py \
    --db data/domain_db/corporate_tax.db \
    --list
```

Coverage reports will annotate matched synonyms:
`verčiasi individualia veikla  TIER4  (≡ individualia veikla besiverčiantys)`

---

## Conflict checking

Within a single DB (same phrase, different definitions):

```bash
python3 src/analyzer/conflict_report.py \
    --db data/domain_db/corporate_tax.db
```

Across two domain DBs (shared terms, diverging definitions):

```bash
python3 src/analyzer/conflict_report.py \
    --db       data/domain_db/corporate_tax.db \
    --cross-db data/domain_db/personal_income_tax.db \
    --lang     lt
```

---

## Coverage verification

```bash
echo "Mokesčių mokėtojas privalo deklaruoti pelno mokestį." > /tmp/sample.txt

python3 src/analyzer/coverage_report.py \
    --lexicon   data/lexicon_db/lexicon_v2.db \
    --domain-db data/domain_db/corporate_tax.db \
    --lang      lt \
    --input     /tmp/sample.txt
```

---

## Adding a second language to an existing domain

Run Phase 1 for the second language:

```bash
python3 src/ingestion/ingest_document.py \
    --source docx \
    --input path/to/law_en.docx \
    --lang en \
    --domain corporate_tax \
    --jurisdiction LT \
    --corpus-dir ~/projects/esperanto-lexicon-corpus/ \
    --db data/domain_db/corporate_tax.db \
    --lexicon data/lexicon_db/lexicon_v2.db
```

Then review and run Phase 2 for EN. The writer deduplicates by phrase + definition
and links new `mwe_lang` rows to existing `mwe` entries where possible.

---

## Troubleshooting

**`permission denied`** — Run `sudo chown -R $USER:$USER <corpus-dir>` or check
file permissions on the target directory.

**`0 definitions found`** — Check that Article 2 uses the `**Term** – definition`
pattern with double-asterisk bold markers (Lithuanian GPMI law convention). Other
formatting requires extending `extract_definitions.py`.

**`spaCy model not found`**:
```bash
pip install spacy --break-system-packages
python -m spacy download lt_core_news_sm
python -m spacy download xx_ent_wiki_sm
```

**`individualia` not matching `individuali veikla`** — Known issue: Lithuanian
spaCy model mislemmatises some inflected adjectives. Phase 2 prefix matching
compensates. If a case is not caught, report it for Stanza integration.
See CLAUDE.md § Known limitations.

**LT Tier 1/2 coverage is 0** — Run `build_lt_lexicon.py` to insert LT entries:
```bash
python3 src/lexicon/build_lt_lexicon.py --db data/lexicon_db/lexicon_v2.db
```

**Conflict detected for shared EO phrase** — Normal behaviour. Two LT terms may
share the same Esperanto canonical form. The system creates separate `mwe` rows
and a `mwe_conflict` record. Resolve via `conflict_report.py` and `link_synonyms.py`.
