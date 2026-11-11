# Step 7: the services

For each chosen service: copy its folder from `templates/compose/<name>` to `/opt/junkyard/<name>`, fill `.env`
from `.env.example` with generated secrets (`chmod 600 .env`), create its data folders on `/mnt/storage`, start
it with `docker compose up -d`, add its route and Access destination (`cloudflare.md`), its monitor and its
dashboard entry (`monitoring.md`), add any new database container to `REQUIRED_DBS` in the backup config, and
run its check. One service at a time; the owner tries it before the next.

## Photos: Immich (`immich`)

- `photos.DOMAIN` → `127.0.0.1:2283`, behind Access; the phone app needs the service token headers.
- Photos in `/mnt/storage/photos`; its Postgres is found by the nightly copy; off-site: the library without
  `encoded-video` and `thumbs` (Immich rebuilds them).
- Update only by the release notes (immich.app): the database image is tied to the version.
- Check: upload from the phone app over mobile data, see it on the web.

## Passwords: Vaultwarden (`vaultwarden`)

- `password.DOMAIN` → `127.0.0.1:8222`, **not** behind Access (the Bitwarden apps cannot pass it): signups
  off, the admin page off or behind its own Access app on `/admin`, a country rule, and the owner turns on 2FA.
- Its SQLite is copied every night; ask the owner to write the Recovery Code on paper.
- Check: log in from the Bitwarden phone app (server URL = `https://password.DOMAIN`), add an item, see it on the web.

## Documents archive: Paperless-ngx + Stirling-PDF (`paperless`, `stirling`)

- `docs.DOMAIN` → `127.0.0.1:8010` and `pdf.DOMAIN` → `127.0.0.1:8085`, both behind Access.
- Paperless joins the assistant network as `paperless`; Stirling as `stirling`. OCR languages: the owner's
  (`PAPERLESS_OCR_LANGUAGE`, for example `ara+eng`).
- Create the admin in `.env` (`PAPERLESS_ADMIN_USER` / `_PASSWORD`), then make the admin's API token in the web
  page (profile → API token) and put it in the secrets file as `paperless_admin_token`. The installer creates the
  document types, the expiry date field, the chat tags, a limited `assistant` user and the two archive workflows.
- Stirling: no login (it is only reached through Access and by the file bridge); it runs some heavy tools, so it
  gets a 2 GB memory limit.
- Check: upload a PDF on the web, it is read (OCR) and the owner gets the assistant's summary in chat.

## Media and downloads: Jellyfin + aria2/yt-dlp (`jellyfin`, `downloads`)

- `download.DOMAIN` → `127.0.0.1:8102` (the AriaNg panel, behind Access). The downloads bridge listens on
  `172.17.0.1:8103` for n8n. Both on the isolated `downloads` network (`jc-isolate downloads`).
- `media.DOMAIN` → `127.0.0.1:8096`, **not** behind Access (TV apps): its own login, a country rule. Libraries:
  `Videos`, `Audio`, `Files`, `Torrents` under `/mnt/storage/downloads`, mounted read only.
- Downloads and media never go off-site and are excluded from the nightly copy (replaceable, large).
- Check: from chat "download <a small Linux ISO link>" → the "finished" message; a YouTube link with "sound
  only" → an mp3 in Audio that Jellyfin shows.

## Saved links: Karakeep (`karakeep`)

- `links.DOMAIN` → `127.0.0.1:3010`, behind Access (the phone app takes the service token headers). n8n reaches it
  at `http://172.17.0.1:3010`. Isolated network `karakeep`: it opens every saved link, so it must never reach the LAN.
- Signups off after the owner's account exists; an API key for n8n (settings → API keys) goes in the secrets
  file as `karakeep_token`. AI tags and summaries use the cheap model in `.env`.
- Check: "save this <link>" in chat, then "find the link about <topic>".

## Smart home: Home Assistant (`homeassistant`)

- Host network (it needs the LAN for discovery); `ha.DOMAIN` → `127.0.0.1:8123` behind Access; ufw allows 8123
  from the LAN only. Add `http: trusted_proxies: [127.0.0.1, ::1]` and `use_x_forwarded_for: true` **before the
  first start**: recent versions keep `http:` settings in `.storage/http` after the first start and roll back
  unconfirmed changes after five minutes (see `lessons.md`).
- Check: open it through the tunnel without a 400 error.

## File browser (`filebrowser`)

- `files.DOMAIN` → `127.0.0.1:8080`, behind Access. Runs as a normal user, sees `/mnt/storage` only (read and write
  to the folders the owner chooses; never `/` or `/etc`).

## Staging for their projects (`staging`)

- One folder per project under `/opt/junkyard/staging/<project>` with its own compose file and its own
  network; the template shows the pattern: the app on `127.0.0.1:<port>`, a hostname `<project>.DOMAIN` behind
  Access (or public if they want to show a client, with the owner's yes), its database found by the nightly copy.
- Deploys: the owner's CI or a `git pull && docker compose up -d --build` you write for them; no SSH from the
  internet is ever opened for this.
