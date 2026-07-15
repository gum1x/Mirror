# Security

Mirror processes some of the most sensitive data you have: your private messages.
Please read this and [THREAT_MODEL.md](THREAT_MODEL.md) before running it on real data.

## Reporting a vulnerability

Open a GitHub issue for non-sensitive reports. For anything that could expose
user data, contact the maintainer privately (see the repo's contact details)
rather than filing a public issue. Please include steps to reproduce and the
affected file/stage.

## What we guarantee, and what we don't

- The **core pipeline** (ingest, normalize, scrub, build, persona) is
  stdlib-only and makes **no network calls**. CI runs the suite on every push.
- PII scrubbing is **regex-based and best-effort**. It catches structured PII
  (emails, phones, cards, SSNs, IPs, basic addresses, dates of birth) but does
  **not** reliably catch names or unusual formats. Treat the privacy notes as
  guidance, not a guarantee. Always review what you're about to upload, and use
  `--custom` (and, optionally, an NER tool such as Microsoft Presidio) for names.
- Scrubbing applies to **message text only**. Metadata fields — `sender`,
  `conversation_id`, and e.g. Gmail's `extra.subject` — keep raw phone numbers,
  emails, and subject lines in `data/scrubbed.jsonl` (for iMessage/SMS the
  sender *is* a phone number). Dataset building and RAG only use the text, so
  this metadata stays local, but the file itself still contains your contact
  graph — treat it accordingly.

## Handling secrets

- API keys are read from the environment (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`)
  by the official SDKs and are never logged by Mirror. Don't paste keys into
  config files or commit them.
- The `.gitignore` excludes your real data (`data/`, `persona/`, `adapters/`,
  `eval/`), your real config (`mirror.config.yaml` at any depth), and generated
  `*.jsonl` (except the bundled `examples/`). Keep it that way.

## Supply chain

- Heavy dependencies (Anthropic/OpenAI SDKs, torch/transformers/peft, Unsloth,
  sentence-transformers) are **optional extras** installed per path, never by the
  core. Pin them where you can.
- Path C loads model weights from the Hugging Face Hub. Prefer pinning a
  `revision` (commit) for the base model and adapter, and install Unsloth from a
  pinned commit (`@<sha>`). Keep `trust_remote_code` off.
- When reporting an issue, include the `request_id` from any failing
  Anthropic/OpenAI call so it can be traced.

## Responsible use

Don't deploy a Mirror that impersonates you to deceive other people. If you point
it at a real conversation, disclose that an AI may be replying. See
[THREAT_MODEL.md](THREAT_MODEL.md) for the impersonation risk.
