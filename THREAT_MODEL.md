# Threat model

What Mirror trusts, what it exposes, and to whom. This is a personal tool run on
your own data; the model below reflects that.

## Assets

- Your messages (raw and scrubbed) in `data/`.
- A profile of how you write (`persona/style_card.*`).
- Models trained on your messages (`adapters/`, `merged/`).
- Your API keys (in the environment).

## Trust boundaries by path

The only places data crosses your machine's boundary are the three serving/training paths.

| Path | What leaves your machine | To whom | Persists where |
|------|--------------------------|---------|----------------|
| **A — Claude persona + RAG** | Your style card + the few retrieved snippets of your real messages + the live conversation, per request | Anthropic API | Per Anthropic's data policy. No training upload. |
| **B — OpenAI fine-tune** | Your **entire scrubbed dataset** (one upload) and every inference request | OpenAI API | An uploaded file + a hosted fine-tuned model remain in your OpenAI account until you delete them (`scripts/maintenance/purge.py` reminds you how). |
| **C — Local LoRA** | Nothing | — | Local only. Trusts the Hugging Face model/adapter supply chain at load time. |

The core pipeline (ingest → format → persona → build) sends nothing anywhere.

## Assumptions

- The machine running Mirror is trusted; disk is not encrypted by Mirror.
- API keys in the environment are controlled by you.
- Regex PII scrubbing is best-effort (see SECURITY.md). A scrub miss in a Path B
  upload is the highest-cost, least-reversible failure; review before uploading.
- Group chats contain other people's words. Mirror only **trains** on your own
  messages (`is_from_me`), but other participants' text is **retrievable context**
  for Path A and is present in `data/`. Don't redistribute it.

## Residual risks (and mitigations)

- **PII leak via scrub miss → Path B upload.** Mitigation: review the dataset,
  use `--custom`/NER, keep a `REDACTION_MANIFEST.json`, and prefer Path A/C if the
  data is especially sensitive.
- **Impersonation / deception.** A Mirror that auto-replies as you can mislead a
  counterparty. Mitigation: get consent, disclose that an AI may reply, and gate
  high-stakes replies behind human review. Don't use it to deceive.
- **Supply chain (Path C).** A swapped/hijacked model repo could ship code or bad
  weights. Mitigation: pin `revision`, install Unsloth from a pinned commit, keep
  `trust_remote_code` off.
- **Forgotten sensitive data.** Local artifacts and a remote OpenAI file/model
  linger. Mitigation: `scripts/maintenance/purge.py`.

## Out of scope

Hardening the host OS, full-disk encryption, network egress filtering, and the
security of Anthropic/OpenAI/Hugging Face themselves are out of scope for this
tool.
