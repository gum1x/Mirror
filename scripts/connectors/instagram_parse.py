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


def _is_system_line(content: str, sender: str) -> bool:
    """Meta's English system notices ALWAYS begin with the sender's own name
    ("Alex sent an attachment.", "Alex reacted ❤️ to your message"). Anchoring
    on the name keeps real prose that merely matches the shape — "i sent an
    attachment." or "sorry i reacted so badly to your message" are messages."""
    if not sender or not content.startswith(sender):
        return False
    rest = content[len(sender):]
    return rest == " sent an attachment." or (
        rest.startswith(" reacted ") and rest.endswith(" to your message"))


def _fix_mojibake(s: str) -> str:
    """Meta writes UTF-8 bytes as latin-1 escapes; reverse it when it round-trips."""
    try:
        return s.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s


def parse_thread(path: str, me: list[str], source: str,
                 title_owner: dict | None = None) -> Iterator[MessageRecord]:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)

    # Meta titles are just display names — two different people called "Alex"
    # produce two threads with the same title, which would interleave into one
    # fake conversation downstream. The thread FOLDER name is unique; use it to
    # disambiguate when (and only when) a second folder claims the same title.
    folder = os.path.basename(os.path.dirname(os.path.abspath(path)))
    title = _fix_mojibake(data.get("title", "")) or folder
    if title_owner is not None:
        owner = title_owner.setdefault(title, folder)
        if owner != folder:
            title = f"{title} ({folder})"
    me_lower = {m.lower() for m in me}
    for msg in data.get("messages", []):
        # Judge by the text, not by media keys: a photo/share sent WITH a
        # caption keeps the caption (your words); media without text has no
        # 'content' and is dropped here.
        content = _fix_mojibake(msg.get("content") or "").strip()
        sender = _fix_mojibake(msg.get("sender_name", "")).strip()
        # Drop Meta's system/placeholder lines.
        if not content or _is_system_line(content, sender):
            continue
        is_me = sender.lower() in me_lower
        ts = None
        if msg.get("timestamp_ms"):
            # Guard like every other connector: one garbage timestamp must not
            # crash the run and (via write_jsonl's staged tmp) discard the lot.
            try:
                ts = iso_utc(datetime.fromtimestamp(msg["timestamp_ms"] / 1000, tz=timezone.utc))
            except (TypeError, ValueError, OSError, OverflowError):
                ts = None
        yield MessageRecord(
            source=source, conversation_id=title, text=content,
            is_from_me=is_me, sender="me" if is_me else (sender or "other"), timestamp=ts,
        )


def main() -> None:
    ap = argparse.ArgumentParser(description="Parse Meta (IG/Messenger) JSON to unified JSONL.")
    ap.add_argument("input", help="The `inbox` folder (or a single message_*.json).")
    ap.add_argument("--me", action="append", required=True,
                    help="Your display name as it appears in sender_name (repeatable — "
                         "it changes across export epochs).")
    ap.add_argument("--source", default="instagram", choices=["instagram", "messenger"])
    ap.add_argument("-o", "--output", default="-", help="Output .jsonl (default stdout).")
    args = ap.parse_args()

    if not os.path.exists(args.input):
        ap.error(f"input not found: {args.input}")
    if os.path.isdir(args.input):
        files = sorted(glob.glob(os.path.join(args.input, "**", "message_*.json"), recursive=True))
    else:
        files = [args.input]
    if not files:
        ap.error(f"no message_*.json found under {args.input}")

    title_owner: dict = {}

    def gen() -> Iterator[MessageRecord]:
        for f in files:
            # One corrupt/truncated export must not abort a whole-folder run and
            # throw away every other thread's output.
            try:
                yield from parse_thread(f, args.me, args.source, title_owner)
            except (json.JSONDecodeError, OSError) as e:
                print(f"⚠️  skipping {f}: {e}", file=sys.stderr)

    n = write_jsonl(gen(), args.output)
    print(f"Wrote {n} messages from {len(files)} thread file(s) → {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
