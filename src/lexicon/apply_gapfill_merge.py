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


# ===========================================================================
# Tier-3 AWL family merge (Phase 4)
#
# Reuses this module's writer primitives (derive_pos, tier_to_cefr, the
# eo_root == concept_root head invariant) rather than forking a second writer.
# The AWL is merged under the LOCKED family model: a family = ONE concept
# carrying N EN concept_lang rows at tier=3, source='awl_t3', insert-only.
# ===========================================================================

AWL_SOURCE_TAG = "awl_t3"
AWL_TIER = 3

# Explicit single-root overrides where the greedy decomposer produces a wrong
# split on a borrowed/opaque root. Named in the Phase-4 hand-off (dinamika) plus
# one caught by the dry-run's single-letter-root guard (incidenco → incid+en+c).
AWL_ROOT_OVERRIDES: dict[str, tuple[str, ...]] = {
    "dinamika": ("dinamik",),   # decomposer split din+amik (would land on 'amik')
    "incidenco": ("incidenc",),  # decomposer split incid+en+c (head 'c')
}


def awl_final_eo_word(row: dict) -> str:
    """The reviewer-authoritative EO anchor: corrected_eo_word on a fix, else current."""
    if row.get("decision", "").strip() == "fix" and row.get("corrected_eo_word", "").strip():
        return row["corrected_eo_word"].strip()
    return (row.get("current_eo_word") or "").strip()


def awl_roots_for(eo_word: str, decomposer) -> tuple[list[tuple[str, str | None]], str]:
    """Return ``([(root, inv_tier), ...], method)`` for a NEW AWL concept.

    Holds the invariant by deriving the root chain from the decomposition (head
    last). Guards against the two failure modes seen in the data:
      * an explicit override for opaque loanroots the greedy splitter mangles;
      * a single-letter content root (a bad greedy split) → fall back to the
        flexion-stripped stem, and if that is still degenerate, the whole word.
    ``method`` is recorded for the audit trail.
    """
    if eo_word in AWL_ROOT_OVERRIDES:
        roots = list(AWL_ROOT_OVERRIDES[eo_word])
        return [(r, decomposer.root_tier(r)) for r in roots], "override"
    dec = decomposer.decompose_word(eo_word)
    roots = [cr.root for cr in dec.content_roots]
    if roots and all(len(r) >= 2 for r in roots):
        return [(r, decomposer.root_tier(r)) for r in roots], "decomposed"
    from eo_root_decomposer import strip_flexion  # local: pure helper

    stem = strip_flexion(eo_word)
    if len(stem) >= 2:
        return [(stem, decomposer.root_tier(stem))], "single-fallback"
    return [(eo_word, decomposer.root_tier(eo_word))], "whole-word"


def resolve_awl_family(
    conn: sqlite3.Connection, head: str, forms: list[str], eo_word: str
) -> tuple[str, int | None, str]:
    """Decide LINK (reuse a concept) vs NEW for a family. Returns (kind, cid, why).

    Priority: (1) a concept already carrying this EO word → that is the family's
    concept; (2) the concept carrying the EN **head** form (the family anchor);
    (3) a single concept carrying any member form; (4) if members span several
    concepts, LINK to the head's concept (or the lowest id) and mark ``AMBIG`` so
    the human can check; else (5) NEW.
    """
    row = conn.execute("SELECT id FROM concept WHERE eo_word=?", (eo_word,)).fetchone()
    if row:
        return "LINK", row[0], "eo_word"

    def concepts_for(word: str) -> set[int]:
        return {
            c for (c,) in conn.execute(
                "SELECT DISTINCT concept_id FROM concept_lang "
                "WHERE lang='en' AND LOWER(word)=?",
                (word.lower(),),
            )
        }

    head_cids = concepts_for(head)
    if len(head_cids) == 1:
        return "LINK", next(iter(head_cids)), "head_form"
    all_cids: set[int] = set()
    for f in forms:
        all_cids |= concepts_for(f)
    if len(all_cids) == 1:
        return "LINK", next(iter(all_cids)), "member_form"
    if len(all_cids) > 1:
        pick = min(head_cids) if head_cids else min(all_cids)
        return "LINK", pick, f"AMBIG:{sorted(all_cids)}"
    return "NEW", None, "new"


def _insert_awl_en_row(
    conn: sqlite3.Connection, cid: int, en_word: str, pos: str
) -> bool:
    """Insert one insert-only EN concept_lang row at tier=3/awl_t3. False if a dupe."""
    cur = conn.execute(
        """INSERT OR IGNORE INTO concept_lang
               (concept_id, lang, word, pos, cefr_level, tier, source)
           VALUES (?, 'en', ?, ?, ?, ?, ?)""",
        (cid, en_word, pos, tier_to_cefr(AWL_TIER), AWL_TIER, AWL_SOURCE_TAG),
    )
    return cur.rowcount > 0


def author_awl_family(
    conn: sqlite3.Connection,
    row: dict,
    forms: list[str],
    existing_en: set[str],
    decomposer,
    pos_tagger,
) -> dict:
    """Author one approved/fixed AWL family (insert-only). Returns a stats dict.

    LINK: attach the family's not-yet-present forms to the resolved concept. NEW:
    author one concept (eo_root from :func:`awl_roots_for`, holding the invariant)
    + its concept_root chain, then attach the forms. Multiword anchors (e.g.
    ``per kio``) do not fit the single-root concept model and are deferred.
    """
    head = row["family_head"].strip().lower()
    eo_word = awl_final_eo_word(row)
    out = {"head": head, "eo_word": eo_word, "kind": "", "why": "",
           "concept_id": None, "new_concept": 0, "rows": 0, "skipped": 0,
           "root_method": "", "deferred": ""}

    if not eo_word:
        out["deferred"] = "no_anchor"
        return out
    if " " in eo_word:  # multiword phrase anchor — needs a schema decision
        out["deferred"] = "multiword"
        return out

    kind, cid, why = resolve_awl_family(conn, head, forms, eo_word)
    out["kind"], out["why"] = kind, why

    if kind == "NEW":
        roots, method = awl_roots_for(eo_word, decomposer)
        out["root_method"] = method
        head_root = roots[-1][0]
        eo_pos = derive_pos(eo_word)
        cur = conn.execute(
            "INSERT INTO concept (eo_root, eo_word, eo_pos, eo_status) "
            "VALUES (?,?,?,'complete')",
            (head_root, eo_word, eo_pos),
        )
        cid = cur.lastrowid
        out["new_concept"] = 1
        for pos_i, (root, rtier) in enumerate(roots):
            conn.execute(
                "INSERT INTO concept_root (concept_id, root, position, is_head, tier) "
                "VALUES (?,?,?,?,?)",
                (cid, root, pos_i, 1 if pos_i == len(roots) - 1 else 0, rtier),
            )
    out["concept_id"] = cid

    for form in forms:
        if form in existing_en:
            out["skipped"] += 1
            continue
        if _insert_awl_en_row(conn, cid, form, pos_tagger(form)):
            out["rows"] += 1
            existing_en.add(form)  # within-run guard against cross-family repeats
        else:
            out["skipped"] += 1
    return out


def audit_eo_root_invariant(
    conn: sqlite3.Connection, new_cids: set[int]
) -> dict:
    """Post-write audit: eo_root == concept_root head, and no degenerate roots.

    Returns counts of head-mismatches (total and among newly-authored concepts)
    and any single-letter head roots. The merge is only sound when the
    new-concept mismatch count is 0.
    """
    mismatches = conn.execute(
        """SELECT c.id FROM concept c
           JOIN concept_root cr ON cr.concept_id=c.id AND cr.is_head=1
           WHERE c.eo_root <> cr.root"""
    ).fetchall()
    mism_ids = {r[0] for r in mismatches}
    new_no_head = [
        cid for cid in new_cids
        if conn.execute(
            "SELECT 1 FROM concept_root WHERE concept_id=? AND is_head=1", (cid,)
        ).fetchone() is None
    ]
    # Degenerate (≤1-char) head roots. Only the NEWLY-authored ones gate the
    # merge; pre-existing ones are a legacy data quirk we must not touch (this
    # merge is insert-only) and are reported for context, not as a failure.
    degen = conn.execute(
        """SELECT c.id FROM concept c
           JOIN concept_root cr ON cr.concept_id=c.id AND cr.is_head=1
           WHERE LENGTH(cr.root) <= 1"""
    ).fetchall()
    degen_ids = {r[0] for r in degen}
    # No new dupes: (a) no eo_word carried by >1 concept among the new ones,
    # (b) no duplicate (concept_id, lang, word, pos) EN rows (UNIQUE-guarded).
    eoword_dupes = conn.execute(
        """SELECT eo_word, COUNT(*) c FROM concept
           WHERE eo_word IS NOT NULL GROUP BY eo_word HAVING c > 1"""
    ).fetchall()
    # Collisions the merge itself introduced: a NEW concept whose eo_word is
    # already carried by some other concept (should be 0 — resolve LINKs on an
    # eo_word match instead of authoring a duplicate).
    new_eoword_collisions = 0
    for cid in new_cids:
        w = conn.execute("SELECT eo_word FROM concept WHERE id=?", (cid,)).fetchone()
        if w and conn.execute(
            "SELECT COUNT(*) FROM concept WHERE eo_word=?", (w[0],)
        ).fetchone()[0] > 1:
            new_eoword_collisions += 1
    cl_dupes = conn.execute(
        """SELECT concept_id, lang, word, pos, COUNT(*) c FROM concept_lang
           GROUP BY concept_id, lang, word, pos HAVING c > 1"""
    ).fetchall()
    return {
        "head_mismatches_total": len(mism_ids),
        "head_mismatches_new": len(mism_ids & new_cids),
        "new_without_head_root": new_no_head,
        "degenerate_head_roots_new": sorted(degen_ids & new_cids),
        "degenerate_head_roots_preexisting": len(degen_ids - new_cids),
        "eo_word_dupe_groups": len(eoword_dupes),
        "new_eo_word_collisions": new_eoword_collisions,
        "concept_lang_dupe_rows": len(cl_dupes),
    }


def run_awl_merge(
    conn: sqlite3.Connection,
    triaged_path: Path,
    awl_json: Path,
    decomposer,
    pos_tagger,
) -> dict:
    """Reconcile + author the whole AWL triaged worksheet inside the open txn."""
    sys.path.insert(0, str(_repo_root() / "src" / "lexicon"))
    from build_awl_worksheet import load_awl_families  # noqa: E402

    families, _ = load_awl_families(awl_json)
    by_head = {f.head: f for f in families}
    triaged = _load_tsv(triaged_path)

    existing_en = {
        w.lower() for (w,) in conn.execute(
            "SELECT word FROM concept_lang WHERE lang='en'"
        )
    }
    new_cids: set[int] = set()
    results: list[dict] = []
    decisions: dict[str, int] = {}
    for row in triaged:
        decision = row.get("decision", "").strip()
        decisions[decision or "(blank)"] = decisions.get(decision or "(blank)", 0) + 1
        if decision not in ("approve", "fix"):
            continue
        head = row["family_head"].strip().lower()
        fam = by_head.get(head)
        forms = list(fam.forms) if fam else [head]
        res = author_awl_family(conn, row, forms, existing_en, decomposer, pos_tagger)
        if res["new_concept"]:
            new_cids.add(res["concept_id"])
        results.append(res)

    processed = [r for r in results if not r["deferred"]]
    return {
        "decisions": decisions,
        "families_processed": len(processed),
        "link": sum(1 for r in processed if r["kind"] == "LINK"),
        "new": sum(1 for r in processed if r["kind"] == "NEW"),
        "new_concepts": len(new_cids),
        "t3_rows": sum(r["rows"] for r in processed),
        "skipped_present": sum(r["skipped"] for r in processed),
        "deferred": [(r["head"], r["deferred"], r["eo_word"]) for r in results if r["deferred"]],
        "ambiguous": [(r["head"], r["why"]) for r in processed if r["why"].startswith("AMBIG")],
        "root_overrides": [
            (r["head"], r["eo_word"], r["root_method"])
            for r in processed if r["root_method"] in ("override", "single-fallback", "whole-word")
        ],
        "special_cases": {
            r["head"]: {"eo_word": r["eo_word"], "kind": r["kind"],
                        "concept_id": r["concept_id"], "why": r["why"],
                        "root_method": r["root_method"]}
            for r in processed if r["head"] in ("via", "dynamic")
        },
        "new_cids": new_cids,
    }


def _load_tsv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def _main_awl(args, decomposer) -> None:
    """Tier-3 AWL family merge: backup + single txn + audit; --dry-run rolls back."""
    if args.no_spacy:
        pos_tagger = _awl_pos_tagger(spacy=False)
    else:
        pos_tagger = _awl_pos_tagger(spacy=True)

    conn = sqlite3.connect(args.lexicon)
    if not args.dry_run:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = args.lexicon.with_suffix(f".db.bak-awl-{stamp}")
        shutil.copy2(args.lexicon, backup)
        print(f"backup: {backup}")

    before = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t in ("concept", "concept_lang", "concept_root")}
    t3_before = conn.execute(
        "SELECT COUNT(*) FROM concept_lang WHERE tier=3"
    ).fetchone()[0]

    conn.execute("BEGIN")
    rep = run_awl_merge(conn, args.awl_triaged, args.awl_json, decomposer, pos_tagger)
    audit = audit_eo_root_invariant(conn, rep["new_cids"])

    after = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
             for t in ("concept", "concept_lang", "concept_root")}
    t3_after = conn.execute(
        "SELECT COUNT(*) FROM concept_lang WHERE tier=3"
    ).fetchone()[0]

    print("=" * 66)
    print("Tier-3 AWL merge — DRY-RUN" if args.dry_run else "Tier-3 AWL merge")
    print("=" * 66)
    print(f"decisions              : {rep['decisions']}")
    print(f"families processed     : {rep['families_processed']}  "
          f"(LINK {rep['link']} / NEW {rep['new']})")
    print(f"NEW concepts           : {rep['new_concepts']}")
    print(f"T3 EN rows inserted    : {rep['t3_rows']}   "
          f"(source={AWL_SOURCE_TAG}, tier={AWL_TIER})")
    print(f"skipped already-present: {rep['skipped_present']}")
    print(f"deferred (not authored): {rep['deferred'] or 'none'}")
    print(f"row deltas             : " + ", ".join(
        f"{t} {before[t]}->{after[t]} (+{after[t]-before[t]})" for t in before))
    print(f"Tier-3 EN rows         : {t3_before} -> {t3_after} (+{t3_after-t3_before})")
    print("-" * 66)
    print("special cases:")
    for head, info in rep["special_cases"].items():
        print(f"  {head:8}: {info}")
    print(f"root overrides/fallbacks ({len(rep['root_overrides'])}):")
    for h, eo, m in rep["root_overrides"]:
        print(f"    {h:12} {eo:12} [{m}]")
    print(f"ambiguous multi-concept families ({len(rep['ambiguous'])}) — REVIEW:")
    for h, why in rep["ambiguous"]:
        print(f"    {h:12} {why}")
    print("-" * 66)
    print("POST-WRITE AUDIT (eo_root_decomposer invariant):")
    print(f"  eo_root↔head mismatches (new concepts): {audit['head_mismatches_new']}  "
          f"(total in DB: {audit['head_mismatches_total']})")
    print(f"  new concepts missing a head root      : {len(audit['new_without_head_root'])}")
    print(f"  degenerate (≤1-char) head roots (new) : {len(audit['degenerate_head_roots_new'])}"
          f"   (pre-existing, untouched: {audit['degenerate_head_roots_preexisting']})")
    print(f"  concept_lang duplicate rows           : {audit['concept_lang_dupe_rows']}")
    print(f"  NEW-concept eo_word collisions        : {audit['new_eo_word_collisions']}")
    print(f"  eo_word shared by >1 concept (groups) : {audit['eo_word_dupe_groups']}  "
          f"(informational — pre-existing derived-word homonyms are normal)")
    ok = (audit["head_mismatches_new"] == 0
          and not audit["new_without_head_root"]
          and not audit["degenerate_head_roots_new"]
          and audit["concept_lang_dupe_rows"] == 0
          and audit["new_eo_word_collisions"] == 0)
    print(f"  AUDIT: {'PASS ✓' if ok else 'FAIL ✗'}")

    if args.dry_run:
        conn.execute("ROLLBACK")
        print("\nDRY-RUN — rolled back, no changes written. Awaiting sign-off for the gated commit.")
    else:
        if not ok:
            conn.execute("ROLLBACK")
            print("\nAUDIT FAILED — rolled back, nothing written.")
        else:
            conn.commit()
            print("\nCOMMITTED.")
    conn.close()


def _awl_pos_tagger(spacy: bool):
    """Build the English POS tagger for AWL rows (shared with the worksheet)."""
    sys.path.insert(0, str(_repo_root() / "src" / "lexicon"))
    if spacy:
        from build_awl_worksheet import load_spacy_tagger
        return load_spacy_tagger()
    from build_awl_worksheet import make_pos_tagger
    return make_pos_tagger(None)


def main(argv: list[str] | None = None) -> None:
    root = _repo_root()
    gf = root / "data" / "analysis" / "gapfill"
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--lexicon", type=Path, default=root / "data" / "lexicon_db" / "lexicon_v2.db")
    ap.add_argument("--inventory", type=Path, default=root / "data" / "lexicon_db" / "eo_inventory.json")
    ap.add_argument("--gapfill", type=Path, default=gf)
    ap.add_argument("--dry-run", action="store_true", help="reconcile + insert then ROLLBACK")
    ap.add_argument("--awl-triaged", type=Path, default=None,
                    help="run the Tier-3 AWL family merge from this triaged worksheet")
    ap.add_argument("--awl-json", type=Path,
                    default=root / "data" / "awl" / "awl_coxhead.json")
    ap.add_argument("--no-spacy", action="store_true",
                    help="AWL: morphology-only POS (skip spaCy fallback)")
    args = ap.parse_args(argv)

    sys.path.insert(0, str(root / "src" / "lexicon"))
    from eo_root_decomposer import Decomposer, load_inventory  # noqa: E402

    decomposer = Decomposer(load_inventory(args.inventory))

    if args.awl_triaged is not None:
        return _main_awl(args, decomposer)
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
