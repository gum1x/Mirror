#!/usr/bin/env python3
"""Score how convincingly the Mirror sounds like the user.

Input: preds.jsonl lines {"prompt":[...], "reference":"...", "prediction":"..."}
(from `mirror_chat.py --batch`). Compares the Mirror's predictions to the user's
measured style fingerprint (persona/style_card.json) and to their real replies,
with an optional Claude LLM-judge.

    python style_eval.py eval/preds.jsonl --style persona/style_card.json
    python style_eval.py eval/preds.jsonl --style persona/style_card.json --judge
"""
from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from lib import style_metrics  # noqa: E402
from lib.style_metrics import WORD  # noqa: E402  (shared with style_analyze)


def fingerprint(texts: list[str]) -> dict:
    """Measure predictions with the SAME definitions style_analyze used on the
    user's real messages (lib.style_metrics) — that's what makes the comparison
    in style_match meaningful."""
    texts = [t for t in texts if t and t.strip()]
    return {
        "chars_mean": style_metrics.chars_mean(texts),
        "all_lowercase_ratio": style_metrics.all_lowercase_ratio(texts),
        "emoji_per_msg": style_metrics.emoji_per_msg(texts),
        "no_end_punctuation_ratio": style_metrics.no_end_punctuation_ratio(texts),
    }


def closeness(pred: float, target: float, scale: float) -> float:
    return max(0.0, 1.0 - abs(pred - target) / max(scale, 1e-6))


def style_match(pred_fp: dict, target: dict) -> dict:
    t_len = target.get("length", {})
    t_sty = target.get("style", {})
    comps = {
        "length": closeness(pred_fp["chars_mean"], t_len.get("chars_mean", 60),
                            max(t_len.get("chars_mean", 60), 40)),
        "lowercase": closeness(pred_fp["all_lowercase_ratio"],
                               t_sty.get("all_lowercase_ratio", 0.0), 1.0),
        "emoji": closeness(pred_fp["emoji_per_msg"],
                           t_sty.get("emoji_per_msg", 0.0),
                           max(t_sty.get("emoji_per_msg", 0.0), 0.2)),
        "punctuation": closeness(pred_fp["no_end_punctuation_ratio"],
                                 t_sty.get("no_end_punctuation_ratio", 0.0), 1.0),
    }
    comps["overall"] = sum(comps.values()) / len(comps)
    return comps


def token_f1(a: str, b: str) -> float:
    ta, tb = set(WORD.findall(a.lower())), set(WORD.findall(b.lower()))
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    if inter == 0:
        return 0.0
    p, r = inter / len(ta), inter / len(tb)
    return 2 * p * r / (p + r)


def llm_judge(rows: list[dict], name: str) -> float:
    try:
        import anthropic
    except ImportError:
        print("  (judge skipped — pip install anthropic)", file=sys.stderr)
        return -1.0
    client = anthropic.Anthropic()
    scores = []
    for row in rows:
        prompt = (f"Two replies to the same message. A is {name}'s real reply, B is "
                  f"a clone's. Rate 0.0–1.0 how likely B was written by the same "
                  f"person as A (voice, tone, length, habits). Reply with ONLY the number.\n\n"
                  f"A: {row['reference']}\nB: {row['prediction']}")
        try:
            resp = client.messages.create(
                model="claude-opus-4-8", max_tokens=32,
                messages=[{"role": "user", "content": prompt}])
            m = re.search(r"[01](?:\.\d+)?", resp.content[0].text)
            if m:
                scores.append(min(1.0, float(m.group())))
        except Exception as e:
            print(f"  judge error: {e}", file=sys.stderr)
    return statistics.mean(scores) if scores else -1.0


def main() -> None:
    ap = argparse.ArgumentParser(description="Score the Mirror's voice match.")
    ap.add_argument("predictions", help="preds.jsonl from mirror_chat.py --batch")
    ap.add_argument("--style", required=True, help="persona/style_card.json")
    ap.add_argument("--judge", action="store_true", help="Add a Claude LLM-judge score.")
    ap.add_argument("--target", type=float, default=0.7, help="Pass/fail threshold.")
    args = ap.parse_args()

    with open(args.predictions, encoding="utf-8") as fh:
        rows = [json.loads(line) for line in fh if line.strip()]
    with open(args.style, encoding="utf-8") as fh:
        style = json.load(fh)
    if not rows:
        sys.exit("No predictions to score.")

    preds = [r.get("prediction", "") for r in rows]
    refs = [r.get("reference", "") for r in rows]

    sm = style_match(fingerprint(preds), style)
    overlap = statistics.mean(token_f1(p, r) for p, r in zip(preds, refs))
    judge = llm_judge(rows, style.get("name", "the user")) if args.judge else -1.0

    if judge >= 0:
        blended = 0.6 * sm["overall"] + 0.2 * overlap + 0.2 * judge
    else:
        blended = 0.75 * sm["overall"] + 0.25 * overlap

    print(f"\n=== Mirror evaluation ({len(rows)} held-out examples) ===")
    print(f"Style fingerprint match : {sm['overall']:.3f}")
    print(f"   length {sm['length']:.2f} | lowercase {sm['lowercase']:.2f} | "
          f"emoji {sm['emoji']:.2f} | punctuation {sm['punctuation']:.2f}")
    print(f"Reference overlap (F1)  : {overlap:.3f}  (secondary — a clone won't match words)")
    if judge >= 0:
        print(f"LLM judge (same person?): {judge:.3f}")
    print(f"\nBLENDED STYLE SCORE     : {blended:.3f}   (target {args.target})")
    print("Result: " + ("✅ PASS — read 10 side-by-sides, then ship." if blended >= args.target
                        else "⚠️  BELOW TARGET — see mirror-evaluation for which lever to pull."))


if __name__ == "__main__":
    main()
