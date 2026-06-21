#!/usr/bin/env python3
"""Parse a Slack workspace/DM export into unified JSONL.

A Slack export is a folder of per-channel/-DM subfolders, each with dated JSON
files (arrays of messages), plus a top-level users.json. We resolve your user id
from users.json (by name/email) and flag your messages.

    python slack_parse.py exports/slack --me "Sam Rivera" -o data/raw/slack.jsonl
    python slack_parse.py exports/slack --me-id U012ABCDEF -o data/raw/slack.jsonl
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from datetime import datetime, timezone
from typing import Iterator, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib.schema import MessageRecord, write_jsonl, iso_utc  # noqa: E402

MENTION = re.compile(r"<@([A-Z0-9]+)>")
LINK = re.compile(r"<(https?://[^>|]+)(?:\|([^>]+))?>")


def load_users(export_dir: str) -> dict[str, str]:
    path = os.path.join(export_dir, "users.json")
    users: dict[str, str] = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            for u in json.load(fh):
                name = (u.get("profile", {}).get("display_name")
                        or u.get("real_name") or u.get("name") or u["id"])
                users[u["id"]] = name
    return users


def resolve_me_id(users: dict[str, str], me: Optional[str], me_id: Optional[str],
                  export_dir: str) -> Optional[str]:
    if me_id:
        return me_id
    if me:
        low = me.lower()
        # Match against display/real/name and email in the raw users.json.
        path = os.path.join(export_dir, "users.json")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                for u in json.load(fh):
                    prof = u.get("profile", {})
                    fields = [u.get("name"), u.get("real_name"),
                              prof.get("display_name"), prof.get("real_name"),
                              prof.get("email")]
                    if any(f and f.lower() == low for f in fields):
                        return u["id"]
        for uid, name in users.items():
            if name.lower() == low:
                return uid
    return None


def clean(text: str, users: dict[str, str]) -> str:
    text = MENTION.sub(lambda m: "@" + users.get(m.group(1), m.group(1)), text)
    text = LINK.sub(lambda m: m.group(2) or m.group(1), text)
    return text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").strip()


def parse(export_dir: str, me_id: Optional[str], users: dict[str, str]) -> Iterator[MessageRecord]:
    for jf in sorted(glob.glob(os.path.join(export_dir, "*", "*.json"))):
        channel = os.path.basename(os.path.dirname(jf))
        with open(jf, encoding="utf-8") as fh:
            try:
                msgs = json.load(fh)
            except json.JSONDecodeError:
                continue
        for m in msgs:
            if m.get("type") != "message" or m.get("subtype"):
                continue
            text = clean(m.get("text", ""), users)
            if not text:
                continue
            uid = m.get("user")
            is_me = me_id is not None and uid == me_id
            ts = None
            if m.get("ts"):
                ts = iso_utc(datetime.fromtimestamp(float(m["ts"]), tz=timezone.utc))
            yield MessageRecord(
                source="slack", conversation_id=channel, text=text, is_from_me=is_me,
                sender="me" if is_me else users.get(uid, uid or "other"), timestamp=ts)


def main() -> None:
    ap = argparse.ArgumentParser(description="Parse a Slack export to unified JSONL.")
    ap.add_argument("input", help="Slack export folder (contains users.json + channel dirs).")
    ap.add_argument("--me", help="Your Slack display/real name or email.")
    ap.add_argument("--me-id", help="Your Slack user id, e.g. U012ABCDEF (most reliable).")
    ap.add_argument("-o", "--output", default="-")
    args = ap.parse_args()
    if not args.me and not args.me_id:
        ap.error("provide --me or --me-id so we can flag your messages.")

    users = load_users(args.input)
    me_id = resolve_me_id(users, args.me, args.me_id, args.input)
    if not me_id:
        print("⚠️  Could not resolve your Slack user id from users.json — pass --me-id. "
              "0 of your messages will be flagged.", file=sys.stderr)
    n = write_jsonl(parse(args.input, me_id, users), args.output)
    print(f"Wrote {n} messages → {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
