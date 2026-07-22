# Security

Mirror processes some of the most sensitive data you have: your private
messages. Read this and [THREAT_MODEL.md](THREAT_MODEL.md) before running it
on real data.

## Supported versions

Mirror is a single-branch personal tool: security fixes land on `main`, and
there are no maintained release branches. Run from a recent `main`.

## Reporting a vulnerability

If a report could expose user data, don't file a public issue. Use GitHub's
private vulnerability reporting on this repo (Security tab → "Report a
vulnerability") or contact the maintainer directly. Include steps to reproduce,
the affected file or stage, and — for a failing Anthropic/OpenAI call — the
`request_id` so it can be traced. Anything non-sensitive can just be a normal
GitHub issue.

## What holds, and what doesn't

- The core pipeline (ingest, normalize, scrub, build, persona) is stdlib-only
  and makes no network calls. CI runs the suite on every push, across Python
  3.9–3.14.
- PII scrubbing is regex-based and best-effort. It catches structured PII
  (URLs, emails, phone numbers, cards, SSNs, IPs, US-style addresses and dates
  of birth) in a single non-overlapping pass, but it does **not** reliably catch
  names or unusual formats. Treat the privacy notes as guidance, not a
  guarantee.
- `--custom` terms are matched as **literal text, not regex** (the scrubber
  warns if you pass regex metacharacters). A term you intended as a pattern
  matches nothing instead — the wrong direction for a privacy scrub — so add
  each spelling you want removed explicitly.
- Scrubbing applies to message **text only**. Metadata fields — `sender`,
  `conversation_id`, and e.g. Gmail's `extra.subject` — keep raw phone numbers,
  emails, and subject lines in `data/scrubbed.jsonl` (for iMessage/SMS the
  sender *is* a phone number). Dataset building and RAG only read the text, so
  this metadata stays local, but the file still holds your contact graph. Treat
  it accordingly.

## Before anything leaves your machine

A scrub miss in a Path B upload is the highest-cost, least-reversible failure —
your whole dataset goes to OpenAI in one shot. Shrink the blast radius:

- **Preview first.** `pii_scrub.py --report` counts redactions without writing
  an output file, so you can eyeball coverage before committing.
- **Keep an audit trail.** `pii_scrub.py --manifest` writes
  `REDACTION_MANIFEST.json` — redaction counts plus SHA-256 hashes of the input
  and output files. It never stores the custom literals themselves (those are
  the PII being hidden).
- **Read the built dataset.** `build_dataset.py` writes a `DATASET_CARD.md` next
  to the output recording exactly what went in (sources, counts, settings).
- **For high-stakes data,** layer a dedicated NER/PII tool (e.g. Microsoft
  Presidio) on top of the regex pass, or prefer a path that uploads nothing:
  Path A retrieves snippets per request, Path C stays fully local.

## Serving over HTTP

`mirror_server.py` is the one long-lived network surface, and with `--rag` it
can quote your real messages to any caller. Treat the endpoint as sensitive:

- **Auth is off until you set `MIRROR_TOKEN`.** Set it to require
  `Authorization: Bearer $MIRROR_TOKEN` on `/chat` and `/v1/chat/completions`
  (the token is compared in constant time). `/healthz` stays open.
- **Binding beyond loopback requires the token.** A `--host` other than
  `127.0.0.1` / `localhost` / `::1` refuses to start without `MIRROR_TOKEN`, so
  you can't accidentally expose your corpus to the network.
- **On loopback without a token, any local process can query the Mirror** (and,
  with `--rag`, retrieve your real messages). The server prints this as a NOTE
  on startup — set the token even locally on a shared machine.
- **DNS-rebinding is blocked on loopback:** the `Host` header is validated
  against the loopback names, so a malicious web page can't rebind its origin
  onto your local server and read the responses.

## Handling secrets and local artifacts

- API keys are read from the environment (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`,
  and `MIRROR_TOKEN` for the server) and are never logged. Don't paste keys into
  config files or commit them.
- `.gitignore` excludes your real data (`data/`, `persona/`, `adapters/`,
  `merged/`, `eval/`), raw exports (`exports/`, `*.mbox`), your real config
  (`mirror.config.yaml`, at any depth), and generated `*.jsonl` (except the
  bundled `examples/`). Keep it that way.
- **Tear down when you're done.** `maintenance/purge.py` (dry-run by default;
  `--yes` to delete) removes local artifacts and reminds you how to delete the
  training file and fine-tuned model a Path B run left in your OpenAI account.
  On SSDs, a delete isn't a secure-erase guarantee.

## Supply chain

- Heavy dependencies (Anthropic/OpenAI SDKs, torch/transformers/peft, Unsloth,
  sentence-transformers) are optional extras installed per path, never by the
  core. Pin them where you can.
- Path C loads model weights from the Hugging Face Hub. Prefer pinning a
  `revision` (commit) for the base model and adapter, and install Unsloth from
  a pinned commit (`@<sha>`). Keep `trust_remote_code` off.
- CI pins its GitHub Actions by commit SHA and ruff by version, so a compromised
  or breaking upstream release can't silently change what runs.

## Responsible use

Don't deploy a Mirror that impersonates you to deceive other people. If you
point it at a real conversation, disclose that an AI may be replying. See
[THREAT_MODEL.md](THREAT_MODEL.md) for the impersonation risk.
