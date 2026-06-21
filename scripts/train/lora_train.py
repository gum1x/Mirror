#!/usr/bin/env python3
"""Local QLoRA fine-tune on Llama/Qwen for the Mirror's voice — Path C.

Trains a LoRA adapter you own; nothing leaves the machine. Uses Unsloth if
installed (fast, low-VRAM), otherwise a plain transformers+peft+trl fallback.

    python lora_train.py data/train.json --base Qwen/Qwen2.5-7B-Instruct \
        --epochs 3 --lora-r 16 --lora-alpha 32 --out adapters/mirror-sam

Input is ShareGPT JSON from `build_dataset.py --format sharegpt`. Requires a GPU.
"""
from __future__ import annotations

import argparse
import json
import sys

ROLE_MAP = {"system": "system", "human": "user", "gpt": "assistant"}


def load_sharegpt(path: str) -> list[dict]:
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    convos = data if isinstance(data, list) else data.get("conversations", [])
    out = []
    for ex in convos:
        msgs = [{"role": ROLE_MAP.get(c["from"], "user"), "content": c["value"]}
                for c in ex.get("conversations", [])]
        if msgs:
            out.append({"messages": msgs})
    return out


def train_unsloth(rows, args) -> bool:
    try:
        from unsloth import FastLanguageModel
        from unsloth.chat_templates import train_on_responses_only
    except ImportError:
        return False

    from datasets import Dataset
    from trl import SFTTrainer, SFTConfig

    print(f"Loading {args.base} in 4-bit via Unsloth …", file=sys.stderr)
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=args.base, max_seq_length=args.max_seq_len,
        load_in_4bit=True, dtype=None)
    model = FastLanguageModel.get_peft_model(
        model, r=args.lora_r, lora_alpha=args.lora_alpha, lora_dropout=0.0,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"],
        use_gradient_checkpointing="unsloth", random_state=args.seed)

    def fmt(ex):
        return {"text": tokenizer.apply_chat_template(
            ex["messages"], tokenize=False, add_generation_prompt=False)}

    ds = Dataset.from_list(rows).map(fmt)

    trainer = SFTTrainer(
        model=model, tokenizer=tokenizer, train_dataset=ds,
        dataset_text_field="text", max_seq_length=args.max_seq_len,
        args=SFTConfig(
            per_device_train_batch_size=2, gradient_accumulation_steps=4,
            warmup_ratio=0.05, num_train_epochs=args.epochs,
            learning_rate=args.lr, logging_steps=10, optim="adamw_8bit",
            lr_scheduler_type="cosine", seed=args.seed, output_dir=args.out + "_ckpt"))

    # Mask everything but the assistant (your) turns so only your voice is learned.
    try:
        trainer = train_on_responses_only(
            trainer,
            instruction_part="<|im_start|>user\n", response_part="<|im_start|>assistant\n")
    except Exception:
        pass  # template-specific; falls back to training on the full text

    trainer.train()
    model.save_pretrained(args.out)
    tokenizer.save_pretrained(args.out)
    print(f"\n✅ Saved LoRA adapter → {args.out}", file=sys.stderr)
    return True


def train_fallback(rows, args) -> None:
    """transformers + peft + trl fallback (slower, more VRAM than Unsloth)."""
    try:
        import torch
        from datasets import Dataset
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
        from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
        from trl import SFTTrainer, SFTConfig
    except ImportError:
        sys.exit("Install Path C deps. Easiest: \n"
                 '  pip install "unsloth[cu121] @ git+https://github.com/unslothai/unsloth.git"\n'
                 "or torch transformers peft trl datasets bitsandbytes.")

    print(f"Loading {args.base} in 4-bit (transformers fallback) …", file=sys.stderr)
    bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                             bnb_4bit_compute_dtype=torch.bfloat16)
    tokenizer = AutoTokenizer.from_pretrained(args.base)
    model = AutoModelForCausalLM.from_pretrained(args.base, quantization_config=bnb,
                                                 device_map="auto")
    model = prepare_model_for_kbit_training(model)
    model = get_peft_model(model, LoraConfig(
        r=args.lora_r, lora_alpha=args.lora_alpha, lora_dropout=0.0, bias="none",
        task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"]))

    def fmt(ex):
        return {"text": tokenizer.apply_chat_template(ex["messages"], tokenize=False)}

    ds = Dataset.from_list(rows).map(fmt)
    SFTTrainer(
        model=model, tokenizer=tokenizer, train_dataset=ds,
        dataset_text_field="text", max_seq_length=args.max_seq_len,
        args=SFTConfig(per_device_train_batch_size=1, gradient_accumulation_steps=8,
                       warmup_ratio=0.05, num_train_epochs=args.epochs,
                       learning_rate=args.lr, logging_steps=10, optim="adamw_8bit",
                       lr_scheduler_type="cosine", seed=args.seed,
                       output_dir=args.out + "_ckpt")).train()
    model.save_pretrained(args.out)
    tokenizer.save_pretrained(args.out)
    print(f"\n✅ Saved LoRA adapter → {args.out}", file=sys.stderr)


def main() -> None:
    ap = argparse.ArgumentParser(description="Local QLoRA fine-tune (Path C).")
    ap.add_argument("input", help="ShareGPT JSON from build_dataset.py --format sharegpt.")
    ap.add_argument("--base", default="Qwen/Qwen2.5-7B-Instruct")
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--lora-r", type=int, default=16)
    ap.add_argument("--lora-alpha", type=int, default=32)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--max-seq-len", type=int, default=2048)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default="adapters/mirror")
    args = ap.parse_args()

    rows = load_sharegpt(args.input)
    if not rows:
        sys.exit("No training examples loaded — check the ShareGPT input.")
    print(f"Loaded {len(rows)} examples. Base={args.base} epochs={args.epochs} "
          f"r={args.lora_r}.", file=sys.stderr)

    if not train_unsloth(rows, args):
        print("Unsloth not found — using transformers+peft fallback.", file=sys.stderr)
        train_fallback(rows, args)


if __name__ == "__main__":
    main()
