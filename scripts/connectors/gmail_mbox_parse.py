#!/usr/bin/env python3
"""Parse a Sent-mail mbox (Google Takeout / Thunderbird) into unified JSONL.

Trains on YOUR composed voice: quoted replies and signatures are stripped so
the model learns your new prose, not the thread you replied to.

    python gmail_mbox_parse.py Sent.mbox --me sam@example.com -o out.jsonl
"""
from __future__ import annotations

import argparse
import mailbox
import os
import re
import sys
from email.utils import parsedate_to_datetime, getaddresses
from typing import Iterator, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib.schema import MessageRecord, write_jsonl, iso_utc  # noqa: E402

# Where a reply's quoted history begins — cut here and everything after.
QUOTE_BOUNDARIES = [
    re.compile(r"^On .*wrote:\s*$"),
    re.compile(r"^-----Original Message-----\s*$"),
    re.compile(r"^_{5,}\s*$"),
    re.compile(r"^From:\s.*$", re.I),          # Outlook quoted header block
    re.compile(r"^\s*>"),                       # quoted lines
    re.compile(r"^-- \s*$"),                    # standard signature delimiter
    re.compile(r"^Sent from my \w+", re.I),     # mobile signatures
]


def _strip_quotes_and_sig(body: str) -> str:
    out = []
    for line in body.splitlines():
        if any(rx.match(line) for rx in QUOTE_BOUNDARIES):
            break
        out.append(line)
    return "\n".join(out).strip()


def _html_to_text(html: str) -> str:
    html = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    html = re.sub(r"(?i)<br\s*/?>", "\n", html)
    html = re.sub(r"(?i)</p>", "\n\n", html)
    html = re.sub(r"<[^>]+>", "", html)
    html = re.sub(r"&nbsp;", " ", html)
    html = re.sub(r"&amp;", "&", html)
    html = re.sub(r"&lt;", "<", html).replace("&gt;", ">")
    return html


def _body(msg) -> str:
    """Prefer text/plain; fall back to stripped HTML."""
    plain = html = None
    for part in (msg.walk() if msg.is_multipart() else [msg]):
        ctype = part.get_content_type()
        if part.get("Content-Disposition", "").startswith("attachment"):
            continue
        try:
            payload = part.get_payload(decode=True)
            if payload is None:
                continue
            text = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        except Exception:
            continue
        if ctype == "text/plain" and plain is None:
            plain = text
        elif ctype == "text/html" and html is None:
            html = text
    body = plain if plain is not None else (_html_to_text(html) if html else "")
    # mboxrd un-escaping: a body line that was ">From ", ">>From ", … had one
    # ">" added at export so it wouldn't look like a message separator. Reverse it
    # so the user's own prose ("From a product angle, …") is restored intact.
    return re.sub(r"(?m)^>(>*From )", r"\1", body)


def parse(path: str, me: list[str], match_from: bool) -> Iterator[MessageRecord]:
    me_lower = {m.lower() for m in me}
    box = mailbox.mbox(path)
    for msg in box:
        # A real Sent message always has From/To headers; a record with neither
        # is junk from a mis-split envelope — skip it rather than emit garbage.
        if not msg.get("From") and not msg.get("To"):
            continue
        body = _strip_quotes_and_sig(_body(msg))
        if not body:
            continue
        from_addrs = [a.lower() for _, a in getaddresses([msg.get("From", "")])]
        to_addrs = getaddresses([msg.get("To", "")])
        is_me = True if not match_from else any(a in me_lower for a in from_addrs)
        ts = None
        if msg.get("Date"):
            try:
                ts = iso_utc(parsedate_to_datetime(msg["Date"]))
            except (TypeError, ValueError):
                ts = None
        convo = (to_addrs[0][1] if to_addrs else (from_addrs[0] if from_addrs else "email"))
        yield MessageRecord(
            source="gmail", conversation_id=convo, text=body,
            is_from_me=is_me, sender="me" if is_me else (from_addrs[0] if from_addrs else "other"),
            timestamp=ts,
            reply_to=msg.get("In-Reply-To"),
            extra={"subject": msg.get("Subject", "")},
        )


def main() -> None:
    ap = argparse.ArgumentParser(description="Parse a Sent mbox to unified JSONL.")
    ap.add_argument("input", help="Path to the .mbox file.")
    ap.add_argument("--me", action="append", default=[], help="Your email address (repeatable).")
    ap.add_argument("--match-from", action="store_true",
                    help="Flag is_from_me by matching the From header (use for a MIXED mbox; "
                         "default assumes a Sent-only mbox where every message is yours).")
    ap.add_argument("-o", "--output", default="-", help="Output .jsonl (default stdout).")
    args = ap.parse_args()
    if args.match_from and not args.me:
        ap.error("--match-from needs at least one --me address.")
    n = write_jsonl(parse(args.input, args.me, args.match_from), args.output)
    print(f"Wrote {n} emails → {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
