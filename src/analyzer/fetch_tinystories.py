#!/usr/bin/env python3
"""Fetch a TinyStories sample and write it as a clean UTF-8 corpus.

TinyStories (HuggingFace ``roneneldan/TinyStories``) is written in a
deliberately tiny (~1,500-word) child vocabulary with no domain content.
This makes it a *coverage probe* for the common (Tier 1/2) lexicon: because
the vocabulary is known-simple by construction, every token the analyzer
cannot classify is, by elimination, a Tier-1/2 coverage gap or a
lemmatisation miss — nothing else it could be.

This script fetches the first ``--num-stories`` stories of the train split
(deterministic — no shuffling, so the corpus is reproducible), lightly
normalises Unicode punctuation to ASCII, and writes the stories to chunked
``.txt`` files under a ``stories/`` subdirectory so that
``batch_coverage_report`` (which only walks corpus *subdirectories*) picks
them up as one stratum.

The output corpus is *raw regenerable data*: it lives in the private
``esperanto-lexicon-corpus`` repo and is gitignored there. Only this build
script is committed.

Why normalise punctuation. Some TinyStories entries use Unicode curly
quotes / en/em dashes / ellipses. Written verbatim these are valid UTF-8,
but they occasionally glom onto adjacent words during tokenisation and
surface as spurious UNKNOWN tokens that have nothing to do with lexicon
coverage. Folding them to their ASCII equivalents keeps the probe measuring
vocabulary coverage rather than punctuation handling. (An earlier corpus
build wrote the text with a mis-configured encoding, producing mojibake such
as ``â€œ`` — normalising to ASCII also side-steps that failure class.)

Usage::

    python3 src/analyzer/fetch_tinystories.py \\
        --num-stories 5000 \\
        --stories-per-chunk 50 \\
        --output-dir ~/projects/esperanto-lexicon-corpus/tinystories/stories
"""

from __future__ import annotations

import argparse
import sys
import unicodedata
from pathlib import Path

# Mojibake repair table. A minority (~7.5%) of TinyStories source records
# contain double-encoded UTF-8 (UTF-8 bytes mis-decoded as CP1252 and
# re-encoded), so a curly quote such as U+201C ("") arrives as the literal
# three-character sequence ``â€œ``. These sequences tokenise into garbage
# UNKNOWN tokens (``â€œbe``, ``better.â€``) that have nothing to do with
# lexicon coverage. We map them straight to their ASCII equivalents; longest
# sequences are listed first so they are applied before shorter prefixes.
# ``\x9d`` is the raw byte that a closing double quote (U+201D) leaves behind
# (CP1252 has no glyph there), so it appears as a bare control character.
_MOJIBAKE_FOLD = {
    "â€œ": '"',
    "â€\x9d": '"',
    "â€™": "'",
    "â€˜": "'",
    "â€”": "-",
    "â€“": "-",
    "â€¦": "...",
    "â€": '"',  # catch-all for any remaining â€X double-quote residue
    "Ã©": "e",
    "Ã¨": "e",
    "Ã ": "a",
    "Ã¡": "a",
}

# Unicode punctuation → ASCII folding table. Applied before NFKC so that the
# result is deterministic and tokeniser-friendly for a child-vocabulary probe.
_PUNCT_FOLD = {
    "“": '"',  # left double quotation mark
    "”": '"',  # right double quotation mark
    "‘": "'",  # left single quotation mark
    "’": "'",  # right single quotation mark (also apostrophe)
    "–": "-",  # en dash
    "—": "-",  # em dash
    "…": "...",  # horizontal ellipsis
    " ": " ",  # non-breaking space
    "‹": "<",
    "›": ">",
    "„": '"',  # low double quote
    "‚": "'",  # low single quote
}


def normalise_text(text: str) -> str:
    """Fold Unicode punctuation to ASCII and normalise whitespace runs.

    Returns the story text with mojibake repaired, curly quotes / dashes /
    ellipses replaced by ASCII equivalents, NFKC-normalised, residual
    non-ASCII characters dropped, and trailing whitespace stripped.

    Residual non-ASCII stripping is safe here because TinyStories is English
    child vocabulary — any surviving non-ASCII byte is mojibake residue, not
    a legitimate character.
    """
    for src, dst in _MOJIBAKE_FOLD.items():
        text = text.replace(src, dst)
    for src, dst in _PUNCT_FOLD.items():
        text = text.replace(src, dst)
    text = unicodedata.normalize("NFKC", text)
    # Collapse Windows newlines; keep paragraph breaks (blank lines) intact.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Drop any non-ASCII residue (mojibake leftovers) while keeping newlines.
    text = "".join(ch for ch in text if ord(ch) < 128)
    return text.strip()


def load_stories(num_stories: int) -> list[str]:
    """Return the first *num_stories* normalised story texts from TinyStories.

    Uses the HuggingFace ``datasets`` streaming API so the full corpus is
    never materialised. Deterministic: takes stories in dataset order.
    """
    from datasets import load_dataset  # late import; heavy dependency

    ds = load_dataset("roneneldan/TinyStories", split="train", streaming=True)
    stories: list[str] = []
    for record in ds:
        text = normalise_text(record["text"])
        if text:
            stories.append(text)
        if len(stories) >= num_stories:
            break
    return stories


def chunk_stories(stories: list[str], per_chunk: int) -> list[str]:
    """Group *stories* into chunk bodies of *per_chunk* stories each.

    Stories within a chunk are separated by a blank line; the analyzer treats
    each chunk file as one document (one CSV row).
    """
    if per_chunk < 1:
        raise ValueError("per_chunk must be >= 1")
    chunks: list[str] = []
    for start in range(0, len(stories), per_chunk):
        block = stories[start : start + per_chunk]
        chunks.append("\n\n".join(block) + "\n")
    return chunks


def write_chunks(chunks: list[str], output_dir: Path) -> list[Path]:
    """Write chunk bodies to ``chunkNNN.txt`` under *output_dir* (UTF-8).

    Any pre-existing ``chunk*.txt`` files are removed first so a re-fetch does
    not leave stale files behind. Returns the list of written paths.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    for stale in output_dir.glob("chunk*.txt"):
        stale.unlink()
    written: list[Path] = []
    width = max(3, len(str(len(chunks) - 1)) if chunks else 3)
    for idx, body in enumerate(chunks):
        path = output_dir / f"chunk{idx:0{width}d}.txt"
        path.write_text(body, encoding="utf-8")
        written.append(path)
    return written


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Fetch a TinyStories sample as a clean UTF-8 chunked corpus."
    )
    parser.add_argument(
        "--num-stories",
        type=int,
        default=5000,
        help="Number of stories to fetch (default: 5000, ~1M tokens).",
    )
    parser.add_argument(
        "--stories-per-chunk",
        type=int,
        default=50,
        help="Stories per chunk file / per analyzer document (default: 50).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(
            "~/projects/esperanto-lexicon-corpus/tinystories/stories"
        ),
        help="Destination directory for chunk*.txt files.",
    )
    args = parser.parse_args(argv)

    print(f"Fetching {args.num_stories} TinyStories records...", file=sys.stderr)
    stories = load_stories(args.num_stories)
    if not stories:
        print("No stories fetched.", file=sys.stderr)
        sys.exit(1)

    chunks = chunk_stories(stories, args.stories_per_chunk)
    written = write_chunks(chunks, args.output_dir.expanduser())

    total_chars = sum(len(s) for s in stories)
    approx_tokens = total_chars // 5  # ~5 chars/token rough estimate
    print(
        f"Wrote {len(stories)} stories in {len(written)} chunks to "
        f"{args.output_dir.expanduser()}",
        file=sys.stderr,
    )
    print(
        f"~{total_chars:,} chars (~{approx_tokens:,} tokens est.)",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
