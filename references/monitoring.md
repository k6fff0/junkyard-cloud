# Step 6: monitoring and the dashboard

## Uptime Kuma (`templates/compose/uptime-kuma`)

Host network, listening on `127.0.0.1:3002`, behind Access at `uptime.DOMAIN`. Everything below is done by
`tools/kuma-setup.py` with no browser (Kuma 2.x has no REST API; the script speaks its socket.io), and is safe to
run again when services are added:

1. Put `kuma_admin_password` in the secrets file (generate it like the others) and write `/etc/junkyard/kuma.json`:
   `{"url": "http://127.0.0.1:3002", "user": "admin", "notify_url": "http://127.0.0.1:5678/webhook/uptime",
   "monitors": [{"name": "Passwords", "url": "http://127.0.0.1:8222"}, ...]}`: one monitor per service on its
   local address (`network.md`), named as the owner should read it in an alert.
2. Run it (a throwaway container, nothing installed on the server):
   ```
   sudo docker run --rm --network host -v /opt/junkyard/src/tools:/t:ro -v /etc/junkyard:/j:ro python:3.14.10-slim \
     sh -c "pip install -q 'python-socketio[client]==5.13.0' && python /t/kuma-setup.py /j/kuma.json /j/secrets.json"
   ```
   It makes the admin account, a **Webhook** notification to the assistant (header `X-Notify-Secret`, default for
   every monitor) and the monitors (HTTP, every minute, accepted 200-399). Until the assistant exists the alerts
   go nowhere: run it again after step 8, or add Kuma's own email notification in its page.
3. The owner's own important sites can be added the same way; the critical ones also go into `call_monitors` in
   the config: when such a site stays down 3 minutes, the assistant phones the owner (calls module).
4. A "push" monitor fed by the nightly backup is not needed: the backup scripts alert by themselves.

Check: stop a test container, see the message arrive, start it, see the "back" message.

## Homepage (`templates/compose/homepage`)

One page with every service, status dots where they can work, and the backup cards. Behind Access at `home.DOMAIN`.

- `services.yaml`: one entry per installed service, `href` = the public URL. A status dot (`siteMonitor`) only
  for services published on `172.17.0.1` (`network.md`: n8n `5678/healthz`, Paperless `8010`, Karakeep `3010`,
  Jellyfin `8096`); a container cannot reach the server's `127.0.0.1`, so services published there only get no
  dot, and Uptime Kuma (which checks everything and alerts in chat) has its own entry on the page.
- Backup cards read the status JSON files through a tiny static server in the same compose (`homepage-status`,
  no published port): Homepage's `customapi` widget reads `http://homepage-status:8080/<name>.json`, fields
  `status`, `finished`, `size`, `snapshots`. (Not `172.17.0.1`: from the container's own network that address
  goes to the host, where ufw drops it; every card showed an error that way.)
- `settings.yaml`: title, the owner's language, `layout` with the groups Apps, Backups, Server health.
- Never put a cards group with numbers inside the Apps group: on phones, Homepage makes a group that holds a
  number widget one column wide, and the whole Apps grid collapses (it happened).

Check on a phone and on a computer: every dot green, every backup card "OK" with a date from last night.
