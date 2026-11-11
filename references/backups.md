# Step 5: backups (set them up before any real data arrives)

Three copies, three disasters (details in `components/backup/README.md`):

| Copy | Script | When | Where |
|---|---|---|---|
| nightly: every database dump, SQLite file, config and volume; 3 days | `jc-backup` | 03:00 | `/mnt/storage/backups/nightly` |
| system disk image (boot a new disk as before); one copy | `jc-snapshot` | every 3 days | local restic repo on the big disk |
| off-site, encrypted: nightly dumps, photos, documents | `jc-offsite` | 05:30 | Cloudflare R2 (restic) |

## Install

```
S=/opt/junkyard/src/components/backup
for f in jc-backup jc-snapshot jc-offsite jc-backup-status jc-notify; do sudo install -m 755 $S/$f /usr/local/sbin/; done
sudo install -m 600 $S/backup.conf.example /etc/junkyard/backup.conf      # then edit it
sudo install -m 644 $S/jc-backup.cron /etc/cron.d/jc-backup
```

Always `install -m 755` (or `chmod 755` after a `mv`): a script that lost its execute bit makes cron skip it
silently, and nobody is told (it happened, see `lessons.md`).

Edit `/etc/junkyard/backup.conf`: `REQUIRED_DBS` = the database containers that exist now (n8n's Postgres,
Immich, Paperless...), `MUST_HAVE`, `LANG_CODE`, the paths.

## restic repositories

Two repositories, one password, generated and saved in the secrets file and the owner's password manager.
**Without that password the copies can never be read.** Say this to the owner plainly.

```
sudo install -d -m 700 /root/.restic
# local (system disk image)
printf 'export RESTIC_REPOSITORY=/mnt/storage/backups/restic-local\nexport RESTIC_PASSWORD_FILE=/root/.restic/password\n' \
  | sudo tee /root/.restic/local.env >/dev/null
# off-site: an R2 bucket and an API token limited to that bucket (Object Read & Write), made by the owner or with the API
printf 'export RESTIC_REPOSITORY=s3:https://<ACCOUNT>.r2.cloudflarestorage.com/<bucket>\nexport AWS_ACCESS_KEY_ID=...\nexport AWS_SECRET_ACCESS_KEY=...\nexport RESTIC_PASSWORD_FILE=/root/.restic/password\n' \
  | sudo tee /root/.restic/offsite.env >/dev/null
sudo chmod 600 /root/.restic/*; . /root/.restic/local.env && restic init; . /root/.restic/offsite.env && restic init
```

R2 is free up to 10 GB, then about 0.015 USD per GB-month; tell the owner the expected size (photos dominate).
Big replaceable things never go off-site: downloads, media, caches, thumbnails.

## Prove it (all of these, not some)

1. `sudo jc-backup && cat /mnt/storage/backups/status/nightly.json` → `OK`; open the newest folder: a dump per
   database, the SQLite files, `/opt/junkyard` under `files/`.
2. Restore test of the nightly copy: load one dump into a throwaway container and count rows:
   `docker run --rm -d --name rt -e POSTGRES_PASSWORD=x postgres:16 ... ; zcat <dump> | docker exec -i rt psql -U postgres`.
3. `sudo FORCE=1 jc-snapshot` → `snapshot.json` OK; `restic snapshots --tag system` shows one.
4. `sudo FORCE_CHECK=1 jc-offsite` → `offsite.json` OK; restore one small file from R2 and compare it.
5. Break it on purpose once: stop a required database, run `jc-backup`, check the owner got the alert, start it again.
6. The full restore of a dead system disk is written in the handover (`handover.md`, section restore); walk
   through it in a VM if the owner wants proof, never on their real disks.

Write the restic password, the bucket name and the restore steps into `/root/JUNKYARD.md` and tell the owner to
keep a copy outside the server.
