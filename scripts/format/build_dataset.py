#!/usr/bin/env python3
"""Build training datasets from unified-JSONL messages.

Groups by conversation, sorts by time, merges consecutive same-sender messages
into turns, then emits examples where YOUR turn is the target the model learns
to produce given the preceding context.

Formats: openai-chat (Path B SFT) · sharegpt (Path C LoRA) · dpo (Path B refine).

    python build_dataset.py data/scrubbed.jsonl --format openai-chat \
        --system-file persona/style_card.md --context-turns 6 \
        --max-per-convo 400 --holdout 0.1 -o data/train.jsonl
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import zlib
from collections import defaultdict
from typing import Iterator, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib.schema import MessageRecord, read_jsonl  # noqa: E402

DEFAULT_SYSTEM = ("You are the user. Reply exactly as they would — matching their "
                  "tone, length, punctuation, capitalization, and word choice. "
                  "Do not be more formal, more verbose, or more polished than they are.")


def load_system(path: Optional[str]) -> str:
    if path and os.path.exists(path):
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read().strip()
    return DEFAULT_SYSTEM


def group_and_order(records: Iterator[MessageRecord]) -> dict[str, list[MessageRecord]]:
    groups: dict[str, list[MessageRecord]] = defaultdict(list)
    for r in records:
        groups[f"{r.source}::{r.conversation_id}"].append(r)
    for key, msgs in groups.items():
        # Stable chronological order; carry the last seen timestamp forward so
        # messages missing a timestamp stay next to their neighbors.
        keyed, last = [], ""
        for i, m in enumerate(msgs):
            last = m.timestamp or last
            keyed.append(((last, i), m))
        keyed.sort(key=lambda x: x[0])
        groups[key] = [m for _, m in keyed]
    return groups


def to_turns(msgs: list[MessageRecord]) -> list[dict]:
    """Merge consecutive same-sender messages into role-tagged turns."""
    turns: list[dict] = []
    for m in msgs:
        role = "assistant" if m.is_from_me else "user"
        text = (m.text or "").strip()
        if not text:
            continue
        if turns and turns[-1]["role"] == role:
            turns[-1]["content"] += "\n" + text
        else:
            turns.append({"role": role, "content": text})
    return turns


def examples_for_convo(turns: list[dict], context_turns: int, min_target: int, mode: str
                       ) -> Iterator[tuple[list[dict], str]]:
    """Yield (context_messages_ending_in_user, target_assistant_text)."""
    for i, turn in enumerate(turns):
        if turn["role"] != "assistant":
            continue
        if len(turn["content"]) < min_target:
            continue
        ctx = turns[max(0, i - context_turns):i]
        while ctx and ctx[0]["role"] == "assistant":
            ctx = ctx[1:]  # context must start with a user turn
        if mode == "reply":
            if not ctx or ctx[-1]["role"] != "user":
                continue  # need a preceding user message to reply to
        elif mode == "autocomplete":
            if not ctx:
                ctx = [{"role": "user", "content": "Continue in my voice."}]
        yield [dict(t) for t in ctx], turn["content"]


def convo_in_holdout(key: str, holdout: float) -> bool:
    if holdout <= 0:
        return False
    h = zlib.crc32(key.encode()) % 10000 / 10000.0
    return h < holdout


def render(fmt: str, system: str, ctx: list[dict], target: str) -> dict:
    if fmt == "openai-chat":
        return {"messages": [{"role": "system", "content": system}, *ctx,
                             {"role": "assistant", "content": target}]}
    if fmt == "sharegpt":
        role_map = {"user": "human", "assistant": "gpt"}
        convs = [{"from": "system", "value": system}]
        convs += [{"from": role_map[t["role"]], "value": t["content"]} for t in ctx]
        convs.append({"from": "gpt", "value": target})
        return {"conversations": convs}
    if fmt == "dpo":
        return {"input": {"messages": [{"role": "system", "content": system}, *ctx]},
                "preferred_output": [{"role": "assistant", "content": target}],
                "non_preferred_output": []}
    raise ValueError(fmt)


def eval_path_for(output: str) -> str:
    base, ext = os.path.splitext(output)
    if "train" in os.path.basename(base):
        return output.replace("train", "eval")
    return f"{base}_eval{ext or '.jsonl'}"


def main() -> None:
    ap = argparse.ArgumentParser(description="Build a training dataset from unified JSONL.")
    ap.add_argument("inputs", nargs="+")
    ap.add_argument("--format", choices=["openai-chat", "sharegpt", "dpo"], default="openai-chat")
    ap.add_argument("--system-file", help="File whose contents become the system prompt (style card).")
    ap.add_argument("--context-turns", type=int, default=6)
    ap.add_argument("--max-per-convo", type=int, default=0, help="Cap examples per conversation (0 = no cap).")
    ap.add_argument("--min-target-chars", type=int, default=1)
    ap.add_argument("--mode", choices=["reply", "autocomplete"], default="reply")
    ap.add_argument("--holdout", type=float, default=0.0, help="Fraction of conversations → eval split.")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("-o", "--output", default="-")
    args = ap.parse_args()

    system = load_system(args.system_file)
    rng = random.Random(args.seed)
    groups = group_and_order(rec for p in args.inputs for rec in read_jsonl(p))

    train, evals = [], []
    for key, msgs in groups.items():
        ex = list(examples_for_convo(to_turns(msgs), args.context_turns,
                                     args.min_target_chars, args.mode))
        if args.max_per_convo and len(ex) > args.max_per_convo:
            ex = rng.sample(ex, args.max_per_convo)
        bucket = evals if convo_in_holdout(key, args.holdout) else train
        for ctx, target in ex:
            bucket.append(render(args.format, system, ctx, target))

    rng.shuffle(train)

    def dump(rows: list[dict], path: str) -> None:
        if path == "-":
            out = sys.stdout
        else:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            out = open(path, "w", encoding="utf-8")
        try:
            if args.format == "sharegpt":            # ShareGPT = one JSON array
                json.dump(rows, out, ensure_ascii=False, indent=0)
            else:                                     # chat / dpo = JSONL
                for row in rows:
                    out.write(json.dumps(row, ensure_ascii=False) + "\n")
        finally:
            if out is not sys.stdout:
                out.close()

    dump(train, args.output)
    msg = f"Wrote {len(train)} training examples → {args.output}"
    if args.holdout > 0 and args.output != "-":
        ep = eval_path_for(args.output)
        dump(evals, ep)
        msg += f"; {len(evals)} eval examples → {ep}"
    print(msg, file=sys.stderr)
    if not train:
        print("⚠️  0 training examples. Check that your messages have is_from_me=true "
              "and that conversations contain back-and-forth (need a message to reply to).",
              file=sys.stderr)


if __name__ == "__main__":
    main()
