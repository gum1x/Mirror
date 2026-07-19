#!/usr/bin/env python3
"""Parse an Android "SMS Backup & Restore" XML export into unified JSONL.

In the app: Back up → choose XML. Each <sms> carries a type: 1=received,
2=sent, 3=draft, 4=outbox, 5=failed, 6=queued. Everything but received (and
drafts, which were never sent) is text you wrote. Streams with the stdlib XML
parser; never loads the whole file into memory.

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
    it = ET.iterparse(path, events=("end",))
    try:
        for _, elem in it:
            if elem.tag != "sms":
                elem.clear()
                continue
            body = (elem.get("body") or "").strip()
            mtype = elem.get("type")
            # Skip drafts (never sent). 2=sent, 4=outbox, 5=failed, 6=queued are
            # all text you wrote; anything else (incl. a missing type) is treated
            # as received, so a stray value never mislabels someone else as you.
            if body and body.lower() != "null" and mtype != "3":
                is_me = mtype in ("2", "4", "5", "6")
                ts = None
                if elem.get("date"):
                    try:
                        ts = iso_utc(datetime.fromtimestamp(int(elem.get("date")) / 1000,
                                                            tz=timezone.utc))
                    except (ValueError, OSError, OverflowError):
                        ts = None
                convo = elem.get("contact_name") or elem.get("address") or "sms"
                yield MessageRecord(
                    source="sms", conversation_id=convo, text=body, is_from_me=is_me,
                    sender="me" if is_me else (elem.get("address") or "other"), timestamp=ts)
            elem.clear()
    except ET.ParseError as e:
        # A malformed byte mid-file must not discard the records already parsed
        # (write_jsonl only swaps the .tmp into place on a clean finish). Stop
        # here and keep what we have, but say so loudly.
        print(f"⚠️  {path}: XML parse error ({e}) — stopping early; records "
              "parsed before this point were kept.", file=sys.stderr)


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
