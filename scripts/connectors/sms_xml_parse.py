#!/usr/bin/env python3
"""Parse an Android "SMS Backup & Restore" XML export into unified JSONL.

In the app: Back up → choose XML. Each <sms> carries a type: 1=received,
2=sent, 3=draft, 4=outbox, 5=failed, 6=queued. Everything but received (and
drafts, which were never sent) is text you wrote. <mms> elements (group chats
and long/media texts) carry the same direction in msg_box, with the text in a
text/plain <part>. Streams with the stdlib XML parser; never loads the whole
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

# 2=sent, 4=outbox, 5=failed, 6=queued are all text you wrote; 1=received,
# 3=draft (never sent). Same values in <sms type=""> and <mms msg_box="">.
SENT_TYPES = {"2", "4", "5", "6"}


def _ts_ms(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return iso_utc(datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc))
    except (ValueError, OSError, OverflowError):
        return None


def _mms_text(elem: ET.Element) -> str:
    """Join the text/plain parts of an MMS (SMIL layout parts are markup, and
    media parts have no text — a media-only MMS yields "" and is dropped)."""
    parts = [p.get("text") for p in elem.iter("part") if p.get("ct") == "text/plain"]
    return "\n".join(t for t in parts if t and t.lower() != "null").strip()


def _mms_sender(elem: ET.Element) -> str | None:
    """The sending address of a received MMS: <addr type="137"> (PduHeaders.FROM).
    Needed for group chats, where the top-level address lists every participant."""
    for a in elem.iter("addr"):
        if a.get("type") == "137" and a.get("address"):
            return a.get("address")
    return None


def parse(path: str) -> Iterator[MessageRecord]:
    # iterparse keeps memory flat on large backups; clear each message element
    # once processed. <mms> children (parts/addrs) must NOT be cleared at their
    # own end-events — the parent still needs them — so only sms/mms are cleared.
    it = ET.iterparse(path, events=("end",))
    try:
        for _, elem in it:
            if elem.tag == "sms":
                body = (elem.get("body") or "").strip()
                mtype = elem.get("type")
                # Skip drafts (never sent). Anything else with an unknown/missing
                # type is treated as received, so a stray value never mislabels
                # someone else as you.
                if body and body.lower() != "null" and mtype != "3":
                    is_me = mtype in SENT_TYPES
                    convo = elem.get("contact_name") or elem.get("address") or "sms"
                    yield MessageRecord(
                        source="sms", conversation_id=convo, text=body, is_from_me=is_me,
                        sender="me" if is_me else (elem.get("address") or "other"),
                        timestamp=_ts_ms(elem.get("date")))
                elem.clear()
            elif elem.tag == "mms":
                mtype = elem.get("msg_box")
                body = _mms_text(elem)
                if body and mtype != "3":
                    is_me = mtype in SENT_TYPES
                    convo = elem.get("contact_name") or elem.get("address") or "sms"
                    sender = "me" if is_me else (
                        _mms_sender(elem) or elem.get("address") or "other")
                    yield MessageRecord(
                        source="sms", conversation_id=convo, text=body, is_from_me=is_me,
                        sender=sender, timestamp=_ts_ms(elem.get("date")))
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
    if not os.path.exists(args.input):
        ap.error(f"input not found: {args.input}")
    n = write_jsonl(parse(args.input), args.output)
    print(f"Wrote {n} SMS/MMS messages → {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
