# Later: updating and removing

Read `/root/JUNKYARD.md` on the server first: it says what was installed, and where.

## Update the skill's code on the server

The server keeps its own copy of this repository in `/opt/junkyard/src`.

```
sudo git -C /opt/junkyard/src pull
cd /opt/junkyard/src && git log --oneline -20          # tell the owner what changed, in plain words
```

Then bring what changed into service, and nothing else:

| Changed | Do |
|---|---|
| `workflows/` or `installer/` | `sudo python3 installer/jc_n8n.py install --config /etc/junkyard/config.json --secrets /etc/junkyard/secrets.json`, then `status` |
| `components/<name>` | in the service folder that builds it: `docker compose up -d --build` |
| `components/backup`, `ops`, `isolate` scripts | `sudo install -m 755` them again to `/usr/local/sbin/` (as in their step) |
| `templates/compose/<name>` | compare with `/opt/junkyard/<name>/compose.yml` and copy the change by hand: the live file has the owner's values |
| `references/` | nothing to run; read what is new |

## Update a service's version

One service at a time, never all at once, never automatically:

1. Read its release notes from the current version to the new one (breaking changes, database migrations).
2. Run the nightly backup now (`sudo jc-backup`) and check it says OK.
3. Change the pinned version in `/opt/junkyard/<name>/compose.yml`, then `docker compose pull && docker compose up -d`.
4. Check it as in its step (`services.md`), and its monitor goes green. If it fails, put the old version back and
   start it again; restore its data from last night's copy only if the new version changed the data.
5. Write the new version in `/root/JUNKYARD.md`.

Ubuntu's security updates install themselves (`unattended-upgrades`). Reboot when `/var/run/reboot-required`
exists, at a time the owner chooses, and run the final check of `handover.md` after it.

## Remove one service

Ask the owner first, and say whether its data stays (the default) or goes.

1. Its Cloudflare route, DNS record and Access application (`cloudflare.md`), its Uptime Kuma monitor, its
   dashboard entry, its database from `REQUIRED_DBS`, its `jc-isolate@<name>` unit (`systemctl disable --now`),
   and its assistant module (`config.json` → `modules`, then `installer/jc_n8n.py install`).
2. `cd /opt/junkyard/<name> && docker compose down` (add `--rmi all` to free the images).
3. Its data on `/mnt/storage` is deleted only after a fresh backup and the owner's explicit yes; tell them the
   nightly copies of it disappear after 3 nights, and the off-site copy after the next `restic forget`.

## Remove everything

Only on the owner's explicit request, with a fresh off-site backup they have proved they can restore. In this
order, so the server is never open while half removed:

1. Cloudflare: delete the tunnel's routes, the DNS records, the Access applications and service tokens, then the
   tunnel; `sudo cloudflared service uninstall`.
2. Every service: `docker compose down --rmi all` in each `/opt/junkyard/<name>` (the assistant last).
3. The server's own parts:
   ```
   for u in $(systemctl list-units --all --plain --no-legend 'jc-isolate@*' | awk '{print $1}'); do
     sudo systemctl disable --now "$u"; done
   sudo rm -f /etc/systemd/system/jc-isolate@.service /etc/cron.d/jc-backup /etc/cron.d/jc-ops \
     /usr/local/sbin/jc-backup /usr/local/sbin/jc-snapshot /usr/local/sbin/jc-offsite \
     /usr/local/sbin/jc-backup-status /usr/local/sbin/jc-notify /usr/local/sbin/jc-ops /usr/local/sbin/jc-isolate
   sudo sed -i '/n8n-jc-ops/d' /root/.ssh/authorized_keys      # the assistant's restricted key
   sudo systemctl daemon-reload
   docker network rm assistant                                 # the one network made by hand (network.md)
   ```
4. `/etc/junkyard` holds every secret: copy it to the owner's password manager if they want it, then delete it.
5. The data on `/mnt/storage` and the R2 bucket stay until the owner deletes them themselves: they are their
   photos and documents, and the last copy of them.

Ubuntu, Docker, the firewall and SSH keys stay: they are a normal, safe machine without this skill.
