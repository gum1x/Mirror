#!/usr/bin/env python3
"""Export a Path C LoRA into a portable, offline model.

`lora_train.py` saves only the LoRA adapter, which still needs the base model and
Python to run. This merges the adapter into the base and (optionally) converts to
GGUF + writes an Ollama Modelfile that bakes in your style card, so you get a
single artifact you can run with Ollama / llama.cpp.

    # merge adapter into base -> a standalone HF model
    python scripts/train/lora_export.py --base Qwen/Qwen2.5-7B-Instruct \
        --adapter adapters/mirror-sam --out merged/mirror-sam

    # also produce GGUF + an Ollama Modelfile that uses your style card
    python scripts/train/lora_export.py --base Qwen/Qwen2.5-7B-Instruct \
        --adapter adapters/mirror-sam --out merged/mirror-sam \
        --gguf --quant q4_k_m --ollama-modelfile --style-card persona/style_card.md

Heavy deps (torch/transformers/peft) are only imported when actually merging.
GGUF conversion shells out to llama.cpp; if it's not found, you get exact
instructions instead of a crash.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys


def merge(base: str, adapter: str, out: str, revision: str | None) -> None:
    try:
        import torch
        from peft import PeftModel
        from transformers import AutoModelForCausalLM, AutoTokenizer
    except ImportError:
        sys.exit("Merging needs the Path C deps. Install with:  pip install \".[lora]\"")

    print(f"Loading base {base} …", file=sys.stderr)
    model = AutoModelForCausalLM.from_pretrained(
        base, torch_dtype=torch.float16, device_map="cpu", revision=revision)
    tok = AutoTokenizer.from_pretrained(base, revision=revision)
    print(f"Applying adapter {adapter} and merging …", file=sys.stderr)
    model = PeftModel.from_pretrained(model, adapter)
    model = model.merge_and_unload()
    os.makedirs(out, exist_ok=True)
    model.save_pretrained(out)
    tok.save_pretrained(out)
    print(f"✅ Merged model → {out}", file=sys.stderr)


def _find_llama_cpp_converter() -> str | None:
    for name in ("convert_hf_to_gguf.py", "convert-hf-to-gguf.py"):
        found = shutil.which(name)
        if found:
            return found
    # common local checkout location
    for cand in ("llama.cpp/convert_hf_to_gguf.py", "../llama.cpp/convert_hf_to_gguf.py"):
        if os.path.exists(cand):
            return cand
    return None


def to_gguf(merged_dir: str, quant: str) -> str | None:
    conv = _find_llama_cpp_converter()
    gguf_path = os.path.join(merged_dir, "model.gguf")
    if not conv:
        quant_path = os.path.join(merged_dir, f"model.{quant}.gguf")
        print("\nllama.cpp converter not found. To make a GGUF:\n"
              "  git clone https://github.com/ggerganov/llama.cpp\n"
              f"  python llama.cpp/convert_hf_to_gguf.py {merged_dir} --outfile {gguf_path}\n"
              f"  ./llama.cpp/llama-quantize {gguf_path} {quant_path} {quant}",
              file=sys.stderr)
        return None
    print(f"Converting to GGUF via {conv} …", file=sys.stderr)
    try:
        subprocess.run([sys.executable, conv, merged_dir, "--outfile", gguf_path], check=True)
    except subprocess.CalledProcessError as e:
        print(f"GGUF conversion failed ({e}); see llama.cpp docs.", file=sys.stderr)
        return None
    print(f"✅ GGUF → {gguf_path}", file=sys.stderr)
    return gguf_path


def write_modelfile(merged_dir: str, gguf_path: str | None, style_card: str | None,
                    temperature: float) -> None:
    system = ""
    if style_card and os.path.exists(style_card):
        system = open(style_card, encoding="utf-8").read().strip()
    from_line = f"FROM ./{os.path.basename(gguf_path)}" if gguf_path else f"FROM {merged_dir}"
    body = [from_line, f"PARAMETER temperature {temperature}"]
    if system:
        esc = system.replace('"', '\\"')
        body.append(f'SYSTEM "{esc}"')
    path = os.path.join(merged_dir, "Modelfile")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(body) + "\n")
    print(f"✅ Modelfile → {path}\n   Run:  ollama create mirror -f {path} && ollama run mirror",
          file=sys.stderr)


def main() -> None:
    ap = argparse.ArgumentParser(description="Export a Path C LoRA to a portable model.")
    ap.add_argument("--base", required=True, help="Base model id (same one you trained on).")
    ap.add_argument("--adapter", required=True, help="LoRA adapter dir from lora_train.py.")
    ap.add_argument("--out", default="merged/mirror", help="Output dir for the merged model.")
    ap.add_argument("--revision", help="Pin the base model to a commit/revision (recommended).")
    ap.add_argument("--gguf", action="store_true", help="Also convert to GGUF (needs llama.cpp).")
    ap.add_argument("--quant", default="q4_k_m", help="GGUF quantization (default q4_k_m).")
    ap.add_argument("--ollama-modelfile", action="store_true",
                    help="Write an Ollama Modelfile (bakes in the style card as SYSTEM).")
    ap.add_argument("--style-card", default="persona/style_card.md",
                    help="Style card used as the Modelfile SYSTEM prompt.")
    ap.add_argument("--temperature", type=float, default=0.8)
    args = ap.parse_args()

    merge(args.base, args.adapter, args.out, args.revision)
    gguf_path = to_gguf(args.out, args.quant) if args.gguf else None
    if args.ollama_modelfile:
        write_modelfile(args.out, gguf_path, args.style_card, args.temperature)


if __name__ == "__main__":
    main()
