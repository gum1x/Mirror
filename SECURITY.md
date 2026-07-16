# Security

Mirror processes some of the most sensitive data you have: your private
messages. Read this and [THREAT_MODEL.md](THREAT_MODEL.md) before running it
on real data.

## Reporting a vulnerability

If a report could expose user data, don't file a public issue. Use GitHub's
private vulnerability reporting on this repo (Security tab → "Report a
vulnerability") or contact the maintainer directly. Include steps to reproduce
and the affected file or stage. Anything non-sensitive can just be a normal
GitHub issue.

## What holds, and what doesn't

- The core pipeline (ingest, normalize, scrub, build, persona) is stdlib-only
  and makes no network calls. CI runs the suite on every push.
- PII scrubbing is regex-based and best-effort. It catches structured PII
  (emails, phones, cards, SSNs, IPs, basic addresses, dates of birth) but it
  does not reliably catch names or unusual formats. Treat the privacy notes as
  guidance, not a guarantee. Always review what you're about to upload, and
  use `--custom` (and, optionally, an NER tool such as Microsoft Presidio) for
  names.
- Scrubbing applies to message text only. Metadata fields — `sender`,
  `conversation_id`, and e.g. Gmail's `extra.subject` — keep raw phone
  numbers, emails, and subject lines in `data/scrubbed.jsonl` (for
  iMessage/SMS the sender *is* a phone number). Dataset building and RAG only
  use the text, so this metadata stays local, but the file itself still
  contains your contact graph. Treat it accordingly.

## Handling secrets

- API keys are read from the environment (`ANTHROPIC_API_KEY`,
  `OPENAI_API_KEY`) by the official SDKs and are never logged by Mirror. Don't
  paste keys into config files or commit them.
- The `.gitignore` excludes your real data (`data/`, `persona/`, `adapters/`,
  `eval/`), your real config (`mirror.config.yaml` at any depth), and
  generated `*.jsonl` (except the bundled `examples/`). Keep it that way.

## Supply chain

- Heavy dependencies (Anthropic/OpenAI SDKs, torch/transformers/peft, Unsloth,
  sentence-transformers) are optional extras installed per path, never by the
  core. Pin them where you can.
- Path C loads model weights from the Hugging Face Hub. Prefer pinning a
  `revision` (commit) for the base model and adapter, and install Unsloth from
  a pinned commit (`@<sha>`). Keep `trust_remote_code` off.
- When reporting an issue, include the `request_id` from any failing
  Anthropic/OpenAI call so it can be traced.

## Responsible use

Don't deploy a Mirror that impersonates you to deceive other people. If you
point it at a real conversation, disclose that an AI may be replying. See
[THREAT_MODEL.md](THREAT_MODEL.md) for the impersonation risk.
