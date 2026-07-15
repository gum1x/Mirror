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


# ── regression: malformed corpus lines → clear errors, skippable, non-fatal ──

def test_missing_required_field_fails_with_line_number_not_traceback(tmp_path):
    src = tmp_path / "in.jsonl"
    good = {"source": "sms", "conversation_id": "c", "is_from_me": True,
            "sender": "me", "text": "hi there"}
    src.write_text(json.dumps(good) + "\n" + '{"text": "no required fields"}\n',
                   encoding="utf-8")
    p = subprocess.run([PY, str(REPO / "scripts/format/normalize.py"), str(src), "-o", "-"],
                       capture_output=True, text=True)
    assert p.returncode != 0
    assert "line 2" in p.stderr                 # clear, located message
    assert "Traceback" not in p.stderr          # not a raw TypeError


def test_skip_bad_lines_and_status_survives_bad_corpus(tmp_path):
    (tmp_path / "data").mkdir()
    src = tmp_path / "data" / "scrubbed.jsonl"
    good = {"source": "sms", "conversation_id": "c", "is_from_me": True,
            "sender": "me", "text": "hi there"}
    good2 = dict(good, text="still here")
    src.write_text(json.dumps(good) + "\n{truncated garbage\n" + json.dumps(good2) + "\n",
                   encoding="utf-8")
    # --skip-bad-lines: warn, keep the good records, exit 0
    p = subprocess.run([PY, str(REPO / "scripts/format/normalize.py"), str(src),
                        "--skip-bad-lines", "-o", "-"],
                       capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    recs = [json.loads(ln) for ln in p.stdout.splitlines() if ln.strip()]
    assert [r["text"] for r in recs] == ["hi there", "still here"]
    assert "skipped" in p.stderr.lower()
    # status.py is read-only reporting: one bad line must not kill it
    p = subprocess.run([PY, str(REPO / "scripts/status.py"), "--dir", str(tmp_path)],
                       capture_output=True, text=True)
    assert p.returncode == 0, p.stderr


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


# ── regression: conversations must sort by parsed time, not timestamp string ──

def test_build_dataset_orders_by_parsed_time_not_string(tmp_path):
    # "…12.500000Z" sorts BEFORE "…12Z" as a string ('.' < 'Z'); parsed, it's after.
    src = tmp_path / "msgs.jsonl"
    recs_in = [
        {"source": "slack", "conversation_id": "c", "is_from_me": False, "sender": "Pat",
         "timestamp": "2024-03-05T21:41:12Z", "text": "hey"},
        {"source": "slack", "conversation_id": "c", "is_from_me": False, "sender": "Pat",
         "timestamp": "2024-03-05T21:41:12.500000Z", "text": "you coming tonight?"},
        {"source": "slack", "conversation_id": "c", "is_from_me": True, "sender": "me",
         "timestamp": "2024-03-05T21:41:13Z", "text": "omw"},
    ]
    src.write_text("".join(json.dumps(r) + "\n" for r in recs_in), encoding="utf-8")
    rows, _ = run("scripts/format/build_dataset.py", src, "--format", "openai-chat")
    assert rows, "no examples built"
    user_turn = rows[0]["messages"][-2]
    assert user_turn["role"] == "user"
    assert user_turn["content"] == "hey\nyou coming tonight?"   # chronological order


# ── regression: no silent fallbacks in build_dataset ─────────────────────────

def test_build_dataset_missing_system_file_is_an_error(tmp_path):
    p = subprocess.run([PY, str(REPO / "scripts/format/build_dataset.py"),
                        str(REPO / "examples/sample_messages.jsonl"),
                        "--system-file", str(tmp_path / "nope.md"),
                        "-o", str(tmp_path / "train.jsonl")],
                       capture_output=True, text=True)
    assert p.returncode != 0, "typo'd --system-file must not fall back silently"
    assert "nope.md" in p.stderr
    assert not (tmp_path / "train.jsonl").exists()


def test_build_dataset_holdout_requires_file_output():
    p = subprocess.run([PY, str(REPO / "scripts/format/build_dataset.py"),
                        str(REPO / "examples/sample_messages.jsonl"),
                        "--holdout", "0.2", "-o", "-"],
                       capture_output=True, text=True)
    assert p.returncode != 0, "--holdout with stdout silently discarded the eval split"
    assert "holdout" in p.stderr.lower()


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


# ── regression: normalize must not decompose emoji or drop one-word replies ──

def test_normalize_preserves_zwj_and_keeps_one_word_messages(tmp_path):
    src = tmp_path / "in.jsonl"
    recs_in = [
        {"source": "whatsapp", "conversation_id": "x", "is_from_me": True, "sender": "me",
         "text": "\U0001f469‍\U0001f4bb love this"},   # 👩‍💻 (ZWJ sequence)
        {"source": "whatsapp", "conversation_id": "x", "is_from_me": True, "sender": "me",
         "text": "می‌خواهم"},  # Persian with ZWNJ
        {"source": "whatsapp", "conversation_id": "x", "is_from_me": True, "sender": "me",
         "text": "video"},           # a genuine one-word reply, not a placeholder
        {"source": "whatsapp", "conversation_id": "x", "is_from_me": True, "sender": "me",
         "text": "video omitted"},   # a placeholder — must still be dropped
    ]
    src.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs_in),
                   encoding="utf-8")
    recs, _ = run("scripts/format/normalize.py", src)
    texts = [r["text"] for r in recs]
    assert "\U0001f469‍\U0001f4bb love this" in texts   # emoji stays composed
    assert "می‌خواهم" in texts  # ZWNJ kept
    assert "video" in texts                                  # real message kept
    assert all("omitted" not in t for t in texts)            # placeholder dropped


def test_whatsapp_iso_dates_tz_and_ios_placeholders(tmp_path):
    f = tmp_path / "WhatsApp Chat with Pat.txt"
    f.write_text(
        "[2024-03-05, 9:41:12 PM] Sam: hello there\n"
        "[2024-03-05, 9:42:00 PM] Sam: ‎image omitted\n"
        "[2024-03-05, 9:43:00 PM] Sam: ‎<attached: 00000042-PHOTO-2024-03-05.jpg>\n",
        encoding="utf-8")
    # year-first dates are unambiguous: --dayfirst must not swap month/day
    recs, _ = run("scripts/connectors/whatsapp_parse.py", f, "--me", "Sam", "--dayfirst")
    assert [r["text"] for r in recs] == ["hello there"]     # iOS placeholders dropped
    assert recs[0]["timestamp"] == "2024-03-05T21:41:12Z"   # not 2024-05-03
    # --tz interprets the export's local wall-clock and converts to real UTC
    recs, _ = run("scripts/connectors/whatsapp_parse.py", f, "--me", "Sam",
                  "--tz", "America/New_York")
    assert recs[0]["timestamp"] == "2024-03-06T02:41:12Z"   # EST is UTC-5 on Mar 5


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


def test_pii_scrub_compact_phones_and_dashless_ssn(tmp_path):
    src = tmp_path / "in.jsonl"
    rec = {"source": "whatsapp", "conversation_id": "x", "is_from_me": True, "sender": "me",
           "text": ("text me at 5551234567 or +15551234567, landline 867-5309, "
                    "ssn is 123456789, order 1234567 arrived, see you in 2023-2024")}
    src.write_text(json.dumps(rec) + "\n", encoding="utf-8")
    recs, _ = run("scripts/format/pii_scrub.py", src)
    t = recs[0]["text"]
    # compact / E.164 phones and dashed 7-digit numbers must be redacted
    assert "5551234567" not in t and "<PHONE>" in t
    assert "867-5309" not in t
    # SSN without dashes must be redacted
    assert "123456789" not in t and "<SSN>" in t
    # precision: bare 7-digit ids and year ranges stay
    assert "order 1234567 arrived" in t
    assert "2023-2024" in t


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


# ── regression: Gmail bottom-posted/inline replies must survive quote strip ──

def test_gmail_keeps_bottom_posted_reply(tmp_path):
    mbox = tmp_path / "Sent.mbox"
    mbox.write_text(
        "From sam@example.com Tue Mar 05 21:41:12 2024\n"
        "From: Sam <sam@example.com>\n"
        "To: Alex <alex@example.com>\n"
        "Subject: re: tonight\n"
        "Date: Tue, 5 Mar 2024 21:41:12 +0000\n"
        "\n"
        "> hey are you coming tonight?\n"
        "\n"
        "yes! omw at 8\n",
        encoding="utf-8")
    recs, _ = run("scripts/connectors/gmail_mbox_parse.py", mbox, "--me", "sam@example.com")
    assert recs, "bottom-posted reply was dropped entirely"
    body = recs[0]["text"]
    assert "yes! omw at 8" in body                     # the composed reply survives
    assert "hey are you coming tonight?" not in body   # the quoted line doesn't


# ── regression: Telegram single-chat export gets a real conversation id ──────

def test_telegram_single_chat_convo_id(tmp_path):
    res = tmp_path / "ChatWithJordan.json"
    res.write_text(json.dumps({"messages": [
        {"id": 1, "type": "message", "date_unixtime": "1712049720",
         "from": "Sam", "from_id": "user111", "text": "hi"},
    ]}), encoding="utf-8")
    recs, _ = run("scripts/connectors/telegram_parse.py", res, "--me", "Sam")
    assert recs and recs[0]["conversation_id"] == "ChatWithJordan"   # not "telegram"


# ── regression: purge must reject unknown targets, not glob-delete them ──────

def test_purge_rejects_unknown_what(tmp_path):
    (tmp_path / "precious.txt").write_text("keep me", encoding="utf-8")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "x.jsonl").write_text("{}\n", encoding="utf-8")
    p = subprocess.run([PY, str(REPO / "scripts/maintenance/purge.py"),
                        "--dir", str(tmp_path), "--what", "*", "--yes"],
                       capture_output=True, text=True)
    assert p.returncode != 0, "unknown --what value must be rejected"
    assert "unknown" in p.stderr.lower()
    assert (tmp_path / "precious.txt").exists()      # nothing deleted
    assert (tmp_path / "data" / "x.jsonl").exists()


def test_purge_dry_run_default_and_targeted_delete(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "x.jsonl").write_text("{}\n", encoding="utf-8")
    (tmp_path / "persona").mkdir()
    (tmp_path / "persona" / "style_card.md").write_text("card", encoding="utf-8")
    (tmp_path / "precious.txt").write_text("keep me", encoding="utf-8")
    purge = str(REPO / "scripts/maintenance/purge.py")
    # dry run by default: reports, deletes nothing
    p = subprocess.run([PY, purge, "--dir", str(tmp_path)],
                       capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    assert "Would remove" in p.stderr
    assert (tmp_path / "data" / "x.jsonl").exists()
    assert (tmp_path / "persona" / "style_card.md").exists()
    # targeted --yes: removes data/ only, leaves everything else
    p = subprocess.run([PY, purge, "--dir", str(tmp_path), "--what", "data", "--yes"],
                       capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    assert not (tmp_path / "data").exists()
    assert (tmp_path / "persona" / "style_card.md").exists()
    assert (tmp_path / "precious.txt").exists()


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
