# Mirror 

**A framework that trains an AI to speak, answer, and think like *you*.**

> ⚠️ **Built with AI.** This project was designed and written with AI assistance
> (Anthropic's Claude). It has been reviewed and tested, but treat it as a
> starting point: read the code before running it on your own data, and treat the
> privacy and security notes below as guidance, not guarantees.

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

# 2. The core pipeline (ingest → format → persona) is STDLIB-ONLY — no install.
#    For a training/serving path, install just that path's deps:
pip install ".[cloud]"      # Paths A & B: Claude + OpenAI + semantic RAG
#   pip install ".[lora]"   # Path C: local QLoRA (heavy GPU stack)

# 3. In Claude Code (or Claude.ai with the Agent Skills), say:
/mirror
```

The `mirror` skill takes it from there — it interviews you, walks you through exporting your data, and runs the pipeline. You can also drive each stage by hand:

```bash
# Parse a WhatsApp export into the unified schema
python scripts/connectors/whatsapp_parse.py "WhatsApp Chat with Alex.txt" --me "Sam" -o data/raw/whatsapp.jsonl

# Clean + scrub PII (always scrub before any upload)
python scripts/format/normalize.py data/raw/*.jsonl --dedup -o data/clean.jsonl
python scripts/format/pii_scrub.py data/clean.jsonl -o data/scrubbed.jsonl

# Analyze your voice into a style card (it becomes the system prompt)
python scripts/persona/style_analyze.py data/scrubbed.jsonl --name "Sam" -o persona/

# Build a training dataset — your messages become the assistant's voice;
# sessions split on a 6h gap, eval is decontaminated, a dataset card is written
python scripts/format/build_dataset.py data/scrubbed.jsonl --format openai-chat \
    --system-file persona/style_card.md --holdout 0.1 -o data/train.jsonl

# ...then choose a path, train (A/B/C), evaluate, and serve.
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

Everything flows through one schema (the **unified message record**), defined and sanity-checked in [`scripts/lib/schema.py`](scripts/lib/schema.py). Connectors emit it; everything downstream consumes it. One JSON object per line:

```json
{"source":"whatsapp","conversation_id":"Alex","timestamp":"2024-03-05T21:41:12Z","sender":"me","is_from_me":true,"text":"running 5 min late lol","reply_to":null,"media":null}
```

---

## Prior art & how Mirror compares

Cloning yourself from chat history is a well-trodden space. Mirror is designed to
be broader and more rigorous than the typical single-source weekend project.

| Project | Source(s) | Method | Eval | Notes |
|---------|-----------|--------|------|-------|
| [WeClone](https://github.com/xming521/WeClone) (~17k★) | WeChat, Telegram | LoRA SFT (LLaMA-Factory) | demo UI + fixed Q file | The category leader; also scrubs PII (Presidio) |
| [ai-clone-whatsapp](https://github.com/kinggongzilla/ai-clone-whatsapp) | WhatsApp | QLoRA (ShareGPT) | — | Clean single-source reference |
| [WhatsApp-Llama](https://github.com/Ads97/WhatsApp-Llama) | WhatsApp | QLoRA | informal Turing test (caught 2/20) | The "Show HN" build |
| [doppelganger](https://github.com/furiousteabag/doppelganger) | Telegram | LoRA | — | **10-min session windowing** |
| [imessage-lm](https://github.com/Dynosol/imessage-lm) | iMessage | LoRA (Unsloth) | — | MIT |
| [lad-gpt](https://github.com/bernhard-pfann/lad-gpt) | WhatsApp | transformer from scratch | informal | nanoGPT-style |
| [Izzy Miller — "robo-boys"](https://www.izzy.co/blogs/robo-boys.html) | iMessage (488k msgs) | Alpaca full FT | informal | **4-hr session windowing** |
| [Edward Donner — 240k msgs](https://edwarddonner.com/2024/01/02/fine-tuning-an-llm-on-240k-text-messages/) | iMessage+WhatsApp | QLoRA | Turing-ish | documents the "mundane loop" failure mode |

Tooling everyone builds on: [Unsloth](https://github.com/unslothai/unsloth),
[LLaMA-Factory](https://github.com/hiyouga/LLaMA-Factory),
[Axolotl](https://github.com/axolotl-ai-cloud/axolotl).

**What Mirror adds over the field:** multi-connector ingestion into one schema
(everyone else is single-source); principled **path selection** (prompt+RAG vs
SFT vs DPO vs QLoRA by use case/privacy/budget — nobody else reasons about this);
a real **quantitative eval** with a conversation-level holdout (the field stops at
an informal Turing test); and an explicit **privacy/egress contract**.

**Best practices Mirror also implements** (borrowed from the projects above and
the wider community): time-gap **session windowing** (`--session-gap-minutes`, à
la doppelganger/Izzy Miller), train/eval **decontamination**, **dataset cards**
for provenance/reproducibility, seeded splits, consecutive-message merging, and
ShareGPT/OpenAI-chat/ChatML/DPO format support. See
[`skills/mirror-model-selection/references/`](skills/mirror-model-selection/references/)
for the research behind the defaults.

## Engineering

- **Tested:** `tests/test_pipeline.py` runs the stdlib pipeline end-to-end and
  pins regressions (run `python tests/test_pipeline.py` or `pytest`); CI runs it
  on every push.
- **Installable extras:** `pyproject.toml` carries per-path optional dependencies
  (`.[cloud]`, `.[lora]`, …); the core needs nothing.

---

Built as a demonstration of composing many Claude skills into a real, reviewed
pipeline. Use it on your own data, for yourself.
