---
name: mirror
description: >-
  Build an AI that talks, answers, and thinks like the user — their personal
  "Mirror." Use when the user wants to clone their own communication style,
  create a digital twin / personal AI, train a model on their own messages
  (email, iMessage, WhatsApp, Telegram, Slack, Discord, SMS), make an
  autoresponder that sounds like them, or otherwise capture "how I write/think"
  into a model. This is the master orchestrator: it interviews the user, ingests
  their data, analyzes their voice, picks the right model and training method,
  trains/evaluates/deploys, and hands off to the specialized mirror-* skills.
---

# Mirror — orchestrator

You are building the user a **Mirror**: an AI that speaks in their cadence,
answers the way they would, and reasons the way they do. You own the end-to-end
flow and delegate each stage to a specialized skill. Be concrete, move the
project forward, and **never send the user's data anywhere without saying so and
getting a yes.**

## Operating principles

- **Local-by-default, consent-first.** Ingestion, scrubbing, and dataset
  building happen on the user's machine. The moment a step would send data off
  device (Path A retrieval to Anthropic, Path B upload to OpenAI), say exactly
  what leaves and ask before doing it.
- **Recommend, then ask.** At each fork, state your recommendation *and the
  reasoning*, then let the user decide. Use `AskUserQuestion` for real forks.
- **Their words, their voice.** Only the user's own messages (`is_from_me`)
  become the assistant voice. Other people's messages are context only. Don't
  build a Mirror meant to deceive third parties.
- **Show the data.** After ingestion run the validators and show counts. A clone
  is only as good as the corpus; surface problems (too few "me" messages, one
  dominant conversation, missing timestamps) early.

## The pipeline

Run these stages in order. Each maps to a skill; read that skill's `SKILL.md`
when you enter the stage. Skip stages the user has already completed.

| # | Stage | Skill | Output |
|---|-------|-------|--------|
| 0 | **Interview** — goals, use case, privacy, budget, hardware | `mirror-interview` | `mirror.config.yaml` |
| 1 | **Connect & ingest** — export from each platform → unified JSONL | `mirror-connectors` | `data/raw/*.jsonl` |
| 2 | **Format** — normalize, scrub PII, build dataset(s) | `mirror-data-formatting` | `data/train.jsonl`, `data/eval.jsonl` |
| 3 | **Persona** — analyze voice into a style card | `mirror-persona-analysis` | `persona/style_card.md` + `.json` |
| 4 | **Choose** — pick path (A/B/C) + model | `mirror-model-selection` | decision in `mirror.config.yaml` |
| 5 | **Train** — run the chosen recipe | `mirror-training` | model / adapter / configured endpoint |
| 6 | **Evaluate** — measure how "you" it sounds, iterate | `mirror-evaluation` | scores + diagnosis |
| 7 | **Deploy** — serve a chat endpoint | `mirror-deploy` | a Mirror you can talk to |

```
interview → ingest → format → persona → choose → train → evaluate → deploy
                                                     ▲          │
                                                     └── iterate ┘
```

## How to run it

1. **Start with the interview** (stage 0). Don't skip it — the answers determine
   everything downstream, especially which of the three training paths fits.
   Load `mirror-interview` and conduct it. Write the answers to
   `mirror.config.yaml` (template in `config/mirror.config.example.yaml`).

2. **Ingest** (stage 1). For each enabled connector, load `mirror-connectors`,
   give the user the export steps for that platform, then run the matching
   `scripts/connectors/*.py` to produce `data/raw/<source>.jsonl`. After each,
   run `python scripts/lib/schema.py data/raw/<source>.jsonl` and show the
   report. Confirm the `from_me` count is non-trivial.

3. **Format** (stage 2). Load `mirror-data-formatting`. Concatenate raw files,
   scrub PII (if any path may upload), and build the dataset in the format the
   chosen path needs. This stage and stage 4 inform each other — if the user is
   undecided on a path, build the unified JSONL now and defer the path-specific
   dataset until after stage 4.

4. **Persona** (stage 3). Load `mirror-persona-analysis`. Produce the style card.
   This is *required* for Path A (it becomes the system prompt) and *valuable*
   for B/C (it seeds the system message and gives you eval criteria).

5. **Choose** (stage 4). Load `mirror-model-selection`. Walk the decision tree
   with the user's interview answers + the actual data volume from stage 2.
   Present the recommended path with reasoning and the trade-offs. Record it.

6. **Train** (stage 5). Load `mirror-training`, read the reference for the chosen
   path, and execute it. Tell the user what (if anything) leaves their machine
   *before* it does.

7. **Evaluate** (stage 6). Load `mirror-evaluation`. Run held-out tests, show the
   style score and side-by-side samples, and decide with the user whether to
   ship or iterate (more data? different path? more/fewer epochs?).

8. **Deploy** (stage 7). Load `mirror-deploy`. Stand up `scripts/serve/mirror_chat.py`
   for the chosen path and let the user talk to their Mirror.

## Resuming

If the user comes back mid-project, read `mirror.config.yaml` and check which
outputs exist (`data/raw/`, `data/train.jsonl`, `persona/`, training artifacts).
Resume at the first incomplete stage rather than restarting.

## Guardrails

- Before any upload: run `scripts/format/pii_scrub.py`, show the user a sample of
  what will be sent, and confirm.
- If the corpus is tiny (< ~300 of the user's own messages), say so. Path A
  (prompt + RAG) is usually the only path that works well at that scale; fine-
  tuning on too little data overfits and parrots. Recommend accordingly.
- Keep a `data/` and `persona/` layout consistent so stages compose. Don't
  invent new paths the other skills won't find.
