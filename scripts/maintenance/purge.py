#!/usr/bin/env python3
"""Tear down a Mirror's local artifacts, and remind you about remote state.

Mirror leaves the most sensitive trail imaginable on disk: your raw + scrubbed
messages (data/), a profile of how you write (persona/), and weights trained on
your messages (adapters/). This removes them. It is DRY-RUN by default and only
deletes when you pass --yes.

    python scripts/maintenance/purge.py                 # show what would be removed
    python scripts/maintenance/purge.py --yes           # actually remove it
    python scripts/maintenance/purge.py --what data,eval --yes
    python scripts/maintenance/purge.py --purge-remote --yes-remote  # delete OpenAI files too

The local path is stdlib-only. The optional OpenAI cleanup needs the `openai` extra.
"""
from __future__ import annotations

import argparse
import glob
import os
import shutil
import sys

TARGETS = {
    "data": ["data"],
    "persona": ["persona"],
    "adapters": ["adapters", "merged"],
    "eval": ["eval"],
    "clean": ["data/clean.jsonl", "data/scrubbed.jsonl"],
}


def _size(path: str) -> int:
    if os.path.isfile(path):
        return os.path.getsize(path)
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def _human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


def collect(base: str, what: list[str]) -> list[str]:
    paths: list[str] = []
    for key in what:
        # Known keys only — never treat user input as a glob pattern, so a typo
        # (or a shell-expanded `*`) can't select paths outside the five targets.
        for pat in TARGETS[key]:
            paths.extend(sorted(glob.glob(os.path.join(base, pat))))
    # de-dupe, keep existing
    return [p for p in dict.fromkeys(paths) if os.path.exists(p)]


def remote_reminder(purge_remote: bool, yes_remote: bool) -> None:
    print("\nRemote state (Path B / OpenAI):", file=sys.stderr)
    print("  Mirror can't know exactly what you uploaded. If you ran Path B, you left a"
          "\n  training file and a fine-tuned model in your OpenAI account. To remove them:"
          "\n    client.files.list(purpose='fine-tune')  ->  client.files.delete(id)"
          "\n    client.models.delete('ft:...')", file=sys.stderr)
    if not purge_remote:
        return
    try:
        from openai import OpenAI
    except ImportError:
        print("  (--purge-remote needs `pip install openai`)", file=sys.stderr)
        return
    client = OpenAI()
    # Iterating the page object (not .data) auto-paginates past the first page.
    files = [f for f in client.files.list() if getattr(f, "purpose", "") == "fine-tune"]
    if not files:
        print("  No purpose='fine-tune' files found in your account.", file=sys.stderr)
        return
    print("  NOTE: this lists EVERY fine-tune file in the account, including ones"
          "\n  Mirror didn't upload.", file=sys.stderr)
    for f in files:
        print(f"  fine-tune file: {f.id}  {getattr(f, 'filename', '')}", file=sys.stderr)
        if yes_remote:
            try:
                client.files.delete(f.id)
                print(f"    deleted {f.id}", file=sys.stderr)
            except Exception as e:  # keep going; report what's left at the end
                print(f"    FAILED to delete {f.id}: {e}", file=sys.stderr)
    if not yes_remote:
        print("  (re-run with --yes-remote to delete the files listed above)", file=sys.stderr)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Remove a Mirror's local artifacts (dry-run by default).")
    ap.add_argument("--dir", default=".", help="Working directory (default: .).")
    ap.add_argument("--what", default="data,persona,adapters,eval",
                    help="Comma list: data,persona,adapters,eval,clean (default: all but clean).")
    ap.add_argument("--yes", action="store_true", help="Actually delete (otherwise dry-run).")
    ap.add_argument("--purge-remote", action="store_true",
                    help="Also list/offer to delete OpenAI fine-tune files (needs openai + key).")
    ap.add_argument("--yes-remote", action="store_true",
                    help="Actually delete the remote OpenAI files (--yes does NOT imply this).")
    args = ap.parse_args()

    what = [w.strip() for w in args.what.split(",") if w.strip()]
    unknown = [k for k in what if k not in TARGETS]
    if unknown:
        ap.error(f"unknown --what target(s): {', '.join(unknown)} "
                 f"(choose from: {', '.join(TARGETS)})")
    paths = collect(args.dir, what)

    failed = 0
    if not paths:
        print("Nothing to remove (no matching artifacts found).", file=sys.stderr)
    else:
        total = sum(_size(p) for p in paths)
        verb = "Removing" if args.yes else "Would remove"
        print(f"{verb} {len(paths)} item(s), {_human(total)}:", file=sys.stderr)
        for p in paths:
            print(f"  {p}  ({_human(_size(p))})", file=sys.stderr)
            if args.yes:
                try:
                    shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
                except OSError as e:
                    failed += 1
                    print(f"    FAILED to remove: {e}", file=sys.stderr)
        if not args.yes:
            print("\nDry run. Re-run with --yes to delete.", file=sys.stderr)
        elif failed:
            print(f"Done with {failed} failure(s) — the paths marked FAILED still exist.",
                  file=sys.stderr)
        else:
            print("Deleted. (Note: on SSDs, overwrite-delete isn't a secure-erase guarantee.)",
                  file=sys.stderr)

    remote_reminder(args.purge_remote, args.yes_remote)

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
