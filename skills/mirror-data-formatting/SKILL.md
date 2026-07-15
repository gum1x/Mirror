---
name: mirror-data-formatting
description: >-
  Turn the user's raw unified-JSONL messages into clean, private, training-ready
  datasets. Use after ingestion (mirror-connectors) and before training. Covers
  normalizing/cleaning text, scrubbing PII before any upload, and building the
  exact dataset format the chosen path needs (OpenAI chat JSONL, ShareGPT for
  LoRA, or a DPO skeleton). Also caps any one conversation from dominating.
---

# Mirror — data formatting

You have `data/raw/*.jsonl` in the unified schema. Now produce the dataset the
trainer eats. Three steps: **normalize → scrub → build.**

## 1. Normalize

Light cleanup that preserves voice (case, emoji, slang are *signal* — keep them):

```bash
python scripts/format/normalize.py data/raw/*.jsonl \
    --min-chars 1 --dedup -o data/clean.jsonl
```

Does: trims whitespace, removes zero-width junk, drops empty/media-only and
exact consecutive duplicates. Optional `--drop-urls` swaps links for `<url>`.

## 2. Scrub PII (required before any upload)

```bash
python scripts/format/pii_scrub.py data/clean.jsonl \
    --custom "my street address" --custom "employer name" -o data/scrubbed.jsonl
```

Redacts emails, phone numbers, credit cards, SSNs, IPs, and any `--custom`
terms (literal strings, case-insensitive — not regexes) → `<EMAIL>`, `<PHONE>`, etc. **Always run this before Path B
(upload to OpenAI).** For Path C (local) it's optional but encouraged. For Path A,
scrub anything you wouldn't want in retrieval results.

> Show the user a `diff`/sample of what changed and confirm before continuing.

## 3. Build the dataset

The builder groups messages by conversation, **splits each into sessions on a
time gap** (so a context window never straddles a 3-week silence), sorts by time,
**merges consecutive messages from the same person into one turn** (people fire
off several texts in a row), then makes examples where **your** turn is the
target the model learns to produce, given the preceding context. It also writes a
`DATASET_CARD.md` next to the output recording provenance and settings.

Pick the format for the chosen path:

```bash
# Path B (OpenAI SFT) — chat JSONL
python scripts/format/build_dataset.py data/scrubbed.jsonl \
    --format openai-chat --system-file persona/style_card.md \
    --context-turns 6 --session-gap-minutes 360 --max-per-convo 400 \
    --holdout 0.1 -o data/train.jsonl   # also writes data/eval.jsonl

# Path C (local LoRA) — ShareGPT (or --format chatml for ChatML-native trainers)
python scripts/format/build_dataset.py data/scrubbed.jsonl \
    --format sharegpt --system-file persona/style_card.md \
    --holdout 0.1 -o data/train.json
# also writes data/eval.json — the eval split is emitted as openai-chat JSONL
# (regardless of --format) so mirror_chat.py --batch can replay it

# Path B refinement (DPO) — preference skeleton (training step fills the rejected side)
python scripts/format/build_dataset.py data/scrubbed.jsonl \
    --format dpo --system-file persona/style_card.md -o data/dpo_skeleton.jsonl
```

Key flags:
- `--context-turns N` — how much prior conversation each example carries (more =
  better grounding, larger/pricier examples). 4–8 is a good range.
- `--session-gap-minutes N` — start a new session when consecutive messages are
  >N min apart (default 360 = 6h; `0` disables). Keeps context coherent; a
  de-facto standard in this space (doppelganger uses 10 min, Izzy Miller 4 h).
- `--max-per-convo N` — cap examples from any single conversation so one chatty
  thread doesn't swamp your voice. Recommended for fine-tunes.
- `--min-target-chars N` — skip trivially short replies ("k", "lol") if you want
  the model to learn substantive responses; keep them for an autoreply Mirror.
- `--holdout R` — split a fraction of *whole conversations* into the eval file
  (the builder prints the exact path it wrote, e.g. `data/eval.jsonl`). Never
  splits mid-conversation. Feeds `mirror-evaluation`.
- `--no-decontaminate` — by default eval examples whose reply also appears in
  train are dropped (so recurring "omw"/"lol" replies don't inflate the score);
  pass this to keep them.
- `--mode reply` (default) needs a preceding message; `--mode autocomplete`
  builds next-passage examples from your writing alone (for `journaling`).

## What the builder produces

**openai-chat** (one example per line):
```json
{"messages":[
  {"role":"system","content":"<your style card>"},
  {"role":"user","content":"you around tonight?"},
  {"role":"assistant","content":"yeah after 8 — wanna grab food?"}
]}
```

**sharegpt** (`{"conversations":[{"from":"system"|"human"|"gpt","value":...}]}`) for
Unsloth/Axolotl/Llama-Factory.

**dpo** (`{"input":{"messages":[...]},"preferred_output":[{"role":"assistant",
"content":"<your real reply>"}],"non_preferred_output":[]}`) — the trainer fills
`non_preferred_output` by sampling the base model, so DPO teaches "more me, less
generic." See `mirror-training/references/path-b-openai-finetune.md`.

## Sanity checks before training

- Re-run `python scripts/lib/schema.py data/scrubbed.jsonl` — confirm `from_me`
  is a healthy share and not ~0.
- Eyeball 10 random examples from `data/train.jsonl`. The `assistant` content
  should *sound like the user*. If it sounds like other people, `--me` was wrong
  upstream — fix the connector, don't paper over it here.
- Count examples. See `mirror-model-selection/references/data-volume-and-epochs.md`
  for what's enough.
