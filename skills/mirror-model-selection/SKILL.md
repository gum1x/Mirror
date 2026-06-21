---
name: mirror-model-selection
description: >-
  Decide HOW to build the Mirror — which of the three paths (Claude persona+RAG,
  OpenAI fine-tune, or local LoRA), which base model, and which training method
  (prompt+RAG / SFT / SFT+DPO / QLoRA) — based on the user's use case, privacy
  needs, budget, hardware, and actual data volume. Use after you know the data
  volume (post-formatting) and the interview answers. Backed by research in
  references/.
---

# Mirror — model selection

Choose the path, the model, and the method. Walk the tree with the user's
interview answers **plus the real example count** from `build_dataset.py`. State
your recommendation and the reasoning, show the trade-offs, then record the
decision in `mirror.config.yaml` under `training`.

Read the references for the details behind each call:
- `references/model-matrix.md` — which concrete models, current as of 2026.
- `references/training-approaches.md` — prompt+RAG vs SFT vs DPO vs LoRA.
- `references/data-volume-and-epochs.md` — how much data, how many "trains."

## The decision tree

```
START
│
├─ Must NOTHING leave the machine? (privacy = fully_local, or "own the weights")
│     └─ YES → PATH C: local LoRA (Llama/Qwen via Unsloth). Need a GPU or rent one.
│
├─ Is the corpus small? (< ~300 of the user's OWN messages)
│     └─ YES → PATH A: Claude persona + RAG. Too little to fine-tune without
│              parroting. (Revisit after they gather more data.)
│
├─ Is the job mostly REASONING / KNOWLEDGE / thought-partner?
│     └─ YES → PATH A: Claude persona + RAG. The frontier model's reasoning +
│              retrieval over the user's real words beats a fine-tune on facts.
│
├─ Is the job mostly SURFACE VOICE at scale? (autoreply, "texts exactly like me")
│   and uploading a scrubbed dataset to one vendor is OK (hosted_finetune)?
│     └─ YES → PATH B: OpenAI SFT on gpt-4.1-mini (add DPO if "indistinguishable").
│
└─ Want the best overall clone and cloud is OK?
      └─ HYBRID: PATH A for brains/knowledge + a PATH B or C model for pure
         voice tasks. Recommend A first (works today), add the voice model later.
```

## Quick recommendation table

| User's situation | Recommend | Model | Method |
|------------------|-----------|-------|--------|
| "I want it today, smartest possible, answers like me" | **A** | `claude-opus-4-8` | style card (system prompt) + RAG |
| "Cheap autoresponder that nails my texting voice" | **B** | `gpt-4.1-mini` | SFT |
| "Indistinguishable from me in writing" + lots of data | **B** | `gpt-4.1` | SFT → DPO |
| "Must be fully private / offline / I own it" | **C** | `Qwen2.5-7B-Instruct` or `Llama-3.1-8B` | QLoRA |
| "Tiny dataset (< 300 of my msgs)" | **A** | `claude-opus-4-8` | prompt + RAG |
| "Full clone, money's fine, cloud OK" | **Hybrid** | Opus 4.8 + a B/C voice model | RAG + SFT/LoRA |

## Why these defaults (the short version)

- **Claude has no public weight fine-tuning**, so the Claude path is *prompt
  engineering + retrieval*, not training. That's a feature: you get the strongest
  reasoning model, grounded in the user's real words via RAG, standable-up in
  minutes, with nothing trained. It's the best path for "answers/thinks like me."
- **Fine-tuning is for surface voice, not knowledge.** SFT bakes in cadence,
  length, punctuation, and idiom. It does *not* reliably add facts — a fine-tune
  asked something it never saw will hallucinate in your voice. For knowledge,
  ground with RAG (Path A) or combine.
- **DPO is a second pass** after SFT: pair the user's real reply (preferred)
  against a generic model reply (rejected) to push "more them, less assistant."
  Use it only when SFT alone isn't convincing enough.
- **Open-source LoRA is the privacy/ownership path.** QLoRA fine-tunes a 7–8B
  model on a single consumer GPU. You keep the weights; nothing leaves.

## After deciding

1. Write `training.path` (A/B/C) and the model/method into `mirror.config.yaml`.
2. If a path requires a specific dataset format, tell `mirror-data-formatting`
   to (re)build it (`openai-chat` for B, `sharegpt` for C; A needs none).
3. Tell the user, explicitly, what will leave their machine for the chosen path.
4. Hand to `mirror-training`.
