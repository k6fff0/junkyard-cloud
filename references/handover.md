# Step 9: prove it, then hand over

## The final check (all of it, and write down the results)

1. `sudo reboot`, then: every container up (`docker ps` shows no restarting), `cloudflared` active, every
   `jc-isolate@*` active, `installer/jc_n8n.py status` all active. A server that only works until the next
   power cut is not done.
2. From outside (mobile data): each hostname loads, protected ones ask for the email code.
3. Backups: last night's cards OK, or run them now (`backups.md`, prove it).
4. Isolation: the two checks in `network.md` for each isolated network.
5. Monitoring: stop one container, get the message, start it, get the "back" message.
6. The assistant: the table in `assistant.md` section 8, with the owner, from their phone.
7. Updates: `unattended-upgrades` active, and `docker compose pull` is never automatic.

## /root/JUNKYARD.md (and a copy for the owner)

Write it in the owner's language, for someone who does not remember any of this:

- what runs: each service, its address, who can open it, where its data is, its version
- the domain, the tunnel name, the Access app and policy, service tokens and their renewal dates
- where the secrets are (`/etc/junkyard/secrets.json`, mode 600) and that a copy must be in their password manager
  (n8n encryption key, restic password, Vaultwarden admin, Paperless admin, n8n owner)
- backups: what, when, where, how many, and **how to restore**:
  - a broken service: stop it, restore its files from `nightly/<date>/files`, load its dump, start it
  - a deleted file: `restic restore` from the local or off-site repository
  - a dead system disk: new disk, Ubuntu live USB, restic restore of the `system` snapshot with the saved layout
    (`/var/backups/jc-layout`), reinstall the boot loader, reboot, then `docker compose up -d --build` in every
    `/opt/junkyard/<service>` (the image holds no Docker images); write the exact commands for this machine
  - a dead house: a new machine, Ubuntu, restic with the off-site env and password, restore, start
- the assistant: its numbers, models, modules, how to re-pair WhatsApp, how to change a key
  (`--update-credentials`), how to turn a module on or off (config, then `install`)
- what is left to do and what the owner must do themselves (2FA, Recovery Code on paper, phone app headers)

Keep the last section honest: anything not tested from the owner's phone is listed as not yet confirmed.
