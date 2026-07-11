#!/usr/bin/env python3
"""British-spelling fold — insert-only ``inflected_forms`` normalization.

Closes the one real leak the cross-corpus UNKNOWN inventory (PR #12) found: the
British/Commonwealth spelling cluster whose **US form already exists as a concept**.
Pure normalization — no new vocabulary, no Esperanto anchoring, no sense review.

Mechanism (LOCKED by the PM): each British surface form gets an insert-only
``inflected_forms`` row ``(inflected_word=<british>, lemma=<us concept word>,
lang='en', form_description='british_spelling', tier=<us concept's tier>)``. The
resolver (``coverage_report.classify_tokens`` via ``load_inflected_forms``) already
maps surface->lemma->tier before falling back to UNKNOWN, so the British surface
resolves to the existing US concept. **The existing US ``concept``/``concept_lang``
rows are never edited or duplicated.**

Data-driven + guarded (no hand-listed pairs):
  * iterate the committed inventory ``pooled_unknown_classified.tsv`` (buckets
    ``local``/``common_gap``/``true_residual``),
  * fold each token with the extended ``build_gapfill_worksheet.uk_to_us``,
  * reduce the folded US form to its concept **lemma** (the lexicon stores base
    forms: ``colours``->``colors``->``color``), and
  * emit a row **only when that lemma is an existing en ``concept_lang`` word**.
This guard covers British inflections directly and rejects junk/typos
(``suprised``->``suprized`` has no US concept -> skipped). British tokens whose US
form is genuinely absent (``fertiliser``->``fertilizer``) are reported as
``us_form_absent`` gaps, never forced.

Read-only on ``concept``/``concept_lang``; insert-only on ``inflected_forms`` with
backup + single transaction + post-write audit. ``--dry-run`` (default) writes only
the review TSV; ``--commit`` writes the DB.
"""

from __future__ import annotations

import argparse
import csv
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_gapfill_worksheet import uk_to_us  # noqa: E402

FORM_DESCRIPTION = "british_spelling"
INVENTORY_BUCKETS = ("local", "common_gap", "true_residual")

# Inflectional de-inflection only (the folded US surface may be a plural/past that
# the lexicon stores in base form): colors->color, colored->color, colouring->color.
_DEINFLECT = (("ies", "y"), ("ied", "y"), ("es", ""), ("ed", ""), ("ing", ""), ("s", ""))


def deinflect_candidates(word: str) -> list[str]:
    out: list[str] = []
    for suf, rep in _DEINFLECT:
        if word.endswith(suf) and len(word) - len(suf) >= 2:
            out.append(word[: -len(suf)] + rep)
    return out


def load_en_word_tiers(conn: sqlite3.Connection) -> dict[str, list[int]]:
    """Map each lowercased en ``concept_lang.word`` to its sorted distinct tiers."""
    tiers: dict[str, set[int]] = {}
    for word, tier in conn.execute(
        "SELECT LOWER(word), tier FROM concept_lang WHERE lang='en'"
    ):
        tiers.setdefault(word, set()).add(tier if tier is not None else -1)
    return {w: sorted(t) for w, t in tiers.items()}


def resolve_us_lemma(us_fold: str, en_tiers: dict[str, list[int]]) -> str | None:
    """Return the concept lemma for a folded US form, or ``None`` if none exists.

    The fold itself if it is a concept word (``color``); else its de-inflected base
    (``colors``->``color``). This is the guard: no concept lemma -> not emitted.
    """
    if us_fold in en_tiers:
        return us_fold
    for cand in deinflect_candidates(us_fold):
        if cand in en_tiers:
            return cand
    return None


def _pick_tier(tiers: list[int]) -> int | None:
    """Lowest real tier of the US concept (resolver checks T1 before T2); None if only NULL."""
    real = [t for t in tiers if t is not None and t >= 0]
    return min(real) if real else None


def read_inventory_tokens(path: Path) -> list[tuple[str, int, str]]:
    """Return ``(token, total_count, bucket)`` for the residual-ish buckets."""
    out: list[tuple[str, int, str]] = []
    with path.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh, delimiter="\t"):
            if r["bucket"] in INVENTORY_BUCKETS:
                out.append((r["token"].strip().lower(),
                            int(r["total_count"]), r["bucket"]))
    return out


def generate_folds(
    tokens: list[tuple[str, int, str]], en_tiers: dict[str, list[int]]
) -> tuple[list[dict], list[dict]]:
    """Split British-looking tokens into (folds-with-US-concept, us_form_absent)."""
    folds: list[dict] = []
    absent: list[dict] = []
    for token, count, bucket in tokens:
        us_fold = uk_to_us(token)
        if us_fold == token:
            continue  # not British-looking (no fold applied)
        lemma = resolve_us_lemma(us_fold, en_tiers)
        if lemma is None:
            absent.append({"uk_form": token, "us_form": us_fold,
                           "total_freq": count, "tier": "", "us_in_lexicon": 0,
                           "bucket": bucket})
            continue
        folds.append({"uk_form": token, "us_form": lemma, "total_freq": count,
                      "tier": _pick_tier(en_tiers[lemma]), "us_in_lexicon": 1,
                      "bucket": bucket})
    folds.sort(key=lambda d: (-d["total_freq"], d["uk_form"]))
    absent.sort(key=lambda d: (-d["total_freq"], d["uk_form"]))
    return folds, absent


def write_folds_tsv(folds: list[dict], absent: list[dict], path: Path) -> None:
    """Write the review TSV (folded pairs first, then us_form_absent gaps)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = ["uk_form", "us_form", "total_freq", "tier", "us_in_lexicon", "bucket"]
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow(cols)
        for d in folds + absent:
            w.writerow([d["uk_form"], d["us_form"], d["total_freq"],
                        d["tier"] if d["tier"] != "" and d["tier"] is not None else "",
                        d["us_in_lexicon"], d["bucket"]])


def apply_folds(conn: sqlite3.Connection, folds: list[dict]) -> dict:
    """Insert-only ``inflected_forms`` rows for each fold. Returns stats."""
    inserted = skipped = 0
    for d in folds:
        before = conn.total_changes  # reliable across INSERT OR IGNORE conflicts
        conn.execute(
            """INSERT OR IGNORE INTO inflected_forms
                   (inflected_word, lemma, lang, form_description, tier)
               VALUES (?, ?, 'en', ?, ?)""",
            (d["uk_form"], d["us_form"], FORM_DESCRIPTION, d["tier"]),
        )
        if conn.total_changes > before:
            inserted += 1
        else:
            skipped += 1
    return {"inserted": inserted, "skipped": skipped}


def audit(conn: sqlite3.Connection, before: dict) -> dict:
    """Post-write audit: concept/concept_lang untouched; no dup inflected_forms."""
    after = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
             for t in ("concept", "concept_lang", "inflected_forms")}
    dupes = conn.execute(
        """SELECT inflected_word, lemma, lang, COUNT(*) c FROM inflected_forms
           GROUP BY inflected_word, lemma, lang HAVING c > 1"""
    ).fetchall()
    return {
        "concept_unchanged": before["concept"] == after["concept"],
        "concept_lang_unchanged": before["concept_lang"] == after["concept_lang"],
        "inflected_before": before["inflected_forms"],
        "inflected_after": after["inflected_forms"],
        "dupe_rows": len(dupes),
    }


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parents[2]
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--lexicon", type=Path, default=root / "data" / "lexicon_db" / "lexicon_v2.db")
    ap.add_argument("--inventory", type=Path,
                    default=root / "data" / "analysis" / "unknown_inventory" / "pooled_unknown_classified.tsv")
    ap.add_argument("--out", type=Path,
                    default=root / "data" / "analysis" / "uk_spelling" / "british_folds.tsv")
    ap.add_argument("--commit", action="store_true", help="write the DB (default: dry-run)")
    args = ap.parse_args(argv)

    conn = sqlite3.connect(args.lexicon)
    en_tiers = load_en_word_tiers(conn)
    tokens = read_inventory_tokens(args.inventory)
    folds, absent = generate_folds(tokens, en_tiers)
    write_folds_tsv(folds, absent, args.out)

    print(f"inventory tokens (local/common_gap/true_residual): {len(tokens)}")
    print(f"British folds (US concept present)  : {len(folds)}  "
          f"({sum(d['total_freq'] for d in folds)} tokens)")
    print(f"us_form_absent (genuine gaps)       : {len(absent)}")
    print(f"wrote review TSV -> {args.out}")
    print("\nfolds:")
    for d in folds:
        print(f"  {d['uk_form']:16} -> {d['us_form']:12} tier={d['tier']} n={d['total_freq']}")
    print("us_form_absent (NOT folded — report as 1-word gaps):")
    for d in absent:
        print(f"  {d['uk_form']:16} -> {d['us_form']:14} n={d['total_freq']} [{d['bucket']}]")

    before = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t in ("concept", "concept_lang", "inflected_forms")}
    if args.commit:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = args.lexicon.with_suffix(f".db.bak-ukfold-{stamp}")
        shutil.copy2(args.lexicon, backup)
        print(f"\nbackup: {backup}")
        conn.execute("BEGIN")
        stats = apply_folds(conn, folds)
        rep = audit(conn, before)
        ok = (rep["concept_unchanged"] and rep["concept_lang_unchanged"]
              and rep["dupe_rows"] == 0)
        print(f"inserted={stats['inserted']} skipped(existing)={stats['skipped']}")
        print(f"AUDIT: concept_unchanged={rep['concept_unchanged']} "
              f"concept_lang_unchanged={rep['concept_lang_unchanged']} "
              f"inflected {rep['inflected_before']}->{rep['inflected_after']} "
              f"dupes={rep['dupe_rows']} -> {'PASS' if ok else 'FAIL'}")
        if ok:
            conn.commit()
            print("COMMITTED.")
        else:
            conn.execute("ROLLBACK")
            print("AUDIT FAILED — rolled back, nothing written.")
    else:
        print("\nDRY-RUN — no DB changes. Re-run with --commit to write inflected_forms.")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
