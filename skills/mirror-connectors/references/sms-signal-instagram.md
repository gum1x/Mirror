# Connector: Instagram / Messenger / Android SMS / Signal

Grouped because each is a "data download" or backup format. All map cleanly to
the unified schema.

## Instagram & Facebook Messenger (Meta)

1. **[Meta Accounts Center](https://accountscenter.meta.com) → Your information
   and permissions → Download your information.**
2. Select **Messages** only, **Format: JSON**, date range = all, media quality
   low (we only use text).
3. You'll get a `.zip` → `your_instagram_activity/messages/inbox/<thread>/message_1.json`
   (or `messages/inbox/...` for Messenger).

Structure (note the classic mojibake — Meta double-encodes UTF-8):
```json
{
  "participants": [{"name": "Sam"}, {"name": "Alex"}],
  "messages": [
    {"sender_name": "Sam", "timestamp_ms": 1709675472000, "content": "running 5 min late lol"}
  ]
}
```

**Parse:**
```bash
python scripts/connectors/instagram_parse.py "exports/instagram/messages/inbox" \
    --me "Sam" -o data/raw/instagram.jsonl
```
The parser:
- Walks every `message_*.json` thread folder.
- **Fixes Meta's mojibake** (`content.encode('latin-1').decode('utf-8')`) so
  emoji and accents come back correctly.
- Flags `is_from_me` where `sender_name == --me`.
- `timestamp_ms` → ISO UTC; `participants` → `conversation_id`.
- Skips reactions, "liked a message", calls, and unsent/empty messages.

(Same parser handles Messenger — point it at the Messenger `inbox` folder.)

## Android SMS / MMS

Use **SMS Backup & Restore** (Play Store) → back up to **XML**. The XML has
`<sms address="..." date="..." type="2" body="..."/>` where `type=2` means
*sent by you* (`type=1` is received). Map `type==2` → `is_from_me=true`,
`date` (epoch ms) → timestamp, `address` → `conversation_id`. A short XML parser
(stdlib `xml.etree.ElementTree`) does it; copy `whatsapp_parse.py`'s CLI shape.

## Signal

Hardest — Signal's DB is encrypted by design.
- **Signal Desktop**: the SQLite DB is encrypted with a key in `config.json`;
  community tools (`signalbackup-tools`, `sigtop`) can decrypt and export to
  JSON/CSV. Then import like Telegram.
- **Android backup**: a `.backup` file decrypted with your 30-digit passphrase
  via `signalbackup-tools`.

Given the friction, only pursue Signal if it's a major share of the user's
conversations. Otherwise skip it.

## iCloud / generic

For anything not listed: if you can get it to **JSON or CSV with (sender,
timestamp, text)**, the formatter's generic importer can map it. Tell Mirror the
column/field names and which value means "you," and it'll write a tiny adapter.
