"""Bundle builder — the compile-once half of build-once / score-many.

Run inside the lexicon repo, where ``lexicon_v2.db`` and ``eo_inventory.json``
are available. Produces a single portable ``.bundle`` that the runtime scorer
loads with no further dependencies.

What it compiles
----------------
1. **Resolver tables** — the word→root map for the requested language packs,
   read straight from ``concept_lang`` joined to ``concept_root`` (compounds
   contribute every root; concepts lacking a ``concept_root`` row fall back to
   ``concept.eo_root``), plus the full Esperanto inventory copied from
   ``eo_inventory.json`` so Esperanto text can be decomposed at score time.
2. **Domain vectors** — each domain spec is turned into a root-frequency map
   ``f_i`` using the *same* resolver, then into an IDF-weighted, L2-normalized
   vector. This is the only place the scoring math is defined; the scorer
   mirrors it.

Scoring math (exact)
--------------------
Given ``N`` domains with root-frequency maps ``f_i``::

    df(r)   = number of domains containing r
    idf(r)  = log((N + 1) / (df(r) + 1)) + 1
    w_i(r)  = (f_i(r) / Σ_r f_i(r)) * idf(r)      then L2-normalize w_i

The bundle vocabulary is every root with ``df >= 1`` (the union of all
domains' roots), in a fixed sorted order.

Domain spec forms
-----------------
* ``{"name", "source": "terms", "terms": [...], "lang": "en"}`` — explicit list.
* ``{"name", "source": "corpus", "path": "...", "lang": "en"}`` — derive the
  profile from an expert corpus file.
* ``{"name", "source": "db", "query": "...", "lang": "en"}`` — pull terms from
  the lexicon DB. A documented hook: the default query returns ``concept_lang``
  words for ``:lang``; adapt ``query`` to the real domain-tagging schema. The
  fully-specified paths are ``terms`` and ``corpus``.
"""

from __future__ import annotations

import datetime
import json
import math
import sqlite3
from collections import Counter
from pathlib import Path

import numpy as np

from .bundle import Bundle
from .resolver import Resolver

# Documented default for source="db": adapt to the real domain-tagging schema.
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
    """Extract a ``(lang, lowercased word) -> [roots]`` map from the lexicon.

    Roots come from ``concept_root`` (full root set per concept, so compounds
    contribute every root); a concept with no ``concept_root`` rows falls back
    to its single ``concept.eo_root``. Only non-Esperanto packs are emitted —
    Esperanto is resolved by morphological decomposition, not by lookup.
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

    # Sort the root lists for deterministic bundle bytes.
    return {k: sorted(v) for k, v in out.items()}


# ---------------------------------------------------------------------------
# Domain profile extraction
# ---------------------------------------------------------------------------


def _domain_terms(spec: dict, lexicon_db: str | Path) -> tuple[list[str], str]:
    """Return ``(text_chunks, lang)`` for a domain spec.

    Each chunk is resolved independently; for ``terms``/``db`` a chunk is one
    term, for ``corpus`` it is the whole file text.
    """
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
        # Accept (term,) or (term, lang) row shapes.
        terms: list[str] = []
        for row in rows:
            if not row:
                continue
            terms.append(str(row[0]))
        return terms, lang
    raise ValueError(f"Unknown domain source {source!r} for domain {spec.get('name')!r}")


def domain_root_frequencies(
    spec: dict, resolver: Resolver, lexicon_db: str | Path
) -> Counter:
    """Resolve a domain spec to a root-frequency map ``f_i``."""
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
    """Compile per-domain frequency maps into vocab + idf + L2 vectors.

    Returns ``(vocab, idf, vectors)`` where ``vocab`` is the sorted union of
    all roots, ``idf`` has shape ``(V,)`` and ``vectors`` has shape ``(D, V)``
    with L2-normalized rows.
    """
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
# Top-level build
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

    ``langs`` lists the supported language codes (default ``["eo", "en", "lt"]``).
    The returned :class:`Bundle` is also the in-memory form just written.
    """
    if not domain_specs:
        raise ValueError("At least one domain spec is required.")
    langs = list(langs) if langs else ["eo", "en", "lt"]

    inv = load_inventory(inventory)
    word_root_map = build_word_root_map(lexicon_db, langs)
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
                **({"n_terms": len(s.get("terms", []))} if s.get("source") == "terms" else {}),
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
        meta=meta,
    )
    bundle.save(out_path)
    return bundle
