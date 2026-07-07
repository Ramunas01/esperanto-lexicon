# Academic Word List (AWL) — vendored source & provenance

`awl_coxhead.json` is a machine-readable rendering of the **Academic Word List
(AWL)**, Averil **Coxhead (2000)**, *A New Academic Word List*, TESOL Quarterly
34(2): 213–238. The AWL is 570 word families that occur with wide range and high
frequency across academic disciplines but are not in West's General Service List —
i.e. the domain-general formal core we want for Tier 3.

## Retrieval
- **Source URL:** https://raw.githubusercontent.com/lpmi-13/machine_readable_wordlists/master/Academic/AWL/AWL.json
- **Repository:** https://github.com/lpmi-13/machine_readable_wordlists (`Academic/AWL/`)
- **Upstream source stated by the repo:** Victoria University of Wellington AWL
  (Coxhead's canonical list), https://www.wgtn.ac.nz/lals/resources/academicwordlist
- **Retrieved:** 2026-07-08
- **Repo license:** CC0-1.0 (public-domain dedication) — free to vendor and redistribute.

## Structure (preserved — head + members + sublist)
```
{ "sublist_1": { "analyse": {"subwords": ["analysis","analytical", ...]}, ... },
  "sublist_2": { ... }, ... "sublist_10": { ... } }
```
Each of the 10 sublists (frequency bands, 1 = most frequent) maps family **head
words** to their **member forms** (`subwords`). A `null` `subwords` value means the
family has no additional members beyond the head (e.g. `despite`, `hence`,
`overall`) — legitimate, not corruption.

## Validation against the published AWL invariants (all PASS)
Checked before use (see `awl-source-invariants` memory / the memo):
- families: **570** ✓
- sublists: **10** (60×9 + 30 in sublist 10) ✓
- Sublist 1 families: **60** ✓
- distinct word forms: **3,107** (published "~3,000", low-3,000s) ✓
- no Academic Keyword List / GSL-exclusion contamination; heads are single lowercase
  tokens.

A source that does not reproduce these was to be rejected; this one does.
