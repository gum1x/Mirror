---
name: mirror-connectors
description: >-
  Export the user's message history from each platform and convert it into
  Mirror's unified JSONL schema. Use during the ingestion stage of a Mirror
  build, or whenever the user wants to pull their messages from WhatsApp,
  iMessage/SMS, Telegram, Gmail/Outlook, Slack, Discord, Instagram, Messenger,
  or Signal for training. Covers the manual export steps per platform plus the
  parser script that normalizes each export.
---

# Mirror — connectors

Your job: get the user's words out of each app and into `data/raw/<source>.jsonl`
in the unified schema (`scripts/lib/schema.py`). Most platforms require a
**manual export by the user** (their data, their account, their consent) — you
provide exact steps, they hand you a file, you run the parser.

## Workflow per platform

1. Read the platform's reference (`references/<platform>.md`) and give the user
   the **export steps**. These change rarely but do change — if the UI differs,
   adapt and tell the user.
2. The user produces an export file/folder.
3. Run the matching parser to emit unified JSONL.
4. Validate: `python scripts/lib/schema.py data/raw/<source>.jsonl`. Show the
   `from_me` count and conversation count.
5. Move to the next enabled connector; repeat.

## Platform → reference → parser

| Platform | Export reference | Parser | Export effort |
|----------|------------------|--------|---------------|
| WhatsApp | `references/whatsapp.md` | `scripts/connectors/whatsapp_parse.py` | Easy (in-app, per chat, ~40k msg cap) |
| Telegram | `references/telegram.md` | `scripts/connectors/telegram_parse.py` | Easy (Desktop → JSON, full history) |
| iMessage / SMS (macOS) | `references/imessage.md` | `scripts/connectors/imessage_extract.py` | Medium (reads `chat.db`, needs Full Disk Access) |
| Gmail / Outlook | `references/gmail.md` | `scripts/connectors/gmail_mbox_parse.py` | Medium (Takeout → mbox; **Sent** mail only) |
| Slack / Discord | `references/slack-discord.md` | `scripts/connectors/*` (JSON) | Medium |
| Instagram / Messenger | `references/sms-signal-instagram.md` | `scripts/connectors/instagram_parse.py` | Medium (Meta data download → JSON) |
| SMS (Android) / Signal | `references/sms-signal-instagram.md` | (XML / desktop backup) | Medium–Hard |

### Live MCP connectors (optional)

If the session has Gmail / Google Drive MCP tools available, you can pull recent
**Sent** email directly instead of waiting on a Takeout export — search the
user's sent mail, then write each as a `MessageRecord` with `is_from_me=true`.
Use this for a quick start; Takeout is still better for *full* history. Always
confirm with the user before reading their live mailbox.

## The one rule every parser follows: who is "me"?

Training depends entirely on `is_from_me`. Each parser takes a `--me` hint (name,
handle, phone, or email depending on platform) and flags the user's own messages.
Pull these from `identity` in `mirror.config.yaml`. If a parser can't confidently
identify "me," it says so — don't let a run finish with `from_me == 0`.

## After all connectors

Concatenate into one corpus and hand to `mirror-data-formatting`:

```bash
python scripts/lib/schema.py data/raw/*.jsonl   # combined sanity report
```

Tips to pass along:
- **More is better, but balance matters.** One giant group chat can swamp your
  voice. The formatter can cap per-conversation contribution.
- **Sent email ≈ your most "composed" voice; texts ≈ your most casual voice.**
  Mixing both gives the model range. Tell the formatter which surface you're
  targeting so it can weight accordingly.
- **Exports can be large.** Parsers stream line-by-line and never load the whole
  file into memory.
