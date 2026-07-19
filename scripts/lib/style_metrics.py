"""Shared style-fingerprint metric definitions.

style_analyze.py measures these on the user's real messages and writes them
into persona/style_card.json; style_eval.py measures the SAME metrics on the
Mirror's predictions and compares the two. The definitions must be identical
on both sides — a drifted copy (e.g. a widened emoji range in one file) would
silently degrade eval scores — so both scripts import from here.
"""
from __future__ import annotations

import re
import statistics

# U+FE0F (variation selector-16) is deliberately excluded: it's an invisible
# modifier appended to many emoji, so counting it double-counts every VS16
# emoji and makes the blank glyph the #1 "top emoji" written into the card.
EMOJI = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F000-\U0001F0FF"
    "\U00002B00-\U00002BFF\U0001F1E6-\U0001F1FF\U00002190-\U000021FF]"
)
WORD = re.compile(r"[a-zA-Z']+")


def chars_mean(texts: list[str]) -> float:
    return statistics.mean(len(t) for t in texts) if texts else 0.0


def all_lowercase_ratio(texts: list[str]) -> float:
    if not texts:
        return 0.0
    return sum(1 for t in texts
               if t == t.lower() and any(c.isalpha() for c in t)) / len(texts)


def emoji_per_msg(texts: list[str]) -> float:
    if not texts:
        return 0.0
    return sum(len(EMOJI.findall(t)) for t in texts) / len(texts)


def no_end_punctuation_ratio(texts: list[str]) -> float:
    if not texts:
        return 0.0
    return sum(1 for t in texts if t and t.rstrip()[-1:] not in ".?!") / len(texts)
