# Reference: model matrix (which model for which path)

Current as of **mid-2026**. Model availability moves fast — re-check vendor docs
(linked at the bottom) before quoting specifics to the user.

## Path A — Claude persona + RAG (no training)

The Mirror *is* a strong system prompt (the style card) + retrieval over the
user's messages, running on Claude. Pick by how much reasoning fidelity you want:

| Model | Use for |
|-------|---------|
| `claude-opus-4-8` | **Default.** Best reasoning/knowledge fidelity — the "thinks like me" target. |
| `claude-sonnet-4-6` | High-volume / cost-sensitive serving where Opus is overkill. |
| `claude-haiku-4-5` | Cheapest, fastest; fine for short autoreply-style turns. |

Why no fine-tune here: Anthropic does **not** offer general consumer
weight-fine-tuning of Claude. The supported way to make Claude sound like you is
prompt + few-shot exemplars + retrieval — which is exactly Path A, and it gets
you the strongest model with zero training cost. (Adaptive thinking lets Opus
reason in your style on hard questions.)

## Path B — OpenAI fine-tune (hosted SFT, optional DPO)

A model that has your surface voice *baked into the weights*, hosted by OpenAI.

| Base model | Use for | Notes |
|------------|---------|-------|
| `gpt-4.1-mini` | **Default.** Cheap, fast, captures texting voice well. | Best $/quality for a voice clone. |
| `gpt-4.1` | "Indistinguishable from me," longer-form, nuanced tone. | More expensive to train + serve. |

- **Methods:** SFT (demonstrate your replies) → optionally DPO (rank your real
  reply over a generic one). RFT (reinforcement fine-tuning, on `o4-mini`) is for
  *verifiable-correct* tasks — not voice — so Mirror doesn't use it.
- The newest frontier family (e.g. GPT-5.x) is generally **not** open for
  fine-tuning; stick to the `gpt-4.1` family for SFT/DPO.
- Data format: chat JSONL (`build_dataset.py --format openai-chat`).

## Path C — local LoRA / QLoRA (you own the weights)

Fully private, offline, yours. QLoRA (4-bit) trains an adapter on a single GPU.

| Base model | Params | Fits on | Use for |
|------------|--------|---------|---------|
| `Qwen/Qwen2.5-7B-Instruct` | 7B | ~8–12 GB VRAM (QLoRA) | **Default.** Strong small instruct model. |
| `meta-llama/Llama-3.1-8B-Instruct` | 8B | ~8–12 GB VRAM | Great general voice clone. |
| `mistralai/Mistral-7B-Instruct` | 7B | ~8 GB | Lightweight alternative. |
| `Qwen/Qwen2.5-14B-Instruct` | 14B | ~16–24 GB | Noticeably better; needs a 24 GB card. |
| `Qwen/Qwen2.5-32B` / `Llama-3.1-70B` | 32–70B | A100/H100 (rent) | Highest-quality local clone. |

- **Tooling:** **Unsloth** (fastest, lowest-memory, single-GPU QLoRA — recommended
  default), **Axolotl** (config-driven, scales to multi-GPU), or HF PEFT+TRL.
  A 7B QLoRA fine-tune fits in roughly 6–12 GB of VRAM.
- Data format: ShareGPT (`build_dataset.py --format sharegpt`).
- No GPU? Rent an A100/H100 by the hour, or fall back to Path A/B.

## Hybrid (the "best clone")

- **Path A for brains + knowledge:** Opus 4.8 + RAG answers questions and reasons
  like the user, grounded in their real words.
- **Path B/C for pure voice:** route short, stylistic tasks (autoreply, "draft a
  text") to the fine-tuned voice model.
- Mirror can serve both behind one endpoint and pick per request, or just start
  with A and add the voice model when the user wants tighter surface mimicry.

## Sources
- OpenAI — [Supervised fine-tuning](https://developers.openai.com/api/docs/guides/supervised-fine-tuning),
  [Direct preference optimization](https://platform.openai.com/docs/guides/direct-preference-optimization),
  [Fine-tuning best practices](https://platform.openai.com/docs/guides/fine-tuning-best-practices)
- [Unsloth — Fine-tuning LLMs guide](https://unsloth.ai/docs/get-started/fine-tuning-llms-guide)
- [Axolotl / Llama-Factory guide (Superteams.ai)](https://www.superteams.ai/blog/a-definitive-guide-to-fine-tuning-llms-using-axolotl-and-llama-factory/)
- [How to Fine-Tune LLMs in 2026 (Spheron)](https://www.spheron.network/blog/how-to-fine-tune-llm-2026/)
- Anthropic Claude model IDs: see the project's `claude-api` skill / platform.claude.com.
