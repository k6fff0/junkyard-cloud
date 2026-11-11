# Step 6: monitoring and the dashboard

## Uptime Kuma (`templates/compose/uptime-kuma`)

Host network, listening on `127.0.0.1:3002`, behind Access at `uptime.DOMAIN`. Create the admin account in the
browser (the owner's password manager keeps it). Then:

1. A notification of type **Webhook**: URL `http://127.0.0.1:5678/webhook/uptime`, method POST, body "Preset -
   application/json", additional header `{"X-Notify-Secret": "<notify_secret>"}`. Set it as default for new
   monitors. (Until the assistant is installed, use Kuma's own email or Telegram notification instead.)
2. Monitors: every public hostname (HTTP, expect 200 or the Access 302: use "Accepted status codes" 200-399),
   the owner's own important sites, and for the critical ones add them to `call_monitors` in the config: when
   such a site stays down 3 minutes, the assistant phones the owner (calls module).
3. A "push" monitor fed by the nightly backup is not needed: the backup scripts alert by themselves.

Check: stop a test container, see the message arrive, start it, see the "back" message.

## Homepage (`templates/compose/homepage`)

One page with every service, a status dot for each, and the backup cards. Behind Access at `home.DOMAIN`.

- `services.yaml`: one entry per installed service, `href` = the public URL, `siteMonitor` = the internal
  address from `network.md` (`http://172.17.0.1:<port>`; Homepage runs on the default bridge and reaches the
  `docker0` address).
- Backup cards read the status JSON files through a tiny static server (the compose template mounts
  `/mnt/storage/backups/status` into nginx on `127.0.0.1:8091` and Homepage's `customapi` widget reads
  `http://172.17.0.1:8091/<name>.json`, fields `status`, `finished`, `size`, `snapshots`).
- `settings.yaml`: title, the owner's language, `layout` with the groups Apps, Backups, Server health.
- Never put a cards group with numbers inside the Apps group: on phones, Homepage makes a group that holds a
  number widget one column wide, and the whole Apps grid collapses (it happened).

Check on a phone and on a computer: every dot green, every backup card "OK" with a date from last night.
