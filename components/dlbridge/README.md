# dlbridge (downloads)

Three containers: `aria2` (files, torrents, magnets; 8 connections per file, resumes after restarts),
`web` (the AriaNg panel behind nginx), and `dlbridge` (between n8n and aria2, plus yt-dlp for video sites).

- links are sorted by kind: magnet or `.torrent` → `Torrents`, a file extension → `Files`, a video site that
  yt-dlp knows → `Videos` (mp4), `kind: audio` → `Audio` (mp3 320k, only when the owner asks for the sound)
- video sites are downloaded by yt-dlp itself, not aria2: YouTube slows other downloaders down a lot
  (measured: aria2 5.5 MB/s with 16 connections, yt-dlp about 12 MB/s). So videos are not in the panel;
  the owner gets "started" (with the full size) and "finished" messages instead
- a server that refuses 8 connections (429) gets the same file again with 2, then 1, from where it stopped;
  the owner hears only about the final result
- links to internal addresses are refused (the firewall also blocks them)
- an alert when the downloads folder passes `ALERT_GB`, repeated daily while above, re-armed below 90%

## Endpoints (header `X-Bridge-Key`, except `/health` and `/status`)

| Endpoint | Body | |
|---|---|---|
| `POST /add` | `{url, kind: auto|file|torrent|video|audio}` | starts a download |
| `GET /list` | | running, waiting and recent downloads |
| `POST /control` | `{id}` or `{match: "part of the name"}`, `{action: pause|resume|cancel}` | |
| `GET /usage` | | folder size and free space |
| `GET /status` | | numbers only, for the home page card |

## Settings

`BRIDGE_KEY`, `ARIA2_SECRET`, `ARIA2_URL`, `NOTIFY_URL`, `NOTIFY_SECRET`, `NOTIFY_CHANNELS` (empty = by priority),
`LANG_CODE` (`en`, `ar`), `ALERT_GB` (500), `VIDEO_JOBS` (2), `DOWNLOAD_ROOT` (`/downloads`), `DATA_DIR` (`/data`), `TZ`.

## Tests

`python -m unittest test_dlbridge` (no network, aria2 or yt-dlp needed).
