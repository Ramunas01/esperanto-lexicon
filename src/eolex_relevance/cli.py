"""``eolex-relevance`` command-line interface — wraps build and score, emits JSON.

    eolex-relevance build  --domains domains.json --lexicon lexicon_v2.db \\
                           --inventory eo_inventory.json --out model.bundle
    eolex-relevance score  --model model.bundle --lang en --text-file t.txt --json

``domains.json`` is a JSON array of domain specs (see
:mod:`eolex_relevance.build`). Score text may come from ``--text``,
``--text-file``, or stdin.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .build import build_bundle
from .scorer import RelevanceScorer


def _read_text(args) -> str:
    if args.text is not None:
        return args.text
    if args.text_file is not None:
        return Path(args.text_file).read_text(encoding="utf-8")
    return sys.stdin.read()


def _cmd_build(args) -> int:
    specs = json.loads(Path(args.domains).read_text(encoding="utf-8"))
    if isinstance(specs, dict):  # tolerate {"domains": [...]} wrapper
        specs = specs.get("domains", specs)
    langs = args.langs.split(",") if args.langs else None
    bundle = build_bundle(
        specs,
        lexicon_db=args.lexicon,
        inventory=args.inventory,
        out_path=args.out,
        langs=langs,
        use_spacy=not args.no_spacy,
    )
    out = {
        "out": str(args.out),
        "domains": bundle.domains,
        "vocab_size": len(bundle.vocab),
        "langs": bundle.langs,
        "build_date": bundle.meta.get("build_date"),
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def _cmd_score(args) -> int:
    scorer = RelevanceScorer.load(args.model, use_spacy=not args.no_spacy)
    text = _read_text(args)
    res = scorer.score(text, lang=args.lang, normalize=args.normalize)
    payload = {
        "domains": res.domains,
        "vector": res.vector,
        "coverage": res.coverage,
        "normalize": res.normalize,
        "resolution": res.resolution,
        "scores": res.as_dict(),
        "n_content_tokens": res.n_content_tokens,
    }
    if args.explain:
        payload["explain"] = {
            d: res.explain(d, top_k=args.explain_top_k) for d in res.domains
        }
    # JSON is the only output format; --json is accepted for explicitness.
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="eolex-relevance",
        description="Score text relevance to domain dictionaries (TF-IDF over "
        "Esperanto roots).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    pb = sub.add_parser("build", help="Compile a .bundle from domain specs.")
    pb.add_argument("--domains", required=True, help="JSON file of domain specs.")
    pb.add_argument("--lexicon", required=True, help="Path to lexicon_v2.db.")
    pb.add_argument("--inventory", required=True, help="Path to eo_inventory.json.")
    pb.add_argument("--out", required=True, help="Output .bundle path.")
    pb.add_argument(
        "--langs", default=None, help="Comma-separated language codes (default eo,en,lt)."
    )
    pb.add_argument("--no-spacy", action="store_true", help="Disable spaCy lemmatization.")
    pb.set_defaults(func=_cmd_build)

    ps = sub.add_parser("score", help="Score text against a .bundle.")
    ps.add_argument("--model", required=True, help="Path to a .bundle.")
    ps.add_argument("--lang", required=True, help="Language code of the input text.")
    g = ps.add_mutually_exclusive_group()
    g.add_argument("--text", default=None, help="Inline text to score.")
    g.add_argument("--text-file", default=None, help="File with text to score.")
    ps.add_argument(
        "--normalize", default="none", choices=("none", "l1", "max"),
        help="Output vector normalization (default none).",
    )
    ps.add_argument("--explain", action="store_true", help="Include top roots per domain.")
    ps.add_argument("--explain-top-k", type=int, default=10)
    ps.add_argument("--json", action="store_true", help="(default) Emit JSON.")
    ps.add_argument("--no-spacy", action="store_true", help="Disable spaCy lemmatization.")
    ps.set_defaults(func=_cmd_score)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
