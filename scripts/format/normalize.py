#!/usr/bin/env python3
"""Light, voice-preserving cleanup of unified-JSONL message records.

Keeps case, emoji, and slang (that's the voice). Trims whitespace, removes
zero-width characters, drops empty/media-only and exact consecutive duplicates,
and optionally normalizes URLs.

    python normalize.py data/raw/*.jsonl --dedup -o data/clean.jsonl
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from collections.abc import Iterator

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib.schema import MessageRecord, read_jsonl, write_jsonl  # noqa: E402

# Strip zero-width space / direction marks / BOM, but keep ZWJ (U+200D) and
# ZWNJ (U+200C): they're meaningful — ZWJ composes emoji sequences (👩‍💻, ❤️‍🔥)
# and ZWNJ is orthographic in Persian/Farsi. Removing them mangles the voice.
ZERO_WIDTH = dict.fromkeys(map(ord, "​‎‏﻿"), None)
URL_RE = re.compile(r"https?://\S+|www\.\S+")
# "omitted" is required: a bare "video" or "sticker" is a real one-word reply.
MEDIA_ONLY = re.compile(r"^\s*<?\s*(media|image|video|audio|gif|sticker"
                        r"|document)\s+omitted\s*>?\s*$", re.I)


def clean_text(text: str, drop_urls: bool) -> str:
    text = text.translate(ZERO_WIDTH)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    if drop_urls:
        text = URL_RE.sub("<url>", text)
    return text.strip()


def normalize(inputs: list[str], min_chars: int, drop_urls: bool, dedup: bool,
              dedup_global: bool, skip_bad: bool = False) -> Iterator[MessageRecord]:
    last_key = None
    seen_global: set = set()
    for path in inputs:
        for rec in read_jsonl(path, skip_bad=skip_bad):
            rec.text = clean_text(rec.text or "", drop_urls)
            if len(rec.text) < min_chars or MEDIA_ONLY.match(rec.text):
                continue
            if dedup:
                key = (rec.conversation_id, rec.is_from_me, rec.text)
                if key == last_key:
                    continue
                last_key = key
            if dedup_global:
                norm = " ".join(rec.text.lower().split())
                if norm in seen_global:
                    continue
                seen_global.add(norm)
            yield rec


def main() -> None:
    ap = argparse.ArgumentParser(description="Normalize unified-JSONL messages.")
    ap.add_argument("inputs", nargs="+", help="One or more .jsonl files.")
    ap.add_argument("--min-chars", type=int, default=1, help="Drop messages shorter than this.")
    ap.add_argument("--drop-urls", action="store_true", help="Replace URLs with <url>.")
    ap.add_argument("--dedup", action="store_true", help="Drop exact consecutive duplicates.")
    ap.add_argument("--dedup-global", action="store_true",
                    help="Drop ALL repeats of the same normalized text corpus-wide "
                         "(removes forwarded/copy-paste spam; also flattens repeated one-liners).")
    ap.add_argument("--skip-bad-lines", action="store_true",
                    help="Warn and skip malformed JSONL lines instead of aborting "
                         "(real exports often have a truncated last line).")
    ap.add_argument("-o", "--output", default="-", help="Output .jsonl (default stdout).")
    args = ap.parse_args()
    n = write_jsonl(normalize(args.inputs, args.min_chars, args.drop_urls, args.dedup,
                              args.dedup_global, args.skip_bad_lines), args.output)
    print(f"Wrote {n} cleaned messages → {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
