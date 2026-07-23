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


def test_slack_tolerates_bad_timestamp(tmp_path):
    # A single non-numeric `ts` must not crash the parser and discard every
    # record (write_jsonl stages to .tmp and only swaps on success, so a crash
    # loses the whole file). Every other connector guards this; Slack must too.
    (tmp_path / "users.json").write_text(
        '[{"id":"U1","profile":{"display_name":"Sam"}},'
        '{"id":"U2","profile":{"display_name":"Alex"}}]', encoding="utf-8")
    chan = tmp_path / "general"
    chan.mkdir()
    (chan / "2024-03-05.json").write_text(json.dumps([
        {"type": "message", "user": "U2", "ts": "1709675400.0", "text": "before"},
        {"type": "message", "user": "U1", "ts": "NaN-oops", "text": "bad ts but keep me"},
        {"type": "message", "user": "U2", "ts": "1709675480.0", "text": "after"},
    ]), encoding="utf-8")
    recs, _ = run("scripts/connectors/slack_parse.py", tmp_path, "--me", "Sam")
    assert [r["text"] for r in recs] == ["before", "bad ts but keep me", "after"]
    bad = next(r for r in recs if r["text"] == "bad ts but keep me")
    assert bad["timestamp"] is None and bad["is_from_me"] is True


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


def test_instagram_keeps_caption_on_media_message(tmp_path):
    thread = tmp_path / "inbox" / "alex_123"
    thread.mkdir(parents=True)
    (thread / "message_1.json").write_text(json.dumps({
        "participants": [{"name": "Sam"}, {"name": "Alex"}],
        "title": "Alex",
        "messages": [
            {"sender_name": "Sam", "timestamp_ms": 1709675480000,
             "photos": [{"uri": "x.jpg"}], "content": "look at this sunset!!"},
            {"sender_name": "Sam", "timestamp_ms": 1709675490000,
             "photos": [{"uri": "y.jpg"}]},   # no caption — still dropped
        ],
    }), encoding="utf-8")
    recs, _ = run("scripts/connectors/instagram_parse.py", tmp_path / "inbox", "--me", "Sam")
    assert [r["text"] for r in recs] == ["look at this sunset!!"]


def test_instagram_keeps_prose_that_ends_like_a_system_line(tmp_path):
    # The system-line filter must anchor on the whole line, not `endswith`:
    # real prose can end "to your message" without being a reaction notice.
    thread = tmp_path / "inbox" / "alex_123"
    thread.mkdir(parents=True)
    (thread / "message_1.json").write_text(json.dumps({
        "participants": [{"name": "Sam"}, {"name": "Alex"}], "title": "Alex",
        "messages": [
            {"sender_name": "Sam", "timestamp_ms": 1709675400000,
             "content": "i keep coming back to your message"},
            {"sender_name": "Alex", "timestamp_ms": 1709675450000,
             "content": "Alex reacted 😍 to your message"},   # real system line
            {"sender_name": "Sam", "timestamp_ms": 1709675470000,
             "content": "Sam sent an attachment."},           # real system line
        ],
    }), encoding="utf-8")
    recs, _ = run("scripts/connectors/instagram_parse.py", tmp_path / "inbox", "--me", "Sam")
    assert [r["text"] for r in recs] == ["i keep coming back to your message"]


# ── Gmail Sent mbox ──────────────────────────────────────────────────────────

def test_gmail_keeps_body_line_starting_from(tmp_path):
    # The quote-stripper cuts at Outlook "From: Name <addr@x>" header blocks, but
    # must NOT fire on a composed line that merely opens "From:" — that silently
    # deletes the rest of the message (the training target).
    mbox = tmp_path / "sent.mbox"
    mbox.write_text(
        "From sam@example.com Tue Mar 05 21:41:12 2024\n"
        "From: Sam <sam@example.com>\n"
        "To: Alex <alex@example.com>\n"
        "Subject: plan\n"
        "Date: Tue, 05 Mar 2024 21:41:12 +0000\n"
        "\n"
        "Heres my plan.\n"
        "From: the numbers, we should ship it.\n"
        "Lets go.\n"
        "\n", encoding="utf-8")
    recs, _ = run("scripts/connectors/gmail_mbox_parse.py", mbox)
    assert len(recs) == 1
    body = recs[0]["text"]
    assert "From: the numbers, we should ship it." in body
    assert body.strip().endswith("Lets go.")


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


# ── Instagram: bad timestamp + corrupt-file tolerance (the #61 shape) ────────

def test_instagram_tolerates_bad_timestamp(tmp_path):
    # instagram was the one connector whose fromtimestamp had no guard: a single
    # garbage timestamp_ms killed the run and (via write_jsonl's staged tmp)
    # discarded every thread's output.
    thread = tmp_path / "inbox" / "alex_123"
    thread.mkdir(parents=True)
    (thread / "message_1.json").write_text(json.dumps({
        "participants": [{"name": "Sam"}, {"name": "Alex"}], "title": "Alex",
        "messages": [
            {"sender_name": "Alex", "timestamp_ms": 1709675400000, "content": "before"},
            {"sender_name": "Sam", "timestamp_ms": "not-a-number", "content": "bad ts keep me"},
            {"sender_name": "Alex", "timestamp_ms": 1709675480000, "content": "after"},
        ],
    }), encoding="utf-8")
    recs, _ = run("scripts/connectors/instagram_parse.py", tmp_path / "inbox", "--me", "Sam")
    assert [r["text"] for r in recs] == ["before", "bad ts keep me", "after"]
    bad = next(r for r in recs if r["text"] == "bad ts keep me")
    assert bad["timestamp"] is None and bad["is_from_me"] is True


def test_instagram_skips_corrupt_thread_file(tmp_path):
    inbox = tmp_path / "inbox"
    good = inbox / "alex_1"
    good.mkdir(parents=True)
    (good / "message_1.json").write_text(json.dumps({
        "title": "Alex",
        "messages": [{"sender_name": "Sam", "timestamp_ms": 1709675400000, "content": "kept"}],
    }), encoding="utf-8")
    bad = inbox / "zzz_2"
    bad.mkdir(parents=True)
    (bad / "message_1.json").write_text("{ not valid json", encoding="utf-8")
    recs, err = run("scripts/connectors/instagram_parse.py", inbox, "--me", "Sam")
    assert [r["text"] for r in recs] == ["kept"]      # good file survives the bad one
    assert "skipping" in err.lower()


# ── SMS: direction across all sent-side types, drafts dropped, truncation ─────

def test_sms_direction_types_and_draft_dropped(tmp_path):
    # type 1 = received; 2 sent, 4 outbox, 5 failed, 6 queued are all you;
    # 3 = draft was never sent and must be dropped entirely.
    f = tmp_path / "sms.xml"
    f.write_text(
        '<?xml version="1.0"?><smses count="4">'
        '<sms address="+1555" date="1709675400000" type="1" body="incoming"/>'
        '<sms address="+1555" date="1709675410000" type="4" body="outbox mine"/>'
        '<sms address="+1555" date="1709675420000" type="5" body="failed mine"/>'
        '<sms address="+1555" date="1709675430000" type="3" body="a draft"/>'
        '</smses>', encoding="utf-8")
    recs, _ = run("scripts/connectors/sms_xml_parse.py", f)
    by = {r["text"]: r for r in recs}
    assert "a draft" not in by
    assert by["incoming"]["is_from_me"] is False
    assert by["outbox mine"]["is_from_me"] is True
    assert by["failed mine"]["is_from_me"] is True


def test_sms_truncated_xml_keeps_earlier_records(tmp_path):
    # A malformed byte mid-file must not discard the records already parsed.
    f = tmp_path / "sms.xml"
    f.write_text(
        '<?xml version="1.0"?><smses count="3">'
        '<sms address="+1555" date="1709675400000" type="2" body="first"/>'
        '<sms address="+1555" date="1709675410000" type="1" body="second"/>'
        '<sms address="+1555" date="1709675420000" type="2" body="third" & broken>',
        encoding="utf-8")
    recs, err = run("scripts/connectors/sms_xml_parse.py", f)
    assert [r["text"] for r in recs] == ["first", "second"]
    assert "parse error" in err.lower()


# ── Discord: 7-digit fractional seconds (3.9 fromisoformat) + broadcast ───────

def test_discord_parses_seven_digit_fractional_seconds(tmp_path):
    # Newer exporter builds emit .0510000; datetime.fromisoformat rejects >6
    # fractional digits before 3.11, which silently nulled EVERY timestamp.
    f = tmp_path / "dm.json"
    f.write_text(json.dumps({
        "channel": {"name": "alex-dm", "id": "99"},
        "messages": [
            {"id": "1", "type": "Default", "timestamp": "2024-03-05T21:50:00.0510000+00:00",
             "author": {"id": "7", "name": "sam"}, "content": "hi"},
        ],
    }), encoding="utf-8")
    recs, _ = run("scripts/connectors/discord_parse.py", f, "--me-id", "7")
    assert recs[0]["timestamp"] == "2024-03-05T21:50:00.051000Z"   # not None


def test_slack_unescapes_entities_in_the_right_order(tmp_path):
    # Slack escapes exactly &, <, > in message text. "&amp;lt;" is a user who
    # literally typed "&lt;" — unescaping &amp; first double-unescaped it to "<".
    (tmp_path / "users.json").write_text(
        '[{"id":"U1","profile":{"display_name":"Sam"}}]', encoding="utf-8")
    chan = tmp_path / "general"
    chan.mkdir()
    (chan / "2024-03-05.json").write_text(json.dumps([
        {"type": "message", "user": "U1", "ts": "1709675400.0",
         "text": "1 &lt; 2 &amp;&amp; 4 &gt; 3, literally &amp;lt;"},
    ]), encoding="utf-8")
    recs, _ = run("scripts/connectors/slack_parse.py", tmp_path, "--me", "Sam")
    assert recs[0]["text"] == "1 < 2 && 4 > 3, literally &lt;"


# ── MMS: group chats / long texts must not be silently dropped ───────────────

def test_mms_text_direction_group_sender_and_media_only_drop(tmp_path):
    f = tmp_path / "sms.xml"
    f.write_text(
        '<?xml version="1.0"?><smses count="4">'
        # received group MMS: text part + SMIL layout part + participant list
        '<mms date="1709675400000" msg_box="1" address="+15551234567~+15559876543"'
        ' contact_name="Mom, Dad"><parts>'
        '<part seq="-1" ct="application/smil" text="&lt;smil&gt;&lt;/smil&gt;"/>'
        '<part seq="0" ct="text/plain" text="who wants pizza tonight"/></parts>'
        '<addrs><addr address="+15559876543" type="137"/>'
        '<addr address="+15551234567" type="151"/></addrs></mms>'
        # sent MMS
        '<mms date="1709675410000" msg_box="2" address="+15551234567" contact_name="Mom">'
        '<parts><part seq="0" ct="text/plain" text="me!! omw"/></parts></mms>'
        # media-only MMS: no text part -> dropped
        '<mms date="1709675420000" msg_box="1" address="+15551234567" contact_name="Mom">'
        '<parts><part seq="0" ct="image/jpeg" data="AAAA"/></parts></mms>'
        # plain sms still parsed alongside
        '<sms address="+15551234567" date="1709675430000" type="1" body="classic sms"'
        ' contact_name="Mom"/>'
        '</smses>', encoding="utf-8")
    recs, _ = run("scripts/connectors/sms_xml_parse.py", f)
    assert [r["text"] for r in recs] == ["who wants pizza tonight", "me!! omw",
                                         "classic sms"]
    incoming = recs[0]
    assert incoming["is_from_me"] is False
    assert incoming["sender"] == "+15559876543"      # group sender from addr type=137
    assert incoming["conversation_id"] == "Mom, Dad"
    sent = recs[1]
    assert sent["is_from_me"] is True and sent["sender"] == "me"
    assert sent["timestamp"] == "2024-03-05T21:50:10Z"


def test_mms_draft_dropped_and_multiple_text_parts_joined(tmp_path):
    f = tmp_path / "sms.xml"
    f.write_text(
        '<?xml version="1.0"?><smses count="2">'
        '<mms date="1709675400000" msg_box="3" address="+1555" contact_name="Mom">'
        '<parts><part seq="0" ct="text/plain" text="never sent draft"/></parts></mms>'
        '<mms date="1709675410000" msg_box="2" address="+1555" contact_name="Mom">'
        '<parts><part seq="0" ct="text/plain" text="part one"/>'
        '<part seq="1" ct="text/plain" text="part two"/></parts></mms>'
        '</smses>', encoding="utf-8")
    recs, _ = run("scripts/connectors/sms_xml_parse.py", f)
    assert [r["text"] for r in recs] == ["part one\npart two"]
    assert recs[0]["is_from_me"] is True


# ── Telegram: left_chats hold your voice too ─────────────────────────────────

def test_telegram_includes_left_chats(tmp_path):
    res = tmp_path / "result.json"
    res.write_text(json.dumps({
        "chats": {"list": [{"name": "Jordan", "id": 1, "messages": [
            {"id": 1, "type": "message", "date_unixtime": "1712049720",
             "from": "Sam", "from_id": "user111", "text": "hi"}]}]},
        "left_chats": {"list": [{"name": "Old Group", "id": 2, "messages": [
            {"id": 2, "type": "message", "date_unixtime": "1712049730",
             "from": "Sam", "from_id": "user111", "text": "bye all"}]}]},
    }), encoding="utf-8")
    recs, _ = run("scripts/connectors/telegram_parse.py", res, "--me", "Sam")
    assert {r["conversation_id"] for r in recs} == {"Jordan", "Old Group"}
    assert all(r["is_from_me"] for r in recs)


# ── Gmail: numeric HTML entities must survive the HTML fallback ─────────────

def test_gmail_html_numeric_entities_unescaped(tmp_path):
    mbox = tmp_path / "Sent.mbox"
    mbox.write_text(
        "From sam@example.com Tue Mar 05 21:41:12 2024\n"
        "From: Sam <sam@example.com>\n"
        "To: Alex <alex@example.com>\n"
        "Subject: html only\n"
        "Date: Tue, 5 Mar 2024 21:41:12 +0000\n"
        "MIME-Version: 1.0\n"
        'Content-Type: text/html; charset="utf-8"\n'
        "\n"
        "<p>We&#8217;ll meet &amp; talk&nbsp;soon</p>\n",
        encoding="utf-8")
    recs, _ = run("scripts/connectors/gmail_mbox_parse.py", mbox, "--me", "sam@example.com")
    assert recs, "html-only email dropped"
    assert "We’ll meet & talk soon" in recs[0]["text"]


# ── WhatsApp: es/pt "p. m." meridiem must not corrupt sender/direction/time ──

def test_whatsapp_spanish_meridiem_and_zero_mine_warning(tmp_path):
    f = tmp_path / "WhatsApp Chat with Alex.txt"
    f.write_text(
        "[5/3/24, 9:41:12 p. m.] Sam: hola que tal\n"
        "[5/3/24, 9:42:00 p. m.] Alex: todo bien\n"
        "[6/3/24, 12:15:00 a. m.] Sam: ya es tarde\n",
        encoding="utf-8")
    recs, _ = run("scripts/connectors/whatsapp_parse.py", f, "--me", "Sam", "--dayfirst")
    assert [r["text"] for r in recs] == ["hola que tal", "todo bien", "ya es tarde"]
    mine = [r for r in recs if r["is_from_me"]]
    assert len(mine) == 2                     # ". m.] Sam" used to break --me matching
    assert mine[0]["sender"] == "me"
    assert recs[0]["timestamp"] == "2024-03-05T21:41:12Z"   # PM offset applied
    assert recs[2]["timestamp"] == "2024-03-06T00:15:00Z"   # 12 a.m. -> 00:15
    # wrong --me must warn instead of silently building a target-less dataset
    _, err = run("scripts/connectors/whatsapp_parse.py", f, "--me", "Nadie", "--dayfirst")
    assert "0 of your messages" in err and "Sam" in err


# ── conversation-id collisions: same display name ≠ same conversation ────────

def test_instagram_same_title_threads_stay_separate(tmp_path):
    inbox = tmp_path / "inbox"
    for folder, text in [("alex_111", "hey its alex smith"),
                         ("alex_222", "hey its alex jones")]:
        d = inbox / folder
        d.mkdir(parents=True)
        (d / "message_1.json").write_text(json.dumps({
            "title": "Alex",
            "messages": [{"sender_name": "Alex", "timestamp_ms": 1709675400000,
                          "content": text}],
        }), encoding="utf-8")
    recs, _ = run("scripts/connectors/instagram_parse.py", inbox, "--me", "Sam")
    convos = {r["conversation_id"] for r in recs}
    assert len(convos) == 2, "two different people named Alex merged into one thread"
    assert "Alex" in convos                    # first keeps the clean name


def test_telegram_same_name_chats_stay_separate(tmp_path):
    res = tmp_path / "result.json"
    res.write_text(json.dumps({"chats": {"list": [
        {"name": "Alex", "id": 111, "messages": [
            {"id": 1, "type": "message", "date_unixtime": "1712049720",
             "from": "Alex", "from_id": "user111", "text": "its alex smith"}]},
        {"name": "Alex", "id": 222, "messages": [
            {"id": 2, "type": "message", "date_unixtime": "1712049730",
             "from": "Alex", "from_id": "user222", "text": "its alex jones"}]},
    ]}}), encoding="utf-8")
    recs, _ = run("scripts/connectors/telegram_parse.py", res, "--me", "Sam")
    convos = {r["conversation_id"] for r in recs}
    assert convos == {"Alex", "Alex (222)"}


# ── generic JSON import: stringly booleans and epoch timestamps ──────────────

def test_imessage_json_stringly_bools_and_epoch_timestamps(tmp_path):
    f = tmp_path / "msgs.json"
    f.write_text(json.dumps([
        {"text": "not mine", "is_from_me": "false", "chat": "Alex",
         "date": 1709675400000},                        # epoch ms
        {"text": "also not mine", "is_from_me": "0", "chat": "Alex",
         "date": 1709675401},                           # epoch s
        {"text": "mine", "is_from_me": "true", "chat": "Alex",
         "timestamp": "2024-03-05T21:42:00Z"},
    ]), encoding="utf-8")
    recs, _ = run("scripts/connectors/imessage_extract.py", f, "--from-json")
    assert [r["is_from_me"] for r in recs] == [False, False, True]
    assert recs[0]["timestamp"] == "2024-03-05T21:50:00Z"   # ms converted, not leaked
    assert recs[1]["timestamp"] == "2024-03-05T21:50:01Z"   # s converted
    assert recs[2]["timestamp"] == "2024-03-05T21:42:00Z"


# ── missing inputs: one-line errors, no tracebacks, no phantom files ─────────

def test_missing_inputs_fail_cleanly_across_connectors(tmp_path):
    cases = [
        ("scripts/connectors/gmail_mbox_parse.py", [str(tmp_path / "nope.mbox")]),
        ("scripts/connectors/whatsapp_parse.py",
         [str(tmp_path / "nope.txt"), "--me", "Sam"]),
        ("scripts/connectors/telegram_parse.py",
         [str(tmp_path / "nope.json"), "--me", "Sam"]),
        ("scripts/connectors/sms_xml_parse.py", [str(tmp_path / "nope.xml")]),
        ("scripts/connectors/imessage_extract.py", [str(tmp_path / "nope.db")]),
        ("scripts/connectors/discord_parse.py",
         [str(tmp_path / "nope.json"), "--me-id", "7"]),
        ("scripts/connectors/instagram_parse.py",
         [str(tmp_path / "nope"), "--me", "Sam"]),
    ]
    for script, argv in cases:
        p = subprocess.run([PY, str(REPO / script), *argv, "-o", "-"],
                           capture_output=True, text=True)
        assert p.returncode != 0, f"{script} exited 0 on a missing input"
        assert "Traceback" not in p.stderr, f"{script} tracebacked:\n{p.stderr}"
    # the old mailbox default CREATED the missing file on a typo'd path
    assert not (tmp_path / "nope.mbox").exists()


def test_imessage_garbage_db_fails_cleanly(tmp_path):
    db = tmp_path / "chat.db"
    db.write_bytes(b"this is not a sqlite database at all")
    p = subprocess.run([PY, str(REPO / "scripts/connectors/imessage_extract.py"),
                        str(db), "-o", "-"], capture_output=True, text=True)
    assert p.returncode != 0
    assert "Traceback" not in p.stderr


def test_connector_creates_missing_output_dir(tmp_path):
    f = tmp_path / "WhatsApp Chat with Pat.txt"
    f.write_text("[2024-03-05, 9:41:12 PM] Sam: hello there\n", encoding="utf-8")
    out = tmp_path / "data" / "raw" / "whatsapp.jsonl"   # data/raw/ doesn't exist yet
    p = subprocess.run([PY, str(REPO / "scripts/connectors/whatsapp_parse.py"),
                        str(f), "--me", "Sam", "-o", str(out)],
                       capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    assert out.exists()


# ── Instagram: system-line filter anchors on the sender's own name ───────────

def test_instagram_system_filter_keeps_first_person_prose(tmp_path):
    thread = tmp_path / "inbox" / "alex_123"
    thread.mkdir(parents=True)
    (thread / "message_1.json").write_text(json.dumps({
        "title": "Alex",
        "messages": [
            {"sender_name": "Sam", "timestamp_ms": 1709675400000,
             "content": "sorry i reacted so badly to your message"},   # real prose
            {"sender_name": "Sam", "timestamp_ms": 1709675410000,
             "content": "i sent an attachment."},                      # real prose
            {"sender_name": "Sam", "timestamp_ms": 1709675420000,
             "content": "Sam sent an attachment."},                    # system notice
            {"sender_name": "Alex", "timestamp_ms": 1709675430000,
             "content": "Alex reacted ❤ to your message"},        # system notice
        ],
    }), encoding="utf-8")
    recs, _ = run("scripts/connectors/instagram_parse.py", tmp_path / "inbox", "--me", "Sam")
    assert [r["text"] for r in recs] == ["sorry i reacted so badly to your message",
                                         "i sent an attachment."]


def test_slack_keeps_thread_broadcast(tmp_path):
    # thread_broadcast is a real message you posted ("also send to channel") —
    # it must not be dropped with the system/bot subtypes.
    (tmp_path / "users.json").write_text(
        '[{"id":"U1","profile":{"display_name":"Sam"}}]', encoding="utf-8")
    chan = tmp_path / "general"
    chan.mkdir()
    (chan / "2024-03-05.json").write_text(json.dumps([
        {"type": "message", "subtype": "thread_broadcast", "user": "U1",
         "ts": "1709675400.0", "text": "shipping the fix now"},
        {"type": "message", "subtype": "channel_join", "user": "U1",
         "ts": "1709675410.0", "text": "joined"},
    ]), encoding="utf-8")
    recs, _ = run("scripts/connectors/slack_parse.py", tmp_path, "--me", "Sam")
    assert [r["text"] for r in recs] == ["shipping the fix now"]   # join dropped, broadcast kept
    assert recs[0]["is_from_me"] is True


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
