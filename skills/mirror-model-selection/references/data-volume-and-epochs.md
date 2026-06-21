# Reference: how much data, how many "trains" (epochs)

There's no magic number — it depends on the model, how varied your voice is, and
how convincing you need it. These are practical, defensible starting points for a
*personal voice clone*, plus the signals that tell you to adjust.

## How many of YOUR messages do you need?

Count **examples where you're the target reply** (the `assistant` turns), not
total messages. After `build_dataset.py`, that's the line count of `train.jsonl`.

| Your-message count | Best path | Why |
|--------------------|-----------|-----|
| < ~300 | **Path A only** (prompt + RAG) | Too little to fine-tune without parroting/overfitting. RAG still works — it retrieves, doesn't train. |
| ~300–1,000 | A, or a light SFT/QLoRA | Enough for a usable voice fine-tune; keep epochs low, expect to lean on the style-card system prompt too. |
| ~1,000–5,000 | **SFT/QLoRA sweet spot** | Solid surface-voice lock-in. This is where fine-tunes start feeling "like you." |
| 5,000–20,000+ | Strong fine-tune; consider DPO | Diminishing returns on raw volume — **curation now matters more than count.** |

The published floor for fine-tuning at all is **≥100 examples, with ≥1,000
preferable** ([Unsloth datasets guide](https://unsloth.ai/docs/get-started/fine-tuning-llms-guide/datasets-guide.md));
OpenAI requires ≥10 but that's far too few for a convincing voice. Below ~300 of
your own messages, prefer Path A.

Quality beats quantity past a few thousand: a clean, representative,
de-duplicated set of your *real* messages outperforms a larger noisy one.
Balance across conversations (`--max-per-convo`) so one chatty thread doesn't
define "you."

## How many epochs ("trains")?

An **epoch** is one full pass over your dataset. You run a few so the model
internalizes the style without memorizing it.

| Setting | Start at | Notes |
|---------|----------|-------|
| OpenAI SFT | **let it default**, then ±1–2 | Vendor picks epochs from dataset size. Increase by 1–2 if the model doesn't follow your style; decrease by 1–2 if outputs get repetitive/less diverse. |
| OpenAI DPO | 1–2 | A polish pass; don't overcook it. |
| LoRA / QLoRA | **2–3** | Style tasks overfit fast. 1 epoch can underfit; 4+ tends to parrot training lines. |

Small datasets sometimes need more epochs (e.g. ~50 examples × 4 epochs for a
narrow conversational task); large datasets need fewer.

## Overfitting vs underfitting — how to tell

Run `mirror-evaluation` on the **held-out** split (never the training data) and
read the symptoms:

| Symptom | Meaning | Fix |
|---------|---------|-----|
| Regurgitates exact training lines; same reply to different prompts; weirdly rigid | **Overfit** | Fewer epochs, lower LoRA `r`, more/varied data, more `--max-per-convo` balance |
| Sounds generic / like a default assistant; ignores your quirks | **Underfit** | More epochs, more data, add DPO (B), raise LoRA `r` |
| Right vibe, wrong facts | Not a data-volume problem | Add **RAG** (Path A layer) — fine-tuning won't fix knowledge |
| Great on training topics, lost on new ones | Narrow corpus | Add data from more conversations/surfaces |

## Practical recipe

1. Build `train.jsonl` + a 10% conversation-level holdout (`--holdout 0.1`).
2. Train one run at the default/recommended epochs.
3. Evaluate on the holdout (style score + side-by-sides).
4. Adjust **one** lever (epochs, data amount, balance, or add DPO/RAG) and retrain.
5. Stop when the style score clears your target (`eval.target_style_score`) and
   the side-by-sides read like you. Usually 1–2 iterations — not dozens.

## Sources
- [OpenAI — Fine-tuning best practices](https://platform.openai.com/docs/guides/fine-tuning-best-practices)
  (let defaults pick epochs; ±1–2 based on adherence/diversity)
- [Unsloth — Fine-tuning guide](https://unsloth.ai/docs/get-started/fine-tuning-llms-guide)
  (epoch/overfit guidance for LoRA)
- [Towards Data Science — How to create an AI that chats like you](https://towardsdatascience.com/how-to-create-an-ai-that-chats-like-you-cb3484824797/)
