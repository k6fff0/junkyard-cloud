# Step 8: the assistant

The assistant is n8n plus a few small services from `components/`, installed by `installer/jc_n8n.py`. The
owner talks to it on WhatsApp (through WAHA, on a second number) or Telegram; it answers with the cheap models
below and acts only through fixed tools. Read this whole file before starting.

## What is where

| Piece | Template / code | Network | Reached at |
|---|---|---|---|
| n8n + Postgres (n8n's database and the assistant's own) | `templates/compose/assistant` | assistant | `http://n8n:5678`, `127.0.0.1:5678`, `172.17.0.1:5678` |
| WAHA (WhatsApp) | same compose | assistant | `http://waha:3000` (never public) |
| filebridge (chat files, archive, file tools) | `components/filebridge`, same compose | assistant | `http://filebridge:8790` |
| voice bridge (calls) | `components/voice-bridge`, `templates/compose/voice` | assistant | `voice.DOMAIN` (public, path secret) |
| web tool + SearXNG | `components/webtool`, `templates/compose/webtool` | webtool (isolated) | `http://172.17.0.1:8787` |
| mail watcher | `components/mailwatch`, `templates/compose/mailwatch` | mailwatch (isolated) | posts to n8n |
| downloads bridge | `components/dlbridge`, `templates/compose/downloads` | downloads (isolated) | `http://172.17.0.1:8103` |
| jc-ops (server actions, reminders) | `components/ops` | the server itself | SSH from n8n, one forced command |

## 1. n8n, its database, WAHA and the file bridge

1. Copy `templates/compose/assistant` to `/opt/junkyard/assistant`, fill `.env` (secrets from the secrets file;
   `N8N_ENCRYPTION_KEY` never changes once set: losing it makes every stored credential unreadable).
2. `docker compose build && docker compose up -d`. The Postgres init script creates the `assistant` database and
   user; then load the schema: `docker compose exec -T postgres psql -U assistant -d assistant < /opt/junkyard/src/workflows/schema.sql`.
3. n8n stays on `127.0.0.1` and `172.17.0.1`. Publish `n8n.DOMAIN` (behind Access) so the owner can look inside.
   With Telegram or Twilio callbacks, `WEBHOOK_URL=https://n8n.DOMAIN/` and an Access **bypass** for
   `n8n.DOMAIN/webhook` only (every webhook checks its own secret header).
4. Owner account and API key without the web page:
   ```
   sudo python3 /opt/junkyard/src/installer/jc_n8n.py bootstrap --email <owner email> \
     --password-file <(jq -r .n8n_owner_password /etc/junkyard/secrets.json) --out /etc/junkyard/n8n-api-key
   ```
   Give the owner the n8n login (email + `n8n_owner_password`) for their password manager.

## 2. WhatsApp (WAHA, the second number)

Explain to the owner first: this is an unofficial WhatsApp link. Use a **second number** (a cheap SIM in any
phone that stays on), never their main one; the assistant writes only to them, and replies only to them.

1. WAHA starts with `WHATSAPP_DEFAULT_ENGINE=GOWS` and the API key from the secrets file.
2. Create the session with the webhook to n8n (check the current API at waha.devlike.pro before calling):
   `POST http://127.0.0.1:3000/api/sessions` with `{"name":"default","config":{"webhooks":[{"url":"http://n8n:5678/webhook/whatsapp-in","events":["message"],"customHeaders":[{"name":"X-Notify-Secret","value":"<notify_secret>"}]}]}}`.
3. Pair by code: `POST /api/default/auth/request-code` with the assistant number → an 8-character code. The owner,
   on the assistant phone: WhatsApp → Linked devices → Link a device → Link with phone number → the code.
4. `GET /api/sessions/default` → `WORKING`. If it ever drops (the phone was off for weeks), pair again the same way.
5. The owner saves the assistant's number as a contact and sends it "hi". The file bridge finds their private
   id (LID) by itself.

## 3. Telegram (optional, or instead of WhatsApp)

The owner talks to @BotFather → `/newbot` → gives you the token (`telegram_token` in the secrets file). They send
`/start` to the new bot; you read their chat id with `https://api.telegram.org/bot<token>/getUpdates` (before
n8n takes the webhook) and put it in the config. Telegram needs the public `/webhook` bypass above.

## 4. Server actions: jc-ops

```
sudo install -m 755 /opt/junkyard/src/components/ops/jc-ops /usr/local/sbin/
sudo install -m 600 /opt/junkyard/src/components/ops/ops.example.json /etc/junkyard/ops.json   # edit it
sudo install -m 644 /opt/junkyard/src/components/ops/jc-ops.cron /etc/cron.d/jc-ops
sudo ssh-keygen -q -t ed25519 -N '' -C n8n-jc-ops -f /root/n8n-jc-ops
echo "restrict,from=\"172.16.0.0/12\",command=\"/usr/local/sbin/jc-ops ssh\" $(cat /root/n8n-jc-ops.pub)" | sudo tee -a /root/.ssh/authorized_keys
```

Put the private key in the secrets file (`ssh_ops_private_key`), then delete `/root/n8n-jc-ops` and its `.pub`.
`ops.json`: `restartable` (never n8n or a database), `disks`, `status_files` (the backup JSON files),
`default_channels`, `lang`. Check it the way n8n will use it, from a container (before deleting the key file):

```
sudo docker run --rm -v /root/n8n-jc-ops:/k:ro alpine:3.22 sh -c 'apk add -q openssh-client &&
  ssh -i /k -o StrictHostKeyChecking=no root@172.17.0.1 status; ssh -i /k -o StrictHostKeyChecking=no root@172.17.0.1 "cat /etc/shadow"'
```

The first prints the status; the second must print `REFUSED`. From the LAN the key must not work at all.

## 5. Optional pieces

- **Calls (Twilio):** the owner makes a Twilio account, buys a number with Voice, verifies their own number, and
  allows calls to their country (Geo permissions). Start `templates/compose/voice` (`STREAM_SECRET` =
  `voice_stream_secret`), publish `voice.DOMAIN` without Access, and set the Twilio number's voice URL to
  `https://voice.DOMAIN/incoming/<voice_stream_secret>` (calls from their number only). `docker compose exec voice python bridge.py selftest` must print `response.done status=completed`.
  Tell the owner to save the Twilio number as "Server" and allow it in their phone's sleep or focus mode.
- **Web:** `templates/compose/webtool`; generate `__SEARXNG_SECRET__` in `searxng/settings.yml`; set
  `DENY_DOMAINS` (their own domains) and `DENY_RESOLVE_HOSTS` (their router's DDNS name, if any); `jc-isolate webtool`.
- **Mail:** `templates/compose/mailwatch` with `accounts.json` (mode 600; Gmail and others need an app password);
  `jc-isolate mailwatch`.
- **Downloads, links, archive:** see `services.md`.

## 6. Install the workflows

```
cd /opt/junkyard/src
sudo python3 installer/jc_n8n.py render  --config /etc/junkyard/config.json --out /tmp/jc-render   # look first
sudo python3 installer/jc_n8n.py install --config /etc/junkyard/config.json --secrets /etc/junkyard/secrets.json
sudo python3 installer/jc_n8n.py status  --config /etc/junkyard/config.json
```

It creates the credentials, the archive setup, every workflow of the chosen modules in the right order, and
turns them on. Safe to run again after changing the config (a turned-off module's workflows are turned off).
Changing a key: edit the secrets file and add `--update-credentials`.

## 7. Models and cost

Each job uses the cheapest model that does it well; this is why 10 USD lasts months. Check names and prices at
OpenAI's pricing page before installing, and change them in `config.json` → `models`:

| Job | Default |
|---|---|
| the assistant, reading documents, looking at photos, mail summaries, link summaries | `gpt-6-luna` |
| website-watch judge, the 3-hourly health ping | `gpt-5-nano` |
| voice notes to text | `gpt-4o-mini-transcribe` |
| live calls | `gpt-realtime-2.1-mini` |
| link search by meaning | `text-embedding-3-small` |

About 12 thousand tokens go in with every chat message (instructions, tools, the last 30 messages), so the main
model's input price matters most. Measure before changing: send the same 9 messages with each candidate and
compare the usage on the OpenAI dashboard.

## 8. Prove it

On the server (no money): `installer/tests/run.sh` against a throwaway stack must pass.
Then with the owner, from their phone, each module they chose (write down every result):

| Say or send | Expect |
|---|---|
| "hi" | an answer in their style within seconds |
| a voice note | it was understood |
| "remember that Ali owes me 500" then, later, "who owes me money?" | it finds the note |
| "remind me in 2 minutes to drink water" | the reminder arrives |
| a photo of a document, no words | "saved document #N ... expires ..." (archive) |
| "send me my passport" | the file comes back (archive) |
| a PDF with "make it Word" | a .docx comes back (files) |
| a YouTube link with "sound only" | "started" then "finished", an mp3 (downloads) |
| a link with "save it", later "find the link about ..." | the link (links) |
| "what's new about <topic>?" | an answer with its source (web) |
| "call me" | the phone rings and they talk to it (calls) |
| a test email with a code | the code alone in chat (mail) |
| a message from another number | no answer at all |
