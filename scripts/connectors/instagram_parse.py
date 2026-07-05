#!/usr/bin/env python3
"""Parse a Meta (Instagram / Messenger) JSON message export into unified JSONL.

Point it at the `inbox` folder from "Download your information" (Format: JSON).
Fixes Meta's classic UTF-8 mojibake so emoji/accents survive.

    python instagram_parse.py exports/instagram/messages/inbox --me "Sam" -o out.jsonl
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from collections.abc import Iterator
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib.schema import MessageRecord, iso_utc, write_jsonl  # noqa: E402

# Keys that mark a non-text (media/system) message we should skip.
MEDIA_KEYS = ("photos", "videos", "audio_files", "gifs", "sticker", "share", "files")


def _fix_mojibake(s: str) -> str:
    """Meta writes UTF-8 bytes as latin-1 escapes; reverse it when it round-trips."""
    try:
        return s.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s


def parse_thread(path: str, me: str, source: str) -> Iterator[MessageRecord]:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)

    title = _fix_mojibake(data.get("title", "")) or os.path.basename(os.path.dirname(path))
    me_lower = me.lower()
    for msg in data.get("messages", []):
        if any(k in msg for k in MEDIA_KEYS):
            continue
        content = msg.get("content")
        if not content:
            continue
        content = _fix_mojibake(content).strip()
        # Drop Meta's system/placeholder lines.
        if not content or content.endswith((" sent an attachment.", " to your message")):
            continue
        sender = _fix_mojibake(msg.get("sender_name", "")).strip()
        is_me = sender.lower() == me_lower
        ts = None
        if msg.get("timestamp_ms"):
            ts = iso_utc(datetime.fromtimestamp(msg["timestamp_ms"] / 1000, tz=timezone.utc))
        yield MessageRecord(
            source=source, conversation_id=title, text=content,
            is_from_me=is_me, sender="me" if is_me else (sender or "other"), timestamp=ts,
        )


def main() -> None:
    ap = argparse.ArgumentParser(description="Parse Meta (IG/Messenger) JSON to unified JSONL.")
    ap.add_argument("input", help="The `inbox` folder (or a single message_*.json).")
    ap.add_argument("--me", required=True, help="Your display name as it appears in sender_name.")
    ap.add_argument("--source", default="instagram", choices=["instagram", "messenger"])
    ap.add_argument("-o", "--output", default="-", help="Output .jsonl (default stdout).")
    args = ap.parse_args()

    if os.path.isdir(args.input):
        files = sorted(glob.glob(os.path.join(args.input, "**", "message_*.json"), recursive=True))
    else:
        files = [args.input]
    if not files:
        ap.error(f"no message_*.json found under {args.input}")

    def gen() -> Iterator[MessageRecord]:
        for f in files:
            yield from parse_thread(f, args.me, args.source)

    n = write_jsonl(gen(), args.output)
    print(f"Wrote {n} messages from {len(files)} thread file(s) → {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
