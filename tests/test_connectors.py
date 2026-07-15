"""Regression tests for the connectors that had no coverage: slack, discord,
sms, instagram. Pins their format-fragile logic (mention/link cleaning, mojibake
reversal, sent-detection, type filtering) so a refactor can't silently zero out a
user's messages.

Run with:  python -m pytest tests/test_connectors.py   (or: python tests/test_connectors.py)
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PY = sys.executable


def run(script, *args):
    cmd = [PY, str(REPO / script), *map(str, args), "-o", "-"]
    p = subprocess.run(cmd, capture_output=True, text=True)
    assert p.returncode == 0, f"{script} failed:\n{p.stderr}"
    return [json.loads(line) for line in p.stdout.splitlines() if line.strip()], p.stderr


# ── Slack ────────────────────────────────────────────────────────────────────

def test_slack_resolves_me_mentions_and_links(tmp_path):
    (tmp_path / "users.json").write_text(json.dumps([
        {"id": "U1", "real_name": "Sam Rivera", "profile": {"display_name": "Sam"}},
        {"id": "U2", "profile": {"display_name": "Alex"}},
    ]), encoding="utf-8")
    chan = tmp_path / "general"
    chan.mkdir()
    (chan / "2024-03-05.json").write_text(json.dumps([
        {"type": "message", "user": "U2", "ts": "1709675400.0",
         "text": "hey <@U1> ship <https://x.io|the PR>?"},
        {"type": "message", "user": "U1", "ts": "1709675472.0", "text": "lgtm, merging"},
        {"type": "message", "subtype": "channel_join", "user": "U1", "ts": "1709675480.0",
         "text": "joined"},
    ]), encoding="utf-8")

    recs, _ = run("scripts/connectors/slack_parse.py", tmp_path, "--me", "Sam Rivera")
    texts = {r["text"]: r for r in recs}
    assert "lgtm, merging" in texts and texts["lgtm, merging"]["is_from_me"] is True
    incoming = next(r for r in recs if not r["is_from_me"])
    assert "@Sam" in incoming["text"]          # <@U1> resolved to display name
    assert "the PR" in incoming["text"]        # <url|label> rendered as label
    assert all(r["conversation_id"] == "general" for r in recs)
    assert all("joined" != r["text"] for r in recs)   # subtype dropped


def test_slack_unknown_me_warns_and_flags_none(tmp_path):
    (tmp_path / "users.json").write_text('[{"id":"U1","profile":{"display_name":"Sam"}}]',
                                         encoding="utf-8")
    chan = tmp_path / "dm"
    chan.mkdir()
    (chan / "2024-01-01.json").write_text('[{"type":"message","user":"U1","ts":"1.0","text":"hi"}]',
                                          encoding="utf-8")
    recs, err = run("scripts/connectors/slack_parse.py", tmp_path, "--me", "Nobody")
    assert all(not r["is_from_me"] for r in recs)
    assert "Could not resolve" in err or "0 of your messages" in err


# ── Discord ──────────────────────────────────────────────────────────────────

def test_discord_filters_types_and_flags_me_by_id(tmp_path):
    f = tmp_path / "dm.json"
    f.write_text(json.dumps({
        "channel": {"name": "alex-dm", "id": "99"},
        "messages": [
            {"id": "1", "type": "Default", "timestamp": "2024-03-05T21:50:00.000+00:00",
             "author": {"id": "42", "name": "alex", "nickname": "Alex"}, "content": "yo"},
            {"id": "2", "type": "Reply", "timestamp": "2024-03-05T21:51:00.000+00:00",
             "author": {"id": "7", "name": "sam"}, "content": "haha hey"},
            {"id": "3", "type": "ChannelPinnedMessage",
             "timestamp": "2024-03-05T21:52:00.000+00:00",
             "author": {"id": "7", "name": "sam"}, "content": "pinned"},
            {"id": "4", "type": "Default", "timestamp": "2024-03-05T21:53:00.000+00:00",
             "author": {"id": "7", "name": "sam"}, "content": ""},
        ],
    }), encoding="utf-8")
    recs, _ = run("scripts/connectors/discord_parse.py", f, "--me-id", "7")
    assert [r["text"] for r in recs] == ["yo", "haha hey"]   # pinned + empty dropped
    assert next(r for r in recs if r["text"] == "haha hey")["is_from_me"] is True
    assert all(r["conversation_id"] == "alex-dm" for r in recs)


# ── Android SMS XML ──────────────────────────────────────────────────────────

def test_sms_sent_detection_and_timestamp(tmp_path):
    f = tmp_path / "sms.xml"
    f.write_text(
        '<?xml version="1.0"?><smses count="3">'
        '<sms address="+15551234567" date="1709675472000" type="2" body="on my way"'
        ' contact_name="Mom"/>'
        '<sms address="+15551234567" date="1709675400000" type="1" body="ok see you"'
        ' contact_name="Mom"/>'
        '<sms address="+15551234567" date="1709675480000" type="2" body="null"/>'
        '</smses>', encoding="utf-8")
    recs, _ = run("scripts/connectors/sms_xml_parse.py", f)
    assert len(recs) == 2                                   # body="null" dropped
    sent = next(r for r in recs if r["text"] == "on my way")
    assert sent["is_from_me"] is True and sent["conversation_id"] == "Mom"
    assert sent["timestamp"] == "2024-03-05T21:51:12Z"      # epoch-ms -> ISO UTC
    assert next(r for r in recs if r["text"] == "ok see you")["is_from_me"] is False


# ── Instagram / Meta JSON ────────────────────────────────────────────────────

def test_instagram_mojibake_and_media_drop(tmp_path):
    thread = tmp_path / "inbox" / "alex_123"
    thread.mkdir(parents=True)
    # Meta double-encodes UTF-8 as latin-1; the parser reverses it. 😅 == \xf0\x9f\x98\x85
    mojibake = "haha yeah ð"
    (thread / "message_1.json").write_text(json.dumps({
        "participants": [{"name": "Sam"}, {"name": "Alex"}],
        "title": "Alex",
        "messages": [
            {"sender_name": "Alex", "timestamp_ms": 1709675400000, "content": "yo"},
            {"sender_name": "Sam", "timestamp_ms": 1709675472000, "content": mojibake},
            {"sender_name": "Sam", "timestamp_ms": 1709675480000, "photos": [{"uri": "x.jpg"}]},
        ],
    }), encoding="utf-8")
    recs, _ = run("scripts/connectors/instagram_parse.py", tmp_path / "inbox", "--me", "Sam")
    assert len(recs) == 2                                   # photo-only message dropped
    mine = next(r for r in recs if r["is_from_me"])
    assert mine["text"] == "haha yeah 😅"                   # mojibake restored
    assert all(r["conversation_id"] == "Alex" for r in recs)


# ── --me must be repeatable everywhere (display names change over the years) ──

def test_me_flag_repeatable_discord_slack_instagram(tmp_path):
    # Discord: two eras of your username — both must flag as you
    dm = tmp_path / "dm.json"
    dm.write_text(json.dumps({
        "channel": {"name": "alex-dm", "id": "99"},
        "messages": [
            {"id": "1", "type": "Default", "timestamp": "2024-03-05T21:50:00.000+00:00",
             "author": {"id": "7", "name": "sam_old"}, "content": "first era"},
            {"id": "2", "type": "Default", "timestamp": "2024-03-05T21:51:00.000+00:00",
             "author": {"id": "8", "name": "sam_new"}, "content": "second era"},
        ],
    }), encoding="utf-8")
    recs, _ = run("scripts/connectors/discord_parse.py", dm,
                  "--me", "sam_old", "--me", "sam_new")
    assert all(r["is_from_me"] for r in recs), "second --me silently dropped the first"

    # Slack: first alias resolves, extra alias must not clobber it
    sl = tmp_path / "slack"
    sl.mkdir()
    (sl / "users.json").write_text('[{"id":"U1","profile":{"display_name":"Sam"}}]',
                                   encoding="utf-8")
    chan = sl / "dm"
    chan.mkdir()
    (chan / "2024-01-01.json").write_text(
        '[{"type":"message","user":"U1","ts":"1.0","text":"hi"}]', encoding="utf-8")
    recs, _ = run("scripts/connectors/slack_parse.py", sl, "--me", "Sam", "--me", "OldNick")
    assert recs and recs[0]["is_from_me"] is True

    # Instagram: name shown differently across export epochs
    thread = tmp_path / "inbox" / "alex_123"
    thread.mkdir(parents=True)
    (thread / "message_1.json").write_text(json.dumps({
        "participants": [{"name": "Sam"}, {"name": "Alex"}], "title": "Alex",
        "messages": [
            {"sender_name": "Sam", "timestamp_ms": 1709675400000, "content": "era one"},
            {"sender_name": "Sam Rivera", "timestamp_ms": 1709675500000, "content": "era two"},
        ],
    }), encoding="utf-8")
    recs, _ = run("scripts/connectors/instagram_parse.py", tmp_path / "inbox",
                  "--me", "Sam", "--me", "Sam Rivera")
    assert all(r["is_from_me"] for r in recs)


# ── iMessage generic JSON import ─────────────────────────────────────────────

def test_imessage_json_uses_date_when_timestamp_missing(tmp_path):
    f = tmp_path / "msgs.json"
    f.write_text(json.dumps([
        {"text": "hey", "is_from_me": 1, "date": "2024-03-05T21:41:12Z", "chat": "Alex"},
        {"text": "yo", "is_from_me": 0, "timestamp": "2024-03-05T21:42:00Z", "chat": "Alex"},
    ]), encoding="utf-8")
    recs, _ = run("scripts/connectors/imessage_extract.py", f, "--from-json")
    assert recs[0]["timestamp"] == "2024-03-05T21:41:12Z"   # 'date' honored as fallback
    assert recs[0]["is_from_me"] is True
    assert recs[1]["timestamp"] == "2024-03-05T21:42:00Z"
    assert all(r["conversation_id"] == "Alex" for r in recs)


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            with tempfile.TemporaryDirectory() as d:
                t(Path(d))
            print(f"PASS {t.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {t.__name__}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
