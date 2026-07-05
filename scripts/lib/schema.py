"""Mirror unified message schema — the contract between every stage.

Connectors emit a stream of `MessageRecord` (one JSON object per line, JSONL).
Everything downstream (formatting, persona analysis, dataset building) consumes
it. Keeping this contract small and stable is what lets the connectors and the
trainers evolve independently.

A record:

    {
      "source": "whatsapp",                 # connector id that produced it
      "conversation_id": "Alex",            # chat / thread identifier
      "timestamp": "2024-03-05T21:41:12Z",  # ISO-8601 UTC, or null if unknown
      "sender": "me",                       # "me" | "other" | "<display name>"
      "is_from_me": true,                   # the one field training relies on
      "text": "running 5 min late lol",     # plain text, media stripped
      "reply_to": null,                     # optional source-native msg id
      "media": null                         # optional {"type": "image", ...}
    }

`is_from_me` is the load-bearing field: your messages become the *assistant*
voice the model learns; everyone else becomes *context*.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterable, Iterator
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

SCHEMA_VERSION = "1.0"

# Connector ids we know about. Connectors may add new ones; this is advisory.
KNOWN_SOURCES = {
    "whatsapp", "telegram", "imessage", "sms", "gmail", "outlook",
    "slack", "discord", "instagram", "messenger", "signal", "imported",
}


@dataclass
class MessageRecord:
    """One message in one conversation."""

    source: str
    conversation_id: str
    text: str
    is_from_me: bool
    sender: str = "me"
    timestamp: str | None = None  # ISO-8601 UTC
    reply_to: str | None = None
    media: dict[str, Any] | None = None
    extra: dict[str, Any] = field(default_factory=dict)  # connector-specific

    def __post_init__(self) -> None:
        if self.sender == "me" and not self.is_from_me:
            # keep the two in sync when only one was provided
            self.sender = "other"
        if self.is_from_me and self.sender == "other":
            self.sender = "me"

    def to_json(self) -> str:
        d = asdict(self)
        if not d["extra"]:
            d.pop("extra")
        return json.dumps(d, ensure_ascii=False)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> MessageRecord:
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        extra = {k: v for k, v in d.items() if k not in known}
        base = {k: v for k, v in d.items() if k in known}
        rec = cls(**base)
        if extra:
            rec.extra.update(extra)
        return rec


def iso_utc(dt: datetime) -> str:
    """Normalize any datetime to an ISO-8601 UTC string with a trailing Z."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def write_jsonl(records: Iterable[MessageRecord], path: str) -> int:
    """Write records to a .jsonl file (or '-' for stdout). Returns the count."""
    n = 0
    out = sys.stdout if path == "-" else open(path, "w", encoding="utf-8")
    try:
        for rec in records:
            out.write(rec.to_json() + "\n")
            n += 1
    finally:
        if out is not sys.stdout:
            out.close()
    return n


def read_jsonl(path: str) -> Iterator[MessageRecord]:
    """Stream MessageRecords from a .jsonl file (or '-' for stdin).

    Fails with a clear, one-line message (not a raw traceback, and not a silent
    exit 0) when the file is missing or a line isn't valid JSON, since the people
    running this are usually feeding in their own messy exports.
    """
    if path == "-":
        fh = sys.stdin
    else:
        try:
            fh = open(path, encoding="utf-8")
        except FileNotFoundError:
            sys.exit(f"Input file not found: {path}")
        except OSError as e:
            sys.exit(f"Could not open {path}: {e}")
    try:
        for i, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as e:
                sys.exit(f"{path} line {i}: not valid JSON ({e.msg}). "
                         "Expected one JSON object per line (unified schema).")
            yield MessageRecord.from_dict(obj)
    finally:
        if fh is not sys.stdin:
            fh.close()


def validate(records: Iterable[MessageRecord]) -> dict[str, Any]:
    """Cheap sanity report so users catch a broken connector early."""
    total = mine = empty = no_ts = 0
    convos: set[str] = set()
    sources: set[str] = set()
    for r in records:
        total += 1
        mine += int(r.is_from_me)
        empty += int(not (r.text or "").strip())
        no_ts += int(r.timestamp is None)
        convos.add(r.conversation_id)
        sources.add(r.source)
    return {
        "total_messages": total,
        "from_me": mine,
        "from_others": total - mine,
        "mine_ratio": round(mine / total, 3) if total else 0.0,
        "conversations": len(convos),
        "sources": sorted(sources),
        "empty_text": empty,
        "missing_timestamp": no_ts,
    }


if __name__ == "__main__":
    # `python schema.py path.jsonl` prints a validation report.
    src = sys.argv[1] if len(sys.argv) > 1 else "-"
    report = validate(read_jsonl(src))
    print(json.dumps(report, indent=2))
    if report["total_messages"] and report["from_me"] == 0:
        print("\n⚠️  No messages flagged is_from_me=true — the model would have "
              "no 'you' voice to learn. Check the connector's --me argument.",
              file=sys.stderr)
