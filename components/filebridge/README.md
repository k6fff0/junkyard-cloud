# filebridge

Moves files between the owner's chats (WhatsApp through WAHA, Telegram), the documents archive
(Paperless-ngx) and the file tools (Stirling-PDF), for the n8n assistant. Only n8n talks to it.

What it handles:
- a file sent with no words is saved to the archive; photos sent together become one PDF; duplicates are refused
- a text about files ("save these as one PDF named ...") collects the files sent just before or after it
- a caption, or a reply to an earlier file, goes to the assistant with the file refs
- forwarded messages are marked as information, not orders; stickers, reactions, groups and strangers are ignored
- tools for the assistant: list file operations, run them (chains too), send a file, archive, look at a file (vision)

## Endpoints (header `X-Bridge-Key` on all but `/health`)

| Endpoint | Body | Answer |
|---|---|---|
| `POST /wa-incoming` | WAHA webhook `{event, payload}` | `{action: agent, text}` / `{action: voice, url, prefix}` / `{action: done}` / `{action: skip}` |
| `POST /incoming` | Telegram `{message}` | same actions |
| `POST /tool` | `{action, arg1, arg2}` | `{result}` (`render` answers `{images, pages}`) |
| `GET /health` | | `{ok, operations, whatsapp, telegram, archive}` |

Tool actions: `ops <query>`, `recent`, `run <operation> {files, params, send, channel}`,
`deliver <ref> {channel}`, `archive <ref> {hint, channel}`, `look <refs> {question, pages}`, `render <ref> {pages}`.
Refs: `f12` (a file in the bridge, kept 3 days) or `doc:7` (an archive document).

## Settings (environment)

| Name | Needed | Meaning |
|---|---|---|
| `BRIDGE_KEY` | yes | shared secret with n8n, 24+ random characters |
| `OWNER_NAME`, `LANG_CODE` | | how tool results name the owner; language of owner messages (`en`, `ar`) |
| `WAHA_URL`, `WAHA_KEY`, `WA_OWNER`, `WA_SESSION` | for WhatsApp | WAHA address and key; owner's phone (digits); session (`default`) |
| `WA_EXTRA_ALLOWED` | | more allowed chat ids, comma separated (the owner's LID is found automatically) |
| `TG_TOKEN`, `TG_CHAT` | for Telegram | bot token; owner's chat id |
| `PAPERLESS_URL`, `PAPERLESS_TOKEN`, `DOCS_URL` | for the archive | API address and token; public link shown to the owner |
| `STIRLING_URL`, `PDF_URL` | for file tools | API address; public link shown to the owner |
| `OPENAI_API_KEY`, `LOOK_MODEL` | for vision | key; model used to look at files |
| `DATA_DIR`, `PORT` | | `/data`, `8790` |

At least one channel (WhatsApp or Telegram) is required. Without the archive, files with no words go to the
assistant, which asks what to do.

## Tests

```
pip install -r requirements.txt
python -m unittest discover -s tests -t .
```
The tests run against one fake server that plays WAHA, Paperless, Stirling, Telegram and OpenAI, and replay
real WhatsApp situations (albums sent as separate messages, a text sent before its photos, forwards, duplicates).
