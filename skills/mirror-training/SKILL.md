---
name: mirror-training
description: >-
  Execute the chosen training path to produce the Mirror. Use after
  model-selection has set training.path in mirror.config.yaml. Path A configures
  Claude with the style card + RAG (no training). Path B runs an OpenAI SFT
  (optionally DPO) fine-tune. Path C runs a local QLoRA fine-tune on Llama/Qwen.
  Read the matching reference in references/ and run the matching script. Always
  tell the user what leaves their machine before it does.
---

# Mirror — training

Read `training.path` from `mirror.config.yaml`, open the matching reference, and
run it. **Before anything uploads, state exactly what leaves the machine and get
a yes.**

| Path | Reference | Script | Leaves the machine? |
|------|-----------|--------|---------------------|
| **A — Claude persona + RAG** | `references/path-a-claude-prompt-rag.md` | `scripts/serve/mirror_chat.py` (config only) | At *serve* time: style card + retrieved snippets per query. No training upload. |
| **B — OpenAI fine-tune** | `references/path-b-openai-finetune.md` | `scripts/train/openai_finetune.py` | **Yes** — the whole scrubbed dataset uploads to OpenAI once. |
| **C — local LoRA** | `references/path-c-opensource-lora.md` | `scripts/train/lora_train.py` | **No** — stays on your GPU. |

## Path A — Claude persona + RAG (no training loop)

There's nothing to "train." You assemble the runtime:
1. Finalize `persona/style_card.md` (the system prompt).
2. Build a retrieval index over `data/scrubbed.jsonl` so answers are grounded in
   the user's real words.
3. That's the Mirror — go straight to `mirror-evaluation`, then `mirror-deploy`.

Fastest path to a working Mirror. Read the Path A reference for the RAG setup.

## Path B — OpenAI fine-tune (SFT, optional DPO)

```bash
# 1. Pre-flight: validate the dataset, then SHOW the user a sample of what uploads.
python scripts/train/openai_finetune.py data/train.jsonl --validate-only

# 2. SFT (uploads dataset, creates job, polls to completion, prints model id):
export OPENAI_API_KEY=...
python scripts/train/openai_finetune.py data/train.jsonl \
    --base gpt-4.1-mini --suffix mirror-sam

# 3. (optional) DPO polish after SFT, if eval says "too generic":
python scripts/train/openai_finetune.py data/dpo.jsonl \
    --method dpo --base <sft-model-id> --suffix mirror-sam-dpo
```

Record the returned `ft:...` model id in `mirror.config.yaml` for serving. Read
the Path B reference for DPO data prep and hyperparameters.

## Path C — local QLoRA (Llama / Qwen)

```bash
# Needs a GPU + the lora extras (see requirements.txt; Unsloth recommended).
python scripts/train/lora_train.py data/train.json \
    --base Qwen/Qwen2.5-7B-Instruct --epochs 3 --out adapters/mirror-sam
```

Produces a LoRA adapter you own. Nothing leaves the machine. Read the Path C
reference for VRAM guidance, hyperparameters, and merge/export.

## After any path

- Note the resulting artifact (Claude config / `ft:` id / adapter dir) in
  `mirror.config.yaml`.
- Go to `mirror-evaluation`. Don't ship on vibes — measure on the holdout.
- If eval falls short, the references and `data-volume-and-epochs.md` say which
  lever to pull (epochs, data, DPO, RAG) — change one and retrain.
