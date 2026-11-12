# Step 1: the interview

Goal: know the machine and the owner well enough to write `/etc/junkyard/config.json`, without asking them
anything you can find out yourself, and without asking implementation questions.

## 1. Look at the machine first (read only)

If Ubuntu is not installed yet, skip to `base-os.md` section 1 and come back. Otherwise, over SSH:

```
hostnamectl; lsb_release -ds; uname -r
nproc; free -h; lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT,MODEL
df -h -x tmpfs -x overlay
ip -br addr; ip route | head -3
systemctl is-active docker cloudflared 2>/dev/null
docker ps --format '{{.Names}} {{.Image}}' 2>/dev/null
```

Write down: CPU count, RAM, the system disk and its free space, a second disk (size, filesystem, mounted or
not), the LAN address and gateway, and anything already running. **Never format or mount a disk that has data
on it without the owner's explicit yes** (see `base-os.md`, the data disk).

What the hardware can carry (measured on a test build, idle; peaks are higher, and swap is always added):

| RAM | Comfortable with |
|---|---|
| 4 GB | the base, the assistant (no archive), Vaultwarden, file browser |
| 8 GB | add the archive (Paperless + Stirling), links, downloads |
| 16 GB | everything, including photos with face and object search and media transcoding |

Memory of the big ones: Paperless (with its workers) ~1 GB, Stirling-PDF ~0.7 GB, n8n ~0.5 GB, WhatsApp (WAHA)
~0.3 GB, link library ~0.3 GB plus a browser while it reads a page, Immich 2-4 GB. If the owner picks more than
the machine carries, **say so before installing** and offer fewer services or a lighter set; a build of the 8 GB
set on 4.8 GB fell over (the assistant stopped answering) until swap was added.

System disk: Docker images alone are ~25 GB for the 8 GB set (Paperless 3.6, Stirling 3.6, WAHA 3.2, Gotenberg
2.5, link library 3.6, n8n 1.8...), plus build caches. **64 GB is the minimum for the system disk**; 40 GB was
85% full after the test build.

## 2. Ask the owner (in their language, a few questions at a time)

1. **Domain:** which domain on Cloudflare will the server use? (services become `name.domain`)
2. **Email for the login codes** (Cloudflare Access sends a code to it). Others who may log in?
3. **Time zone and language** they want the server and the assistant to use.
4. **The menu** (show the two tables in `SKILL.md`): which services, which assistant modules. Recommend, do
   not interrogate: for most people the base, Vaultwarden, the archive, links, downloads, and the assistant
   with files, archive, web, links, downloads and mail.
5. **The assistant:** its name; what it calls them; how it talks to them (for example "Egyptian Arabic, technical
   terms in English", or "friendly English"); the language for text it writes for other people; a few lines
   about them it should know (work, family names it will see on documents, how they like answers). Their full
   name as printed on documents helps the archive.
6. **Chat:** WhatsApp (needs a second number for the assistant) and/or Telegram. Which is the main one?
7. **Calls:** do they want the server to phone them? (needs Twilio)
8. **Mail:** which inboxes should the assistant watch? (IMAP host, user, an app password)
9. **Off-site copy:** do they agree to a Cloudflare R2 bucket for the encrypted copy (costs cents)?
10. **Their own projects to stage**, if they chose staging.

Do not ask about ports, images, databases or networks: those are yours.

## 3. Secrets

Generate on the server, never in chat:

Everything here is root's (the files are mode 600), so the whole block runs as root:

```
sudo bash -s <<'SH'
install -d -m 700 /etc/junkyard
python3 - <<'PY'
import json, os, secrets, string
p = "/etc/junkyard/secrets.json"
s = json.load(open(p)) if os.path.exists(p) else {}
for k in ("assistant_db_password", "waha_key", "notify_secret", "mail_secret", "filebridge_key", "downloads_key",
          "webtool_key", "voice_stream_secret", "n8n_encryption_key"):
    s.setdefault(k, secrets.token_hex(24))
# n8n wants upper- and lower-case letters and a digit in its owner password
abc = string.ascii_letters + string.digits
s.setdefault("n8n_owner_password", "Jc7" + "".join(secrets.choice(abc) for _ in range(29)))
fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
json.dump(s, os.fdopen(fd, "w"), indent=1)
PY
python3 -c 'import json;print(json.load(open("/etc/junkyard/secrets.json"))["notify_secret"], end="")' \
  > /etc/junkyard/notify-secret && chmod 600 /etc/junkyard/notify-secret
SH
```

Keys the owner brings (OpenAI, Telegram bot token, Twilio, mailbox app passwords, Cloudflare API token) are
added to the same file when they give them. Ask them to paste a key into a file on the server, or into the
terminal you are running, not into a chat that is stored elsewhere when that can be avoided. At the end, tell
them to save the whole file in their password manager.

## 4. Write the config

`/etc/junkyard/config.json` is read by the installer (`installer/jc_n8n.py`, see `installer/config.example.json`
for every field) and by you. It holds no secrets. Fill:

- `owner` (name, call, full_name, family, profile lines, mail_context), `assistant.name`, `lang` (`en` or `ar`;
  other languages fall back to English messages), `style`, `formal`, `tz`
- `modules` and `main_channel`
- `whatsapp.owner_phone` (their own number, digits with country code), `telegram.chat_id` (found in step 8)
- `email.from` / `email.to`, `calls` (Twilio number, their phone, `voice_host`)
- `urls`: the internal addresses from `network.md` and the public ones from `cloudflare.md`
- `restartable`: container names the assistant may restart (never n8n or a database)
- `mail_aliases` (addresses that should label mail instead of the inbox name), `call_monitors` (sites whose
  outage should phone them)

Show the owner a short summary of what you will build (in their language) and get a yes before step 2.
