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

**Parse:** use the generic JSON importer pattern (point the formatter at the
folder); flag `is_from_me` where `user == <your Slack user id>`. Find your id in
`users.json` by matching your name/email.

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
- Flag `is_from_me` where `author.id == <your Discord user id>` (stable) or
  `author.name == <your handle>`.
- Skip system messages (`type` other than `Default`/`Reply`), embeds-only, and
  empty content.

## Importing either

Both are close enough to the unified schema that the formatter's generic importer
handles them. In `mirror-data-formatting`, map fields:

| Unified | Slack | Discord |
|---------|-------|---------|
| `text` | `text` (resolve mentions/links) | `content` |
| `is_from_me` | `user == my_id` | `author.id == my_id` |
| `timestamp` | `ts` (epoch s) | `timestamp` (ISO) |
| `sender` | `users.json[user].name` | `author.nickname or .name` |
| `conversation_id` | channel/DM name | channel/DM name |

If you prefer a dedicated script, copy `telegram_parse.py` as a template — the
shape is nearly identical.
