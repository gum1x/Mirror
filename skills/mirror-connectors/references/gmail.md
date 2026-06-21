# Connector: Gmail / Outlook (email)

**Effort:** medium · **Output:** an `mbox` file · **Key idea:** train on your
**Sent** mail — that's your own composed voice. Received mail is other people's
words and is only useful as context.

## Why Sent-only

Email is your most *deliberate* writing. A Mirror trained on Sent mail captures
how you open, structure, sign off, and handle tone in longer-form writing — great
for the `email` surface and for `knowledge_qa`. Pulling the whole mailbox would
drown your voice in newsletters and other people's threads.

## Export steps — Gmail (Google Takeout)

1. Go to **[Google Takeout](https://takeout.google.com)** → Deselect all →
   select **Mail**.
2. Click **All Mail data included** → deselect everything except the **Sent**
   label (and optionally **Drafts**). This keeps the export to *your* writing.
3. Export → choose `.mbox`, download the archive, unzip. You'll get `Sent.mbox`.

## Export steps — Outlook / other IMAP

- **Outlook desktop:** File → Open & Export → Import/Export → Export to a file →
  not mbox-native; easier to use a tool like `imap_tools` or Thunderbird's
  ImportExportTools NG add-on to export the Sent folder to mbox.
- **Any IMAP account:** add it to Thunderbird, then ImportExportTools NG → export
  the Sent folder as mbox.

## Parse

```bash
python scripts/connectors/gmail_mbox_parse.py exports/gmail/Sent.mbox \
    --me sam@example.com -o data/raw/gmail.jsonl
```

`--me` is your email address; every message in a Sent mailbox is from you, so the
parser flags `is_from_me=true` for all of them. Pass `--me` multiple times if you
used several addresses.

## Format notes (handled by the parser)

The parser uses Python's stdlib `mailbox` + `email`:
- Walks each message, prefers the `text/plain` part; falls back to stripping HTML
  from `text/html`.
- **Strips quoted reply text** (lines beginning with `>`, "On … wrote:" blocks,
  and common signature delimiters `-- `) so the model learns *your* new prose,
  not the thread it's replying to.
- `conversation_id` = the recipient (`To:` first address) so threads with one
  person group together; `timestamp` from the `Date:` header; `reply_to` from
  `In-Reply-To`.
- Drops empty bodies, auto-replies, and calendar invites.

## Gotchas

- **Signatures**: the stripper removes a standard `-- ` signature block; if yours
  is unusual, add it to `data.custom_redactions` so it isn't learned as boilerplate.
- **HTML-only mail**: the parser's HTML→text is intentionally simple; for heavy
  HTML newsletters it may be noisy — but those shouldn't be in a Sent export.
- **Length**: emails are long. The formatter can split very long messages or cap
  example length so they don't dominate a fine-tune.
