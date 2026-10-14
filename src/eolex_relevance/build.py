"""Bundle builder — the compile-once half of build-once / score-many.

Run inside the lexicon repo, where ``lexicon_v2.db`` and ``eo_inventory.json``
are available. Produces a single portable ``.bundle`` that the runtime scorer
loads with no further dependencies.

What it compiles
----------------
1. **Resolver tables** — the word→root map for the requested language packs,
   read straight from ``concept_lang`` joined to ``concept_root`` (compounds
   contribute every root; concepts lacking a ``concept_root`` row fall back to
   ``concept.eo_root``), plus the full Esperanto inventory.
2. **Pedagogical tier map** — ``(lang, word) → (ped_tier, cefr_level)`` from
   ``concept_lang``. For Esperanto, synthesised via ``concept.eo_word`` join
   (minimum tier across associated languages).
3. **Domain vectors** — each domain spec is turned into a root-frequency map
   then into an IDF-weighted, L2-normalized vector. (Absent in lexicon-only
   bundles produced by :func:`build_lexicon_bundle`.)

Scoring math (exact)
--------------------
Given ``N`` domains with root-frequency maps ``f_i``::

    df(r)   = number of domains containing r
    idf(r)  = log((N + 1) / (df(r) + 1)) + 1
    w_i(r)  = (f_i(r) / Σ_r f_i(r)) * idf(r)      then L2-normalize w_i
"""

from __future__ import annotations

import datetime
import json
import math
import sqlite3
from collections import Counter
from pathlib import Path

import numpy as np

from eolex.bundle import Bundle
from eolex.resolver import Resolver

DEFAULT_DB_QUERY = "SELECT word FROM concept_lang WHERE lang = :lang"


# ---------------------------------------------------------------------------
# Resolver-table extraction
# ---------------------------------------------------------------------------


def load_inventory(inventory: str | Path) -> dict:
    with Path(inventory).open(encoding="utf-8") as fh:
        return json.load(fh)


def build_word_root_map(
    lexicon_db: str | Path, langs: list[str]
) -> dict[tuple[str, str], list[str]]:
    """Extract ``(lang, lowercased word) -> [roots]`` from the lexicon.

    Roots come from ``concept_root``; concepts with no ``concept_root`` rows
    fall back to ``concept.eo_root``. Only non-Esperanto packs are emitted —
    Esperanto is resolved by morphological decomposition.
    """
    pack_langs = [l for l in langs if l != "eo"]
    if not pack_langs:
        return {}

    conn = sqlite3.connect(str(lexicon_db))
    try:
        roots_by_concept: dict[int, list[str]] = {}
        for cid, root in conn.execute(
            "SELECT concept_id, root FROM concept_root ORDER BY concept_id, position"
        ):
            if root:
                roots_by_concept.setdefault(cid, []).append(root)

        eo_root_by_concept: dict[int, str] = {
            cid: root
            for cid, root in conn.execute(
                "SELECT id, eo_root FROM concept WHERE eo_root IS NOT NULL "
                "AND eo_root != ''"
            )
        }

        placeholders = ",".join("?" for _ in pack_langs)
        out: dict[tuple[str, str], set[str]] = {}
        for lang, word, cid in conn.execute(
            f"SELECT lang, word, concept_id FROM concept_lang "
            f"WHERE lang IN ({placeholders})",
            pack_langs,
        ):
            if not word:
                continue
            roots = roots_by_concept.get(cid)
            if not roots:
                fallback = eo_root_by_concept.get(cid)
                roots = [fallback] if fallback else []
            if not roots:
                continue
            key = (lang, word.strip().lower())
            out.setdefault(key, set()).update(roots)
    finally:
        conn.close()

    return {k: sorted(v) for k, v in out.items()}


def build_concept_lang_data(
    lexicon_db: str | Path, langs: list[str]
) -> dict[tuple[str, str], tuple[int | None, str | None]]:
    """Extract ``(lang, lowercased_word) -> (ped_tier, cefr_level)`` map.

    For non-Esperanto langs: read directly from ``concept_lang``, taking
    MIN(tier) and MIN(cefr_level) per word to deduplicate multi-sense entries.
    For Esperanto: synthesise from ``concept.eo_word`` joined to
    ``concept_lang``, taking the minimum tier across all associated languages.
    """
    conn = sqlite3.connect(str(lexicon_db))
    try:
        out: dict[tuple[str, str], tuple[int | None, str | None]] = {}

        pack_langs = [l for l in langs if l != "eo"]
        if pack_langs:
            placeholders = ",".join("?" for _ in pack_langs)
            for lang, word, tier, cefr in conn.execute(
                f"SELECT lang, word, MIN(tier), MIN(cefr_level) "
                f"FROM concept_lang "
                f"WHERE lang IN ({placeholders}) "
                f"AND tier IS NOT NULL AND word IS NOT NULL AND word != '' "
                f"GROUP BY lang, word",
                pack_langs,
            ):
                out[(lang, word.strip().lower())] = (tier, cefr)

        if "eo" in langs:
            for eo_word, tier, cefr in conn.execute(
                "SELECT c.eo_word, MIN(cl.tier), MIN(cl.cefr_level) "
                "FROM concept c "
                "JOIN concept_lang cl ON cl.concept_id = c.id "
                "WHERE cl.tier IS NOT NULL "
                "AND c.eo_word IS NOT NULL AND c.eo_word != '' "
                "GROUP BY c.id, c.eo_word"
            ):
                out[("eo", eo_word.strip().lower())] = (tier, cefr)

        return out
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Domain profile extraction
# ---------------------------------------------------------------------------


def _domain_terms(spec: dict, lexicon_db: str | Path) -> tuple[list[str], str]:
    source = spec.get("source")
    lang = spec.get("lang", "en")
    if source == "terms":
        return list(spec.get("terms", [])), lang
    if source == "corpus":
        text = Path(spec["path"]).read_text(encoding="utf-8")
        return [text], lang
    if source == "db":
        query = spec.get("query", DEFAULT_DB_QUERY)
        conn = sqlite3.connect(str(lexicon_db))
        try:
            rows = conn.execute(query, {"lang": lang}).fetchall()
        finally:
            conn.close()
        terms: list[str] = []
        for row in rows:
            if not row:
                continue
            terms.append(str(row[0]))
        return terms, lang
    raise ValueError(
        f"Unknown domain source {source!r} for domain {spec.get('name')!r}"
    )


def domain_root_frequencies(
    spec: dict, resolver: Resolver, lexicon_db: str | Path
) -> Counter:
    chunks, lang = _domain_terms(spec, lexicon_db)
    freq: Counter = Counter()
    for chunk in chunks:
        for tr in resolver.resolve(chunk, lang):
            for root in tr.roots:
                freq[root] += 1
    return freq


# ---------------------------------------------------------------------------
# Vector compilation
# ---------------------------------------------------------------------------


def compile_vectors(
    domain_freqs: list[Counter],
) -> tuple[list[str], np.ndarray, np.ndarray]:
    """Compile per-domain frequency maps into vocab + idf + L2 vectors."""
    n_domains = len(domain_freqs)
    vocab = sorted({root for f in domain_freqs for root in f})
    root_index = {r: i for i, r in enumerate(vocab)}
    V = len(vocab)

    df = np.zeros(V, dtype=np.float64)
    for f in domain_freqs:
        for root in f:
            df[root_index[root]] += 1.0

    idf = np.log((n_domains + 1) / (df + 1)) + 1.0

    vectors = np.zeros((n_domains, V), dtype=np.float64)
    for di, f in enumerate(domain_freqs):
        total = sum(f.values())
        if total == 0:
            continue
        row = vectors[di]
        for root, count in f.items():
            j = root_index[root]
            row[j] = (count / total) * idf[j]
        norm = float(np.linalg.norm(row))
        if norm > 0:
            vectors[di] = row / norm

    return vocab, idf, vectors


# ---------------------------------------------------------------------------
# Top-level builds
# ---------------------------------------------------------------------------


def build_bundle(
    domain_specs: list[dict],
    lexicon_db: str | Path,
    inventory: str | Path,
    out_path: str | Path,
    *,
    langs: list[str] | None = None,
    use_spacy: bool = True,
    build_date: str | None = None,
) -> Bundle:
    """Compile ``domain_specs`` into a portable bundle written to ``out_path``.

    The bundle includes domain vectors for :class:`~eolex_relevance.RelevanceScorer`
    plus the pedagogical tier map (``concept_lang``) from the lexicon DB.
    """
    if not domain_specs:
        raise ValueError("At least one domain spec is required.")
    langs = list(langs) if langs else ["eo", "en", "lt"]

    inv = load_inventory(inventory)
    word_root_map = build_word_root_map(lexicon_db, langs)
    concept_lang_map = build_concept_lang_data(lexicon_db, langs)
    resolver = Resolver(inv, word_root_map, langs, use_spacy=use_spacy)

    domains: list[str] = []
    domain_freqs: list[Counter] = []
    for spec in domain_specs:
        name = spec.get("name")
        if not name:
            raise ValueError(f"Domain spec missing 'name': {spec}")
        domains.append(name)
        domain_freqs.append(domain_root_frequencies(spec, resolver, lexicon_db))

    vocab, idf, vectors = compile_vectors(domain_freqs)

    conn = sqlite3.connect(str(lexicon_db))
    try:
        concept_count = conn.execute("SELECT COUNT(*) FROM concept").fetchone()[0]
        concept_lang_count = conn.execute(
            "SELECT COUNT(*) FROM concept_lang"
        ).fetchone()[0]
    finally:
        conn.close()

    meta = {
        "build_date": build_date or datetime.date.today().isoformat(),
        "langs": langs,
        "inventory": inv.get("meta", {}),
        "lexicon_db": {
            "path": str(lexicon_db),
            "concept_count": concept_count,
            "concept_lang_count": concept_lang_count,
        },
        "scoring": {
            "idf": "log((N+1)/(df+1)) + 1",
            "tf": "root_count / total_content_roots",
            "vector_norm": "l2",
            "spacy": bool(use_spacy),
        },
        "domain_specs": [
            {
                "name": s.get("name"),
                "source": s.get("source"),
                "lang": s.get("lang", "en"),
                **({"path": s["path"]} if s.get("source") == "corpus" else {}),
                **(
                    {"n_terms": len(s.get("terms", []))}
                    if s.get("source") == "terms"
                    else {}
                ),
            }
            for s in domain_specs
        ],
    }

    bundle = Bundle(
        domains=domains,
        vocab=vocab,
        idf=idf,
        vectors=vectors,
        word_root_map=word_root_map,
        inventory=inv,
        concept_lang_map=concept_lang_map,
        meta=meta,
    )
    bundle.save(out_path)
    return bundle


def build_lexicon_bundle(
    lexicon_db: str | Path,
    inventory: str | Path,
    out_path: str | Path,
    *,
    langs: list[str] | None = None,
    build_date: str | None = None,
) -> Bundle:
    """Build a lexicon-only bundle (no domain vectors) for ``eolex``.

    The resulting bundle can answer all :class:`~eolex.Lexicon` queries:
    morphological decomposition, word→root resolution, and pedagogical tiers.
    It carries no domain-scoring machinery and has a minimal footprint.

    This is the function that produces ``eolex/eolex/data/lexicon.bundle``.
    """
    langs = list(langs) if langs else ["eo", "en", "lt"]

    inv = load_inventory(inventory)
    word_root_map = build_word_root_map(lexicon_db, langs)
    concept_lang_map = build_concept_lang_data(lexicon_db, langs)

    conn = sqlite3.connect(str(lexicon_db))
    try:
        concept_count = conn.execute("SELECT COUNT(*) FROM concept").fetchone()[0]
        concept_lang_count = conn.execute(
            "SELECT COUNT(*) FROM concept_lang"
        ).fetchone()[0]
    finally:
        conn.close()

    meta = {
        "build_date": build_date or datetime.date.today().isoformat(),
        "langs": langs,
        "bundle_type": "lexicon",
        "inventory": inv.get("meta", {}),
        "lexicon_db": {
            "path": str(lexicon_db),
            "concept_count": concept_count,
            "concept_lang_count": concept_lang_count,
        },
    }

    bundle = Bundle(
        domains=[],
        vocab=[],
        idf=np.array([], dtype=np.float64),
        vectors=np.zeros((0, 0), dtype=np.float64),
        word_root_map=word_root_map,
        inventory=inv,
        concept_lang_map=concept_lang_map,
        meta=meta,
    )
    bundle.save(out_path)
    return bundle
