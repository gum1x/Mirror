# Reference: training approaches (prompt+RAG vs SFT vs DPO vs LoRA)

The four levers Mirror can pull, what each actually does for a *voice/clone*
task, and when to reach for it.

## 1. Prompt + RAG (Path A) — no weight changes

**What it is:** a detailed system prompt (the style card) tells the model *how*
to sound; retrieval pulls the user's real past messages relevant to the current
query and drops them in context so the model answers with the user's actual
positions and knowledge.

**Captures:** reasoning style, knowledge/facts (grounded, not hallucinated),
tone — and you can change any of it instantly by editing the prompt.
**Misses:** the very last 5% of *surface* mimicry that only weight-tuning locks
in (a fine-tune "is" you without being told; a prompt "acts" like you).

**Reach for it when:** you want it working today; the task is reasoning/knowledge
/thought-partner; the corpus is small; you can't or won't train; you want the
smartest base model. **This is Mirror's default and the best path for "answers
and thinks like me."**

**RAG mechanics (see `mirror-training/references/path-a-claude-prompt-rag.md`):**
index the user's messages; at query time retrieve the top-k most similar past
messages (semantic or keyword) and the surrounding turns; include them as
"here's how you've talked about this before."

## 2. Supervised fine-tuning — SFT (Paths B & C)

**What it is:** show the model thousands of (context → your reply) pairs; it
adjusts weights to imitate. This is the core "train it to write like me" step.

**Captures:** surface voice — cadence, length, punctuation, idiom, sign-offs —
baked in, no prompt needed at inference.
**Misses:** facts it never saw (it'll confabulate in your voice). Don't rely on
SFT for knowledge; ground with RAG if you need it.

**Reach for it when:** the job is producing your voice at scale (autoreply), you
have enough data (see data-volume reference), and a hosted (B) or local (C)
trained model is acceptable.

**Knobs:** base model, epochs (1–4), learning-rate multiplier, context length.
Start with vendor defaults; tune epochs by the overfitting signals below.

## 3. Direct Preference Optimization — DPO (Path B refine, after SFT)

**What it is:** a *second* pass after SFT. Give pairs of (preferred = your real
reply, rejected = a more generic/assistant-y reply). The model learns to prefer
"more you, less generic."

**Captures:** sharper voice and tone — kills the residual "helpful assistant"
register SFT sometimes leaves.
**Use when:** SFT alone reads slightly too polished/generic and the user wants
"indistinguishable." Skip it if SFT is already convincing.

**Data:** `build_dataset.py --format dpo` emits the preferred side (your real
replies) + a skeleton; the training step fills the rejected side by sampling the
*base* model on the same prompts. (DPO is normally a polish pass on top of SFT,
not a replacement.)

## 4. LoRA / QLoRA (Path C) — parameter-efficient SFT you own

**What it is:** SFT, but instead of updating all weights you train a small
low-rank *adapter* (LoRA). QLoRA quantizes the base to 4-bit so a 7–8B model
fine-tunes on a single consumer GPU; you get an adapter file (tens of MB) you
merge or load at inference.

**Captures:** same as SFT (surface voice), fully locally, weights you own.
**Reach for it when:** privacy/ownership is the priority, or you want offline.

**Knobs:** `r` (rank, 8–32; higher = more capacity/overfit risk), `alpha`
(usually 2×r), target modules (attention + MLP projections), epochs (1–3),
4-bit vs 8-bit. Defaults in `config/mirror.config.example.yaml`.

## Putting it together — the "how many trains" question

A full clone is usually **not one train but a small sequence of stages**:

| Stage | What it does | Path |
|-------|--------------|------|
| 0. Style card | Encodes voice as a prompt | A (and seeds B/C system msg) |
| 1. SFT / QLoRA | Bakes in surface voice | B / C |
| 2. DPO (optional) | Sharpens "more me, less generic" | B |
| 3. RAG layer | Grounds answers in real knowledge | A (or bolt onto B/C at serve time) |
| 4. Eval loop | Measure → adjust data/epochs → retrain | all |

Most users need **stage 0 alone (Path A)** or **stages 0–1 (one SFT/QLoRA run)**.
Add stage 2 only if eval says the voice is too generic; add stage 3 whenever
knowledge fidelity matters. Expect to iterate stage 1 once or twice as the eval
loop tells you to add data or change epochs — not dozens of runs.
