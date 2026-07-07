#!/usr/bin/env python3
"""Phase D — gated, insert-only merge of the approved gap-fill set into lexicon_v2.db.

Consumes the Phase-C-approved artifacts and authors new concepts. Insert-only,
except the single approved ``number`` tier demotion. Backs up the DB and runs
inside one transaction; ``--dry-run`` rolls back and reports without writing.

Approved inputs (``data/analysis/gapfill/``):
  * ``accepts_clean.tsv``            — TinyStories accepts (source=tinystories_gap_v1)
  * ``tier_triage_rare_triaged.tsv`` — tail overrides: ``drop`` removes a row; ``keep``
                                        carries ``final_tier``
  * ``set_gaps_triaged.tsv``         — systematic-set additions (source=set_completeness_v1);
                                        ``fix`` rows carry ``corrected_eo_word``

Reconciliation:
  * drop rows flagged ``drop`` in the tail triage (``beachs``);
  * set-gaps are authoritative — a plain accept whose word is also a set-gap member is
    skipped (seed tier wins); sense-split accepts (``lemma#sense``) are each authored as
    their own concept and are never skipped;
  * skip anything whose English word already resolves in the lexicon (idempotent).

The ``number`` change (concept 2694): tier 3→1, anchor filled to ``nombr``/``nombro``,
``cefr_level`` left untouched (Ramunas ruling).
"""

from __future__ import annotations

import argparse
import csv
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

NUMBER_CONCEPT_ID = 2694
NUMBER_ANCHOR = ("nombr", "nombro", "NOUN")

_POS_BY_ENDING = {"o": "NOUN", "a": "ADJ", "i": "VERB", "e": "ADV"}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def derive_pos(eo_word: str) -> str:
    """Map a dictionary-form Esperanto word to a coarse POS by its ending."""
    return _POS_BY_ENDING.get(eo_word[-1:], "X") if eo_word else "X"


def tier_to_cefr(tier: int) -> str:
    return {1: "A1", 2: "A2", 3: "C1"}.get(tier, "")


# ---------------------------------------------------------------------------
# Reconciliation (pure)
# ---------------------------------------------------------------------------


def reconcile(
    accepts: list[dict], rare: list[dict], set_gaps: list[dict], existing_en: set[str]
) -> list[dict]:
    """Return the ordered list of concepts to author.

    Each row: ``{en_word, eo_word, eo_root, tier, source, key}``. ``key`` is the
    full sense-split lemma (for logging); ``en_word`` is the base before ``#``.
    """
    drops = {r["en_lemma"] for r in rare if r["decision"].strip().lower() == "drop"}
    rare_tier = {
        r["en_lemma"]: r["final_tier"].strip()
        for r in rare
        if r["decision"].strip().lower() == "keep" and r["final_tier"].strip()
    }

    # Set-gaps first (authoritative). ``fix`` rows use the corrected anchor.
    sg_rows: list[dict] = []
    sg_words: set[str] = set()
    for r in set_gaps:
        if r["decision"].strip().lower() not in ("ok", "fix"):
            continue
        member = r["member_en"].strip().lower()
        corrected = (r.get("corrected_eo_word") or "").strip()
        anchor = r.get("proposed_eo_anchor") or ""  # "root/word"
        a_root, _, a_word = anchor.partition("/")
        eo_word = corrected or a_word or a_root
        if not eo_word or member in existing_en:
            continue
        sg_words.add(member)
        sg_rows.append(
            {
                "en_word": member, "eo_word": eo_word,
                "eo_root": a_root or "", "tier": int(r["proposed_tier"]),
                "source": "set_completeness_v1", "key": member,
            }
        )

    acc_rows: list[dict] = []
    for r in accepts:
        key = r["en_lemma"]
        if key in drops:
            continue
        base = key.split("#", 1)[0].strip().lower()
        is_split = "#" in key
        if base in existing_en:
            continue
        if not is_split and base in sg_words:
            continue  # set-gap (seed tier) wins for plain overlaps
        eo_word = (r.get("final_eo_word") or "").strip()
        if not eo_word:
            continue
        tier = int(rare_tier.get(key, r["proposed_tier"]))
        acc_rows.append(
            {
                "en_word": base, "eo_word": eo_word,
                "eo_root": (r.get("final_eo_root") or "").strip(),
                "tier": tier, "source": "tinystories_gap_v1", "key": key,
            }
        )
    return sg_rows + acc_rows


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def _roots_for(eo_word: str, fallback_root: str, decomposer) -> list[tuple[str, str | None]]:
    """Return ``[(root, inventory_tier), ...]`` for *eo_word* (head last)."""
    dec = decomposer.decompose_word(eo_word)
    roots = [cr.root for cr in dec.content_roots] if dec.content_roots else []
    if not roots:
        roots = [fallback_root or eo_word]
    return [(r, decomposer.root_tier(r)) for r in roots]


def _already_authored(conn: sqlite3.Connection, en_word: str, eo_word: str) -> bool:
    row = conn.execute(
        """SELECT 1 FROM concept_lang cl JOIN concept c ON c.id = cl.concept_id
           WHERE cl.lang='en' AND LOWER(cl.word)=? AND c.eo_word=? LIMIT 1""",
        (en_word.lower(), eo_word),
    ).fetchone()
    return row is not None


def author_concept(conn: sqlite3.Connection, row: dict, decomposer) -> bool:
    """Insert one concept (+concept_lang +concept_root). Return False if skipped."""
    if _already_authored(conn, row["en_word"], row["eo_word"]):
        return False
    pos = derive_pos(row["eo_word"])
    roots = _roots_for(row["eo_word"], row["eo_root"], decomposer)
    head_root = roots[-1][0]
    # Lexicon convention (0 exceptions in the base DB): concept.eo_root == the
    # concept_root head root. Deriving it from the decomposition keeps that
    # invariant and side-steps stale/curated roots that disagree with eo_word.
    cur = conn.execute(
        "INSERT INTO concept (eo_root, eo_word, eo_pos, eo_status) VALUES (?,?,?,'complete')",
        (head_root, row["eo_word"], pos),
    )
    cid = cur.lastrowid
    conn.execute(
        """INSERT INTO concept_lang (concept_id, lang, word, pos, cefr_level, tier, source)
           VALUES (?, 'en', ?, ?, ?, ?, ?)""",
        (cid, row["en_word"], pos, tier_to_cefr(row["tier"]), row["tier"], row["source"]),
    )
    for pos_i, (root, rtier) in enumerate(roots):
        conn.execute(
            "INSERT INTO concept_root (concept_id, root, position, is_head, tier) VALUES (?,?,?,?,?)",
            (cid, root, pos_i, 1 if pos_i == len(roots) - 1 else 0, rtier),
        )
    return True


def apply_number(conn: sqlite3.Connection, decomposer) -> dict:
    """Apply the approved `number` change: tier 3→1 + anchor; cefr untouched."""
    root, word, pos = NUMBER_ANCHOR
    conn.execute(
        "UPDATE concept_lang SET tier=1 WHERE concept_id=? AND lang='en' AND LOWER(word)='number'",
        (NUMBER_CONCEPT_ID,),
    )
    conn.execute(
        "UPDATE concept SET eo_root=?, eo_word=?, eo_pos=?, eo_status='complete' WHERE id=?",
        (root, word, pos, NUMBER_CONCEPT_ID),
    )
    exists = conn.execute(
        "SELECT 1 FROM concept_root WHERE concept_id=? LIMIT 1", (NUMBER_CONCEPT_ID,)
    ).fetchone()
    if not exists:
        conn.execute(
            "INSERT INTO concept_root (concept_id, root, position, is_head, tier) VALUES (?,?,0,1,?)",
            (NUMBER_CONCEPT_ID, root, decomposer.root_tier(root)),
        )
    return {"tier": "3->1", "anchor": f"{root}/{word}"}


def _load_tsv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def main(argv: list[str] | None = None) -> None:
    root = _repo_root()
    gf = root / "data" / "analysis" / "gapfill"
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--lexicon", type=Path, default=root / "data" / "lexicon_db" / "lexicon_v2.db")
    ap.add_argument("--inventory", type=Path, default=root / "data" / "lexicon_db" / "eo_inventory.json")
    ap.add_argument("--gapfill", type=Path, default=gf)
    ap.add_argument("--dry-run", action="store_true", help="reconcile + insert then ROLLBACK")
    args = ap.parse_args(argv)

    sys.path.insert(0, str(root / "src" / "lexicon"))
    from eo_root_decomposer import Decomposer, load_inventory  # noqa: E402

    decomposer = Decomposer(load_inventory(args.inventory))
    accepts = _load_tsv(args.gapfill / "accepts_clean.tsv")
    rare = _load_tsv(args.gapfill / "tier_triage_rare_triaged.tsv")
    set_gaps = _load_tsv(args.gapfill / "set_gaps_triaged.tsv")

    conn = sqlite3.connect(args.lexicon)
    existing_en = {x[0].lower() for x in conn.execute("SELECT word FROM concept_lang WHERE lang='en'")}
    plan = reconcile(accepts, rare, set_gaps, existing_en)

    if not args.dry_run:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = args.lexicon.with_suffix(f".db.bak-{stamp}")
        shutil.copy2(args.lexicon, backup)
        print(f"backup: {backup}")

    before = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t in ("concept", "concept_lang", "concept_root")}
    conn.execute("BEGIN")
    authored = skipped = 0
    by_source: dict[str, int] = {}
    by_tier: dict[int, int] = {}
    for r in plan:
        if author_concept(conn, r, decomposer):
            authored += 1
            by_source[r["source"]] = by_source.get(r["source"], 0) + 1
            by_tier[r["tier"]] = by_tier.get(r["tier"], 0) + 1
        else:
            skipped += 1
    num = apply_number(conn, decomposer)

    after = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
             for t in ("concept", "concept_lang", "concept_root")}

    print(f"plan rows          : {len(plan)}")
    print(f"authored (new)     : {authored}   skipped (already present): {skipped}")
    print(f"  by source        : {by_source}")
    print(f"  by tier          : {dict(sorted(by_tier.items()))}")
    print(f"number change      : {num}")
    print(f"row deltas         : " + ", ".join(
        f"{t} {before[t]}->{after[t]} (+{after[t]-before[t]})" for t in before))

    if args.dry_run:
        conn.execute("ROLLBACK")
        print("DRY-RUN — rolled back, no changes written.")
    else:
        conn.commit()
        print("COMMITTED.")
    conn.close()


if __name__ == "__main__":
    main()
