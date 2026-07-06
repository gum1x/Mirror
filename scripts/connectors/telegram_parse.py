#!/usr/bin/env python3
"""Parse a Telegram Desktop JSON export (result.json) into unified JSONL.

Handles both the full-account export (chats.list) and single-chat exports.

    python telegram_parse.py result.json --me "Sam" -o out.jsonl
    python telegram_parse.py result.json --me-id user123456789 -o out.jsonl
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Iterator
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib.schema import MessageRecord, iso_utc, write_jsonl  # noqa: E402


def _flatten_text(text) -> str:
    """Telegram `text` is a string OR a list of strings / entity dicts."""
    if isinstance(text, str):
        return text
    if isinstance(text, list):
        out = []
        for part in text:
            if isinstance(part, str):
                out.append(part)
            elif isinstance(part, dict):
                out.append(part.get("text", ""))
        return "".join(out)
    return ""


def _ts(msg: dict, tz: str | None) -> str | None:
    # Prefer the absolute epoch; it's unambiguous.
    if msg.get("date_unixtime"):
        try:
            dt = datetime.fromtimestamp(int(msg["date_unixtime"]), tz=timezone.utc)
            return iso_utc(dt)
        except (ValueError, OSError):
            pass
    if msg.get("date"):
        try:
            dt = datetime.fromisoformat(msg["date"])  # naive, local source time
            if tz:
                try:
                    from zoneinfo import ZoneInfo
                    dt = dt.replace(tzinfo=ZoneInfo(tz))
                except Exception:
                    pass
            return iso_utc(dt)
        except ValueError:
            return None
    return None


def _chats(data: dict) -> Iterator[dict]:
    if "chats" in data and isinstance(data["chats"], dict):
        yield from data["chats"].get("list", [])
    elif "messages" in data:           # single-chat export
        yield data
    else:                              # some exports nest differently
        for v in data.values():
            if isinstance(v, dict) and "messages" in v:
                yield v


def parse(path: str, me: list[str], me_id: str | None, tz: str | None
          ) -> tuple[Iterator[MessageRecord], set]:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)

    me_lower = {m.lower() for m in me}
    seen_senders: set = set()
    # Single-chat exports often lack a top-level name/id; fall back to the file
    # name so two such exports don't both collapse into one "telegram" bucket.
    default_convo = os.path.splitext(os.path.basename(path))[0]
    if default_convo in ("result", "messages"):
        default_convo = os.path.basename(os.path.dirname(os.path.abspath(path))) or "telegram"

    def gen() -> Iterator[MessageRecord]:
        for chat in _chats(data):
            convo = chat.get("name") or (str(chat["id"]) if chat.get("id") else default_convo)
            for msg in chat.get("messages", []):
                if msg.get("type") != "message":
                    continue
                text = _flatten_text(msg.get("text", "")).strip()
                if not text:
                    continue
                sender = (msg.get("from") or "").strip()
                fid = msg.get("from_id")
                if sender:
                    seen_senders.add(sender)
                is_me = (me_id is not None and fid == me_id) or \
                        (sender.lower() in me_lower)
                yield MessageRecord(
                    source="telegram", conversation_id=convo, text=text,
                    is_from_me=is_me, sender="me" if is_me else (sender or "other"),
                    timestamp=_ts(msg, tz),
                    reply_to=(str(msg["reply_to_message_id"])
                              if msg.get("reply_to_message_id") else None),
                )

    return gen(), seen_senders


def main() -> None:
    ap = argparse.ArgumentParser(description="Parse Telegram result.json to unified JSONL.")
    ap.add_argument("input", help="Path to result.json")
    ap.add_argument("--me", action="append", default=[], help="Your display name (repeatable).")
    ap.add_argument("--me-id", help="Your Telegram from_id, e.g. user123456789 (most reliable).")
    ap.add_argument("--tz", help="IANA source timezone for naive dates, e.g. America/New_York.")
    ap.add_argument("-o", "--output", default="-", help="Output .jsonl (default stdout).")
    args = ap.parse_args()

    if not args.me and not args.me_id:
        ap.error("provide --me and/or --me-id so we can flag your messages.")

    records, seen = parse(args.input, args.me, args.me_id, args.tz)
    # Materialize so we can report seen senders even on stdout.
    records = list(records)
    n = write_jsonl(iter(records), args.output)
    mine = sum(1 for r in records if r.is_from_me)
    print(f"Wrote {n} messages ({mine} from you) → {args.output}", file=sys.stderr)
    if mine == 0:
        print("⚠️  Found 0 of your messages. Senders seen: "
              + ", ".join(sorted(seen)[:20]), file=sys.stderr)
        print("   Re-run with --me set to your exact name above (or --me-id).",
              file=sys.stderr)


if __name__ == "__main__":
    main()
