<!-- Keep this short. Delete sections that don't apply. -->

## What this changes

<!-- One or two sentences. What did you add or fix, and why? -->

## Stage(s) touched

<!-- e.g. connect/ingest (telegram), format (build_dataset), serve -->

## Checklist

- [ ] Ran the suite: `python tests/test_pipeline.py` (and `make test` if you added tests)
- [ ] If I changed a script's flags or output, I updated its `SKILL.md` and any docs that quote the command
- [ ] No real data, secrets, or other people's messages in fixtures — sample data is synthetic
- [ ] If I added a connector, it emits the unified schema and round-trips through `scripts/lib/schema.py`
