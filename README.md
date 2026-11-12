<div align="center">

# Junkyard Cloud

**Turn an old PC into your own private cloud, with a personal AI assistant on WhatsApp.**

An agent skill for Claude Code, Codex and any agent that reads `SKILL.md`. *By Corvita.*

[![License: MIT](https://img.shields.io/badge/License-MIT-black.svg)](LICENSE)
![Agent Skill](https://img.shields.io/badge/Agent%20Skill-SKILL.md-black)
![Ubuntu Server](https://img.shields.io/badge/Ubuntu%20Server-LTS-black)

</div>

---

You already pay for a domain, use Cloudflare and have an AI subscription. The PC in the corner is doing nothing.
Install this skill, tell your agent *"build me a home server"*, and it turns that PC into:

- **your own services on your own domain**: `photos.you.com`, `docs.you.com`, `password.you.com`...
  with no port opened on your router and a login code on every page
- **an assistant you text on WhatsApp** that files your documents, converts your files, downloads what you send
  it, reminds you, and calls you when something breaks
- **a server that looks after itself**: nightly backups, an encrypted copy outside the house, a disk image you
  can boot again, monitoring that messages you, and a dashboard

It is not a script that runs once and leaves you alone with it. Your agent interviews you, shows you the menu,
builds one piece at a time, proves each piece works, and leaves you a handover file that says what is where and
how to restore it.

Everything in it was first built and used every day on a real home server, running on a PC rescued from the
junk. This repository is that server's code and know-how, generalized and tested.

## Contents

- [What you get](#what-you-get)
- [The assistant](#the-assistant)
- [Security](#security)
- [What you need](#what-you-need)
- [Install the skill](#install-the-skill)
- [Use it](#use-it)
- [Update and uninstall the skill](#update-and-uninstall-the-skill)
- [Your server later: updates and removal](#your-server-later-updates-and-removal)
- [How it works](#how-it-works)
- [Costs](#costs)
- [What has been tested](#what-has-been-tested)
- [Repository layout](#repository-layout)
- [Contributing](#contributing)
- [License](#license)

## What you get

**The base (always built):** this is what makes it a server and not a pile of containers.

| Part | What it does |
|---|---|
| Ubuntu Server, hardened | SSH keys only, firewall, automatic security updates. Every SSH or firewall change has an automatic undo timer, so you are never locked out. |
| Cloudflare Tunnel + Access | Every service on `name.your-domain.com`, reached through one outgoing tunnel. No open ports, no public IP needed. A login code sent to your email in front of every page. |
| Isolation | Services that open links from the internet (downloads, link reader, web search) live on networks that can reach the internet and nothing in your home. |
| Backups | Every database and setting every night (3 days kept), a full image of the system disk every 3 days, and an encrypted off-site copy on Cloudflare R2. A message to you when any of them fails. |
| Monitoring + dashboard | Uptime Kuma checks every service and messages you (or calls you) when one goes down. One dashboard page with every service and the backup status. |

**The menu (pick what you want):**

| Service | Replaces |
|---|---|
| Photos (Immich) | iCloud / Google Photos |
| Passwords (Vaultwarden) | Bitwarden / 1Password |
| Documents archive (Paperless-ngx) + file tools (Stirling-PDF) | paper folders, online converters |
| Media (Jellyfin) + downloads (aria2, yt-dlp) | a personal Netflix, a download manager |
| Saved links (Karakeep) | Pocket |
| Smart home (Home Assistant) | vendor apps |
| File browser | Dropbox |
| Staging for your own projects | a paid VPS |

## The assistant

It lives on your server (n8n, Postgres and a few small services), talks to you on WhatsApp or Telegram, and
acts only through fixed tools. Each part is a module you turn on or off:

| Module | You say or send | It does |
|---|---|---|
| core | "remember that Ali owes me 500", later "who owes me money?" | notes, reminders (once, daily, weekly), voice notes, server status, notifications from the server |
| archive | a photo of your passport, no words | reads it, titles it, files it, notes the expiry date and reminds you before it expires. "Send me my passport" sends it back |
| files | a PDF with "make it Word" | 60+ file operations from chat: convert, merge, compress, protect, watermark. It can also look at photos and PDFs |
| downloads | a YouTube link with "sound only" | downloads it (mp3 here) and tells you when it is done. Files, torrents and videos |
| links | a link with "save it", later "find the link about tax" | saves links and finds them by meaning |
| web | "what's new about Ubuntu 26.04?" | searches and reads pages, with sources. "Tell me when a flat under X appears" watches a site for you |
| mail | (nothing: it watches your inboxes) | one-time codes reach the chat at once, important mail is summarized now, the rest in one evening digest |
| calls | "call me at 9 tomorrow" | the server phones you (a voice reads the alert), or you talk to the assistant live on the phone |
| uptime | (nothing) | a site going down and back up, critical ones escalate to a phone call |

It answers only you, in your language and style (English and Arabic messages are built in). Messages you
forward, emails and web pages are treated as information, never as orders. Anything that reads the web locks
its other tools for that turn, and server actions go through one restricted command that cannot open a shell.

Models: OpenAI, with the cheapest model that does each job well (one for chat and documents, a smaller one for
checks, one for voice notes, one for calls, one for search by meaning). Change any of them in one config file.

## Security

- No port is opened on your router. The only way in from the internet is the Cloudflare Tunnel.
- Every web page is behind Cloudflare Access (a code sent to your email). The few apps that cannot pass it
  (the password manager, the media player) get their own protection: invitation-only accounts, country rules,
  two-factor login.
- Docker never publishes on all addresses (it bypasses the firewall): only on `127.0.0.1` for the tunnel, or on
  the Docker bridge for other containers.
- Secrets are generated on the server, kept in one file readable by root only, never printed and never
  committed. The repository has a pre-commit check that refuses keys.
- The assistant can run exactly one command on the server, through an SSH key that is limited to that command
  and to the Docker networks.

## What you need

- a PC that can stay on: 4 GB RAM for the base and the assistant, 8 GB with documents and downloads, 16 GB with
  photos; a 64 GB system disk, and a second disk for your data
- a domain on Cloudflare (the free plan is enough)
- an AI coding agent: [Claude Code](https://code.claude.com), [Codex](https://developers.openai.com/codex), or
  another agent that reads `SKILL.md`, on a computer that can reach the PC over SSH
- for the assistant: an OpenAI API key, and a second WhatsApp number (a cheap SIM) or a Telegram bot. The
  WhatsApp link is unofficial, so never use your own number for it.
- optional: a Twilio account for phone calls

## Install the skill

Install it on the computer where your agent runs (not on the old PC: the agent puts what the server needs on it
by itself).

**Claude Code**

```bash
# macOS / Linux
git clone --depth 1 https://github.com/k6fff0/junkyard-cloud.git ~/.claude/skills/junkyard-cloud
```

```powershell
# Windows (PowerShell)
git clone --depth 1 https://github.com/k6fff0/junkyard-cloud.git "$HOME\.claude\skills\junkyard-cloud"
```

**Codex**

```bash
# macOS / Linux
git clone --depth 1 https://github.com/k6fff0/junkyard-cloud.git ~/.agents/skills/junkyard-cloud
```

```powershell
# Windows (PowerShell)
git clone --depth 1 https://github.com/k6fff0/junkyard-cloud.git "$HOME\.agents\skills\junkyard-cloud"
```

**Any other agent:** clone it anywhere and tell your agent: *"Read SKILL.md in `<that folder>` and follow it."*

Restart the agent after installing, so it sees the new skill.

## Use it

Start your agent in any folder and ask in your own words:

> Build me a home server with Junkyard Cloud. The old PC is at 192.168.1.50, user `me`.

In Claude Code you can also call it directly with `/junkyard-cloud`, and in Codex with `$junkyard-cloud`.

What happens next:

1. **The interview.** It looks at the machine, then asks you a few questions at a time: your domain, your email
   for the login codes, your language, which services and which assistant modules you want. It warns you if
   your choice is too big for the machine.
2. **The build.** Base first, then backups and monitoring, then one service at a time. Before anything that
   deletes data, costs money or sends something to someone, it shows you and waits for your yes.
3. **The proof.** It reboots the server and checks everything comes back, checks the backups and the isolation,
   and gives you a short list of things to try from your phone.
4. **The handover.** `/root/JUNKYARD.md` on the server (and a copy for you): what runs where, who can open it,
   where the data and the secrets are, and how to restore after a broken service, a dead disk or a dead house.

Already have a server built with it? Ask: *"Add the documents archive to my Junkyard server"* or
*"Turn on the downloads module"*.

## Update and uninstall the skill

| | Claude Code | Codex |
|---|---|---|
| Update | `git -C ~/.claude/skills/junkyard-cloud pull` | `git -C ~/.agents/skills/junkyard-cloud pull` |
| Uninstall (macOS / Linux) | `rm -rf ~/.claude/skills/junkyard-cloud` | `rm -rf ~/.agents/skills/junkyard-cloud` |
| Uninstall (Windows) | `Remove-Item -Recurse -Force "$HOME\.claude\skills\junkyard-cloud"` | `Remove-Item -Recurse -Force "$HOME\.agents\skills\junkyard-cloud"` |

On Windows, `git -C` works the same in PowerShell (`git -C "$HOME\.claude\skills\junkyard-cloud" pull`).
Uninstalling the skill does not touch any server you built with it.

## Your server later: updates and removal

Ask your agent; it follows [`references/maintenance.md`](references/maintenance.md):

- *"Update my Junkyard server"*: pulls the new version of this repository on the server
  (`/opt/junkyard/src`), tells you what changed, and applies only that (the assistant's workflows, a rebuilt
  component, a script).
- *"Update Immich to the latest version"*: one service at a time, after reading its release notes and taking a
  fresh backup, with a way back if it fails. Nothing is ever updated automatically except Ubuntu's security
  updates.
- *"Remove Jellyfin"*: takes away its route, login rule, monitor, dashboard entry and containers. Its data stays
  unless you say otherwise.
- *"Remove everything"*: takes the server back to a plain, safe Ubuntu machine, in an order that never leaves it
  open. Your photos, documents and off-site backup stay until you delete them yourself.

## How it works

The skill is a guide plus tested code. `SKILL.md` tells the agent the rules and the journey; each step has a
reference file it reads when it gets there:

| # | Step | Reference |
|---|---|---|
| 1 | Interview, look at the machine, write the config | [`interview.md`](references/interview.md) |
| 2 | Ubuntu, SSH keys, firewall, updates, swap, Docker | [`base-os.md`](references/base-os.md) |
| 3 | Domain: tunnel, Access, DNS | [`cloudflare.md`](references/cloudflare.md) |
| 4 | The network plan and isolation | [`network.md`](references/network.md) |
| 5 | Backups, before any data arrives | [`backups.md`](references/backups.md) |
| 6 | Monitoring and the dashboard | [`monitoring.md`](references/monitoring.md) |
| 7 | The services you chose | [`services.md`](references/services.md) |
| 8 | The assistant | [`assistant.md`](references/assistant.md) |
| 9 | Prove it works, then hand over | [`handover.md`](references/handover.md) |

Before it starts, the agent reads [`lessons.md`](references/lessons.md): every line in it is something that
broke on a real server, and is now a rule.

The agent installs and configures the code in this repository; it does not write the server from scratch. The
assistant's n8n workflows are installed by one command (`installer/jc_n8n.py`), which is safe to run again
whenever you change your choices.

## Costs

| Item | Cost |
|---|---|
| Cloudflare Tunnel and Access | free (up to 50 users) |
| Domain | what you already pay |
| Electricity | one always-on PC |
| OpenAI | cents per day with the default models; 10 USD lasts months for one person |
| Off-site backup on Cloudflare R2 | free up to 10 GB, then about 0.015 USD per GB per month |
| Phone calls (optional, Twilio) | about 0.30 USD per short call |

Every service on the menu is free and open source.

## What has been tested

- Every component has its own tests: the file bridge (52), downloads (18), web tool (12), mail watcher (9),
  server actions (13), the voice bridge (7, with a simulated call), network isolation (19 checks) and the backup
  scripts (22 checks, with real Postgres and MariaDB, in Docker-in-Docker).
- The assistant's installer runs end to end against a real n8n with a simulated WhatsApp and OpenAI
  (23 scenarios), and its archive setup against a real Paperless-ngx (11 checks).
- A fresh AI agent, given only this skill, built the whole server on a clean Ubuntu Server 24.04 machine and
  exercised every assistant module it installed, then rebooted it: everything came back on its own. What it
  found along the way is fixed and covered by the tests above.
- The code itself runs every day on the server it came from.

Tested on Ubuntu Server 24.04 LTS.

## Repository layout

```
SKILL.md                 the skill: rules, journey, menu, costs (the agent starts here)
references/              one guide per step, lessons.md, maintenance.md
templates/compose/       one folder per service: compose.yml + .env.example, versions pinned
components/              code written for this server, each with tests and a README
  filebridge/            chat files, the archive, file tools
  dlbridge/              downloads (aria2, yt-dlp)
  webtool/               web search and page reading (with SearXNG)
  mailwatch/             inbox watcher (IMAP IDLE)
  voice-bridge/          live phone calls (Twilio + OpenAI Realtime)
  ops/                   jc-ops: the only actions the assistant may run on the server
  isolate/               jc-isolate: network isolation per Docker network
  backup/                jc-backup, jc-snapshot, jc-offsite, jc-notify
workflows/               the assistant's n8n workflows (templates), prompts, messages, database schema
installer/               jc_n8n.py: installs the assistant into n8n; its tests
tools/                   setup scripts (Uptime Kuma, Karakeep) and the repository's secret check
```

## Contributing

Issues and pull requests are welcome: a service for the menu, a language for the assistant's messages
(`workflows/locales/`), a lesson learned on your own server.

- Keep versions pinned, and keep every port on `127.0.0.1` or the Docker bridge.
- Add or update the tests of what you change, and run them.
- Install the secret check once: `sh tools/install-hooks.sh`. It refuses commits that contain keys or tokens.
- No personal data in examples: use `example.com` and made-up names.

## License

[MIT](LICENSE). Use it, change it, share it.

<div align="center">

Made with care by **Corvita**, from a PC someone threw away.

</div>
