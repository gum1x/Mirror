#!/usr/bin/env python3
"""Redact PII from unified-JSONL messages before any upload.

Replaces emails, phone numbers, credit cards, SSNs, IPs, and custom terms with
typed placeholders (<EMAIL>, <PHONE>, ...). Run before Path B (OpenAI upload);
optional but encouraged for Path A retrieval and Path C.

    python pii_scrub.py data/clean.jsonl --custom "123 Main St" -o data/scrubbed.jsonl
    python pii_scrub.py data/clean.jsonl --report   # just count, don't write
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from typing import Iterator

sys.path.insert(0, __import__("os").path.dirname(
    __import__("os").path.dirname(__import__("os").path.abspath(__file__))))
from lib.schema import MessageRecord, read_jsonl, write_jsonl  # noqa: E402

# Order matters: match longer/structured things first.
PATTERNS = [
    ("<CARD>", re.compile(r"\b(?:\d[ -]?){13,16}\b")),
    ("<SSN>", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("<EMAIL>", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    ("<IP>", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
    # Phone: +country, separators, 7-15 digits. Conservative to avoid eating IDs.
    ("<PHONE>", re.compile(r"(?<!\w)(?:\+?\d{1,3}[ .-]?)?(?:\(\d{1,4}\)[ .-]?)?"
                           r"\d{3}[ .-]?\d{3,4}[ .-]?\d{0,4}(?!\w)")),
]


def build_custom(terms: list[str]) -> list[tuple[str, re.Pattern]]:
    out = []
    for t in terms:
        out.append(("<REDACTED>", re.compile(re.escape(t), re.I)))
    return out


def scrub_text(text: str, extra: list[tuple[str, re.Pattern]], counts: Counter) -> str:
    for tag, rx in extra + PATTERNS:
        def repl(m, tag=tag):
            counts[tag] += 1
            return tag
        text = rx.sub(repl, text)
    return text


def scrub(inputs: list[str], extra: list[tuple[str, re.Pattern]], counts: Counter
          ) -> Iterator[MessageRecord]:
    for path in inputs:
        for rec in read_jsonl(path):
            rec.text = scrub_text(rec.text or "", extra, counts)
            yield rec


def main() -> None:
    ap = argparse.ArgumentParser(description="Redact PII from unified-JSONL messages.")
    ap.add_argument("inputs", nargs="+", help="One or more .jsonl files.")
    ap.add_argument("--custom", action="append", default=[],
                    help="Extra literal string to redact (repeatable).")
    ap.add_argument("--report", action="store_true", help="Only print counts; don't write output.")
    ap.add_argument("-o", "--output", default="-", help="Output .jsonl (default stdout).")
    args = ap.parse_args()

    counts: Counter = Counter()
    extra = build_custom(args.custom)
    if args.report:
        for _ in scrub(args.inputs, extra, counts):
            pass
        n = 0
    else:
        n = write_jsonl(scrub(args.inputs, extra, counts), args.output)

    summary = ", ".join(f"{k}:{v}" for k, v in sorted(counts.items())) or "none found"
    print(f"Redactions — {summary}", file=sys.stderr)
    if not args.report:
        print(f"Wrote {n} messages → {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
