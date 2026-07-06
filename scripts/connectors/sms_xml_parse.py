#!/usr/bin/env python3
"""Parse an Android "SMS Backup & Restore" XML export into unified JSONL.

In the app: Back up → choose XML. Each <sms> has type="2" for messages you SENT
(type="1" = received). Streams with the stdlib XML parser; never loads the whole
file into memory.

    python sms_xml_parse.py exports/sms-backup.xml -o data/raw/sms.jsonl
"""
from __future__ import annotations

import argparse
import os
import sys
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib.schema import MessageRecord, iso_utc, write_jsonl  # noqa: E402


def parse(path: str) -> Iterator[MessageRecord]:
    # iterparse keeps memory flat on large backups; clear elements as we go.
    for _, elem in ET.iterparse(path, events=("end",)):
        if elem.tag != "sms":
            elem.clear()
            continue
        body = (elem.get("body") or "").strip()
        if body and body.lower() != "null":
            is_me = elem.get("type") == "2"        # 2 = sent by you, 1 = received
            ts = None
            if elem.get("date"):
                try:
                    ts = iso_utc(datetime.fromtimestamp(int(elem.get("date")) / 1000,
                                                        tz=timezone.utc))
                except (ValueError, OSError):
                    ts = None
            convo = elem.get("contact_name") or elem.get("address") or "sms"
            yield MessageRecord(
                source="sms", conversation_id=convo, text=body, is_from_me=is_me,
                sender="me" if is_me else (elem.get("address") or "other"), timestamp=ts)
        elem.clear()


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Parse Android SMS Backup & Restore XML to unified JSONL.")
    ap.add_argument("input", help="The .xml backup file.")
    ap.add_argument("-o", "--output", default="-")
    args = ap.parse_args()
    n = write_jsonl(parse(args.input), args.output)
    print(f"Wrote {n} SMS messages → {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
