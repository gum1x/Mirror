#!/usr/bin/env python3
"""Parse WhatsApp "Export Chat" .txt files into Mirror's unified JSONL.

Handles the common export variants (bracketed/dashed, 12h/24h, several date
orders), joins multi-line messages, and drops system/media lines.

    python whatsapp_parse.py "WhatsApp Chat with Alex.txt" --me Sam -o out.jsonl
    python whatsapp_parse.py exports/whatsapp/ --me Sam --me "Sam Rivera" -o out.jsonl
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import sys
from datetime import datetime
from typing import Iterator, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib.schema import MessageRecord, write_jsonl, iso_utc  # noqa: E402

# Line starting a new message: optional LTR mark, optional [, date, time,
# optional ], optional dash, then "Sender: message" (or a system line).
LINE_RE = re.compile(
    r"^‎?\[?"
    r"(?P<date>\d{1,4}[./-]\d{1,2}[./-]\d{1,4})"
    r",?\s+"
    r"(?P<time>\d{1,2}:\d{2}(?::\d{2})?\s*[APMapm]{0,2})"
    r"\]?\s*[-–]?\s*"
    r"(?P<rest>.*)$"
)

# System lines (no real sender) we drop even when they parse as a message.
SYSTEM_MARKERS = (
    "Messages and calls are end-to-end encrypted",
    "You deleted this message",
    "This message was deleted",
    "<Media omitted>",
    "image omitted",
    "video omitted",
    "audio omitted",
    "GIF omitted",
    "sticker omitted",
    "document omitted",
    "Contact card omitted",
    "changed the subject",
    "changed this group's icon",
    "added", "removed", "left", "joined using",
    "created group", "changed their phone number",
    "Your security code with", "Tap to learn more",
    "‎",  # lone LTR/format marker lines
)


def _norm_spaces(s: str) -> str:
    return s.replace(" ", " ").replace(" ", " ").replace("‎", "")


def _parse_dt(date_s: str, time_s: str, dayfirst: bool) -> Optional[str]:
    date_s, time_s = _norm_spaces(date_s).strip(), _norm_spaces(time_s).strip().upper()
    parts = re.split(r"[./-]", date_s)
    if len(parts) != 3:
        return None
    nums = [int(p) for p in parts]

    # Identify the year (the 4-digit part, or a 2-digit > 31), then day/month.
    yi = next((i for i, n in enumerate(nums) if n > 99 or len(parts[i]) == 4), None)
    if yi is None:
        yi = 2  # assume trailing 2-digit year (e.g. 3/5/24)
    year = nums[yi]
    if year < 100:
        year += 2000
    rest_idx = [i for i in range(3) if i != yi]
    a, b = nums[rest_idx[0]], nums[rest_idx[1]]
    if a > 12:        # a must be the day
        day, month = a, b
    elif b > 12:      # b must be the day
        day, month = b, a
    else:
        day, month = (a, b) if dayfirst else (b, a)

    m = re.match(r"(\d{1,2}):(\d{2})(?::(\d{2}))?\s*([AP]M)?", time_s)
    if not m:
        return None
    hh, mm = int(m.group(1)), int(m.group(2))
    ss = int(m.group(3) or 0)
    ap = m.group(4)
    if ap == "PM" and hh != 12:
        hh += 12
    elif ap == "AM" and hh == 12:
        hh = 0
    try:
        return iso_utc(datetime(year, month, day, hh, mm, ss))
    except ValueError:
        return None


def _is_system(text: str) -> bool:
    t = text.strip()
    return (not t) or any(mark in t for mark in SYSTEM_MARKERS)


def _convo_from_filename(path: str) -> str:
    stem = os.path.splitext(os.path.basename(path))[0]
    m = re.search(r"Chat (?:with|-)\s*(.+)", stem, re.I)
    return (m.group(1) if m else stem).strip()


def parse_file(path: str, me: list[str], dayfirst: bool) -> Iterator[MessageRecord]:
    convo = _convo_from_filename(path)
    me_lower = {m.lower() for m in me}
    cur: Optional[dict] = None

    def flush() -> Optional[MessageRecord]:
        if not cur:
            return None
        text = cur["text"].strip()
        if _is_system(text) or not cur["sender"]:
            return None
        is_me = cur["sender"].lower() in me_lower
        return MessageRecord(
            source="whatsapp", conversation_id=convo, text=text,
            is_from_me=is_me, sender="me" if is_me else cur["sender"],
            timestamp=cur["ts"],
        )

    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            line = raw.rstrip("\n")
            m = LINE_RE.match(line)
            if m:
                rec = flush()
                if rec:
                    yield rec
                rest = m.group("rest")
                if ": " in rest:
                    sender, text = rest.split(": ", 1)
                else:
                    sender, text = "", rest  # system line w/o sender
                cur = {
                    "ts": _parse_dt(m.group("date"), m.group("time"), dayfirst),
                    "sender": sender.strip(),
                    "text": text,
                }
            elif cur is not None:
                cur["text"] += "\n" + line  # continuation of multi-line message
    rec = flush()
    if rec:
        yield rec


def iter_inputs(path: str) -> Iterator[str]:
    if os.path.isdir(path):
        yield from sorted(glob.glob(os.path.join(path, "*.txt")))
    else:
        yield path


def main() -> None:
    ap = argparse.ArgumentParser(description="Parse WhatsApp exports to unified JSONL.")
    ap.add_argument("input", help="A .txt export or a folder of them.")
    ap.add_argument("--me", action="append", required=True,
                    help="Your display name in the export (repeatable).")
    ap.add_argument("--dayfirst", action="store_true",
                    help="Interpret ambiguous dates as D/M (default M/D).")
    ap.add_argument("-o", "--output", default="-", help="Output .jsonl (default stdout).")
    args = ap.parse_args()

    def all_records() -> Iterator[MessageRecord]:
        for f in iter_inputs(args.input):
            yield from parse_file(f, args.me, args.dayfirst)

    n = write_jsonl(all_records(), args.output)
    print(f"Wrote {n} messages → {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
