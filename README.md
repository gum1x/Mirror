# Mirror

Self-hosted clone of your own writing voice. Pulls your real messages from the apps you already use (iMessage, WhatsApp, Telegram, Gmail, Slack, Discord, Instagram, SMS), normalizes them into one format, figures out how you actually write (length, punctuation, emoji, slang, the way you explain things), picks a training method that fits your data and how much privacy you want, trains it, and checks how close it sounds to you on conversations it never saw. Goal is something that texts in your cadence and answers the way you would, grounded in what you've actually said, not a generic chatbot wearing your name.

9 skills, 20 runnable scripts, no dependencies for the core pipeline.

> Built with AI assistance (Anthropic's Claude). I've reviewed and tested it, but read the code before running it on your own data, and treat the privacy notes as guidance, not a guarantee.

## Why I built this

Same recipe everywhere for this kind of project: grab one chat export, fine-tune a small model on it, ship it. That gets you the surface stuff fine, your cadence, your filler words, how short your texts run. The problem is a fine-tune doesn't actually know anything. Ask it something it didn't see in training and it'll make something up in your voice, which is worse than a wrong answer in a stranger's voice, because now it sounds like you said it.

So Mirror keeps two things apart. Your voice goes into the model, either as fine-tuned weights or a style prompt. What you actually know and think stays in your real messages and gets pulled in by retrieval when it's relevant. It also doesn't assume everyone wants the same setup, so it asks a few questions first and suggests one of three paths: Claude with a style prompt plus retrieval if you want the strongest version with no GPU, an OpenAI fine-tune if you want your voice baked into a hosted model, or a local LoRA if you'd rather nothing leave your machine.

None of this is new, people have been cloning themselves from chat history for a while (comparison table further down), and Mirror borrows from them. What I mostly tried to get right is the boring stuff: use each app's own export instead of scraping it, scrub PII locally before anything uploads, split conversations on a time gap so a six-week silence doesn't land inside one training example, keep the eval set away from training, and actually measure how close the output is to you instead of eyeballing it. Whether that's worth the extra moving parts is your call.

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
                                    │  Path B: OpenAI fine-tune (SFT, DPO) │
                                    │  Path C: local LoRA (Llama / Qwen)   │
                                    └────────────────┬─────────────────────┘
                                                     ▼
                                   training ──▶ evaluation ──▶ deploy ──▶ 🪞
                                                     ▲            │
                                                     └─ iterate ──┘
```

Each box is a skill under `skills/`. Each skill calls a script under `scripts/`, and the choices the skills make are backed by notes in their `references/` folders.

## Quickstart

Mirror is meant to be driven by Claude. The short version:

```bash
# 1. Install the skills (Claude Code)
cp -r skills/* ~/.claude/skills/

# 2. The core pipeline (ingest, format, persona) is stdlib-only, no install.
#    For a training or serving path, install just that path's deps:
pip install ".[cloud]"      # Paths A and B: Claude + OpenAI + semantic RAG
#   pip install ".[lora]"   # Path C: local QLoRA (heavy GPU stack)

# 3. In Claude Code (or Claude.ai with the Agent Skills), say:
/mirror
```

The `mirror` skill takes it from there. It interviews you, walks you through exporting your data, and runs the pipeline. You can also drive each stage by hand:

```bash
# Parse a WhatsApp export into the unified schema
python scripts/connectors/whatsapp_parse.py "WhatsApp Chat with Alex.txt" --me "Sam" -o data/raw/whatsapp.jsonl

# Clean and scrub PII (always scrub before any upload)
python scripts/format/normalize.py data/raw/*.jsonl --dedup -o data/clean.jsonl
python scripts/format/pii_scrub.py data/clean.jsonl -o data/scrubbed.jsonl

# Analyze your voice into a style card (it becomes the system prompt)
python scripts/persona/style_analyze.py data/scrubbed.jsonl --name "Sam" -o persona/

# Build a training dataset. Your messages become the assistant's voice;
# sessions split on a 6h gap, the eval set is decontaminated, a dataset card is written.
python scripts/format/build_dataset.py data/scrubbed.jsonl --format openai-chat \
    --system-file persona/style_card.md --holdout 0.1 -o data/train.jsonl

# ...then choose a path, train (A/B/C), evaluate, and serve.
```

See `skills/mirror/SKILL.md` for the full flow.

## The three paths

Mirror doesn't assume one approach. It suggests one based on your answers (the logic lives in `skills/mirror-model-selection`):

| Path | What it produces | Best when | Trains weights? | Runs where |
|------|------------------|-----------|-----------------|------------|
| A. Claude persona + RAG | A style prompt (your style card) plus retrieval over your real messages, on Claude | You want the strongest clone and the best reasoning, with no GPU and nothing to train | No | Anthropic API |
| B. OpenAI fine-tune | A `gpt-4.1` or `gpt-4.1-mini` model that writes in your voice (SFT, optionally plus DPO) | You want your surface voice baked into a hosted model, cheaply | Yes (hosted) | OpenAI API |
| C. Local LoRA | A LoRA adapter on Llama or Qwen that you own | You want privacy and offline use, and to keep the weights | Yes (you) | Your GPU or cloud |

A lot of people end up wanting a mix: Path A for reasoning and knowledge, plus a Path B or C model for pure voice tasks like autoreply. Mirror will suggest one if you're not sure.

## Privacy and safety

- Local by default. Parsing, scrubbing, and dataset building happen on your machine. Nothing leaves until you pick a path that needs it.
- You're told before data leaves. Path A sends retrieved snippets plus your style card to Anthropic, Path B uploads your dataset to OpenAI, Path C sends nothing. Mirror says which one applies and asks first.
- PII scrubbing runs before any upload (`scripts/format/pii_scrub.py`): emails, phone numbers, cards, SSNs, IPs, basic street addresses, and any custom terms you add. It is regex-based and best-effort, so look at the output and add your own terms for names and anything unusual.
- Consent matters. Group chats contain other people's words. Mirror only trains on your messages; everyone else is context. Don't point it at a real conversation to deceive someone.
- Only your own accounts. Export from accounts you own and control.

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
  connectors/  format/  persona/  train/  eval/  serve/  maintenance/  lib/
  status.py               ← build progress + the next command to run
config/        mirror.config.example.yaml
examples/      sample_messages.jsonl
docs/          TUTORIAL.md · TROUBLESHOOTING.md
tests/         stdlib-only regression suite (also run by CI)
```

## The data contract

Everything flows through one schema, the unified message record, defined and sanity-checked in `scripts/lib/schema.py`. Connectors emit it, everything downstream reads it. One JSON object per line:

```json
{"source":"whatsapp","conversation_id":"Alex","timestamp":"2024-03-05T21:41:12Z","sender":"me","is_from_me":true,"text":"running 5 min late lol","reply_to":null,"media":null}
```

## Prior art

Cloning yourself from chat history is well-trodden ground, and Mirror leans on a lot of work that came before it:

| Project | Source(s) | Method | Eval | Notes |
|---------|-----------|--------|------|-------|
| [WeClone](https://github.com/xming521/WeClone) (~17k stars) | WeChat, Telegram | LoRA SFT (LLaMA-Factory) | demo UI + fixed question file | The popular one; also scrubs PII with Presidio |
| [ai-clone-whatsapp](https://github.com/kinggongzilla/ai-clone-whatsapp) | WhatsApp | QLoRA (ShareGPT) | none | Clean single-source reference |
| [WhatsApp-Llama](https://github.com/Ads97/WhatsApp-Llama) | WhatsApp | QLoRA | informal Turing test (caught 2/20) | The "Show HN" build |
| [doppelganger](https://github.com/furiousteabag/doppelganger) | Telegram | LoRA | none | 10-min session windowing |
| [imessage-lm](https://github.com/Dynosol/imessage-lm) | iMessage | LoRA (Unsloth) | none | MIT |
| [lad-gpt](https://github.com/bernhard-pfann/lad-gpt) | WhatsApp | transformer from scratch | informal | nanoGPT-style |
| [Izzy Miller, "robo-boys"](https://www.izzy.co/blogs/robo-boys.html) | iMessage (488k msgs) | Alpaca full fine-tune | informal | 4-hr session windowing |
| [Edward Donner, 240k msgs](https://edwarddonner.com/2024/01/02/fine-tuning-an-llm-on-240k-text-messages/) | iMessage + WhatsApp | QLoRA | informal | writes up the "mundane loop" failure mode |

Most of these build on [Unsloth](https://github.com/unslothai/unsloth), [LLaMA-Factory](https://github.com/hiyouga/LLaMA-Factory), or [Axolotl](https://github.com/axolotl-ai-cloud/axolotl).

Where Mirror differs: it reads from several apps into one schema instead of a single source, it picks a training method from your answers instead of defaulting to a 7B LoRA, and it reports a style-match score on a held-out set instead of relying on an eyeball check. Trade-off is more moving parts. If you only care about one source and one model, one of the projects above is probably the simpler choice.

Things it borrows from the field and the wider community: time-gap session windowing (like doppelganger and Izzy Miller), keeping train and eval separate, dataset cards for provenance, seeded splits, merging consecutive messages into one turn, and ShareGPT / OpenAI-chat / ChatML / DPO output formats. The reasoning behind the defaults is in `skills/mirror-model-selection/references`.

## Running the tests

```bash
make test                         # runs both suites; or: pytest
python tests/test_pipeline.py     # pipeline + regression suite
python tests/test_connectors.py   # connector regression suite
```

The suite runs the stdlib pipeline end to end on the bundled sample and pins bugs found in review so they don't come back. CI runs it on every push.

## License

MIT. See [LICENSE](LICENSE).

Use it on your own data, for yourself.
