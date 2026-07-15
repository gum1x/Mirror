#!/usr/bin/env python3
"""Build training datasets from unified-JSONL messages.

Groups by conversation, splits each into sessions on a time gap, sorts by time,
merges consecutive same-sender messages into turns, then emits examples where
YOUR turn is the target the model learns to produce given the preceding context.

Formats: openai-chat (Path B SFT) · sharegpt (Path C LoRA) · chatml · dpo.

    python build_dataset.py data/scrubbed.jsonl --format openai-chat \
        --system-file persona/style_card.md --context-turns 6 \
        --session-gap-minutes 360 --max-per-convo 400 --holdout 0.1 -o data/train.jsonl

Writes a DATASET_CARD.md next to the output recording provenance + settings.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import random
import sys
import zlib
from collections import Counter, defaultdict
from collections.abc import Iterator

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib.schema import MessageRecord, read_jsonl  # noqa: E402

DEFAULT_SYSTEM = ("You are the user. Reply exactly as they would — matching their "
                  "tone, length, punctuation, capitalization, and word choice. "
                  "Do not be more formal, more verbose, or more polished than they are.")


def load_system(path: str | None) -> str:
    if path:
        # An explicitly requested style card that doesn't exist must be an
        # error: silently falling back to the generic prompt builds (and pays
        # for) a fine-tune without the persona, with no hint anything is off.
        if not os.path.exists(path):
            sys.exit(f"--system-file {path} does not exist. Fix the path, or drop "
                     "the flag to use the built-in default prompt.")
        with open(path, encoding="utf-8") as fh:
            return fh.read().strip()
    return DEFAULT_SYSTEM


def _parse_ts(ts: str | None) -> dt.datetime | None:
    if not ts:
        return None
    try:
        return dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def group_and_order(records: Iterator[MessageRecord]
                    ) -> tuple[dict[str, list[MessageRecord]], dict]:
    groups: dict[str, list[MessageRecord]] = defaultdict(list)
    stats = {"total": 0, "from_me": 0, "sources": Counter(), "no_ts": 0}
    for r in records:
        groups[f"{r.source}::{r.conversation_id}"].append(r)
        stats["total"] += 1
        stats["from_me"] += int(r.is_from_me)
        stats["sources"][r.source] += 1
        stats["no_ts"] += int(r.timestamp is None)
    for key, msgs in groups.items():
        # Sort on parsed datetimes, not the raw strings: "…12.500000Z" sorts
        # before "…12Z" as text ('.' < 'Z'), and non-Z offsets sort arbitrarily.
        # Messages without a (parseable) timestamp inherit the last known one;
        # the index tiebreaker keeps input order within equal times.
        keyed, last = [], dt.datetime.min.replace(tzinfo=dt.timezone.utc)
        for i, m in enumerate(msgs):
            t = _parse_ts(m.timestamp)
            if t is not None:
                if t.tzinfo is None:
                    t = t.replace(tzinfo=dt.timezone.utc)
                last = t
            keyed.append(((last, i), m))
        keyed.sort(key=lambda x: x[0])
        groups[key] = [m for _, m in keyed]
    stats["conversations"] = len(groups)
    return groups, stats


def split_sessions(msgs: list[MessageRecord], gap_minutes: int) -> list[list[MessageRecord]]:
    """Split a conversation into sessions wherever the time gap exceeds the limit,
    so a context window never straddles a long silence (e.g. a 3-week gap)."""
    if gap_minutes <= 0:
        return [msgs]
    sessions, cur, prev = [], [], None
    limit = dt.timedelta(minutes=gap_minutes)
    for m in msgs:
        t = _parse_ts(m.timestamp)
        if cur and prev is not None and t is not None and (t - prev) > limit:
            sessions.append(cur)
            cur = []
        cur.append(m)
        if t is not None:
            prev = t
    if cur:
        sessions.append(cur)
    return sessions


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


def examples_for_turns(turns: list[dict], context_turns: int, min_target: int, mode: str
                       ) -> Iterator[tuple[list[dict], str]]:
    for i, turn in enumerate(turns):
        if turn["role"] != "assistant" or len(turn["content"]) < min_target:
            continue
        ctx = turns[max(0, i - context_turns):i]
        while ctx and ctx[0]["role"] == "assistant":
            ctx = ctx[1:]
        if mode == "reply":
            if not ctx or ctx[-1]["role"] != "user":
                continue
        elif mode == "autocomplete" and not ctx:
            ctx = [{"role": "user", "content": "Continue in my voice."}]
        yield [dict(t) for t in ctx], turn["content"]


def convo_in_holdout(key: str, holdout: float, seed: int) -> bool:
    if holdout <= 0:
        return False
    h = zlib.crc32(f"{seed}:{key}".encode()) % 10000 / 10000.0
    return h < holdout


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def render(fmt: str, system: str, ctx: list[dict], target: str) -> dict:
    if fmt == "openai-chat":
        return {"messages": [{"role": "system", "content": system}, *ctx,
                             {"role": "assistant", "content": target}]}
    if fmt == "sharegpt":
        rm = {"user": "human", "assistant": "gpt"}
        convs = [{"from": "system", "value": system}]
        convs += [{"from": rm[t["role"]], "value": t["content"]} for t in ctx]
        convs.append({"from": "gpt", "value": target})
        return {"conversations": convs}
    if fmt == "chatml":
        parts = [f"<|im_start|>system\n{system}<|im_end|>"]
        parts += [f"<|im_start|>{t['role']}\n{t['content']}<|im_end|>" for t in ctx]
        parts.append(f"<|im_start|>assistant\n{target}<|im_end|>")
        return {"text": "\n".join(parts) + "\n"}
    if fmt == "dpo":
        return {"input": {"messages": [{"role": "system", "content": system}, *ctx]},
                "preferred_output": [{"role": "assistant", "content": target}],
                "non_preferred_output": []}
    raise ValueError(fmt)


def eval_path_for(output: str) -> str:
    d, base = os.path.dirname(output), os.path.basename(output)
    stem, ext = os.path.splitext(base)
    # Replace a whole-word "train" token only in the basename; else append "_eval"
    # (so paths like data/mytrainset.jsonl aren't mangled to data/myevalset.jsonl).
    if "train" in stem.split("_"):
        new = "_".join("eval" if p == "train" else p for p in stem.split("_"))
    else:
        new = stem + "_eval"
    return os.path.join(d, new + (ext or ".jsonl"))


def write_dataset_card(path: str, args, stats: dict, n_train: int, n_eval: int,
                       n_decontam: int) -> None:
    src = ", ".join(f"{k}:{v}" for k, v in sorted(stats["sources"].items()))
    card = f"""# Dataset card — Mirror training data

- Generated: {dt.datetime.now().astimezone().isoformat(timespec='seconds')}
- Format: `{args.format}`
- Output: `{args.output}`{f' (+ eval: `{eval_path_for(args.output)}`)' if args.holdout > 0 else ''}

## Provenance
- Source messages: {stats['total']} across {stats['conversations']} conversations
- Sources: {src or 'n/a'}
- From you (`is_from_me`): {stats['from_me']} ({stats['from_me'] / max(stats['total'],1):.1%})
- Messages missing a timestamp: {stats['no_ts']}

## Build settings
- context_turns: {args.context_turns}
- session_gap_minutes: {args.session_gap_minutes}
- min_target_chars: {args.min_target_chars}
- max_per_convo: {args.max_per_convo or 'none'}
- mode: {args.mode}
- holdout: {args.holdout} (conversation-level split, seed {args.seed})
- decontaminate eval↔train: {'on' if not args.no_decontaminate else 'off'}
- system prompt: {f'style card ({args.system_file})' if args.system_file else 'built-in default'}

## Result
- Training examples: {n_train}
- Eval examples: {n_eval} (removed {n_decontam} as train/eval duplicates)

_Auto-generated by build_dataset.py. Records provenance for reproducibility._
"""
    cpath = os.path.join(os.path.dirname(args.output) or ".", "DATASET_CARD.md")
    with open(cpath, "w", encoding="utf-8") as fh:
        fh.write(card)
    print(f"Wrote dataset card → {cpath}", file=sys.stderr)


def main() -> None:
    ap = argparse.ArgumentParser(description="Build a training dataset from unified JSONL.")
    ap.add_argument("inputs", nargs="+")
    ap.add_argument("--format", choices=["openai-chat", "sharegpt", "chatml", "dpo"],
                    default="openai-chat")
    ap.add_argument("--system-file",
                    help="File whose contents become the system prompt (style card).")
    ap.add_argument("--context-turns", type=int, default=6)
    ap.add_argument("--session-gap-minutes", type=int, default=360,
                    help="Start a new session when consecutive messages are >N min apart "
                         "(so context never crosses a long silence). 0 disables.")
    ap.add_argument("--max-per-convo", type=int, default=0,
                    help="Cap examples per conversation (0 = no cap).")
    ap.add_argument("--min-target-chars", type=int, default=1)
    ap.add_argument("--mode", choices=["reply", "autocomplete"], default="reply")
    ap.add_argument("--holdout", type=float, default=0.0,
                    help="Fraction of conversations → eval split.")
    ap.add_argument("--no-decontaminate", action="store_true",
                    help="Skip removing eval examples whose reply also appears in train.")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("-o", "--output", default="-")
    args = ap.parse_args()

    if args.holdout > 0 and args.output == "-":
        ap.error("--holdout needs a file output (-o path.jsonl): the eval split "
                 "has nowhere to go when the training set is written to stdout.")
    system = load_system(args.system_file)
    rng = random.Random(args.seed)
    groups, stats = group_and_order(rec for p in args.inputs for rec in read_jsonl(p))

    train_pairs, eval_pairs = [], []
    for key, msgs in groups.items():
        ex = []
        for session in split_sessions(msgs, args.session_gap_minutes):
            ex.extend(examples_for_turns(to_turns(session), args.context_turns,
                                         args.min_target_chars, args.mode))
        if args.max_per_convo and len(ex) > args.max_per_convo:
            ex = rng.sample(ex, args.max_per_convo)
        (eval_pairs if convo_in_holdout(key, args.holdout, args.seed) else train_pairs).extend(ex)

    # Decontaminate: drop eval examples whose target reply also appears in train,
    # so eval measures generalization (recurring "haha"/"omw" replies otherwise leak).
    n_decontam = 0
    if not args.no_decontaminate and eval_pairs:
        train_targets = {_norm(t) for _, t in train_pairs}
        kept = [(c, t) for c, t in eval_pairs if _norm(t) not in train_targets]
        n_decontam = len(eval_pairs) - len(kept)
        eval_pairs = kept

    rng.shuffle(train_pairs)
    train = [render(args.format, system, c, t) for c, t in train_pairs]
    evals = [render(args.format, system, c, t) for c, t in eval_pairs]

    def write_rows(out, rows: list[dict]) -> None:
        if args.format == "sharegpt":
            json.dump(rows, out, ensure_ascii=False, indent=0)
        else:
            for row in rows:
                out.write(json.dumps(row, ensure_ascii=False) + "\n")

    msg = f"Wrote {len(train)} training examples → {args.output}"
    if args.output == "-":
        write_rows(sys.stdout, train)
    else:
        pending = [(train, args.output)]
        if args.holdout > 0:
            ep = eval_path_for(args.output)
            pending.append((evals, ep))
            msg += f"; {len(evals)} eval examples → {ep}"
        # Stage every file first and swap them into place together, so a crash
        # can't pair a fresh train file with a stale eval file from a prior run.
        staged = []
        try:
            for rows, path in pending:
                os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
                tmp = path + ".tmp"
                staged.append((tmp, path))
                with open(tmp, "w", encoding="utf-8") as out:
                    write_rows(out, rows)
        except BaseException:
            for tmp, _ in staged:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
            raise
        for tmp, path in staged:
            os.replace(tmp, path)
    print(msg, file=sys.stderr)
    if args.output != "-":
        write_dataset_card(args.output, args, stats, len(train), len(evals), n_decontam)
    if not train:
        print("⚠️  0 training examples. Check that your messages have is_from_me=true "
              "and that conversations contain back-and-forth (need a message to reply to).",
              file=sys.stderr)


if __name__ == "__main__":
    main()
