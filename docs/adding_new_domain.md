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

### Identifying the right source document

EUR-Lex publishes three kinds of HTML for any given regulation:

1. **The original act** as published in the Official Journal (Formex-style HTML using
   `oj-*` classes, found under URLs like `L_YYYYNNNXX_NNNNNN_fmx_xml.html`).
2. **The consolidated text** combining the original act with all subsequent amendments
   as of a given date (consolidated-style HTML using ELI semantic classes —
   `eli-subdivision`, `norm`, `grid-list`).
3. **Amending and implementing acts** that modify the original by reference (also
   Formex-style; typically 1–5 articles long, none of which are Definitions articles).

For domain lexicon construction, **only use (2)**. The consolidated text contains all
current definitions in one document. Original and amending acts either lack definitions
(amending acts) or are superseded by the consolidated version.

The URL pattern for consolidated texts is:

```
https://eur-lex.europa.eu/legal-content/{LANG}/TXT/HTML/?uri=CELEX:0{NNNNN}-{YYYYMMDD}
```

where the leading `0` in the CELEX identifier marks the consolidated form. Compare with
original-act URLs which use `CELEX:3{NNNNN}` (no leading `0`).

Before running the extractor, verify the document is consolidated by listing its
articles:

```bash
python3 src/extractor/extract_eurlex_definitions.py \
    --input <html> --celex <celex_id> --lang en --list-articles
```

A consolidated regulation typically has 50+ articles; an amending act has 1–5. If the
list is short and no article is named "Definitions", you have the wrong document — fetch
the consolidated version instead.

Once you confirm the document is correct, use `--auto-article=definitions` to
automatically select the definitions article rather than guessing the article number:

```bash
python3 src/extractor/extract_eurlex_definitions.py \
    --input <html> --celex <celex_id> --lang en \
    --output data/domain_db/<domain>_definitions_en.jsonl \
    --auto-article definitions
```

If the extractor prints `0 definitions extracted` after running without `--article`,
it will also list the articles present. Use that list to diagnose whether the document
is the wrong type or the definitions article uses a layout not yet supported.

---

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

## Cross-language grouping key

Every domain must declare how `domain_db_writer.py` groups records across languages
into shared `mwe` concepts. This is the single most error-prone decision when
onboarding a new domain — get it wrong and you will see one of two failure modes:

**Over-merging**: distinct concepts collapse into one `mwe` row. Symptoms include
`mwe_conflict` rows appearing for legitimately different terms, or `mwe_lang` rows
whose phrase and definition do not correspond.

**Under-merging**: each language's records become their own concepts. Symptom: total
`mwe` count equals the sum of per-language record counts, instead of the per-language
count. This is what happened with the first EUR-Lex run (41 + 41 → 82 `mwe` rows
instead of 41).

### How to choose a grouping key

The grouping key is a tuple of record fields. It must satisfy three properties:

1. **Identical across all language versions of the same source.** A field whose value
   depends on how a specific language renders the source (DOM IDs, structural paths
   reconstructed from translated headings, locale-specific numbering) must not appear
   in the key.
2. **Unique within the domain.** A field that takes the same value for two different
   concepts (e.g. `clause_num = "1"` appearing in two unrelated source documents
   within one domain) must be combined with a document identifier.
3. **Present on every record the writer will see.** If any record type emitted by the
   extractor lacks a key field, the writer cannot group it; either add the field
   upstream in the extractor or exclude that record type from grouping.

A useful test: for any two records that *should* pair, write down the key tuple from
each — they must be byte-identical strings. For any two records that *should not* pair,
the tuples must differ in at least one field.

### Recommended keys for known domain shapes

| Domain shape | Recommended key |
|---|---|
| Single-source domain (e.g. GPMI: one tax-law document, multiple languages) | `(clause_num,)` |
| Multi-source legislative domain (e.g. EUR-Lex: many regulations, multiple languages each) | `(celex_id, article_number, list_path)` |
| Multi-source non-legislative domain (terminology databases, glossaries) | `(source_doc_id, entry_id)` or equivalent |

### What NOT to put in the key

- **Structural paths reconstructed from DOM** (e.g. `enc_1.tis_I.cpt_1.art_5`).
  EUR-Lex's EN HTML emits these from stable IDs; the LT HTML lacks the same IDs, so
  the LT extractor synthesises a shorter form. Two records that should pair will have
  different `structural_path` strings.
- **Article rubrics or section headings** ("Definitions" / "Terminų apibrėžtys" /
  "Définitions"). These translate.
- **Term text itself** ("customs authorities" / "muitinė"). Terms translate by
  definition; using them in the key defeats grouping.
- **Footnote IDs, amendment marker text, or any field that exists for provenance
  tracking.** These are stored alongside the record but never compared.

### Verification before committing

After configuring the writer for a new domain, run the writer on at least two language
versions of the same source and check:

```bash
sqlite3 <domain>.db "SELECT COUNT(*) FROM mwe;"
sqlite3 <domain>.db "SELECT COUNT(*) FROM mwe_lang;"
sqlite3 <domain>.db \
  "SELECT mwe_id, COUNT(DISTINCT lang) FROM mwe_lang GROUP BY mwe_id;"
```

The expected pattern: `mwe` count equals the per-language record count, `mwe_lang`
count equals the per-language count times the number of languages, and every `mwe_id`
has exactly as many distinct languages as you loaded. Any deviation indicates a key
mismatch — usually a field that differs across languages when it should not.

### History note

This guidance is the lesson from the UCC EUR-Lex onboarding: the initial writer used
`structural_path` in the key, which differed between EN and LT because LT's HTML lacks
the corresponding stable DOM IDs. The writer produced 82 `mwe` rows instead of 41,
with each language's records orphaned in their own concepts. See
`tests/test_domain_db_writer.py::test_eurlex_records_group_by_list_path_across_languages`
for the regression test that prevents recurrence.

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
