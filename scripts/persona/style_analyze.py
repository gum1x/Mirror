#!/usr/bin/env python3
"""Analyze the user's own messages into a style card (JSON stats + Markdown prompt).

    python style_analyze.py data/scrubbed.jsonl -o persona/ --name Sam
    python style_analyze.py data/scrubbed.jsonl --samples 40   # print sample msgs

Only the user's messages (is_from_me=true) are analyzed — that's their voice.
Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
from collections import Counter
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib.schema import read_jsonl  # noqa: E402

EMOJI = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F000-\U0001F0FF"
    "\U00002B00-\U00002BFF\U0001F1E6-\U0001F1FF\U00002190-\U000021FF\U0000FE0F]"
)
WORD = re.compile(r"[a-zA-Z']+")
SLANG = ["lol", "lmao", "lmao", "rofl", "idk", "idc", "tbh", "ngl", "imo", "imho",
         "fr", "ong", "istg", "smh", "iirc", "btw", "rn", "ttyl", "omw", "wyd",
         "hbu", "ily", "nvm", "wtf", "af", "lowkey", "highkey", "deadass", "bet"]
STOPWORDS = set("the a an and or but to of in on at for is am are was were be been i "
                "you he she it we they me my your our their this that with as so if "
                "do does did have has had not no yes ok okay just like u ur im its "
                "im going get got go can will would should could about out up".split())


def analyze(messages: list[str], name: str) -> dict:
    n = len(messages)
    char_lens = [len(m) for m in messages]
    word_lens = [len(m.split()) for m in messages]
    joined = "\n".join(messages)
    low = joined.lower()

    emoji_hits = EMOJI.findall(joined)
    all_lower = sum(1 for m in messages if m and m == m.lower() and any(c.isalpha() for c in m))
    no_end_punct = sum(1 for m in messages if m and m.rstrip()[-1:] not in ".?!")
    ellipsis = low.count("...")
    exclaim = joined.count("!")
    lone_i = len(re.findall(r"(?<![A-Za-z])i(?![A-Za-z'])", joined))  # lowercase standalone "i"

    words = [w.lower() for w in WORD.findall(joined)]
    content = [w for w in words if w not in STOPWORDS and len(w) > 2]
    bigrams = Counter(zip(words, words[1:]))
    trigrams = Counter(zip(words, words[1:], words[2:]))

    openers = Counter((m.split() or [""])[0].lower().strip(".,!?…")
                      for m in messages if m.strip())
    openers.pop("", None)
    # Whole-word matches only — avoid "af" inside "after", "ong" inside "wrong".
    slang_counts = {}
    for s in dict.fromkeys(SLANG):  # dedup, preserve order
        c = len(re.findall(r"\b" + re.escape(s) + r"\b", low))
        if c:
            slang_counts[s] = c

    def pct(x: int) -> float:
        return round(x / n, 3) if n else 0.0

    return {
        "name": name,
        "message_count": n,
        "length": {
            "chars_mean": round(statistics.mean(char_lens), 1) if n else 0,
            "chars_median": int(statistics.median(char_lens)) if n else 0,
            "words_mean": round(statistics.mean(word_lens), 1) if n else 0,
            "very_short_ratio": pct(sum(1 for c in char_lens if c <= 15)),
            "long_ratio": pct(sum(1 for c in char_lens if c >= 120)),
        },
        "style": {
            "all_lowercase_ratio": pct(all_lower),
            "no_end_punctuation_ratio": pct(no_end_punct),
            "lowercase_standalone_i": lone_i,
            "exclaims_per_msg": round(exclaim / n, 3) if n else 0,
            "ellipsis_count": ellipsis,
            "emoji_per_msg": round(len(emoji_hits) / n, 3) if n else 0,
        },
        "top_emoji": [e for e, _ in Counter(emoji_hits).most_common(8)],
        "favorite_words": [w for w, _ in Counter(content).most_common(25)],
        "signature_bigrams": [" ".join(b) for b, c in bigrams.most_common(40)
                              if c > 2 and not all(w in STOPWORDS for w in b)][:12],
        "signature_trigrams": [" ".join(t) for t, c in trigrams.most_common(60)
                               if c > 1 and sum(w in STOPWORDS for w in t) < 3][:8],
        "common_openers": [o for o, _ in openers.most_common(8)],
        "slang": slang_counts,
    }


def to_markdown(s: dict) -> str:
    name = s["name"]
    L, st = s["length"], s["style"]
    rules = []
    if st["all_lowercase_ratio"] > 0.5:
        rules.append("- Write in all lowercase (capitalize only for real emphasis).")
    if st["no_end_punctuation_ratio"] > 0.5:
        rules.append("- Usually no end punctuation. Don't end texts with a period.")
    if L["very_short_ratio"] > 0.4:
        rules.append("- Keep it short — often one line. Prefer several quick messages "
                     "over one long paragraph.")
    elif L["long_ratio"] > 0.3:
        rules.append("- Comfortable writing longer, fuller messages when it matters.")
    if s["style"]["emoji_per_msg"] > 0.2 and s["top_emoji"]:
        rules.append(f"- Emoji, used sparingly: {' '.join(s['top_emoji'][:5])}.")
    elif s["style"]["emoji_per_msg"] < 0.05:
        rules.append("- Rarely uses emoji.")
    if s["slang"]:
        rules.append(f"- Natural slang/abbreviations: {', '.join(list(s['slang'])[:8])}.")
    if s["common_openers"]:
        rules.append(f"- Common openers: {', '.join(s['common_openers'][:6])}.")
    voice = "\n".join(rules) or "- (Add observations from sample messages.)"

    return f"""You are {name}. Write exactly the way {name} writes — same tone,
length, punctuation, and word choice. Never sound more formal, polished, or
verbose than they do.

## VOICE (measured from {s['message_count']} of their messages)
{voice}

Favorite words: {', '.join(s['favorite_words'][:15])}
Signature phrases: {', '.join(s['signature_bigrams'][:8]) or '(none detected)'}
Typical length: ~{L['words_mean']} words / ~{L['chars_median']} chars.

## REASONING  (fill in from sample messages — see mirror-persona-analysis)
- How they think through a problem (lists? analogies? lead with the take?):
- How they handle uncertainty (hedge with "i think"/"tbh" vs assert):
- Humor:

## NEVER
- (Things this person would never say or do — fill in.)

<!-- Auto-generated by style_analyze.py. Edit freely; this file is the system
prompt for Path A and the --system-file for training Paths B/C. -->
"""


def main() -> None:
    ap = argparse.ArgumentParser(description="Analyze the user's voice into a style card.")
    ap.add_argument("inputs", nargs="+")
    ap.add_argument("--name", default="the user")
    ap.add_argument("--filter-source", help="Only analyze one source (e.g. gmail, whatsapp).")
    ap.add_argument("--samples", type=int, default=0,
                    help="Instead of writing a card, print N of the longest messages.")
    ap.add_argument("-o", "--output-dir", default="persona", help="Where to write the card.")
    args = ap.parse_args()

    msgs = []
    for p in args.inputs:
        for r in read_jsonl(p):
            if r.is_from_me and (r.text or "").strip():
                if args.filter_source and r.source != args.filter_source:
                    continue
                msgs.append(r.text.strip())

    if not msgs:
        print("No messages with is_from_me=true found — nothing to analyze.", file=sys.stderr)
        sys.exit(1)

    if args.samples:
        for m in sorted(msgs, key=len, reverse=True)[:args.samples]:
            print("—", m.replace("\n", " ⏎ "))
        return

    stats = analyze(msgs, args.name)
    os.makedirs(args.output_dir, exist_ok=True)
    with open(os.path.join(args.output_dir, "style_card.json"), "w", encoding="utf-8") as fh:
        json.dump(stats, fh, ensure_ascii=False, indent=2)
    with open(os.path.join(args.output_dir, "style_card.md"), "w", encoding="utf-8") as fh:
        fh.write(to_markdown(stats))
    print(f"Wrote style_card.json + style_card.md to {args.output_dir}/ "
          f"(analyzed {len(msgs)} messages). Now enrich the REASONING/NEVER sections.",
          file=sys.stderr)


if __name__ == "__main__":
    main()
