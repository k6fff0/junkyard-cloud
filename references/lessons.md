# Lessons (read before you start)

Each line here broke something on the real server this skill comes from. They are rules now.

## The machine
- **Docker bypasses ufw.** A port published as `5678:5678` is open to the whole LAN whatever ufw says. Publish on
  `127.0.0.1` or `172.17.0.1` only.
- **After a reboot, Docker can start before the LAN address exists**, and a container that binds to that address
  fails ("cannot assign requested address"). The `wait-lan.conf` drop-in in `base-os.md` fixes it; a container that
  failed this way is fixed with `docker compose up -d --force-recreate <service>` (a plain `docker start` brings it
  up without the port).
- **Samba and other host services that bind to the LAN address** need the same wait (`After=network-online.target`
  plus a loop until the address exists).
- **A netplan file that names one network card** stops working on a new card. Match `en*` with DHCP and keep the
  address fixed by a reservation in the router.
- **Some old boards boot-loop with a weak or new BIOS battery** and run fine without one: if the owner sees the
  PC turning on and off every few seconds, try without the battery (the clock is fixed by NTP after boot).
- **Disk space:** Docker build caches grow with every rebuild (1 GB per deploy was seen). Show the owner
  `docker system df`; clean only when they ask (`docker builder prune`), never on a schedule they did not choose.

## Scripts and cron
- **A script rewritten with `mv` loses its execute bit**, and cron skips it silently: the off-site copy did not run
  one night and nobody was told. Always `install -m 755` or `chmod 755` after `mv`, and make every scheduled job
  report failure (the backup scripts do).
- **Never put a secret in a command line** that ends up in shell history or logs; read it from a file.
- **Edits that contain quotes or expressions** (n8n code, JSON) go through a file you upload, never inline in an
  SSH command: quoting broke a live workflow for a minute.

## Cloudflare
- **Vaultwarden and Jellyfin cannot sit behind Access**: their apps never show the email page. Protect them as in
  `cloudflare.md`.
- **A Home Assistant behind the tunnel answers 400** until `trusted_proxies` includes `127.0.0.1` and `::1`.
- **Home Assistant (2026.x) stores `http:` settings in `.storage/http` after the first start**, ignores the YAML,
  and rolls back a change that is not confirmed in its web page within five minutes. Set `http:` before the first
  start; to change it later, stop the container, edit `.storage/http` (`data.stable`, and `pending: null`), start it.

## WhatsApp, files, the assistant
- **WhatsApp sends an album as separate messages**, a few seconds apart, and sometimes sends the owner's private
  LID instead of their number. The file bridge groups photos by time and learns the LID from WAHA.
- **A text sent just before its photos** ("save these as one PDF") was handled twice (once by the text, once by the
  photos): every file now has exactly one owner (a claim in the database).
- **Paperless accepts the same file twice when both copies are processed at the same time.** The bridge checks a
  SHA-256 before uploading and refuses repeats.
- **Stirling-PDF fails on non-ASCII file names.** Send an ASCII name, put the real name back on the result.
- **YouTube slows down download managers** (aria2: 5.5 MB/s with 16 connections; yt-dlp: about 12 MB/s). Video
  sites are downloaded by yt-dlp; "download this" on a video link means the video, "sound only" means mp3.
- **Gmail drops a silent IMAP IDLE connection** after about 26 minutes and the next email is late. Renew IDLE every
  9 minutes with TCP keepalive.
- **Python 3.13+ `getaddresses()` returns nothing if one header is empty**: leave empty headers out (the To list
  was empty for most mail).
- **n8n 2.x: `PUT /workflows/{id}` saves a draft only**; activate it to publish, and wait a few seconds before testing.
- **n8n's AI agent uses the OpenAI Responses API** (`/v1/responses`); plain HTTP nodes use chat completions.
- **A node that reads a node removed with a module** makes the whole workflow fail; the installer refuses such
  templates.
- **The model invents causes when it does not know** ("the file had two pages"). The prompt tells it to say it is
  not sure.
- **The assistant re-created reminders it had just listed**, and added ones nobody asked for. It must list before
  and after, never re-create, and the server refuses the same time and words twice.
- **"I can't see the photo"**: the model said this without trying. It has a tool to look and must use it first.
- **Short replies after a notification** ("try again") refer to the notification: notifications are written into
  the assistant's memory.
- **Mail and web content must never steer the assistant**: content from outside is marked as data, models that
  read it have no tools, and any run that read the web has its other tools locked.

## Working with the owner
- They judge by what they see on their phone. A feature that is not reachable from chat or the dashboard does not
  exist for them.
- When they say something is broken, it is. Investigate, do not explain why they are wrong.
- Steps they must do: numbered, short, doable from a phone; anything with accounts or settings waits until they
  are at a computer.
