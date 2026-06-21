#!/usr/bin/env python3
"""Extract iMessage/SMS history from a macOS chat.db into unified JSONL.

    cp ~/Library/Messages/chat.db /tmp/chat.db     # copy first; live DB is locked
    python imessage_extract.py /tmp/chat.db -o out.jsonl

Reads message.is_from_me directly, converts the Apple-epoch timestamp, and
decodes attributedBody for messages whose plain `text` is NULL. Requires Full
Disk Access for your terminal. Opens the DB read-only.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from typing import Iterator, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib.schema import MessageRecord, write_jsonl, iso_utc  # noqa: E402

APPLE_EPOCH = 978307200  # seconds between 1970-01-01 and 2001-01-01 (UTC)

QUERY = """
SELECT m.text, m.attributedBody, m.is_from_me, m.date, m.service,
       h.id AS handle, c.chat_identifier, c.display_name
FROM message m
LEFT JOIN handle h ON m.handle_id = h.ROWID
LEFT JOIN chat_message_join cmj ON cmj.message_id = m.ROWID
LEFT JOIN chat c ON c.ROWID = cmj.chat_id
WHERE (m.associated_message_type IS NULL OR m.associated_message_type = 0)
ORDER BY m.date ASC
"""


def apple_to_iso(value: Optional[int]) -> Optional[str]:
    if not value:
        return None
    # Modern macOS stores nanoseconds; older stored seconds.
    secs = value / 1e9 if value > 1e11 else float(value)
    try:
        return iso_utc(datetime.fromtimestamp(secs + APPLE_EPOCH, tz=timezone.utc))
    except (ValueError, OSError, OverflowError):
        return None


def decode_attributed_body(blob: Optional[bytes]) -> Optional[str]:
    """Tolerant extractor for NSAttributedString typedstream blobs.

    Modern Messages stores rich text in `attributedBody` with `text` NULL. This
    pulls the readable run out of the archive. It won't handle every exotic
    message, but covers the vast majority; failures return None and are dropped.
    """
    if not blob:
        return None
    try:
        tail = blob.split(b"NSString", 1)[1][5:]  # skip class chaff after NSString
        b0 = tail[0]
        if b0 == 0x81:                             # u16 little-endian length
            length, start = int.from_bytes(tail[1:3], "little"), 3
        elif b0 == 0x82:                           # u32 little-endian length
            length, start = int.from_bytes(tail[1:5], "little"), 5
        else:                                      # single-byte length
            length, start = b0, 1
        text = tail[start:start + length].decode("utf-8", errors="replace")
        if not text:
            return None
        # Reject a binary mis-slice by RATIO of control chars (not a flat count),
        # so legitimate multi-paragraph messages with several newlines survive.
        ctrl = sum(1 for c in text if ord(c) < 32 and c not in "\n\t\r")
        return text if ctrl / len(text) < 0.1 else None
    except Exception:
        return None


def extract(db_path: str, service: Optional[str], me_handle: Optional[str]
            ) -> Iterator[MessageRecord]:
    uri = f"file:{os.path.expanduser(db_path)}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    try:
        for row in con.execute(QUERY):
            if service and (row["service"] or "").lower() != service.lower():
                continue
            text = row["text"]
            if not text:
                text = decode_attributed_body(row["attributedBody"])
            if not text or not text.strip():
                continue
            is_me = bool(row["is_from_me"])
            convo = row["display_name"] or row["chat_identifier"] or row["handle"] or "imessage"
            sender = "me" if is_me else (row["handle"] or me_handle or "other")
            yield MessageRecord(
                source="imessage", conversation_id=convo, text=text.strip(),
                is_from_me=is_me, sender=sender, timestamp=apple_to_iso(row["date"]),
                extra={"service": row["service"]} if row["service"] else {},
            )
    finally:
        con.close()


def extract_from_json(path: str) -> Iterator[MessageRecord]:
    """Generic importer for a JSON array (e.g. from imessage-exporter).

    Expects objects with: text, is_from_me (bool/int), timestamp (ISO) or
    date, conversation_id (or chat), sender (optional).
    """
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    items = data if isinstance(data, list) else data.get("messages", [])
    for it in items:
        text = (it.get("text") or "").strip()
        if not text:
            continue
        is_me = bool(it.get("is_from_me"))
        yield MessageRecord(
            source="imessage",
            conversation_id=str(it.get("conversation_id") or it.get("chat") or "imessage"),
            text=text, is_from_me=is_me,
            sender="me" if is_me else str(it.get("sender") or "other"),
            timestamp=it.get("timestamp"),
        )


def main() -> None:
    ap = argparse.ArgumentParser(description="Extract iMessage/SMS to unified JSONL.")
    ap.add_argument("input", help="Path to chat.db (or a .json with --from-json).")
    ap.add_argument("--service", choices=["imessage", "sms"],
                    help="Restrict to one service (default: both).")
    ap.add_argument("--me-handle", help="Your phone/email — labels the other party in 1:1s.")
    ap.add_argument("--from-json", action="store_true",
                    help="Treat input as a generic JSON export, not chat.db.")
    ap.add_argument("-o", "--output", default="-", help="Output .jsonl (default stdout).")
    args = ap.parse_args()

    gen = (extract_from_json(args.input) if args.from_json
           else extract(args.input, args.service, args.me_handle))
    n = write_jsonl(gen, args.output)
    print(f"Wrote {n} messages → {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
