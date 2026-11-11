# webtool (web search and page reading)

SearXNG for search and a headless Chromium for reading pages, for the assistant's `web_search` and `web_read`.
The assistant must never be steered by what it reads, so there are five layers:

1. the network: the containers reach the public internet only (`jc-isolate webtool`)
2. every request the browser makes (redirects, scripts, popups) must go to a public address on port 80/443;
   the owner's own domains (`DENY_DOMAINS`) and own public IPs (`DENY_RESOLVE_HOSTS`, refreshed every 10 minutes)
   are refused
3. `/read` opens a link only if the owner wrote its domain in their message, or the exact link came back from a
   search or a page in the same n8n run (`exec_id`), so the model cannot build a link that carries data out
4. what comes back is visible text only, hidden characters removed, wrapped between random markers as
   untrusted data
5. in n8n: once a run has read from the web, every other tool is locked for that run (Guarded Action)

Endpoints (header `X-Webtool-Key`): `POST /search {q, exec_id}`, `POST /read {url, exec_id, user_text, max_links}`,
`GET /health`. Settings: `WEBTOOL_KEY`, `OWNER_NAME`, `SEARX_URL`, `DENY_DOMAINS`, `DENY_RESOLVE_HOSTS`,
`MAX_CHARS`, `MAX_LINKS`, `NAV_TIMEOUT_MS`, `DATA_DIR`. `searxng/settings.yml` gets a fresh `secret_key` per server.

Tests: `python -m unittest test_webtool` (no browser or network needed).
