"""Portable ``.bundle`` artifact — the only data file a consumer needs.

A bundle is a single versioned SQLite file holding everything the runtime
scorer requires and nothing it does not: the text→roots resolver tables, the
compiled per-domain weight vectors with their IDF weights, the Esperanto
decomposition inventory, and provenance metadata. It carries no lexicon
database and needs no network at load time.

Layout (schema version 1)
--------------------------
``meta``        ``key TEXT, value TEXT`` — JSON-encoded scalars/objects
``domain``      ``idx INTEGER, name TEXT`` — fixed domain order
``vocab``       ``idx INTEGER, root TEXT, idf REAL`` — bundle vocabulary
``weight``      ``domain_idx INTEGER, vocab_idx INTEGER, w REAL`` — sparse,
                L2-normalized domain vectors (zero weights omitted)
``word_root``   ``lang TEXT, word TEXT, root TEXT`` — pack word→root map
``eo_root``     ``root TEXT, tier TEXT, prod INTEGER, gloss TEXT`` — inventory
``eo_affix``    ``kind TEXT, value TEXT`` — suffixes/prefixes/correlatives/
                other/number_roots/verb_endings/nominal_endings

All weights are reproducible from a known bundle: ``meta`` records the schema
version, build date, source DB/inventory versions, the domain list and the
scoring config, so a vector can always be traced back to how it was compiled.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

SCHEMA_VERSION = 1

# Inventory keys that are stored as eo_affix rows (kind = key name).
_AFFIX_KINDS = (
    "suffixes",
    "prefixes",
    "correlatives",
    "other",
    "number_roots",
    "verb_endings",
    "nominal_endings",
)


@dataclass
class Bundle:
    """In-memory form of a loaded bundle."""

    domains: list[str]
    vocab: list[str]  # root strings, in column order
    idf: np.ndarray  # shape (V,)
    vectors: np.ndarray  # shape (D, V), L2-normalized rows
    word_root_map: dict[tuple[str, str], list[str]]
    inventory: dict
    meta: dict
    root_index: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.root_index:
            self.root_index = {r: i for i, r in enumerate(self.vocab)}

    @property
    def langs(self) -> list[str]:
        return list(self.meta.get("langs", []))

    # -- write -----------------------------------------------------------

    def save(self, path: str | Path) -> None:
        path = Path(path)
        if path.exists():
            path.unlink()
        conn = sqlite3.connect(path)
        try:
            self._write(conn)
            conn.commit()
        finally:
            conn.close()

    def _write(self, conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE domain (idx INTEGER PRIMARY KEY, name TEXT NOT NULL);
            CREATE TABLE vocab (idx INTEGER PRIMARY KEY, root TEXT NOT NULL,
                                idf REAL NOT NULL);
            CREATE TABLE weight (domain_idx INTEGER NOT NULL,
                                 vocab_idx INTEGER NOT NULL, w REAL NOT NULL);
            CREATE TABLE word_root (lang TEXT NOT NULL, word TEXT NOT NULL,
                                    root TEXT NOT NULL);
            CREATE TABLE eo_root (root TEXT PRIMARY KEY, tier TEXT,
                                  prod INTEGER, gloss TEXT);
            CREATE TABLE eo_affix (kind TEXT NOT NULL, value TEXT NOT NULL);
            CREATE INDEX idx_weight_domain ON weight(domain_idx);
            CREATE INDEX idx_word_root ON word_root(lang, word);
            """
        )

        meta = dict(self.meta)
        meta["schema_version"] = SCHEMA_VERSION
        meta["domains"] = self.domains
        conn.executemany(
            "INSERT INTO meta(key, value) VALUES (?, ?)",
            [(k, json.dumps(v, ensure_ascii=False)) for k, v in meta.items()],
        )
        conn.executemany(
            "INSERT INTO domain(idx, name) VALUES (?, ?)",
            list(enumerate(self.domains)),
        )
        conn.executemany(
            "INSERT INTO vocab(idx, root, idf) VALUES (?, ?, ?)",
            [(i, r, float(self.idf[i])) for i, r in enumerate(self.vocab)],
        )
        weights = []
        for di in range(self.vectors.shape[0]):
            for vi in range(self.vectors.shape[1]):
                w = float(self.vectors[di, vi])
                if w != 0.0:
                    weights.append((di, vi, w))
        conn.executemany(
            "INSERT INTO weight(domain_idx, vocab_idx, w) VALUES (?, ?, ?)",
            weights,
        )
        conn.executemany(
            "INSERT INTO word_root(lang, word, root) VALUES (?, ?, ?)",
            [
                (lang, word, root)
                for (lang, word), roots in self.word_root_map.items()
                for root in roots
            ],
        )
        roots = self.inventory.get("roots", {})
        conn.executemany(
            "INSERT INTO eo_root(root, tier, prod, gloss) VALUES (?, ?, ?, ?)",
            [
                (
                    r,
                    (info or {}).get("tier"),
                    (info or {}).get("prod"),
                    (info or {}).get("gloss"),
                )
                for r, info in roots.items()
            ],
        )
        affix_rows = []
        for kind in _AFFIX_KINDS:
            for value in self.inventory.get(kind, []):
                affix_rows.append((kind, value))
        conn.executemany(
            "INSERT INTO eo_affix(kind, value) VALUES (?, ?)", affix_rows
        )

    # -- read ------------------------------------------------------------

    @classmethod
    def load(cls, path: str | Path) -> "Bundle":
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Bundle not found: {path}")
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        try:
            return cls._read(conn)
        finally:
            conn.close()

    @classmethod
    def _read(cls, conn: sqlite3.Connection) -> "Bundle":
        meta = {
            row["key"]: json.loads(row["value"])
            for row in conn.execute("SELECT key, value FROM meta")
        }
        version = meta.get("schema_version")
        if version != SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported bundle schema version {version!r} "
                f"(this build supports {SCHEMA_VERSION})."
            )

        domains = [
            row["name"]
            for row in conn.execute("SELECT idx, name FROM domain ORDER BY idx")
        ]
        vocab_rows = list(
            conn.execute("SELECT idx, root, idf FROM vocab ORDER BY idx")
        )
        vocab = [row["root"] for row in vocab_rows]
        idf = np.array([row["idf"] for row in vocab_rows], dtype=np.float64)

        vectors = np.zeros((len(domains), len(vocab)), dtype=np.float64)
        for row in conn.execute("SELECT domain_idx, vocab_idx, w FROM weight"):
            vectors[row["domain_idx"], row["vocab_idx"]] = row["w"]

        word_root_map: dict[tuple[str, str], list[str]] = {}
        for row in conn.execute("SELECT lang, word, root FROM word_root"):
            word_root_map.setdefault((row["lang"], row["word"]), []).append(
                row["root"]
            )

        roots: dict = {}
        for row in conn.execute("SELECT root, tier, prod, gloss FROM eo_root"):
            roots[row["root"]] = {
                "tier": row["tier"],
                "prod": row["prod"],
                "gloss": row["gloss"],
            }
        inventory: dict = {"roots": roots}
        for kind in _AFFIX_KINDS:
            inventory[kind] = [
                row["value"]
                for row in conn.execute(
                    "SELECT value FROM eo_affix WHERE kind = ?", (kind,)
                )
            ]

        return cls(
            domains=domains,
            vocab=vocab,
            idf=idf,
            vectors=vectors,
            word_root_map=word_root_map,
            inventory=inventory,
            meta=meta,
        )

    def gloss_of(self, root: str) -> str | None:
        info = self.inventory.get("roots", {}).get(root)
        return info.get("gloss") if info else None
