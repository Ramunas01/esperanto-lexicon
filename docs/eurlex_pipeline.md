# EUR-Lex Ingestion Pipeline

This guide covers downloading EUR-Lex HTML for any EU regulation and running
the multi-language ingestion pipeline.

---

## Downloading EUR-Lex HTML

EUR-Lex publishes consolidated acts as structured HTML files.  The URL pattern is:

```
https://eur-lex.europa.eu/legal-content/{LANG}/TXT/HTML/?uri=CELEX:{celex}
```

Where:
- `{LANG}` is the two-letter language code: `EN`, `LT`, `DE`, `FR`, etc.
- `{celex}` is the CELEX identifier of the consolidated act.

**Example — Union Customs Code (UCC):**

```bash
# English
curl -o ucc_en.html \
  "https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX:02013R0952-20221212"

# Lithuanian
curl -o ucc_lt.html \
  "https://eur-lex.europa.eu/legal-content/LT/TXT/HTML/?uri=CELEX:02013R0952-20221212"
```

**Example — CBAM (Carbon Border Adjustment Mechanism):**

```bash
curl -o cbam_en.html \
  "https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX:02023R0956-20230516"

curl -o cbam_lt.html \
  "https://eur-lex.europa.eu/legal-content/LT/TXT/HTML/?uri=CELEX:02023R0956-20230516"
```

**Finding the CELEX identifier:**

1. Search for the regulation on [EUR-Lex](https://eur-lex.europa.eu/).
2. Navigate to the consolidated version (look for the clock icon — "Consolidated text").
3. The CELEX appears in the URL after `CELEX:`, e.g. `02013R0952-20221212`.
   - `0` prefix = consolidated act
   - `2013R0952` = Regulation 952/2013
   - `20221212` = consolidated as of 12 Dec 2022

---

## Directory layout and symlinks

Place raw HTML files in:

```
~/projects/esperanto-lexicon-corpus/customs/CBAM/raw/
```

Create symlinks with clean names:

```bash
cd ~/projects/esperanto-lexicon-corpus/customs/CBAM/raw/
ln -s cbam_en_downloaded.html cbam_en.html
ln -s cbam_lt_downloaded.html cbam_lt.html
```

The pipeline uses the symlinks so you can replace the underlying file
(e.g. when EUR-Lex publishes a new consolidation) without changing scripts.

---

## Running the pipeline

### Phase 1 — Extract definitions

```bash
python3 src/ingestion/ingest_eurlex.py \
    --input-en ~/projects/esperanto-lexicon-corpus/customs/CBAM/raw/cbam_en.html \
    --input-lt ~/projects/esperanto-lexicon-corpus/customs/CBAM/raw/cbam_lt.html \
    --celex 02023R0956-20230516 \
    --domain cbam \
    --jurisdiction EU \
    --db data/domain_db/cbam.db \
    --definitions-article 2 \
    --output-dir data/domain_db/
```

This produces:
- `data/domain_db/cbam_definitions_en.jsonl` — EN extracted definitions
- `data/domain_db/cbam_definitions_lt.jsonl` — LT extracted definitions
- `data/domain_db/cbam_definitions_combined.jsonl` — combined for review
- `data/domain_db/cbam_corpus_en.txt` — clean corpus text for stat detection
- `data/domain_db/cbam_corpus_lt.txt` — (if LT HTML provided)

### Review

```bash
python3 src/extractor/review_cli.py \
    --input data/domain_db/cbam_definitions_combined.jsonl \
    --lang en lt
```

Keyboard shortcuts: `[a]` approve both, `[r]` reject both, `[1]`/`[2]` approve one language only, `[s]` skip, `[q]` quit.

### Phase 2 — Commit to domain DB

```bash
python3 src/ingestion/ingest_eurlex.py --phase 2 \
    --celex 02023R0956-20230516 \
    --domain cbam \
    --jurisdiction EU \
    --db data/domain_db/cbam.db \
    --output-dir data/domain_db/ \
    --lexicon data/lexicon_db/lexicon_v2.db
```

Phase 2:
1. Writes approved records to `cbam.db` (EN and LT paired by list_path).
2. Runs statistical MWE detection on the corpus text files (if `--lexicon` provided).

---

## HTML layout variants

The extractor handles two structural layouts automatically via `detect_layout()`:

| Layout | Languages | Structure |
|--------|-----------|-----------|
| `divlayout` | English and most western EU languages | Definitions inside `<div class="eli-subdivision">` wrappers with grid-list sub-items |
| `tablelayout` | Lithuanian and some other translations | Definitions in `<table>` rows: `<td><p class="dlist-term">N)</p></td>` / `<td><p class="dlist-definition">…</p></td>` |

**No manual flag is needed.** `detect_layout()` inspects the HTML and selects
the correct parser path.  To debug:

```python
from extractor.extract_eurlex_definitions import EurLexExtractor, detect_layout
ext = EurLexExtractor("02023R0956-20230516", "lt")
soup = ext.parse_html(Path("cbam_lt.html"))
print(detect_layout(soup))   # 'tablelayout' or 'divlayout'
```

The key difference: `divlayout` is EN EUR-Lex convention; `tablelayout` appears
in LT (and potentially other languages) where the article HTML uses flat table
rows instead of `eli-subdivision` wrappers.

---

## Cross-language pairing

The writer groups EN and LT records by `(celex_id, article_number, list_path)`.
`structural_path` is excluded because it differs between language versions of
the same document (EN renders full chapter nesting; LT renders only the article
node ID).

Result: one `mwe` row per defined concept, with two `mwe_lang` rows (en + lt).

---

## Cross-domain conflict detection

After building two domain DBs (e.g. UCC and CBAM), check for shared terms with
diverging definitions:

```bash
python3 src/analyzer/conflict_report.py \
    --db       data/domain_db/cbam.db \
    --cross-db data/domain_db/ucc_customs.db \
    --lang     en
```

Example conflict: the UCC defines "customs authorities" as the administrations
of Member States; a hypothetical future regulation might define the term more
narrowly.  Cross-domain conflicts are flagged with `conflict_type='text_divergence'`
and `resolution_status='open'`.

---

## Statistical MWE detection (standalone)

Phase 2 runs the detector automatically, but you can also run it standalone
after Phase 1:

```bash
python3 src/extractor/statistical_mwe_detector.py \
    --input  data/domain_db/cbam_corpus_en.txt \
    --lang   en \
    --lexicon data/lexicon_db/lexicon_v2.db \
    --domain-db data/domain_db/cbam.db \
    --output data/domain_db/cbam_mwe_en.jsonl \
    --output-ne data/domain_db/cbam_ne_en.jsonl \
    --top-n 200
```

Review candidates with the quality report before approving:

```bash
python3 src/extractor/candidate_quality_report.py \
    --input data/domain_db/cbam_mwe_en.jsonl \
    --domain-db data/domain_db/cbam.db \
    --ne-file data/domain_db/cbam_ne_en.jsonl \
    --cross-db data/domain_db/ucc_customs.db
```
