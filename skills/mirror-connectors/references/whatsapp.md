# Connector: WhatsApp

**Effort:** easy · **Output:** one `.txt` per chat · **Limit:** ~40,000 messages
per export (export your most important chats individually to get more).

## Export steps (give these to the user)

**On phone (iOS or Android):**
1. Open the chat (1:1 or group) you want.
2. Tap the contact/group name → scroll down → **Export Chat**.
3. Choose **Without Media** (text only — what we want; media is stripped anyway).
4. Save / send the resulting `.txt` to yourself (AirDrop, email, Files).
5. Repeat for each chat you want in the corpus. Put the `.txt` files in one
   folder, e.g. `exports/whatsapp/`.

> WhatsApp caps an export at ~40k messages and "Without Media" raises the cap.
> For very long chats, this is the most you can get per export.

## Parse

```bash
# One chat:
python scripts/connectors/whatsapp_parse.py "exports/whatsapp/WhatsApp Chat with Alex.txt" \
    --me "Sam" -o data/raw/whatsapp.jsonl

# A whole folder (globs *.txt, concatenates):
python scripts/connectors/whatsapp_parse.py exports/whatsapp/ \
    --me "Sam" -o data/raw/whatsapp.jsonl
```

`--me` is your **display name exactly as it appears in the export** (the name
after the timestamp). If unsure, open the `.txt` and look at how your own lines
are labeled — group exports use the sender's saved contact name.

## Format notes (handled by the parser)

WhatsApp lines look like one of these (locale- and OS-dependent):

```
[2024-03-05, 9:41:12 PM] Sam: running 5 min late lol
2024-03-05, 21:41 - Sam: running 5 min late lol
3/5/24, 9:41 PM - Sam: running 5 min late lol
```

The parser:
- Handles bracketed and dash-delimited variants, 12h/24h, and several date orders.
- Joins multi-line messages (a line with no timestamp continues the previous one).
- Drops system lines ("Messages and calls are end-to-end encrypted", "You
  deleted this message", "<Media omitted>", "image omitted", "‎" markers).
- The conversation id defaults to the filename's "Chat with X" part.

## Gotchas

- **Ambiguous date order** (M/D vs D/M): the parser infers from values where it
  can; pass `--dayfirst` if your locale is D/M and dates look wrong.
- **Your name changed** over the years or differs per group: pass `--me` multiple
  times (`--me "Sam" --me "Sam Rivera"`).
- Group chats: everyone else becomes `other`/context; only your lines train.
