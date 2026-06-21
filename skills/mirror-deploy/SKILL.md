---
name: mirror-deploy
description: >-
  Serve the finished Mirror so the user can talk to it. Use after evaluation
  passes. Stands up scripts/serve/mirror_chat.py for the chosen path (Claude
  persona+RAG, an OpenAI fine-tune, or a local LoRA), wires in the style card and
  retrieval, and offers an interactive chat plus options to expose it as an API
  or route to it from real surfaces.
---

# Mirror — deploy

Turn the artifact into something the user can actually talk to. One script serves
all three paths; it loads the style card, optionally retrieves from the user's
messages (RAG), and chats.

## Talk to your Mirror (interactive)

```bash
# Path A — Claude persona + RAG (recommended default)
python scripts/serve/mirror_chat.py --path A \
    --style-card persona/style_card.md --corpus data/scrubbed.jsonl --rag

# Path B — OpenAI fine-tune (style card as system; RAG optional)
python scripts/serve/mirror_chat.py --path B --model ft:gpt-4.1-mini:...:mirror-sam \
    --style-card persona/style_card.md --corpus data/scrubbed.jsonl --rag

# Path C — local LoRA (fully offline)
python scripts/serve/mirror_chat.py --path C \
    --base Qwen/Qwen2.5-7B-Instruct --adapter adapters/mirror-sam \
    --style-card persona/style_card.md --corpus data/scrubbed.jsonl --rag
```

Type to chat; the Mirror replies in the user's voice. Retrieval is **off by
default — pass `--rag` to enable it** (omit it to disable); `--semantic` switches
to embedding-based retrieval (needs sentence-transformers); `--k 6` tunes how many
of the user's real messages are retrieved per turn.

## Keys & privacy at serve time

- Path A needs `ANTHROPIC_API_KEY`; only the style card + retrieved snippets +
  the live conversation go to Anthropic.
- Path B needs `OPENAI_API_KEY`; the model is hosted at OpenAI.
- Path C needs the GPU; **nothing leaves the machine**, RAG included.

## Beyond the REPL

- **Batch / eval:** `--batch eval.jsonl --out preds.jsonl` (used by `mirror-evaluation`).
- **As an API:** wrap `mirror_chat.generate()` in a small FastAPI/Flask endpoint;
  the function takes a message list and returns the Mirror's reply. Keep the
  style card and retriever loaded once at startup.
- **Real surfaces (advanced, opt-in):** the same `generate()` can back an
  autoresponder. **Get explicit consent and disclose** — a Mirror replying as the
  user to other people must not be used to deceive. Gate it behind human review
  for anything that matters, and tell counterparties they may be talking to an AI.

## Hybrid serving

For the "best clone," run Path A for reasoning/knowledge and route short stylistic
turns to a Path B/C voice model. Simplest version: serve Path A by default; add a
flag/heuristic (short, casual prompt → call the fine-tuned voice model) later.
Start with one path that passed eval; add the second only if the user wants
tighter surface mimicry.

## Hand-off

Tell the user:
- which path is serving and what (if anything) leaves their machine,
- how to start it again (the exact command),
- how to update it (re-ingest new messages → re-run persona → retrain/refresh),
- and the consent/disclosure expectations if they point it at real conversations.

That's the Mirror. 🪞
