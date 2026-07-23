#!/usr/bin/env python3
"""Drive an OpenAI fine-tune (SFT or DPO) for the Mirror's voice — Path B.

    python openai_finetune.py data/train.jsonl --validate-only
    python openai_finetune.py data/train.jsonl --base gpt-4.1-mini --suffix mirror-sam
    python openai_finetune.py data/dpo_skeleton.jsonl --build-dpo --base gpt-4.1-mini \
        -o data/dpo.jsonl
    python openai_finetune.py data/dpo.jsonl --method dpo --base ft:... --suffix mirror-sam-dpo

Validation runs with no API key. Training/DPO-build need OPENAI_API_KEY.
"""
from __future__ import annotations

import argparse
import functools
import json
import os
import sys
import time
from collections import Counter


def load_jsonl(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def validate_sft(rows: list[dict]) -> bool:
    ok = True
    roles = Counter()
    for i, row in enumerate(rows):
        msgs = row.get("messages")
        if not msgs:
            print(f"  line {i}: missing 'messages'", file=sys.stderr)
            ok = False
            continue
        for m in msgs:
            roles[m.get("role")] += 1
        if msgs[-1].get("role") != "assistant":
            print(f"  line {i}: last message must be 'assistant'", file=sys.stderr)
            ok = False
        if not any(m.get("role") == "user" for m in msgs):
            print(f"  line {i}: needs at least one 'user' message", file=sys.stderr)
            ok = False
    print(f"Examples: {len(rows)} | role counts: {dict(roles)}", file=sys.stderr)
    if len(rows) < 10:
        print("  ⚠️  OpenAI requires ≥10 examples; aim for hundreds for a voice clone.",
              file=sys.stderr)
    print("Validation: " + ("PASS" if ok else "FAIL"), file=sys.stderr)
    return ok


def validate_dpo(rows: list[dict]) -> bool:
    ok = True
    for i, row in enumerate(rows):
        if not row.get("input", {}).get("messages"):
            print(f"  line {i}: missing input.messages", file=sys.stderr)
            ok = False
        if not row.get("preferred_output"):
            print(f"  line {i}: missing preferred_output", file=sys.stderr)
            ok = False
        if not row.get("non_preferred_output"):
            print(f"  line {i}: empty non_preferred_output — run --build-dpo first "
                  "to fill the rejected side", file=sys.stderr)
            ok = False
    print(f"DPO examples: {len(rows)} | validation: " + ("PASS" if ok else "FAIL"),
          file=sys.stderr)
    return ok


def get_client():
    try:
        from openai import OpenAI
    except ImportError:
        sys.exit("Install the client first:  pip install openai")
    return OpenAI()


def _with_retries(fn, what: str, tries: int = 5):
    """Run fn() with exponential backoff; each completion here costs money, so
    a transient 429/5xx at row 900/1000 must not throw away 900 paid calls."""
    for attempt in range(tries):
        try:
            return fn()
        except Exception as e:
            if attempt == tries - 1:
                raise
            wait = 2 * 2 ** attempt
            print(f"  {what}: {e} — retrying in {wait}s", file=sys.stderr)
            time.sleep(wait)


def build_dpo(rows: list[dict], base: str, out: str) -> None:
    """Fill non_preferred_output by sampling the base model on each prompt.

    Appends to `out` and resumes after the rows already written (one output
    line per input row, always), so a crash at row N doesn't re-buy N
    completions on the rerun.
    """
    client = get_client()
    done = 0
    if os.path.exists(out):
        with open(out, encoding="utf-8") as fh:
            done = sum(1 for line in fh if line.strip())
        if done:
            print(f"  resuming: {done}/{len(rows)} rows already in {out}", file=sys.stderr)
    unfilled = 0
    with open(out, "a", encoding="utf-8") as fh:
        for i, row in enumerate(rows[done:], start=done):
            resp = _with_retries(
                functools.partial(client.chat.completions.create, model=base,
                                  messages=row["input"]["messages"],
                                  temperature=1.0, max_tokens=300),
                f"row {i}")
            rejected = resp.choices[0].message.content
            if rejected:
                row["non_preferred_output"] = [{"role": "assistant", "content": rejected}]
            else:
                # content filter etc. can return None; keep the row (and the
                # 1:1 line alignment resume depends on) but leave it unfilled
                unfilled += 1
                print(f"  row {i}: empty completion — left unfilled", file=sys.stderr)
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            fh.flush()
            if (i + 1) % 25 == 0:
                print(f"  built {i + 1}/{len(rows)} DPO triples", file=sys.stderr)
    print(f"Wrote DPO dataset → {out}", file=sys.stderr)
    if unfilled:
        print(f"  ⚠️  {unfilled} row(s) have an empty non_preferred_output; validation "
              "will flag them — remove those lines before training.", file=sys.stderr)


def run_job(path: str, base: str, method: str, suffix: str, epochs) -> None:
    client = get_client()
    print(f"Uploading {path} …", file=sys.stderr)
    with open(path, "rb") as fh:
        up = client.files.create(file=fh, purpose="fine-tune")

    hp = {} if epochs is None else {"n_epochs": epochs}
    method_obj = ({"type": "supervised", "supervised": {"hyperparameters": hp}}
                  if method == "sft" else
                  {"type": "dpo", "dpo": {"hyperparameters": hp}})
    job = client.fine_tuning.jobs.create(
        training_file=up.id, model=base, suffix=suffix, method=method_obj)
    job_id = job.id
    print(f"Created job {job_id} ({method} on {base}). Polling …", file=sys.stderr)
    print(f"  (Ctrl-C is safe: the job keeps running remotely. Check on it later with\n"
          f"   client.fine_tuning.jobs.retrieve('{job_id}'))", file=sys.stderr)

    last = None
    while True:
        try:
            job = client.fine_tuning.jobs.retrieve(job_id)
        except Exception as e:
            # A transient network error must not kill the watcher after the
            # upload and job creation already succeeded.
            print(f"  poll failed ({e}); retrying in 60s — job {job_id} is still "
                  "running remotely", file=sys.stderr)
            time.sleep(60)
            continue
        if job.status != last:
            print(f"  status: {job.status}", file=sys.stderr)
            last = job.status
        if job.status in ("succeeded", "failed", "cancelled"):
            break
        time.sleep(20)

    if job.status == "succeeded":
        print(f"\n✅ Fine-tuned model: {job.fine_tuned_model}")
        print("   Record this id under training in mirror.config.yaml and serve with "
              "scripts/serve/mirror_chat.py --path B --model " + str(job.fine_tuned_model),
              file=sys.stderr)
    else:
        print(f"\n❌ Job {job.status}. Inspect: client.fine_tuning.jobs.list_events('{job.id}')",
              file=sys.stderr)
        # Exit nonzero so a scripted pipeline doesn't march on serving a model
        # that was never produced.
        sys.exit(1)


def main() -> None:
    ap = argparse.ArgumentParser(description="OpenAI fine-tune driver for Mirror (Path B).")
    ap.add_argument("input",
                    help="train.jsonl (sft) / dpo.jsonl (dpo) / dpo_skeleton.jsonl (--build-dpo)")
    ap.add_argument("--base", default="gpt-4.1-mini", help="Base model or a prior ft: id.")
    ap.add_argument("--method", choices=["sft", "dpo"], default="sft")
    ap.add_argument("--suffix", default="mirror", help="Name suffix for the fine-tuned model.")
    ap.add_argument("--epochs", type=int, default=None,
                    help="Override n_epochs (default: let OpenAI pick).")
    ap.add_argument("--validate-only", action="store_true")
    ap.add_argument("--build-dpo", action="store_true",
                    help="Fill rejected outputs in a DPO skeleton by sampling --base.")
    ap.add_argument("-o", "--output", help="Output path for --build-dpo.")
    args = ap.parse_args()

    rows = load_jsonl(args.input)

    if args.build_dpo:
        if not args.output:
            ap.error("--build-dpo requires -o OUTPUT")
        build_dpo(rows, args.base, args.output)
        return

    valid = validate_sft(rows) if args.method == "sft" else validate_dpo(rows)
    if args.validate_only:
        # Exit nonzero on a bad dataset so `--validate-only` is a usable pre-flight
        # gate in scripts/CI (previously it always exited 0, even on FAIL).
        sys.exit(0 if valid else 1)
    if not valid:
        sys.exit("Fix the dataset before training.")

    run_job(args.input, args.base, args.method, args.suffix, args.epochs)


if __name__ == "__main__":
    main()
