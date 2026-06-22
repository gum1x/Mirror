# Tutorial: zero to a built dataset on the sample

This walks the whole core pipeline on the bundled `examples/sample_messages.jsonl`
(24 messages, 12 from "Sam"). It needs **no API keys, no GPU, and nothing
installed** — the core is stdlib-only. By the end you'll have a style card and a
training dataset, and you'll know exactly where the three paths take over.

Run everything from the repo root.

## 1. Look at the data

```bash
python scripts/lib/schema.py examples/sample_messages.jsonl
```

```json
{
  "total_messages": 24,
  "from_me": 12,
  "from_others": 12,
  "mine_ratio": 0.5,
  "conversations": 2,
  "sources": ["telegram", "whatsapp"]
}
```

`from_me` is the number that matters: those 12 messages are the voice the model
learns. If this were 0, the connector's `--me` was wrong (see TROUBLESHOOTING).

## 2. Normalize

```bash
python scripts/format/normalize.py examples/sample_messages.jsonl --dedup -o data/clean.jsonl
# Wrote 24 cleaned messages -> data/clean.jsonl
```

Light cleanup that keeps your voice intact (case, emoji, slang are signal).

## 3. Analyze your voice into a style card

```bash
python scripts/persona/style_analyze.py data/clean.jsonl --name Sam -o persona/
```

Open `persona/style_card.md`. On this sample it really produces things like
"Write in all lowercase", "Usually no end punctuation", "Natural slang: lol, tbh",
and a list of favorite words. The `REASONING` and `NEVER` sections are stubs for
you to fill in by hand — that's where you capture *how you think*, which stats
can't measure. This file becomes the system prompt for Path A and the
`--system-file` for training Paths B/C.

## 4. Build a training dataset

```bash
python scripts/format/build_dataset.py data/clean.jsonl --format openai-chat \
    --system-file persona/style_card.md --holdout 0.1 -o data/train.jsonl
```

This groups by conversation, splits on a time gap, merges consecutive messages
into turns, and writes examples where *your* reply is the target. It also writes
`DATASET_CARD.md` (provenance: counts, sources, settings) next to the output. One
line of `data/train.jsonl` looks like:

```json
{"messages":[{"role":"system","content":"<your style card>"},
             {"role":"user","content":"you around tonight?"},
             {"role":"assistant","content":"yeah after 8 probably"}]}
```

> Tip: with only 2 conversations, a large `--holdout` can produce 0 eval examples
> (the split is whole-conversation). That's expected on the tiny sample; on a real
> corpus you'll have many conversations. See TROUBLESHOOTING.

## 5. Where the three paths take over

You now have a style card and a dataset. From here each path needs real
keys/hardware, so the tutorial stops at a built dataset:

| Path | What you'd run next | What leaves your machine |
|------|---------------------|--------------------------|
| A. Claude persona + RAG | `scripts/serve/mirror_chat.py --path A --style-card persona/style_card.md --corpus data/clean.jsonl --rag` | style card + retrieved snippets, per request |
| B. OpenAI fine-tune | `scripts/train/openai_finetune.py data/train.jsonl --validate-only` then train | the scrubbed dataset (one upload) |
| C. Local LoRA | `scripts/train/lora_train.py data/train.json --base Qwen/Qwen2.5-7B-Instruct` (build with `--format sharegpt`) | nothing |

See `skills/mirror-model-selection` for how to choose, and `skills/mirror-training`
for each recipe. On real data, run `scripts/format/pii_scrub.py` between steps 2
and 3, and **always** before any Path B upload.

## What you learned

The pipeline is a chain of small, inspectable scripts joined by one schema. Each
stage reads a file and writes a file, so you can stop, look, and resume anywhere
(`python scripts/status.py` shows where you are).
