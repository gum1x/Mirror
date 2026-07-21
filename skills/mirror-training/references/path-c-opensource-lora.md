# Path C — local QLoRA (Llama / Qwen), you own the weights

Fully private, offline, yours. QLoRA trains a small adapter on a 4-bit-quantized
base so a 7–8B model fine-tunes on a single consumer GPU. Nothing leaves the
machine.

## Hardware → model

| GPU VRAM | Recommended base | Notes |
|----------|------------------|-------|
| 8–12 GB | `Qwen/Qwen2.5-7B-Instruct`, `Llama-3.1-8B-Instruct`, `Mistral-7B-Instruct` | QLoRA 4-bit; the sweet spot. ~6–12 GB used. |
| 16–24 GB | `Qwen/Qwen2.5-14B-Instruct` | Noticeably better voice. |
| A100/H100 (rent) | `Qwen2.5-32B`, `Llama-3.1-70B` | Highest-quality local clone. |
| No GPU | — | Rent by the hour, or use Path A/B. |

## Setup

Unsloth is the recommended trainer (fastest, lowest memory, single-GPU QLoRA):
```bash
pip install "unsloth[cu121] @ git+https://github.com/unslothai/unsloth.git@<commit-sha>"
# (pins compatible torch / transformers / peft / trl / bitsandbytes)
# PIN the commit (@<commit-sha>) — SECURITY.md requires it for supply-chain safety.
```
Axolotl or HF PEFT+TRL also work; `lora_train.py` uses Unsloth if present and
falls back to a plain TRL `SFTTrainer` otherwise.

## Data

`build_dataset.py --format sharegpt` → `data/train.json` (ShareGPT: a JSON array
of `{"conversations":[{"from":"system"|"human"|"gpt","value":...}]}`). The
trainer applies the base model's chat template and masks everything but your
`gpt` turns so only your voice is learned.

## Train

```bash
python scripts/train/lora_train.py data/train.json \
    --base Qwen/Qwen2.5-7B-Instruct \
    --epochs 3 --lora-r 16 --lora-alpha 32 \
    --out adapters/mirror-sam
```

**Hyperparameters (good defaults):**
- `lora_r = 16`, `lora_alpha = 32` (≈ 2×r). Raise `r` to 32 for more capacity if
  underfitting; lower to 8 if it parrots.
- `epochs = 2–3`. Style tasks overfit fast — 1 can underfit, 4+ tends to
  memorize training lines.
- `learning_rate = 2e-4` (QLoRA-typical), warmup ~5%, cosine schedule.
- 4-bit load (`bnb` NF4), `max_seq_len` 1024–2048 (texts are short).
- Target modules: attention + MLP projections (Unsloth handles this).

## Export & serve

The adapter (tens of MB) is yours. To serve:
- **Quick:** load base + adapter with transformers/PEFT (what `mirror_chat.py
  --path C` does).
- **Merge** the adapter into the base for a standalone model:
  `model.merge_and_unload()` → save → optionally convert to GGUF and run in
  **Ollama** / **llama.cpp** for a local app.

Keep the style card as the system message at inference, same as the other paths.

## Knowledge caveat

Same as SFT: this learns *voice*, not *facts*. For knowledge fidelity, add the
same local RAG retrieval as Path A at serve time (fully offline) — `mirror_chat.py`
can do RAG in front of the local model too.

## Sources
- [Unsloth — Fine-tuning LLMs guide](https://unsloth.ai/docs/get-started/fine-tuning-llms-guide)
- [QLoRA + Unsloth complete guide (Pockit)](https://pockit.tools/blog/fine-tuning-llms-qlora-unsloth-complete-guide/)
- [Axolotl / Llama-Factory guide (Superteams.ai)](https://www.superteams.ai/blog/a-definitive-guide-to-fine-tuning-llms-using-axolotl-and-llama-factory/)
