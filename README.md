# Mirror 🪞

**A framework that trains an AI to speak, answer, and think like *you*.**

Mirror is an end-to-end pipeline, driven by [Claude skills](https://docs.claude.com/en/docs/agents-and-tools/agent-skills/overview), that:

1. **Connects** to where your words already live — email, iMessage, WhatsApp, Telegram, Slack, Discord, Instagram, SMS, and more.
2. **Downloads & formats** your real messages into a clean, private, training-ready dataset.
3. **Analyzes your voice** — tone, vocabulary, message length, punctuation, reasoning patterns — into a portable *style card*.
4. **Picks the right model and training method** for *your* use case, data volume, budget, and privacy needs.
5. **Trains / configures** the model (Claude persona + RAG, an OpenAI fine-tune, or a fully-local LoRA — Mirror chooses).
6. **Evaluates** how convincingly the result sounds like you, and iterates.
7. **Deploys** a chat endpoint you can talk to — your Mirror.

By the end you have an AI that texts in your cadence, answers questions the way you would, and reasons the way you do.

> **The whole thing is interactive.** Mirror interviews you, recommends an approach with its reasoning, and asks before doing anything irreversible or anything that sends your data off-device. Your messages are *yours* — Mirror is privacy-first and local-by-default.

---

## How it works

```
                                ┌─────────────────────────────────────────┐
   YOU ──/mirror──▶  interview  │  goals · use case · privacy · budget     │
                                └───────────────┬─────────────────────────┘
                                                ▼
        ┌──────────── connectors ───────────┐   normalize    ┌── persona ──┐
        │ gmail · imessage · whatsapp ·      │ ─────────────▶ │ style card  │
        │ telegram · slack · discord · sms   │  unified JSONL  │ (your voice)│
        └────────────────────────────────────┘                └──────┬──────┘
                                                ▼                     │
                                       ┌─────────────────┐            │
                                       │ data-formatting │            │
                                       │  PII scrub +     │            │
                                       │  dataset build   │            │
                                       └────────┬────────┘            │
                                                ▼                     ▼
                                    ┌──────────────────────────────────────┐
                                    │           model-selection            │
                                    │  Path A: Claude persona + RAG        │
                                    │  Path B: OpenAI fine-tune (SFT→DPO)  │
                                    │  Path C: local LoRA (Llama / Qwen)   │
                                    └────────────────┬─────────────────────┘
                                                     ▼
                                   training ──▶ evaluation ──▶ deploy ──▶ 🪞
                                                     ▲            │
                                                     └─ iterate ──┘
```

Each box is a **skill** under [`skills/`](skills/). Each skill calls **real, runnable scripts** under [`scripts/`](scripts/). The decisions skills make are backed by **research** in their `references/` folders.

---

## Quickstart

Mirror is meant to be *driven by Claude*. The fastest path:

```bash
# 1. Install the skills (Claude Code)
cp -r skills/* ~/.claude/skills/

# 2. Install Python deps for the scripts
pip install -r requirements.txt

# 3. In Claude Code (or Claude.ai with the Agent Skills), say:
/mirror
```

The `mirror` skill takes it from there — it interviews you, walks you through exporting your data, and runs the pipeline. You can also drive each stage by hand:

```bash
# Parse a WhatsApp export into the unified schema
python scripts/connectors/whatsapp_parse.py "WhatsApp Chat with Alex.txt" --me "Sam" -o data/raw/whatsapp.jsonl

# Build a training dataset (your messages become the assistant's voice)
python scripts/format/build_dataset.py data/raw/*.jsonl --format openai-chat -o data/train.jsonl

# Analyze your voice into a style card
python scripts/persona/style_analyze.py data/raw/*.jsonl -o persona/

# ...then train (Path A/B/C), evaluate, and serve.
```

See [`skills/mirror/SKILL.md`](skills/mirror/SKILL.md) for the full orchestration and [`docs map`](#repository-map) below.

---

## The three training paths

Mirror doesn't assume one approach. It **chooses** based on your answers (full logic in [`skills/mirror-model-selection`](skills/mirror-model-selection/)):

| Path | What it produces | Best when | Trains weights? | Runs where |
|------|------------------|-----------|-----------------|------------|
| **A — Claude persona + RAG** | A strong system prompt (your style card) + retrieval over your real messages, on Claude | You want the *smartest* clone, best reasoning/knowledge fidelity, fastest to stand up, no GPU | No | Anthropic API |
| **B — OpenAI fine-tune** | A `gpt-4.1` / `gpt-4.1-mini` model that *writes* in your voice (SFT, optionally + DPO) | You want a hosted model that has your surface voice "baked in" cheaply | Yes (hosted) | OpenAI API |
| **C — Local LoRA** | A LoRA adapter on Llama / Qwen you fully own | Maximum privacy, offline, you own the weights | Yes (you) | Your GPU / cloud |

Most people want a **hybrid**: Path A for reasoning + knowledge, optionally a Path B/C model for pure surface-voice tasks (autoreply). Mirror will tell you.

---

## Privacy & safety (read this)

- **Local-by-default.** Parsing, scrubbing, and dataset building happen on your machine. Nothing leaves until you choose a path that requires it.
- **You're told before data leaves.** Path A sends retrieved snippets + your style card to Anthropic; Path B uploads your dataset to OpenAI; Path C sends nothing. Mirror states this explicitly and asks first.
- **PII scrubbing** runs before any upload ([`scripts/format/pii_scrub.py`](scripts/format/pii_scrub.py)) — emails, phone numbers, cards, SSNs, addresses, and configurable custom terms.
- **Consent matters.** Group chats contain other people's words. Mirror trains on *your* messages (the `assistant` voice); other participants only ever form context. Don't deploy a Mirror that impersonates you to deceive others.
- **Only your own accounts.** Export data from accounts you own and control.

---

## Repository map

```
skills/
  mirror/                 ← master orchestrator (start here: /mirror)
  mirror-interview/       ← the questions Mirror asks you
  mirror-connectors/      ← export guides per platform (+ references/)
  mirror-data-formatting/ ← normalize, scrub PII, build datasets
  mirror-persona-analysis/← extract your voice into a style card
  mirror-model-selection/ ← choose path + model (+ research references/)
  mirror-training/        ← recipes for Path A / B / C (+ references/)
  mirror-evaluation/      ← measure how "you" the Mirror sounds
  mirror-deploy/          ← serve and chat with your Mirror
scripts/
  connectors/  format/  persona/  train/  eval/  serve/  lib/
config/        mirror.config.example.yaml
examples/      sample_messages.jsonl
```

## The data contract

Everything flows through one schema (the **unified message record**), defined and validated in [`scripts/lib/schema.py`](scripts/lib/schema.py). Connectors emit it; everything downstream consumes it. One JSON object per line:

```json
{"source":"whatsapp","conversation_id":"Alex","timestamp":"2024-03-05T21:41:12Z","sender":"me","is_from_me":true,"text":"running 5 min late lol","reply_to":null,"media":null}
```

---

Built as a demonstration of composing many Claude skills into a real pipeline. Use it on your own data, for yourself.
