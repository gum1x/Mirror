# Connector: iMessage / SMS (macOS)

**Effort:** medium · **Output:** reads the local `chat.db` SQLite database ·
**Note:** Apple has **no in-app "Export Chat"** button. Messages are in a local
database on your Mac.

## Two ways to get the data

### Option 1 — read `chat.db` directly (no third-party tool)

iMessage + SMS sync to `~/Library/Messages/chat.db` on macOS. Mirror's parser
reads it directly.

1. **Grant Full Disk Access** to your terminal:
   System Settings → Privacy & Security → **Full Disk Access** → add Terminal
   (or iTerm). Without this you'll get `unable to open database file`.
2. Make a copy first (the live DB is locked while Messages runs):
   ```bash
   cp ~/Library/Messages/chat.db /tmp/chat.db
   ```
3. Parse:
   ```bash
   python scripts/connectors/imessage_extract.py /tmp/chat.db \
       --me-handle "+15551234567" -o data/raw/imessage.jsonl
   # or identify yourself by email Apple ID:
   python scripts/connectors/imessage_extract.py /tmp/chat.db \
       --me-handle "sam@icloud.com" -o data/raw/imessage.jsonl
   ```

   Actually you usually **don't need** `--me-handle`: the DB stores
   `message.is_from_me` directly, and the parser uses it. `--me-handle` only
   helps label the `other` party in 1:1 chats nicely.

### Option 2 — a third-party exporter (if you prefer a GUI / are on iPhone only)

- **imessage-exporter** (open-source CLI) → exports to TXT/HTML/JSON.
- **iMazing** (commercial GUI) → reads an iPhone backup, exports chats.

Then convert: imessage-exporter's JSON can be fed through
`scripts/connectors/imessage_extract.py --from-json`, or use the generic
importer pattern in `mirror-data-formatting`.

## Format notes (handled by the parser)

Key tables: `message`, `handle`, `chat`, `chat_message_join`, `chat_handle_join`.
The important columns:
- `message.text` — the body (modern macOS stores rich text in
  `message.attributedBody`; the parser falls back to decoding that when `text`
  is NULL).
- `message.is_from_me` — **1 if you sent it** (this is our `is_from_me`).
- `message.date` — nanoseconds since the Apple epoch (2001-01-01 UTC). The
  parser converts: `unix = apple_ns / 1e9 + 978307200`.
- `handle.id` — the other party's phone/email.

The parser joins these, derives a `conversation_id` (the chat's display name or
the other handle for 1:1s), and skips empty/attachment-only messages and
tapbacks/reactions.

## Gotchas

- **`attributedBody`**: newer messages may have `text = NULL` and the real
  content in a binary `attributedBody` (a serialized `NSAttributedString`). The
  parser extracts the readable run with a tolerant decoder; a few exotic
  messages may come out empty — that's fine, they're dropped.
- **SMS vs iMessage**: both live in `chat.db`; `message.service` is `iMessage`
  or `SMS`. The parser keeps both by default (`--service imessage` to restrict).
- **Group chats**: handled; only your lines (`is_from_me=1`) train.
- This is **macOS-only**. On iPhone-only setups, use Option 2.
