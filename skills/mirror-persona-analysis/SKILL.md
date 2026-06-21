---
name: mirror-persona-analysis
description: >-
  Analyze the user's own messages to capture their voice into a portable "style
  card." Use after formatting and before/during model selection. Produces
  persona/style_card.json (hard statistics about tone, length, punctuation,
  emoji, signature phrases) and persona/style_card.md (the system prompt that
  IS the Mirror for Path A, and seeds the system message for Paths B/C). Combines
  a deterministic analyzer with your own qualitative read of sample messages.
---

# Mirror — persona analysis

The style card is the soul of the Mirror. For **Path A it literally is the
model** (the system prompt). For **Paths B/C** it's the system message every
training example carries, plus the rubric `mirror-evaluation` scores against.

## Step 1 — run the analyzer (deterministic stats)

```bash
python scripts/persona/style_analyze.py data/scrubbed.jsonl -o persona/ --name "Sam"
```

Writes:
- `persona/style_card.json` — measured voice: message-length distribution,
  emoji rate + favorites, punctuation/capitalization habits, all-lowercase
  ratio, signature words/phrases (n-grams), common openers and sign-offs, slang
  inventory, average burst length.
- `persona/style_card.md` — a first-draft system prompt auto-generated from those
  stats (e.g. "writes in all lowercase," "rarely uses end punctuation," "opens
  with 'yo' / 'hey'," "favorite words: …").

## Step 2 — enrich it (your qualitative read)

Stats capture *surface* voice. You add what they can't: **how the user thinks.**

1. Pull ~40 of the user's longer, substantive messages:
   ```bash
   python scripts/persona/style_analyze.py data/scrubbed.jsonl --samples 40
   ```
2. Read them and extend `style_card.md` with sections the analyzer can't measure:
   - **Reasoning style** — do they think in lists, analogies, first-principles,
     stories? Hedge or assert? Ask questions back?
   - **Values & recurring takes** — what they care about, opinions they repeat.
   - **Humor** — dry, self-deprecating, pun-heavy, none.
   - **Tone range** — warm with friends vs. crisp at work (note per-surface).
   - **Hard "nevers"** — things this person would never say or do (e.g. never
     uses corporate filler, never sends one-word replies to a real question).
3. Keep it concrete and prescriptive — it's a prompt, not an essay. Short,
   declarative voice rules outperform adjectives.

## Step 3 — make it the system prompt

The finished `style_card.md` becomes:
- Path A: the system prompt for `scripts/serve/mirror_chat.py`.
- Paths B/C: pass it via `--system-file persona/style_card.md` to
  `build_dataset.py` so every training example is anchored to the same voice.

## What good looks like

A strong style card reads like instructions a impersonator would need:

```
You are Sam. Write the way Sam texts.

VOICE
- All lowercase, except for emphasis (RARELY).
- Short. Usually 1–2 lines. Multiple quick messages over one long one.
- Minimal punctuation; no end periods. Em-dashes for asides.
- Emoji: sparing, mostly 😭 and 💀 for emphasis, never 🙂.
- Openers: "yo", "ok so", "honestly". Sign-offs: none, or "lmk".

REASONING
- Thinks out loud, then lands on a take. Leads with the conclusion when sure.
- Hedges with "i think" / "tbh" when unsure rather than faking confidence.
- Answers a question with the useful part first, caveats after.

NEVER
- Never corporate ("circle back", "per my last"). Never one-word replies to a
  real question. Never over-explains a joke.
```

## Tips

- Re-run the analyzer per surface (`--filter-source gmail` vs `--filter-source
  whatsapp`) — composed email voice differs from texting voice. If the Mirror
  targets one surface, build the card from that surface's messages.
- The JSON is also a machine-readable eval target — `mirror-evaluation` checks
  whether the Mirror's outputs match the measured length/emoji/lowercase stats.
