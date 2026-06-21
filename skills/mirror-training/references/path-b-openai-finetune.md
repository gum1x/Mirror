# Path B — OpenAI fine-tune (SFT, optional DPO)

Bake the user's surface voice into a hosted model. Two stages: **SFT** (always),
then **DPO** (only if SFT reads too generic).

## Stage 1 — SFT

**Data:** `build_dataset.py --format openai-chat` → `data/train.jsonl`, one chat
example per line, the user's reply as the final `assistant` turn, the style card
as the `system` message.

**Validate, then show the user what uploads, then train:**
```bash
python scripts/train/openai_finetune.py data/train.jsonl --validate-only
# → counts examples, checks roles/format, flags anything malformed.

export OPENAI_API_KEY=...
python scripts/train/openai_finetune.py data/train.jsonl \
    --base gpt-4.1-mini --suffix mirror-sam
# → uploads the file, creates the SFT job, polls, prints the ft:... model id.
```

**Base model:** `gpt-4.1-mini` (default; best $/quality for voice) or `gpt-4.1`
("indistinguishable," longer-form). The newest frontier family is generally not
fine-tunable — stay on the 4.1 family.

**Hyperparameters:** let OpenAI default `n_epochs` from dataset size; adjust only
on eval evidence — **+1–2 epochs** if it doesn't follow your style, **−1–2** if
outputs get repetitive/less diverse. (See `data-volume-and-epochs.md`.)

**What uploads:** the entire `data/train.jsonl`. Run `pii_scrub.py` first and
show a sample before confirming.

## Stage 2 — DPO (optional polish)

Use only if SFT still sounds a little too "assistant." DPO teaches *prefer my
real reply over a generic one*.

**Data prep:** `build_dataset.py --format dpo` emits the preferred side (your real
replies) + an empty `non_preferred_output`. Fill the rejected side by sampling
the **base** model on each prompt:
```bash
python scripts/train/openai_finetune.py data/dpo_skeleton.jsonl \
    --build-dpo --base gpt-4.1-mini -o data/dpo.jsonl
# → for each prompt, calls the base model to generate a "generic" rejected reply,
#   writes complete DPO triples (prompt, preferred=yours, rejected=generic).
```
Then train DPO on top of the SFT model:
```bash
python scripts/train/openai_finetune.py data/dpo.jsonl \
    --method dpo --base <your-sft-ft-id> --suffix mirror-sam-dpo
```
DPO is a *light* pass — 1–2 epochs. It sharpens tone; it won't add knowledge.

## Serving

Record the final `ft:...` id in `mirror.config.yaml`. Serve with
`scripts/serve/mirror_chat.py --path B --model ft:...`. Keep the style card as the
system message at inference too — fine-tuning + a matching system prompt
reinforce each other.

## Knowledge caveat

SFT/DPO bake in *voice*, not *facts*. If the Mirror needs to answer from the
user's real knowledge, bolt RAG on at serve time (same retrieval as Path A) or
run a Hybrid. Don't try to "teach facts" by adding more epochs — that overfits.

## Cost & privacy

- You pay for training tokens (once) + per-token inference (ongoing). `4.1-mini`
  is much cheaper to train and serve than `4.1`.
- Your scrubbed dataset is uploaded to OpenAI for training and the model is
  hosted there. If that's unacceptable, use Path C instead.

## Sources
- [OpenAI — Supervised fine-tuning](https://developers.openai.com/api/docs/guides/supervised-fine-tuning)
- [OpenAI — Direct preference optimization](https://platform.openai.com/docs/guides/direct-preference-optimization)
- [OpenAI cookbook — SFT vs DPO vs RFT](https://cookbook.openai.com/examples/fine_tuning_direct_preference_optimization_guide)
