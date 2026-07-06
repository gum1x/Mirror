#!/usr/bin/env python3
"""Serve the Mirror — chat with the clone, on any path (A/B/C), with optional RAG.

    python mirror_chat.py --path A --style-card persona/style_card.md \
        --corpus data/scrubbed.jsonl --rag
    python mirror_chat.py --path B --model ft:... --style-card persona/style_card.md
    python mirror_chat.py --path C --base Qwen/Qwen2.5-7B-Instruct --adapter adapters/mirror-sam
    python mirror_chat.py --path A --batch data/eval.jsonl --out eval/preds.jsonl   # for eval

RAG retrieves the user's own past messages and grounds the reply in their real
words/views. Keyword retrieval needs nothing; --semantic needs sentence-transformers.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib.schema import read_jsonl  # noqa: E402

WORD = re.compile(r"[a-zA-Z']+")
DEFAULT_SYSTEM = "You are the user. Reply exactly as they would."


# ───────────────────────── retrieval ─────────────────────────
class Retriever:
    def __init__(self, texts: list[str], semantic: bool):
        self.texts = texts
        self.semantic = semantic and self._init_semantic()
        if not self.semantic:
            self.tokens = [set(WORD.findall(t.lower())) for t in texts]

    def _init_semantic(self) -> bool:
        try:
            import numpy as np
            from sentence_transformers import SentenceTransformer
            self.np = np
            self.model = SentenceTransformer("all-MiniLM-L6-v2")
            emb = self.model.encode(self.texts, normalize_embeddings=True,
                                    show_progress_bar=False)
            self.emb = np.asarray(emb)
            return True
        except Exception as e:
            print(f"(semantic retrieval unavailable: {e}; using keyword)", file=sys.stderr)
            return False

    def top_k(self, query: str, k: int) -> list[str]:
        if not self.texts:
            return []
        if self.semantic:
            q = self.model.encode([query], normalize_embeddings=True)[0]
            scores = self.emb @ q
            idx = self.np.argsort(-scores)[:k]
            return [self.texts[i] for i in idx]
        q = set(WORD.findall(query.lower()))
        scored = sorted(range(len(self.texts)),
                        key=lambda i: len(q & self.tokens[i]), reverse=True)
        return [self.texts[i] for i in scored[:k] if q & self.tokens[i]]


def load_corpus(path: str) -> list[str]:
    seen, out = set(), []
    for r in read_jsonl(path):
        t = (r.text or "").strip()
        if r.is_from_me and len(t) > 8 and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def build_system(style_card: str, snippets: list[str]) -> str:
    sys_text = style_card or DEFAULT_SYSTEM
    if snippets:
        block = "\n".join(f"- {s}" for s in snippets)
        sys_text += ("\n\n## Things YOU have actually said (use your real voice and "
                     "views; if these don't cover it, reason as yourself — don't invent "
                     f"facts)\n{block}")
    return sys_text


# ───────────────────────── generators ─────────────────────────
class Mirror:
    def __init__(self, args, style_card: str, retriever: Retriever | None):
        self.args = args
        self.style_card = style_card
        self.retriever = retriever
        self._local = None  # lazy (path C)

    def _snippets(self, turns: list[dict]) -> list[str]:
        query = next((m["content"] for m in reversed(turns) if m["role"] == "user"), "")
        return self.retriever.top_k(query, self.args.k) if self.retriever else []

    def reply(self, turns: list[dict]) -> str:
        snips = self._snippets(turns)
        if self.args.path == "A":
            return self._claude(snips, turns)
        system = build_system(self.style_card, snips)
        if self.args.path == "B":
            return self._openai(system, turns)
        return self._local_gen(system, turns)

    def _claude(self, snippets: list[str], turns: list[dict]) -> str:
        import anthropic
        client = anthropic.Anthropic()
        # Cache the stable style card (prefix); keep volatile RAG snippets after the
        # breakpoint so the cache survives across turns. Stream to stay timeout-safe.
        system_blocks = [{"type": "text", "text": self.style_card or DEFAULT_SYSTEM,
                          "cache_control": {"type": "ephemeral"}}]
        if snippets:
            block = "\n".join(f"- {s}" for s in snippets)
            system_blocks.append({"type": "text", "text":
                "## Things YOU have actually said (use your real voice and views; if "
                "these don't cover it, reason as yourself — don't invent facts)\n" + block})
        with client.messages.stream(
                model=self.args.model or "claude-opus-4-8",
                max_tokens=self.args.max_tokens, system=system_blocks,
                thinking={"type": "adaptive"},
                messages=[{"role": m["role"], "content": m["content"]} for m in turns]) as stream:
            final = stream.get_final_message()
        return "".join(b.text for b in final.content
                       if getattr(b, "type", "") == "text").strip()

    def _openai(self, system: str, turns: list[dict]) -> str:
        from openai import OpenAI
        client = OpenAI()
        resp = client.chat.completions.create(
            model=self.args.model, max_tokens=self.args.max_tokens,
            messages=[{"role": "system", "content": system}, *turns])
        return resp.choices[0].message.content.strip()

    def _ensure_local(self):
        if self._local:
            return self._local
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        tok = AutoTokenizer.from_pretrained(self.args.base)
        model = AutoModelForCausalLM.from_pretrained(
            self.args.base, device_map="auto", torch_dtype=torch.bfloat16)
        if self.args.adapter:
            from peft import PeftModel
            model = PeftModel.from_pretrained(model, self.args.adapter)
        self._local = (tok, model)
        return self._local

    def _local_gen(self, system: str, turns: list[dict]) -> str:
        import torch
        tok, model = self._ensure_local()
        msgs = [{"role": "system", "content": system}, *turns]
        ids = tok.apply_chat_template(msgs, add_generation_prompt=True, return_tensors="pt")
        ids = ids.to(model.device)
        with torch.no_grad():
            out = model.generate(ids, max_new_tokens=self.args.max_tokens,
                                 do_sample=True, temperature=0.8, top_p=0.9,
                                 pad_token_id=tok.eos_token_id)
        return tok.decode(out[0][ids.shape[1]:], skip_special_tokens=True).strip()


# ───────────────────────── modes ─────────────────────────
def repl(mirror: Mirror) -> None:
    print("🪞 Mirror ready. Type to chat (Ctrl-C to quit).\n", file=sys.stderr)
    history: list[dict] = []
    try:
        while True:
            user = input("you ▸ ").strip()
            if not user:
                continue
            history.append({"role": "user", "content": user})
            out = mirror.reply(history)
            history.append({"role": "assistant", "content": out})
            print(f"🪞 ▸ {out}\n")
    except (KeyboardInterrupt, EOFError):
        print("\nbye", file=sys.stderr)


def batch(mirror: Mirror, path: str, out_path: str) -> None:
    with open(path, encoding="utf-8") as fh:
        rows = [json.loads(line) for line in fh if line.strip()]
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as out:
        for i, row in enumerate(rows):
            msgs = row.get("messages", [])
            turns = [m for m in msgs if m["role"] != "system"]
            reference = ""
            if turns and turns[-1]["role"] == "assistant":
                reference = turns[-1]["content"]
                turns = turns[:-1]
            if not turns:
                continue
            pred = mirror.reply(turns)
            out.write(json.dumps({"prompt": turns, "reference": reference,
                                  "prediction": pred}, ensure_ascii=False) + "\n")
            if (i + 1) % 10 == 0:
                print(f"  generated {i + 1}/{len(rows)}", file=sys.stderr)
    print(f"Wrote predictions → {out_path}", file=sys.stderr)


def main() -> None:
    ap = argparse.ArgumentParser(description="Serve / chat with the Mirror.")
    ap.add_argument("--path", choices=["A", "B", "C"], required=True)
    ap.add_argument("--model",
                    help="Path A: Claude model (default claude-opus-4-8). Path B: ft: id.")
    ap.add_argument("--base", help="Path C: base model, e.g. Qwen/Qwen2.5-7B-Instruct.")
    ap.add_argument("--adapter", help="Path C: LoRA adapter dir.")
    ap.add_argument("--style-card", default="persona/style_card.md")
    ap.add_argument("--corpus", help="unified JSONL for RAG (your messages).")
    ap.add_argument("--rag", action="store_true", help="Enable retrieval over your messages.")
    ap.add_argument("--semantic", action="store_true",
                    help="Use embedding retrieval (needs sentence-transformers).")
    ap.add_argument("--k", type=int, default=6, help="Retrieved snippets per turn.")
    ap.add_argument("--max-tokens", type=int, default=512)
    ap.add_argument("--batch", help="eval.jsonl (openai-chat) to score; with --out.")
    ap.add_argument("--out", help="Output predictions path for --batch.")
    args = ap.parse_args()

    if args.path == "B" and not args.model:
        ap.error("--path B needs --model ft:...")
    if args.path == "C" and not args.base:
        ap.error("--path C needs --base (and usually --adapter)")

    style_card = ""
    if os.path.exists(args.style_card):
        style_card = open(args.style_card, encoding="utf-8").read().strip()
    else:
        print(f"(no style card at {args.style_card}; using a generic system prompt)",
              file=sys.stderr)

    retriever = None
    if args.rag:
        if not args.corpus:
            ap.error("--rag needs --corpus path/to/messages.jsonl")
        texts = load_corpus(args.corpus)
        print(f"RAG index: {len(texts)} of your messages.", file=sys.stderr)
        retriever = Retriever(texts, args.semantic)

    mirror = Mirror(args, style_card, retriever)
    if args.batch:
        if not args.out:
            ap.error("--batch needs --out")
        batch(mirror, args.batch, args.out)
    else:
        repl(mirror)


if __name__ == "__main__":
    main()
