"""Stdlib-only integration + regression tests for the Mirror core pipeline.

Run with:  python -m pytest tests/        (or:  python tests/test_pipeline.py)

These exercise the real scripts as subprocesses on synthetic fixtures, and pin
the bugs found in review so they can't regress.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PY = sys.executable


def run(script, *args):
    """Run a Mirror script with `-o -`, return (records, stderr)."""
    cmd = [PY, str(REPO / script), *map(str, args), "-o", "-"]
    p = subprocess.run(cmd, capture_output=True, text=True)
    assert p.returncode == 0, f"{script} failed:\n{p.stderr}"
    recs = [json.loads(line) for line in p.stdout.splitlines() if line.strip()]
    return recs, p.stderr


# ── core pipeline ────────────────────────────────────────────────────────────

def test_schema_validate_sample():
    p = subprocess.run([PY, str(REPO / "scripts/lib/schema.py"),
                        str(REPO / "examples/sample_messages.jsonl")],
                       capture_output=True, text=True)
    report = json.loads(p.stdout)
    assert report["total_messages"] == 24
    assert report["from_me"] > 0
    assert report["from_me"] + report["from_others"] == report["total_messages"]


def test_write_jsonl_in_place_does_not_truncate_input(tmp_path):
    src = tmp_path / "clean.jsonl"
    rec = {"source": "whatsapp", "conversation_id": "x", "is_from_me": True,
           "sender": "me", "text": "hello world"}
    src.write_text(json.dumps(rec) + "\n", encoding="utf-8")
    # same file as input and output — must not truncate the input before reading
    p = subprocess.run([PY, str(REPO / "scripts/format/normalize.py"),
                        str(src), "-o", str(src)],
                       capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    lines = [ln for ln in src.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 1, "in-place run truncated the corpus"
    assert json.loads(lines[0])["text"] == "hello world"
    assert not (tmp_path / "clean.jsonl.tmp").exists()   # no staging file left behind


def test_build_dataset_targets_are_mine(tmp_path):
    out = tmp_path / "train.jsonl"
    p = subprocess.run([PY, str(REPO / "scripts/format/build_dataset.py"),
                        str(REPO / "examples/sample_messages.jsonl"),
                        "--format", "openai-chat", "-o", str(out)],
                       capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    rows = [json.loads(line) for line in out.read_text().splitlines() if line.strip()]
    assert rows, "no training examples built"
    for r in rows:
        assert r["messages"][0]["role"] == "system"
        assert r["messages"][-1]["role"] == "assistant"   # target is YOUR turn
    # a known 'me' line should appear as a target
    targets = {r["messages"][-1]["content"] for r in rows}
    assert any("ship the two that work" in t for t in targets)
    assert (tmp_path / "DATASET_CARD.md").exists()         # provenance card emitted


# ── regression: WhatsApp must NOT drop real messages containing system words ──

def test_whatsapp_keeps_messages_with_systemish_words(tmp_path):
    f = tmp_path / "WhatsApp Chat with Pat.txt"
    f.write_text(
        "[2024-03-05, 9:41:12 PM] Sam: i left work early today\n"
        "[2024-03-05, 9:42:00 PM] Pat: you added a great point earlier\n"
        "[2024-03-05, 9:43:00 PM] Sam: <Media omitted>\n"
        "[2024-03-05, 9:44:00 PM] Messages and calls are end-to-end encrypted.\n",
        encoding="utf-8")
    recs, _ = run("scripts/connectors/whatsapp_parse.py", f, "--me", "Sam")
    texts = [r["text"] for r in recs]
    assert "i left work early today" in texts          # was dropped by the substring bug
    assert "you added a great point earlier" in texts  # ditto ("added")
    assert all("Media omitted" not in t for t in texts)   # placeholder dropped
    assert all("end-to-end encrypted" not in t for t in texts)  # senderless system line dropped


# ── regression: PII scrubber coverage + no over/under-match ──────────────────

def test_pii_scrub_coverage_and_precision(tmp_path):
    src = tmp_path / "in.jsonl"
    rec = {"source": "whatsapp", "conversation_id": "x", "is_from_me": True, "sender": "me",
           "text": ("mail me at a@b.com or https://x.io/r?token=secret123, "
                    "call +44 20 7946 0958, born 04/17/1989, at 742 Evergreen Terrace, "
                    "order 1234567 shipped after the wrong turn")}
    src.write_text(json.dumps(rec) + "\n", encoding="utf-8")
    recs, _ = run("scripts/format/pii_scrub.py", src)
    t = recs[0]["text"]
    # covered
    assert "<EMAIL>" in t and "a@b.com" not in t
    assert "<URL>" in t and "secret123" not in t
    assert "<PHONE>" in t and "+44" not in t           # whole token redacted, no prefix leak
    assert "<DOB>" in t and "1989" not in t
    assert "<ADDRESS>" in t and "Evergreen" not in t
    # precision: don't eat plain words or a bare 7-digit id
    assert "after the wrong turn" in t
    assert "1234567" in t                              # no separators ⇒ not a phone


# ── regression: Gmail mboxrd un-escaping ─────────────────────────────────────

def test_gmail_mboxrd_unescape(tmp_path):
    mbox = tmp_path / "Sent.mbox"
    mbox.write_text(
        "From sam@example.com Tue Mar 05 21:41:12 2024\n"
        "From: Sam <sam@example.com>\n"
        "To: Alex <alex@example.com>\n"
        "Subject: re\n"
        "Date: Tue, 5 Mar 2024 21:41:12 +0000\n"
        "\n"
        "Here is my take.\n"
        ">From a product angle this is fine.\n",
        encoding="utf-8")
    recs, _ = run("scripts/connectors/gmail_mbox_parse.py", mbox, "--me", "sam@example.com")
    assert recs, "no email parsed"
    body = recs[0]["text"]
    assert "From a product angle this is fine." in body
    assert ">From a product angle" not in body


# ── regression: Gmail empty text/plain part must fall back to the HTML body ──

def test_gmail_empty_plain_falls_back_to_html(tmp_path):
    mbox = tmp_path / "Sent.mbox"
    mbox.write_text(
        "From sam@example.com Tue Mar 05 21:41:12 2024\n"
        "From: Sam <sam@example.com>\n"
        "To: Alex <alex@example.com>\n"
        "Subject: multipart\n"
        "Date: Tue, 5 Mar 2024 21:41:12 +0000\n"
        "MIME-Version: 1.0\n"
        'Content-Type: multipart/alternative; boundary="BOUND"\n'
        "\n"
        "--BOUND\n"
        'Content-Type: text/plain; charset="utf-8"\n'
        "\n"
        "\n"
        "--BOUND\n"
        'Content-Type: text/html; charset="utf-8"\n'
        "\n"
        "<p>hello from the html side</p>\n"
        "--BOUND--\n",
        encoding="utf-8")
    recs, _ = run("scripts/connectors/gmail_mbox_parse.py", mbox, "--me", "sam@example.com")
    assert recs, "email with empty text/plain part was dropped"
    assert "hello from the html side" in recs[0]["text"]


# ── regression: Telegram single-chat export gets a real conversation id ──────

def test_telegram_single_chat_convo_id(tmp_path):
    res = tmp_path / "ChatWithJordan.json"
    res.write_text(json.dumps({"messages": [
        {"id": 1, "type": "message", "date_unixtime": "1712049720",
         "from": "Sam", "from_id": "user111", "text": "hi"},
    ]}), encoding="utf-8")
    recs, _ = run("scripts/connectors/telegram_parse.py", res, "--me", "Sam")
    assert recs and recs[0]["conversation_id"] == "ChatWithJordan"   # not "telegram"


if __name__ == "__main__":
    # Lightweight runner so the suite works without pytest installed.
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        name = t.__name__
        try:
            if "tmp_path" in t.__code__.co_varnames:
                with tempfile.TemporaryDirectory() as d:
                    t(Path(d))
            else:
                t()
            print(f"PASS {name}")
        except Exception:
            failed += 1
            print(f"FAIL {name}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
