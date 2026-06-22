# Troubleshooting

The common, reproducible failure modes and how to fix them. When in doubt, re-run
`python scripts/lib/schema.py <file>` (or `python scripts/status.py`) and read the
report first.

## "No messages flagged is_from_me=true" / `from_me: 0`

The connector couldn't tell which messages are yours, so there's no voice to
learn. Fix the "who is me" argument, which differs per connector:

| Connector | How you identify yourself |
|-----------|---------------------------|
| WhatsApp, Instagram | `--me "Your Display Name"` (exactly as it appears in the export) |
| Telegram, Slack, Discord | `--me "Name"` and/or `--me-id <stable id>` (id is most reliable) |
| Gmail | `--me you@example.com`; add `--match-from` only for a mixed mbox |
| iMessage | usually nothing — the DB stores `is_from_me`; `--me-handle` only labels the other party |
| SMS (Android) | nothing — auto-detected from `type="2"` (sent) |

Open the export and check how your own lines are labeled, then pass that exact value.

## iMessage: "unable to open database file"

macOS protects `chat.db`. Grant your terminal **Full Disk Access** (System
Settings → Privacy & Security → Full Disk Access), and copy the DB first because
it's locked while Messages runs:

```bash
cp ~/Library/Messages/chat.db /tmp/chat.db
python scripts/connectors/imessage_extract.py /tmp/chat.db -o data/raw/imessage.jsonl
```

## WhatsApp dates look wrong (off by a month, or in the future)

WhatsApp exports are locale-dependent (M/D/Y vs D/M/Y). If dates look swapped,
pass `--dayfirst`:

```bash
python scripts/connectors/whatsapp_parse.py "chat.txt" --me Sam --dayfirst -o out.jsonl
```

## "0 eval examples" after `--holdout`

The holdout splits **whole conversations** (never mid-conversation, to avoid
leakage), and then decontaminates the eval set against train. With very few
conversations there may be nothing to hold out. Options: add more conversations,
lower `--holdout`, or pass `--no-decontaminate` to inspect what's being removed.
On the 24-message sample this is expected (only 2 conversations).

## "0 training examples"

`--mode reply` (the default) needs a message from someone else to reply to. If
your corpus is almost entirely your own writing (e.g. a journal, or Sent email
only), use `--mode autocomplete` instead.

## Tiny dataset → the clone parrots / overfits

Fine-tuning on too little data memorizes instead of generalizing. Under roughly
300 of *your own* messages, prefer **Path A** (Claude persona + RAG), which
retrieves rather than trains. See
`skills/mirror-model-selection/references/data-volume-and-epochs.md`.

## "Which path do I pick?"

- Want it today, smartest, answers from your knowledge → **A** (Claude + RAG).
- Cheap hosted model that texts like you → **B** (OpenAI fine-tune).
- Fully private / offline / you own the weights → **C** (local LoRA).
- Tiny dataset → **A** regardless.

Full logic: `skills/mirror-model-selection`.

## Semantic RAG "fell back to keyword"

`mirror_chat.py --semantic` prints `(semantic retrieval unavailable: ...; using
keyword)` when `sentence-transformers` isn't installed. Either install it
(`pip install ".[rag]"`) or drop `--semantic` to use the stdlib keyword retriever.

## Eval score looks implausibly high or low

Make sure you generated predictions with the **same serving flags you'll deploy
with** (`--style-card`, and `--corpus … --rag` if you use retrieval). Without
them, `mirror_chat.py --batch` scores a generic default prompt, not your Mirror.
Also confirm you're scoring the held-out `data/eval.jsonl`, not training data.

## A script printed a traceback

Re-run the failing stage on its input with `python scripts/lib/schema.py <file>` —
a missing file or a malformed JSONL line is reported with the path and line
number. If a connector produced `from_me: 0`, that's the real problem; fix `--me`
upstream rather than downstream.
