---
name: junkyard-cloud
description: Build a secure self-hosted home server (homelab) on an old PC, on the owner's own domain through Cloudflare Tunnel and Access, with nightly and off-site backups, monitoring, a dashboard, optional self-hosted services (photos, passwords, documents archive, media, downloads, saved links, smart home, file browser, staging for the owner's projects), and a personal AI assistant on WhatsApp or Telegram that saves documents, converts files, downloads videos, reminds and calls the owner. Use when someone wants a home server, homelab, self-hosted cloud, or a WhatsApp/Telegram assistant running on their own machine, or wants to add a service or the assistant to a server built with this skill.
---

# Junkyard Cloud

You are building a home server for the person you are working with (the owner) on a PC they own, usually an
old one. When you finish, they have:

- the server reachable on their own domain (`service.their-domain.com`) through a Cloudflare Tunnel: no port is
  opened on their router, and every web service sits behind a login code sent to their email (Cloudflare Access)
- nightly backups, an image of the system disk, and an encrypted copy outside the house, with alerts on failure
- monitoring that messages them (and can call them) when something is down, and a dashboard page
- the services they chose from the menu below
- a personal assistant on WhatsApp (or Telegram) that lives on their server: they send a photo and it is filed
  in their archive with its expiry date, they send a link and it is downloaded, they say "remind me" or
  "call me" and it does

Everything here was built and used daily on a real server first; the code in this repository is that code,
generalized and tested. Install it, configure it, and test it. Do not rewrite it.

## Golden rules

1. **The owner's machine, the owner's decisions.** Technical choices are yours; product choices are theirs
   (which services, which language, what the assistant is called). Ask product questions, never implementation
   questions. Before anything that deletes data, sends something to other people, or costs money, show it and
   wait for a yes.
2. **Never lock them out.** Every change to SSH, the firewall or the network is made with an automatic undo
   timer (see `references/base-os.md`) and confirmed only after you reconnected. Keep a working way in at all times.
3. **Nothing on the internet without protection.** A web service is published only through the tunnel and
   behind Cloudflare Access, except the few whose apps cannot pass Access (listed in `references/services.md`,
   each with its own protection). Docker publishes ports on `127.0.0.1` (for the tunnel) or `172.17.0.1` (for
   other containers), never on all addresses: Docker bypasses `ufw`.
4. **No default passwords, no secrets in chat or git.** Generate every secret (`openssl rand -hex 32`), keep
   them in `/etc/junkyard/secrets.json` (mode 600) and in the owner's password manager, and never print them.
5. **Measure, then say.** "Done" means you ran it and saw it work. Report what works, what does not, and what
   was skipped, with real numbers. A test the owner must do from their phone is listed as theirs, not as done.
6. **Pin versions.** Use the image versions in `templates/compose/`. Update one service at a time, after a backup.
7. **Leave a handover.** At the end write `/root/JUNKYARD.md` on the server (and a copy for the owner): what
   is installed, where, how to reach it, how to restore it, and what is left. The next session starts there.
8. **Read `references/lessons.md` before you start.** Every line in it cost a real outage.

## What you need from the owner

- a PC that can run all day (4 GB RAM minimum, 8+ for photos and documents; a second disk for data is best)
- a domain on Cloudflare (free plan) and access to that Cloudflare account
- an email address for the login codes
- for the assistant: an OpenAI API key (an API account, not a ChatGPT subscription; with the cheap models
  configured here, 10 USD lasts months) and a **second WhatsApp number** for the assistant (a cheap SIM): the
  WhatsApp link used here is unofficial, so their own number must never be used. Telegram is the official
  alternative and needs only a bot token.
- optional: a Twilio account for phone calls (about 0.30 USD per short call)

## The journey

Work through these in order. Each step has its own reference file: read it when you reach the step.

| # | Step | Reference |
|---|---|---|
| 1 | Interview the owner, look at the machine, write `/etc/junkyard/config.json` | `references/interview.md` |
| 2 | Prepare the machine: Ubuntu, SSH keys, firewall, updates, Docker | `references/base-os.md` |
| 3 | Domain and protection: tunnel, Access, DNS | `references/cloudflare.md` |
| 4 | The network plan and isolation | `references/network.md` |
| 5 | Backups (before any data arrives) | `references/backups.md` |
| 6 | Monitoring and the dashboard | `references/monitoring.md` |
| 7 | The services they chose | `references/services.md` |
| 8 | The assistant | `references/assistant.md` |
| 9 | Prove it works, then hand over | `references/handover.md` |

Steps 2 to 5 are not optional: they are what makes this a server and not a pile of containers.

## The menu (show it to the owner in step 1)

Services (each is optional):

| Service | Replaces | Template |
|---|---|---|
| Photos (Immich) | iCloud / Google Photos | `templates/compose/immich` |
| Passwords (Vaultwarden) | Bitwarden / 1Password | `templates/compose/vaultwarden` |
| Documents archive (Paperless-ngx) + file tools (Stirling-PDF) | paper folders, online converters | `templates/compose/paperless`, `stirling` |
| Media (Jellyfin) + downloads (aria2, yt-dlp) | a personal Netflix, IDM | `templates/compose/jellyfin`, `downloads` |
| Saved links (Karakeep) | Pocket | `templates/compose/karakeep` |
| Smart home (Home Assistant) | vendor apps | `templates/compose/homeassistant` |
| File browser | Dropbox | `templates/compose/filebrowser` |
| Staging for their own projects | a paid VPS | `templates/compose/staging` |

What the assistant can do (each is a module; the ones that need a service install it):

| Module | What the owner gets |
|---|---|
| core (always) | chat and voice notes, one memory across channels, notes ("remember that..."), reminders (once, daily, weekly), notifications from the server, server status and restarts (after confirmation), alerts when the AI credit runs out |
| whatsapp / telegram | the chat channel(s); at least one |
| email | notifications by email |
| calls | the server phones them (a voice reads the alert), live phone conversations with the assistant |
| files | 60+ file operations from chat (to Word/PDF, merge, compress, password, watermark...), and the assistant can look at photos and PDFs |
| archive | photos and files sent with no words are filed, read, titled, given their expiry date, and reminded before they expire; "send me my passport" |
| web | web search and page reading, and website watches ("tell me when a flat under X appears") |
| links | save and find links by meaning |
| downloads | "download this" for files, torrents and videos ("sound only" = mp3) |
| mail | one-time codes from their inboxes reach the chat at once, important mail is summarized now, the rest in one evening digest |
| uptime | sites going down and up; important ones escalate to a phone call |

## Repository map

- `components/`: code written for this server, each with tests: `filebridge` (chat files, archive, file tools),
  `dlbridge` (downloads), `webtool` (search and reading), `mailwatch`, `voice-bridge` (calls), `ops` (`jc-ops`,
  the only actions the assistant may run on the server), `isolate` (`jc-isolate`, network isolation),
  `backup` (`jc-backup`, `jc-snapshot`, `jc-offsite`, `jc-notify`)
- `workflows/`: the assistant's n8n workflows as templates, its prompts, its messages (English, Arabic) and
  database schema
- `installer/jc_n8n.py`: installs the assistant into n8n (credentials, workflows, archive setup), safe to re-run
- `templates/compose/`: one folder per service, with `compose.yml` and `.env.example`
- `references/`: the step guides above, and `lessons.md`

## Costs to tell the owner honestly

- domain: what they already pay; Cloudflare Tunnel and Access: free (up to 50 users)
- electricity of one always-on PC
- OpenAI: cents per day with the models in `references/assistant.md`; Twilio calls if they enable them
- off-site backup on Cloudflare R2: free up to 10 GB, then about 0.015 USD per GB per month
