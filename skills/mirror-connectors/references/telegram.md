# Connector: Telegram

**Effort:** easy · **Output:** one `result.json` · **Limit:** none (full cloud
history, machine-readable).

## Export steps (Telegram **Desktop** required)

1. Install Telegram Desktop (the mobile apps can't export to JSON).
2. **Settings → Advanced → Export Telegram data.**
3. Choose what to include — for Mirror you want **"Personal chats"** (and
   optionally group chats you talk in). You can also export a single chat:
   open it → **⋮ menu → Export chat history.**
4. **Format: Machine-readable JSON** (not HTML).
5. Uncheck media/photos/videos/files to keep it small and fast (text is all we
   use). Run the export.
6. You'll get a folder containing `result.json`. Point Mirror at it.

## Parse

```bash
python scripts/connectors/telegram_parse.py exports/telegram/result.json \
    --me "Sam" -o data/raw/telegram.jsonl
```

`--me` matches the `from` field. Telegram also stores a stable `from_id` like
`user123456789`; if you know yours, pass `--me-id user123456789` for an exact
match (more reliable than display name). The parser prints the set of distinct
senders it saw if it can't find `--me`, so you can pick the right one.

## Format notes (handled by the parser)

`result.json` has a top-level `chats.list` (full export) **or** is a single
chat object (single-chat export). Each message:

```json
{
  "id": 12345,
  "type": "message",
  "date": "2024-03-05T21:41:12",
  "from": "Sam",
  "from_id": "user123456789",
  "text": "running 5 min late lol",
  "reply_to_message_id": 12340
}
```

The parser:
- Handles both export shapes (full vs single chat).
- Flattens `text` when it's an array of entities (links, bold, mentions) into a
  plain string.
- Skips `type: "service"` messages (joins, pins, calls) and empty/media-only
  messages.
- Carries `reply_to_message_id` into `reply_to` so the formatter can thread.
- Uses the chat `name` as `conversation_id`.

## Gotchas

- Telegram dates in the export are **local time without zone**; the parser treats
  them as local and normalizes to UTC. Pass `--tz America/New_York` if you want
  a specific source zone.
- Bots and channels: exclude noisy channels at export time, or filter later by
  `conversation_id` in the formatter.
