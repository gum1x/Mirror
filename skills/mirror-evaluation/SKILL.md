---
name: mirror-evaluation
description: >-
  Measure how convincingly the Mirror sounds like the user, on held-out data,
  before shipping. Use after training (any path) and to decide whether to iterate.
  Generates the Mirror's replies to held-out prompts, scores them against the
  user's measured style fingerprint and their real replies, optionally adds an
  LLM-as-judge authenticity score, and tells you which lever to pull if it falls
  short.
---

# Mirror — evaluation

Never ship on vibes. Score the Mirror on the **held-out** conversations
(`data/eval.jsonl`, created by `build_dataset.py --holdout 0.1`) — data it was
never trained on, so you measure generalization, not memorization.

## 1. Generate the Mirror's replies on the holdout

Run the served Mirror in batch over the eval prompts (it strips each real reply,
generates its own, and records both):

```bash
python scripts/serve/mirror_chat.py --path A --batch data/eval.jsonl --out eval/preds.jsonl
#   --path B --model ft:...        for an OpenAI fine-tune
#   --path C --adapter adapters/mirror-sam --base Qwen/Qwen2.5-7B-Instruct
```

`preds.jsonl` lines: `{"prompt": [...], "reference": "<your real reply>", "prediction": "<mirror's reply>"}`.

## 2. Score

```bash
python scripts/eval/style_eval.py eval/preds.jsonl --style persona/style_card.json
# add an LLM judge (Claude rates "same person?" 0–1):
python scripts/eval/style_eval.py eval/preds.jsonl --style persona/style_card.json --judge
```

It reports:
- **Style-fingerprint match (0–1):** does the Mirror match the user's measured
  length, lowercase ratio, emoji rate, and punctuation habits?
- **Reference overlap:** light lexical similarity to the user's actual reply (a
  loose content signal — a good clone won't match word-for-word, so this is
  secondary).
- **Judge score (optional, 0–1):** an LLM rates whether prediction and reference
  read like the same person.
- **Blended style score** vs. your `eval.target_style_score` target.

## 3. Read it and decide

Compare against `eval.target_style_score` in `mirror.config.yaml` (default 0.7),
**and read 10 side-by-sides yourself** — numbers don't capture everything.

| What you see | Diagnosis | Lever (see data-volume-and-epochs.md) |
|--------------|-----------|----------------------------------------|
| Replays exact training lines; rigid | Overfit | Fewer epochs / lower LoRA `r` / more, balanced data |
| Generic, assistant-ish, ignores quirks | Underfit | More epochs / more data / add **DPO** (Path B) / sharpen style card |
| Right voice, wrong facts | Knowledge gap | Add **RAG** (`--rag`); don't add epochs |
| Too long / too formal vs. you | Style drift | Strengthen the style card's length/NEVER rules; lower `--max-tokens` |
| Great on seen topics, lost on new ones | Narrow corpus | Ingest more conversations/surfaces |

## 4. Iterate or ship

Change **one** lever, retrain, re-evaluate. Usually 1–2 iterations clears the
bar. When the blended score clears target *and* the side-by-sides read like the
user, go to `mirror-deploy`.

## Honesty

- Report the real numbers and show failing examples — don't oversell the Mirror.
- A high style score with low knowledge fidelity means "sounds like me but
  doesn't *know* like me" → say so, recommend RAG/Hybrid.
- The holdout must be **whole conversations** the model never saw. If you
  evaluate on training data the scores are meaningless; `build_dataset.py` splits
  at the conversation level for exactly this reason.
