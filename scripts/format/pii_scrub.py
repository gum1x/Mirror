#!/usr/bin/env python3
"""Redact PII from unified-JSONL messages before any upload.

Single-pass, non-overlapping redaction (later patterns can't corrupt an earlier
substitution). Covers URLs, emails, cards, SSNs, IPs, phone numbers, US-style
street addresses, and US-style dates of birth, plus any --custom terms.

    python pii_scrub.py data/clean.jsonl --custom "123 Main St" -o data/scrubbed.jsonl
    python pii_scrub.py data/clean.jsonl --report   # count only, don't write

NOTE: regex PII detection is best-effort. Names and unusual address/ID formats
are NOT reliably caught — pass them via --custom, and for high-stakes uploads
consider a dedicated NER/PII tool (e.g. Microsoft Presidio) on top of this.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import sys
from collections import Counter
from typing import Iterator

sys.path.insert(0, __import__("os").path.dirname(
    __import__("os").path.dirname(__import__("os").path.abspath(__file__))))
from lib.schema import MessageRecord, read_jsonl, write_jsonl  # noqa: E402

# (tag, regex). Order matters within the combined alternation: structured /
# longer things first so they win at a given position (leftmost-longest-ish).
BUILTINS = [
    ("<URL>", r"https?://\S+|www\.\S+"),
    ("<EMAIL>", r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),
    ("<CARD>", r"\b\d(?:[ -]?\d){12,15}\b"),                       # ends on a digit
    ("<SSN>", r"\b\d{3}-\d{2}-\d{4}\b"),
    ("<IP>", r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    ("<DOB>", r"\b(?:0?[1-9]|1[0-2])[/-](?:0?[1-9]|[12]\d|3[01])[/-](?:19|20)\d\d\b"),
    ("<ADDRESS>", r"\b\d{1,5}\s+(?:[A-Za-z]+\.?\s+){1,4}"
                  r"(?:St|Street|Ave|Avenue|Rd|Road|Blvd|Boulevard|Ln|Lane|Dr|Drive|"
                  r"Ct|Court|Way|Pl|Place|Ter|Terrace|Hwy|Highway)\b\.?"),
    # Phone: require >=2 separated digit groups so bare IDs/timestamps don't match,
    # and consume the whole token so no prefix leaks.
    ("<PHONE>", r"(?<!\w)\+?\(?\d{1,4}\)?(?:[ .\-]\d{2,4}){2,4}(?!\w)"),
]


def build_scrubber(custom: list[str]) -> tuple[re.Pattern, dict[str, str]]:
    specs = [("<REDACTED>", re.escape(t)) for t in custom] + BUILTINS
    tags, parts = {}, []
    for i, (tag, rx) in enumerate(specs):
        g = f"g{i}"
        tags[g] = tag
        parts.append(f"(?P<{g}>{rx})")
    return re.compile("|".join(parts), re.IGNORECASE), tags


def scrub_text(text: str, master: re.Pattern, tags: dict[str, str], counts: Counter) -> str:
    def repl(m: re.Match) -> str:
        for g, tag in tags.items():
            if m.group(g) is not None:
                counts[tag] += 1
                return tag
        return m.group(0)
    return master.sub(repl, text)


def scrub(inputs: list[str], master: re.Pattern, tags: dict[str, str], counts: Counter
          ) -> Iterator[MessageRecord]:
    for path in inputs:
        for rec in read_jsonl(path):
            rec.text = scrub_text(rec.text or "", master, tags, counts)
            yield rec


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def write_manifest(path: str, args, counts: Counter, n: int) -> None:
    """Auditable record of what was scrubbed. Stores counts + file hashes only —
    never the custom literals (those are the very PII being hidden)."""
    manifest = {
        "generated": datetime.datetime.now().isoformat(timespec="seconds"),
        "engine": "regex",
        "redaction_tags": sorted({tag for tag, _ in BUILTINS}),
        "custom_terms_count": len(args.custom),  # count only, never the strings
        "redactions": {k: v for k, v in sorted(counts.items())},
        "messages": n,
        "inputs": [{"path": p, "sha256": _sha256(p)} for p in args.inputs
                   if os.path.isfile(p)],
        "output": {"path": args.output, "sha256": _sha256(args.output)}
        if args.output != "-" and os.path.isfile(args.output) else None,
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)
    print(f"Wrote redaction manifest → {path}", file=sys.stderr)


def main() -> None:
    ap = argparse.ArgumentParser(description="Redact PII from unified-JSONL messages.")
    ap.add_argument("inputs", nargs="+", help="One or more .jsonl files.")
    ap.add_argument("--custom", action="append", default=[],
                    help="Extra literal string to redact, case-insensitive (repeatable).")
    ap.add_argument("--report", action="store_true", help="Only print counts; don't write output.")
    ap.add_argument("--manifest", nargs="?", const="REDACTION_MANIFEST.json", default=None,
                    help="Write an auditable manifest (counts + file hashes, never the "
                         "literals). Defaults next to -o when given with no path.")
    ap.add_argument("-o", "--output", default="-", help="Output .jsonl (default stdout).")
    args = ap.parse_args()

    counts: Counter = Counter()
    master, tags = build_scrubber(args.custom)
    if args.report:
        for _ in scrub(args.inputs, master, tags, counts):
            pass
        n = 0
    else:
        n = write_jsonl(scrub(args.inputs, master, tags, counts), args.output)

    summary = ", ".join(f"{k}:{v}" for k, v in sorted(counts.items())) or "none found"
    print(f"Redactions — {summary}", file=sys.stderr)
    print("Reminder: names and unusual formats are not auto-detected; use --custom "
          "for those (see header).", file=sys.stderr)
    if not args.report:
        print(f"Wrote {n} messages → {args.output}", file=sys.stderr)
        if args.manifest is not None:
            mpath = args.manifest
            if mpath == "REDACTION_MANIFEST.json" and args.output != "-":
                mpath = os.path.join(os.path.dirname(args.output) or ".",
                                     "REDACTION_MANIFEST.json")
            write_manifest(mpath, args, counts, n)


if __name__ == "__main__":
    main()
