#!/usr/bin/env python3
"""Show how far along a Mirror build is, and the next command to run.

Inspects the standard output layout in a working directory and prints a stage
checklist plus a recommended next step. Read-only; never writes anything.

    python scripts/status.py            # inspect ./
    python scripts/status.py --dir my-mirror --json
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.schema import read_jsonl, validate  # noqa: E402


def _exists_any(*patterns: str) -> list[str]:
    out: list[str] = []
    for p in patterns:
        out.extend(sorted(glob.glob(p)))
    return out


def _counts(path: str) -> dict:
    try:
        return validate(read_jsonl(path))
    except (Exception, SystemExit):
        # read_jsonl raises SystemExit (not an Exception) on a bad line; a
        # read-only status report should degrade, not die on a corrupt corpus.
        return {}


def assess(base: str) -> dict:
    j = lambda *p: os.path.join(base, *p)  # noqa: E731
    raw = _exists_any(j("data", "raw", "*.jsonl"))
    scrubbed = _exists_any(j("data", "scrubbed.jsonl"))
    clean = _exists_any(j("data", "clean.jsonl"))
    style = os.path.exists(j("persona", "style_card.md"))
    train = _exists_any(j("data", "train.jsonl"), j("data", "train.json"))
    evals = _exists_any(j("data", "eval.jsonl"), j("data", "eval.json"))
    adapters = _exists_any(j("adapters", "*"))
    preds = _exists_any(j("eval", "preds.jsonl"))

    corpus = (scrubbed or clean or raw)
    corpus_report = _counts(corpus[0]) if corpus else {}

    stages = [
        ("1. Ingest", bool(raw), f"{len(raw)} raw file(s)" if raw else "no data/raw/*.jsonl yet",
         'parse an export, e.g. python scripts/connectors/whatsapp_parse.py "chat.txt" '
         "--me NAME -o data/raw/whatsapp.jsonl"),
        ("2. Format (scrub)", bool(scrubbed), "data/scrubbed.jsonl present" if scrubbed
         else ("clean.jsonl only — scrub next" if clean else "not started"),
         "python scripts/format/normalize.py data/raw/*.jsonl --dedup -o data/clean.jsonl && "
         "python scripts/format/pii_scrub.py data/clean.jsonl -o data/scrubbed.jsonl"),
        ("3. Persona", style, "persona/style_card.md present" if style else "no style card",
         "python scripts/persona/style_analyze.py data/scrubbed.jsonl --name NAME -o persona/"),
        ("4. Dataset", bool(train),
         (f"{os.path.basename(train[0])} present" + (" (+ eval split)" if evals else ""))
         if train else "no training set",
         "python scripts/format/build_dataset.py data/scrubbed.jsonl --format openai-chat "
         "--system-file persona/style_card.md --holdout 0.1 -o data/train.jsonl"),
        ("5. Train", bool(adapters), f"{len(adapters)} adapter dir(s)" if adapters
         else "no local adapter (Path A/B may need none)",
         "train your chosen path (see skills/mirror-training), or skip for Path A"),
        ("6. Evaluate", bool(preds), "eval/preds.jsonl present" if preds else "not evaluated",
         "python scripts/serve/mirror_chat.py --path A --batch data/eval.jsonl "
         "--style-card persona/style_card.md --corpus data/scrubbed.jsonl --rag "
         "--out eval/preds.jsonl"),
    ]

    next_cmd = next((cmd for _, done, _, cmd in stages if not done), None)
    return {
        "base": os.path.abspath(base),
        "corpus": (os.path.relpath(corpus[0]) if corpus else None),
        "corpus_report": corpus_report,
        "stages": [{"name": n, "done": d, "detail": det} for n, d, det, _ in stages],
        "next": next_cmd,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Show Mirror build progress + the next step.")
    ap.add_argument("--dir", default=".", help="Working directory to inspect (default: .).")
    ap.add_argument("--json", action="store_true", help="Machine-readable output.")
    args = ap.parse_args()

    st = assess(args.dir)
    if args.json:
        print(json.dumps(st, indent=2))
        return

    print(f"🪞  Mirror status — {st['base']}\n")
    if st["corpus_report"]:
        r = st["corpus_report"]
        print(f"Corpus ({st['corpus']}): {r.get('total_messages', 0)} messages, "
              f"{r.get('from_me', 0)} from you ({r.get('mine_ratio', 0):.0%}), "
              f"{r.get('conversations', 0)} conversations, sources {r.get('sources', [])}")
        if r.get("from_me", 0) == 0 and r.get("total_messages", 0):
            print("  ⚠️  0 messages flagged as yours — check the connector's --me argument.")
        print()
    for s in st["stages"]:
        mark = "✅" if s["done"] else "⬜"
        print(f"  {mark}  {s['name']:<18} {s['detail']}")
    print()
    if st["next"]:
        print(f"Next:\n  {st['next']}")
    else:
        print("All tracked stages have outputs. Deploy with scripts/serve/mirror_chat.py.")


if __name__ == "__main__":
    main()
