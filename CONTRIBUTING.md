# Contributing to Mirror

Thanks for helping. The most common and most valuable contribution is a **new
connector** (a parser for another app's export), so this guide focuses on that.

## Dev setup

The core pipeline is stdlib-only, so there's nothing to install to work on it.

```bash
python tests/test_pipeline.py        # regression suite (no deps)
python tests/test_connectors.py      # connector coverage
# or, with pytest:  pip install ".[dev]" && pytest
make lint                            # ruff check — CI gates on this
```

CI compiles `scripts` + `tests`, runs both suites on Python 3.9–3.12, and fails
on any `ruff check` finding. Keep the
core stdlib-only and avoid syntax newer than 3.9; put any heavy dependency behind
an optional extra in `pyproject.toml`.

## The data contract

Every connector emits the same record (one JSON object per line), defined in
`scripts/lib/schema.py`:

```json
{"source":"whatsapp","conversation_id":"Alex","timestamp":"2024-03-05T21:41:12Z",
 "sender":"me","is_from_me":true,"text":"running 5 min late lol","reply_to":null,"media":null}
```

`is_from_me` is load-bearing: the user's own messages become the voice the model
learns; everyone else is context. Get this right or the clone learns the wrong
person.

## Anatomy of a connector

Copy an existing one (`telegram_parse.py` is a good template) and follow the shape:

1. Bootstrap the import and pull in the schema helpers:
   ```python
   sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
   from lib.schema import MessageRecord, write_jsonl, iso_utc  # noqa: E402
   ```
2. `argparse` with: a positional `input`, a "who is me" flag (`--me` / `--me-id` /
   `--me-handle` as appropriate), and `-o/--output` defaulting to `-` (stdout).
3. A **streaming** generator — read the export line-by-line or with `iterparse`;
   never load a whole large export into memory.
4. For each message, build a `MessageRecord`, converting the timestamp to UTC with
   `iso_utc(...)` and setting `is_from_me`.
5. Finish with `n = write_jsonl(gen(), args.output)` and a one-line stderr report,
   including a warning if `is_from_me` was never true (don't ship `from_me == 0`
   silently).

## Checklist for a new connector

- [ ] Add the platform's `source` id to `KNOWN_SOURCES` in `scripts/lib/schema.py`.
- [ ] Stream input; drop media/placeholder/system lines (match whole lines, not
      substrings — see the WhatsApp parser's history for why).
- [ ] Make `--me*` detection fail loudly (warn on `from_me == 0`) rather than ship
      an empty voice.
- [ ] Add a fixture-based test to `tests/test_connectors.py` (subprocess style:
      build a tiny export in a temp dir, run the script, assert the records).
- [ ] Add `skills/mirror-connectors/references/<platform>.md` with the export steps.
- [ ] Register the platform in the table in `skills/mirror-connectors/SKILL.md`.

## Style

- Match the tone and structure of the existing scripts. Use forward-slash paths.
- Keep skill docs free of time-sensitive text ("currently", dates) per Anthropic's
  agent-skills guidance.
- No secrets or real PII in fixtures or examples.

## Pull requests

Run the tests, update the relevant `SKILL.md`/`references/` if you changed any
flags, and keep each PR focused on one change. See the PR template for the
checklist.
