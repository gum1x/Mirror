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
from collections.abc import Iterator
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib.schema import MessageRecord, iso_utc, write_jsonl  # noqa: E402

# Line starting a new message: optional LTR mark, optional [, date, time,
# optional ], optional dash, then "Sender: message" (or a system line).
# The meridiem must cover the es/pt "p. m." / "a. m." forms too — stopping at
# the lone "p" leaves ". m.] Sam" in <rest>, which corrupts the sender (so
# --me never matches), the direction, AND drops the 12-hour offset.
LINE_RE = re.compile(
    r"^‎?\[?"
    r"(?P<date>\d{1,4}[./-]\d{1,2}[./-]\d{1,4})"
    r",?\s+"
    r"(?P<time>\d{1,2}:\d{2}(?::\d{2})?(?:\s*[APap]\.?\s?[Mm]\.?)?)"
    r"\]?\s*[-–]?\s*"
    r"(?P<rest>.*)$"
)

# A message whose WHOLE body is one of these is a placeholder we drop. We match
# the entire line (not a substring) so a real message that merely contains the
# word "left" / "added" / "omitted" is never discarded. Senderless lines
# (group-event notices like "Sam added Alex") are dropped separately, by the
# absence of a sender, so we don't need to enumerate every notice here.
_PLACEHOLDER_RE = re.compile(
    r"(?:<\s*Media omitted\s*>"
    r"|(?:image|video|audio|GIF|sticker|document|Contact card) omitted"
    r"|<attached:[^>]*>"                     # iOS "export with media" variant
    r"|This message was deleted|You deleted this message|null)",
    re.IGNORECASE,
)


def _norm_spaces(s: str) -> str:
    return s.replace(" ", " ").replace(" ", " ").replace("‎", "")


def _parse_dt(date_s: str, time_s: str, dayfirst: bool, tz: str | None = None) -> str | None:
    date_s, time_s = _norm_spaces(date_s).strip(), _norm_spaces(time_s).strip().upper()
    # "p. m." / "P.M." (es/pt exports) → "PM" so the meridiem regex below sees it
    time_s = re.sub(r"([AP])\.?\s*M\.?", r"\1M", time_s)
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
    if yi == 0:       # year-first (ISO-style) is always Y-M-D — never ambiguous
        month, day = a, b
    elif a > 12:      # a must be the day
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
        d = datetime(year, month, day, hh, mm, ss)
    except ValueError:
        return None
    # Export timestamps are local wall-clock; with --tz we can convert them to
    # real UTC instead of just labeling them Z (same behavior as telegram_parse).
    if tz:
        try:
            from zoneinfo import ZoneInfo
            d = d.replace(tzinfo=ZoneInfo(tz))
        except Exception:
            pass
    return iso_utc(d)


def _is_droppable(text: str) -> bool:
    """A message body that's empty or a pure media/deleted placeholder."""
    # iOS exports prefix placeholders with U+200E/200F direction marks, which
    # str.strip() doesn't remove (format chars, not whitespace).
    t = text.replace("‎", "").replace("‏", "").strip()
    return (not t) or bool(_PLACEHOLDER_RE.fullmatch(t))


def _convo_from_filename(path: str) -> str:
    stem = os.path.splitext(os.path.basename(path))[0]
    m = re.search(r"Chat (?:with|-)\s*(.+)", stem, re.I)
    return (m.group(1) if m else stem).strip()


def parse_file(path: str, me: list[str], dayfirst: bool,
               tz: str | None = None) -> Iterator[MessageRecord]:
    convo = _convo_from_filename(path)
    me_lower = {m.lower() for m in me}
    cur: dict | None = None

    def flush() -> MessageRecord | None:
        if not cur:
            return None
        text = cur["text"].strip()
        # No sender ⇒ a senderless system notice (encryption, group events, etc.).
        # Otherwise drop only empty or pure-placeholder bodies — never a real
        # message that happens to contain a word like "added" or "left".
        if not cur["sender"] or _is_droppable(text):
            return None
        is_me = cur["sender"].lower() in me_lower
        return MessageRecord(
            source="whatsapp", conversation_id=convo, text=text,
            is_from_me=is_me, sender="me" if is_me else cur["sender"],
            timestamp=cur["ts"],
        )

    with open(path, encoding="utf-8", errors="replace") as fh:
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
                    "ts": _parse_dt(m.group("date"), m.group("time"), dayfirst, tz),
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
    ap.add_argument("--tz", help="IANA timezone the export was written in "
                                 "(e.g. America/New_York); converts to real UTC. "
                                 "Without it, local wall-clock times are labeled Z.")
    ap.add_argument("-o", "--output", default="-", help="Output .jsonl (default stdout).")
    args = ap.parse_args()

    if not os.path.exists(args.input):
        ap.error(f"input not found: {args.input}")

    counts = {"mine": 0}
    seen: set[str] = set()

    def all_records() -> Iterator[MessageRecord]:
        for f in iter_inputs(args.input):
            for rec in parse_file(f, args.me, args.dayfirst, args.tz):
                counts["mine"] += int(rec.is_from_me)
                if not rec.is_from_me:
                    seen.add(rec.sender)
                yield rec

    n = write_jsonl(all_records(), args.output)
    print(f"Wrote {n} messages ({counts['mine']} from you) → {args.output}", file=sys.stderr)
    if n and not counts["mine"]:
        # Same guard the telegram connector has: a wrong --me otherwise builds
        # a dataset with zero assistant targets, silently.
        print("⚠️  Found 0 of your messages. Senders seen: "
              + ", ".join(sorted(seen)[:20]), file=sys.stderr)
        print("   Re-run with --me set to your exact name above.", file=sys.stderr)


if __name__ == "__main__":
    main()
