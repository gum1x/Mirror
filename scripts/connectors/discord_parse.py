#!/usr/bin/env python3
"""Parse DiscordChatExporter JSON exports into unified JSONL.

Export a DM/channel with DiscordChatExporter (Format: JSON) → one .json per
channel. Point at a file or a folder of them.

    python discord_parse.py exports/discord --me-id 123456789012345678 -o data/raw/discord.jsonl
    python discord_parse.py exports/discord --me "sam" -o data/raw/discord.jsonl
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from collections.abc import Iterator
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib.schema import MessageRecord, iso_utc, write_jsonl  # noqa: E402

KEEP_TYPES = {"Default", "Reply", "", None}


def parse_file(path: str, me: list[str], me_id: str | None) -> Iterator[MessageRecord]:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    chan = data.get("channel", {})
    convo = chan.get("name") or chan.get("id") or os.path.splitext(os.path.basename(path))[0]
    me_lower = {m.lower() for m in me}
    for m in data.get("messages", []):
        if m.get("type") not in KEEP_TYPES:
            continue
        content = (m.get("content") or "").strip()
        if not content:
            continue
        author = m.get("author", {})
        is_me = (me_id is not None and author.get("id") == me_id) or \
                bool(me_lower & {(author.get("name") or "").lower(),
                                 (author.get("nickname") or "").lower()})
        ts = None
        if m.get("timestamp"):
            try:
                ts = iso_utc(datetime.fromisoformat(m["timestamp"].replace("Z", "+00:00")))
            except ValueError:
                ts = None
        yield MessageRecord(
            source="discord", conversation_id=str(convo), text=content, is_from_me=is_me,
            sender="me" if is_me else (author.get("nickname") or author.get("name") or "other"),
            timestamp=ts)


def main() -> None:
    ap = argparse.ArgumentParser(description="Parse DiscordChatExporter JSON to unified JSONL.")
    ap.add_argument("input", help="A DiscordChatExporter .json or a folder of them.")
    ap.add_argument("--me", action="append", default=[],
                    help="Your Discord username or nickname (repeatable — names "
                         "change across export epochs).")
    ap.add_argument("--me-id", help="Your Discord user id (most reliable).")
    ap.add_argument("-o", "--output", default="-")
    args = ap.parse_args()
    if not args.me and not args.me_id:
        ap.error("provide --me or --me-id so we can flag your messages.")

    files = (sorted(glob.glob(os.path.join(args.input, "*.json")))
             if os.path.isdir(args.input) else [args.input])
    if not files:
        ap.error(f"no .json found under {args.input}")

    def gen() -> Iterator[MessageRecord]:
        for f in files:
            yield from parse_file(f, args.me, args.me_id)

    n = write_jsonl(gen(), args.output)
    print(f"Wrote {n} messages from {len(files)} file(s) → {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
