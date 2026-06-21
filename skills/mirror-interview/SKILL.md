---
name: mirror-interview
description: >-
  Interview the user before building their Mirror. Use at the start of a Mirror
  project (or when mirror.config.yaml is missing/incomplete) to elicit goals,
  use case, data sources, privacy constraints, budget, and hardware. Produces
  the answers that drive connector selection and the model-selection decision.
---

# Mirror — interview

Conduct a short, friendly interview, then write `mirror.config.yaml`. Don't ask
all of this at once — group into a few `AskUserQuestion` rounds, lead with your
recommendation where there's an obvious default, and skip questions the user has
already answered. Each answer maps to a concrete downstream decision (right
column) — keep that in mind so you ask only what changes the build.

## Round 1 — What are we building?

| Question | Options | Drives |
|----------|---------|--------|
| **What should your Mirror do?** | `autoreply` (texts/emails for me) · `knowledge_qa` (answers questions as me, from what I know) · `thought_partner` (thinks through problems like me) · `full_clone` (all of it) · `journaling` (continues my private writing) | The whole model-selection tree. `knowledge_qa`/`thought_partner` lean Path A; `autoreply` leans B/C; `full_clone` → hybrid. |
| **Where will you use it?** | chat · email · SMS/iMessage · API/embed | Surface affects message-length targets and serving. |
| **How "you" does it need to be?** | "sounds roughly like me" · "indistinguishable from me" | Higher bar → fine-tune + DPO and/or larger corpus. |

## Round 2 — Privacy & ownership (this is the big fork)

| Question | Options | Drives |
|----------|---------|--------|
| **Where is it OK for your data to go?** | `cloud_ok` (Anthropic/OpenAI APIs are fine) · `hosted_finetune` (OK to upload a scrubbed dataset to one vendor) · `fully_local` (nothing leaves my machine, ever) | `fully_local` ⇒ **Path C only**. `cloud_ok` opens Path A. `hosted_finetune` opens Path B. |
| **Do you want to *own the weights*?** | yes (a model file I keep) · no (a hosted endpoint is fine) | "yes" ⇒ Path C. "no" is fine for A/B. |

State plainly what each path sends where:
- **Path A (Claude prompt + RAG):** your style card + retrieved snippets of your
  messages go to Anthropic at inference time. No training upload.
- **Path B (OpenAI fine-tune):** your *whole scrubbed dataset* is uploaded to
  OpenAI once for training; inference is hosted.
- **Path C (local LoRA):** nothing leaves your machine.

## Round 3 — Budget & hardware

| Question | Options | Drives |
|----------|---------|--------|
| **Budget?** | none · low (~$ tens) · medium (~$ hundreds) · high | None+local ⇒ Path C on your GPU. Low ⇒ Path A pay-as-you-go or Path B mini. |
| **Do you have a GPU?** | no · yes — consumer (8–24 GB) · yes — datacenter (A100/H100) | Consumer GPU runs 7–8B QLoRA. None ⇒ rent or go hosted. |
| **How soon do you want a working Mirror?** | today · this week · no rush | "today" ⇒ Path A (no training loop). |

## Round 4 — Data inventory

Ask which platforms they have history on, and roughly how much. The more "me"
messages, the more fine-tuning becomes viable.

| Question | Why |
|----------|-----|
| **Which apps hold your conversations?** (WhatsApp, iMessage/SMS, Telegram, Gmail/Outlook, Slack, Discord, Instagram, …) | Enables connectors; each has its own export path (`mirror-connectors`). |
| **Roughly how many years / messages?** | Sets expectations. < ~300 of *your* messages ⇒ Path A strongly preferred. |
| **Any conversations or topics to exclude?** | Feeds `data.custom_redactions` and conversation filtering. |
| **What's your name/handle/number/email on each platform?** | Needed so connectors can flag `is_from_me` correctly. |

## After the interview

1. Write `mirror.config.yaml` from `config/mirror.config.example.yaml`, filling in
   `identity`, `goal`, `connectors`, and a *provisional* `training.path` (the
   model-selection skill confirms it later).
2. Give the user a one-paragraph summary: "Here's what I'll build, here's the
   path I expect to recommend, and here's what (if anything) will leave your
   machine."
3. Hand back to the `mirror` orchestrator to begin ingestion.

## Quick mapping cheat-sheet

```
fully_local .................................. Path C (local LoRA)
cloud_ok + today + reasoning/knowledge ....... Path A (Claude prompt + RAG)
hosted_finetune + autoreply + lots of data ... Path B (OpenAI SFT, +DPO if picky)
full_clone + cloud_ok ........................ Hybrid: A for brains + B/C for voice
< ~300 of my own messages .................... Path A regardless (too little to train)
```
