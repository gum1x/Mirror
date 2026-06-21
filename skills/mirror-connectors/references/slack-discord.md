# Connector: Slack & Discord

Both export to JSON. Both are chatty and casual — good for the `autoreply` and
`chat` surfaces.

## Slack

**Personal DMs (what you usually want):**
- Slack restricts DM export to the workspace **Owner/Admin** via
  *Settings → Import/Export Data → Export* (and DM export often requires a paid
  plan + a self-serve or approved request). If you own the workspace, export and
  you'll get a `.zip` of per-channel/-DM JSON folders.
- If you only need *your own* data and aren't an admin, use **Slack's "Download
  your data"** where available, or copy/paste shorter histories.

**Structure:** `<channel>/<YYYY-MM-DD>.json`, each file an array of messages:
```json
{ "type": "message", "user": "U12345", "ts": "1709675472.000200", "text": "lgtm 🚀" }
```
- `user` is an opaque ID → map to you via the export's `users.json`.
- `ts` is a Unix epoch (seconds) string.
- Text contains `<@U123>` mentions and `<url|label>` links → normalize.

**Parse:**
```bash
python scripts/connectors/slack_parse.py exports/slack --me "Sam Rivera" -o data/raw/slack.jsonl
# most reliable — by id:  --me-id U012ABCDEF
```
The parser loads `users.json`, resolves your user id from `--me` (name/email) or
`--me-id`, rewrites `<@U123>` mentions and `<url|label>` links to readable text,
and skips join/system (`subtype`) messages. If it can't resolve your id it warns
and flags 0 of your messages — pass `--me-id` then.

## Discord

Discord has **no native bulk export**. Use **DiscordChatExporter** (open-source,
widely used) to export a DM or channel to **JSON**:
```
DiscordChatExporter  →  Export format: JSON  →  one .json per channel/DM
```
Structure:
```json
{
  "messages": [
    { "id": "...", "timestamp": "2024-03-05T21:41:12.000+00:00",
      "author": { "id": "...", "name": "sam", "nickname": "Sam" },
      "content": "running 5 min late lol" }
  ]
}
```
**Parse:**
```bash
python scripts/connectors/discord_parse.py exports/discord --me-id 123456789012345678 \
    -o data/raw/discord.jsonl
# or by handle:  --me "sam"
```
Point it at a single `.json` or a folder of them. It flags `is_from_me` by
`author.id == --me-id` (stable) or username/nickname match, skips non
`Default`/`Reply` messages and empty content, and uses the channel name as the
conversation id.

## Field mapping (for reference / custom adapters)

| Unified | Slack | Discord |
|---------|-------|---------|
| `text` | `text` (mentions/links resolved) | `content` |
| `is_from_me` | `user == my_id` | `author.id == my_id` |
| `timestamp` | `ts` (epoch s) | `timestamp` (ISO) |
| `sender` | `users.json[user].name` | `author.nickname or .name` |
| `conversation_id` | channel/DM name | channel/DM name |
