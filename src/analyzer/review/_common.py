"""Shared logic for the gap-fill review harness (pure, testable functions).

The CLI scripts (``review_context``, ``review_record``, ``review_merge``,
``export_snapshot``, ``set_completeness``) are thin wrappers over the helpers
here. Nothing in this module writes to ``lexicon_v2.db`` or the reviewer's live
``.xlsx``.
"""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

# --- repo-relative default paths -------------------------------------------


def repo_root() -> Path:
    """Return the repository root (three levels up from this file)."""
    return Path(__file__).resolve().parents[3]


def default_paths() -> dict[str, Path]:
    """Canonical file locations the harness reads/writes."""
    root = repo_root()
    gapfill = root / "data" / "analysis" / "gapfill"
    return {
        "gapfill": gapfill,
        "xlsx": gapfill / "gapfill_review.xlsx",
        "snapshot": gapfill / "worksheet_export.tsv",
        "decisions": gapfill / "review_decisions.tsv",
        "reviewed": gapfill / "gapfill_review.reviewed.xlsx",
        "set_gaps": gapfill / "set_gaps.tsv",
        "triaged": root / "data" / "analysis" / "tinystories_unknown_triaged.tsv",
        "espdic": root / "data" / "lexicon_db" / "espdic.txt",
        "lexicon": root / "data" / "lexicon_db" / "lexicon_v2.db",
        "inventory": root / "data" / "lexicon_db" / "eo_inventory.json",
        "chunks": Path(
            "~/projects/esperanto-lexicon-corpus/tinystories/stories"
        ).expanduser(),
    }


# --- decisions sidecar TSV -------------------------------------------------

DECISION_FIELDS = [
    "en_lemma",
    "decision",  # accept | reject | hold | postpone
    "note",
    "eo_root_override",
    "eo_word_override",
    "source",  # human | auto
    "reason",
    "ts",
]
VALID_DECISIONS = {"accept", "reject", "hold", "postpone"}


def load_decisions(path: Path) -> dict[str, dict[str, str]]:
    """Return ``{en_lemma: last_decision_row}`` (last write per lemma wins)."""
    if not path.exists():
        return {}
    out: dict[str, dict[str, str]] = {}
    with path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            out[row["en_lemma"]] = row  # later rows overwrite earlier
    return out


def append_decision(path: Path, row: dict[str, str]) -> None:
    """Append one decision row, writing the header if the file is new."""
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with path.open("a", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=DECISION_FIELDS, delimiter="\t")
        if new:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in DECISION_FIELDS})


# --- surface forms + name signal (from the triaged TSV) --------------------


def load_surface_map(triaged_path: Path) -> dict[str, list[dict[str, object]]]:
    """Map ``lemma -> [{token, freq, is_propn, caps_majority}, ...]``.

    Built from ``tinystories_unknown_triaged.tsv`` so the harness can grep the
    real surface tokens (``hugged``) for a lemma (``hug``), and reuse the
    per-token case/PROPN signals already computed by the triage.
    """
    out: dict[str, list[dict[str, object]]] = {}
    if not triaged_path.exists():
        return out
    with triaged_path.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh, delimiter="\t"):
            lemma = (r.get("lemma") or r["token"]).strip().lower()
            out.setdefault(lemma, []).append(
                {
                    "token": r["token"],
                    "freq": int(r["frequency"]),
                    "is_propn": r.get("is_propn") == "1",
                    "caps_majority": r.get("caps_majority") == "1",
                }
            )
    return out


def name_signal(surfaces: list[dict[str, object]]) -> dict[str, object]:
    """Summarise name-vs-common evidence for a lemma's surface tokens.

    Returns ``caps_majority`` (freq-weighted share of occurrences whose token is
    majority-capitalised), ``ever_propn`` (spaCy ever tagged it PROPN), and
    ``lowercase_common_freq`` (occurrences of tokens used lowercase — evidence of
    genuine common-noun use).
    """
    total = sum(int(s["freq"]) for s in surfaces) or 1
    caps = sum(int(s["freq"]) for s in surfaces if s["caps_majority"])
    lower = sum(int(s["freq"]) for s in surfaces if not s["caps_majority"])
    return {
        "caps_majority": caps / total,
        "ever_propn": any(bool(s["is_propn"]) for s in surfaces),
        "lowercase_common_freq": lower,
        "total_freq": total,
    }


# --- corpus usage ----------------------------------------------------------

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")


def read_corpus(chunks_dir: Path) -> str:
    """Concatenate every ``chunk*.txt`` (single newline-joined blob)."""
    if not chunks_dir.exists():
        return ""
    parts = [p.read_text(encoding="utf-8") for p in sorted(chunks_dir.glob("chunk*.txt"))]
    return "\n".join(parts)


def _word_re(tokens: list[str]) -> re.Pattern[str]:
    alt = "|".join(re.escape(t) for t in sorted(set(tokens), key=len, reverse=True))
    return re.compile(rf"\b(?:{alt})\b", re.IGNORECASE)


def matching_sentences(text: str, tokens: list[str]) -> list[str]:
    """Return de-duplicated sentences containing any of *tokens* as whole words."""
    if not tokens or not text:
        return []
    pat = _word_re(tokens)
    seen: set[str] = set()
    out: list[str] = []
    for line in text.split("\n"):
        for sent in _SENT_SPLIT.split(line.strip()):
            s = sent.strip()
            if s and s not in seen and pat.search(s):
                seen.add(s)
                out.append(s)
    return out


def select_diverse(sentences: list[str], tokens: list[str], k: int = 6) -> list[str]:
    """Greedily pick up to *k* sentences that maximise lexical diversity.

    Prefers sentences whose surrounding words are new relative to those already
    chosen, so distinct senses (polysemy) surface instead of k near-duplicates.
    """
    if len(sentences) <= k:
        return sentences
    target = {t.lower() for t in tokens}

    def content(s: str) -> set[str]:
        return {w for w in re.findall(r"[a-z']+", s.lower()) if w not in target}

    chosen: list[str] = [sentences[0]]
    seen_words: set[str] = content(sentences[0])
    pool = sentences[1:]
    while len(chosen) < k and pool:
        best = max(pool, key=lambda s: len(content(s) - seen_words))
        chosen.append(best)
        seen_words |= content(best)
        pool.remove(best)
    return chosen


# --- Esperanto anchor round-trip -------------------------------------------


def roundtrip_glosses(eo_word: str, forward_gloss: dict[str, str]) -> list[str]:
    """Return the ESPDIC English senses of *eo_word* (empty if unknown)."""
    raw = forward_gloss.get(eo_word, "")
    if not raw:
        return []
    senses = []
    for part in re.split(r"[,;]", raw):
        s = re.sub(r"\(.*?\)", "", part).strip().lower()
        s = re.sub(r"^(to|a|an|the)\s+", "", s).strip()
        if s:
            senses.append(s)
    return senses


def roundtrip_matches(lemma: str, glosses: list[str], limit: int | None = None) -> bool:
    """True iff the English *lemma* appears among the round-trip glosses.

    Confirms the proposed Esperanto anchor actually means the English word
    (``brakumi`` -> "to embrace, hug" contains "hug" → match). With *limit*,
    only the first *limit* glosses are considered — used to tell a *primary*
    sense (``lageto`` -> "pond") from a buried, secondary one (``miso`` ->
    "evil, fault, foul, bug", where "bug" is the wrong, 4th sense).
    """
    l = lemma.lower()
    pool = glosses[:limit] if limit is not None else glosses
    return any(l == g or l in g.split() for g in pool)


# --- recommendation --------------------------------------------------------


def recommend(
    row: dict[str, str],
    sig: dict[str, object],
    glosses: list[str],
    alt_glosses: dict[str, list[str]],
    corpus_count: int,
) -> tuple[str, str]:
    """Return ``(verdict, reason)`` — ``ACCEPT`` / ``REJECT(name)`` / ``ASK(...)``.

    Conservative by design: only clean, unambiguous rows earn ACCEPT; every
    name-ambiguous or sense-uncertain row becomes ASK so the human decides.
    ``alt_glosses`` maps each alternative Esperanto candidate to its ESPDIC
    senses — used to catch polysemy (a better-fitting alternative exists) and
    wrong-sense picks (the lemma is only a buried, secondary gloss).
    """
    lemma = row.get("en_lemma", "").lower()
    priority = row.get("priority", "")
    flag = row.get("flag", "")
    action = row.get("action", "")
    caps = float(sig.get("caps_majority", 0.0))
    lower_freq = int(sig.get("lowercase_common_freq", 0))

    # No anchor at all -> always a question.
    if flag == "no_match" or action not in {"LINK", "NEW"} or not row.get("eo_root"):
        return "ASK", "no_match — needs a manual Esperanto anchor"

    name_band = priority.startswith("P1_name")
    strongly_name = caps >= 0.95 and lower_freq == 0
    name_ambiguous = name_band and not (caps < 0.5 and lower_freq > 0)

    # Unambiguous proper name: recommend rejecting, but P1 is never auto-applied
    # (protocol item 6) — the caller surfaces it as ASK regardless.
    if strongly_name and name_band:
        return "REJECT(name)", f"caps-majority {caps:.0%}, never used lowercase"

    if name_ambiguous:
        return "ASK", f"name-or-word (caps {caps:.0%}, {lower_freq} lowercase uses)"

    if corpus_count == 0:
        return "ASK", "no corpus usage found to verify the sense"

    if flag == "compound":
        return "ASK", "compound — verify the component split"

    if not roundtrip_matches(lemma, glosses):
        gl = ", ".join(glosses[:4]) or "(no gloss)"
        return "ASK", f"round-trip gloss ({gl}) doesn't contain '{lemma}'"

    # Polysemy guard: a better-fitting alternative exists when some other
    # candidate carries the lemma as its PRIMARY sense while ours does not.
    ours_primary = roundtrip_matches(lemma, glosses, limit=2)
    better = [
        a for a, g in alt_glosses.items() if roundtrip_matches(lemma, g, limit=1)
    ]
    if better and not (ours_primary and roundtrip_matches(lemma, glosses, limit=1)):
        return "ASK", f"polysemy — '{lemma}' is the primary sense of {', '.join(better[:3])}"
    if not ours_primary:
        return "ASK", f"'{lemma}' is only a secondary sense of {row.get('eo_word','')}"

    return "ACCEPT", "valid anchor, round-trip matches the primary sense"


# --- misc ------------------------------------------------------------------


def add_repo_src_to_path() -> None:
    """Put ``src/lexicon`` on ``sys.path`` so we can reuse ``parse_espdic``."""
    root = repo_root()
    for sub in ("src/lexicon",):
        p = str(root / sub)
        if p not in sys.path:
            sys.path.insert(0, p)
