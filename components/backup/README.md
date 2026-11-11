# backup

Three copies, each answering a different disaster:

| Script | When | What | Answers |
|---|---|---|---|
| `jc-backup` | nightly 03:00 | dumps of every database, SQLite copies, files and volumes, onto the big disk; 3 days kept | "I broke something yesterday" |
| `jc-snapshot` | every 3 days | one image of the whole system disk (with its layout) in a local restic repository | "the system disk died" |
| `jc-offsite` | nightly 05:30 | encrypted copy of the nightly dumps, photos and documents to Cloudflare R2 (restic) | "the house burned / the big disk died" |

- databases are found by themselves: every running Postgres / MySQL / MariaDB container with its data in
  `/var/lib/postgresql` or `/var/lib/mysql` is dumped consistently while it runs, and the dump is checked
- an old copy is deleted only after the new one passed every check; on failure the owner is told (`jc-notify`)
  and the older copies are untouched
- unchanged files are hard links to yesterday's copy, so a day costs only what changed
- every script writes a small status JSON for the home page cards
- `jc-offsite` reads back 1/20 of the data every Sunday to prove the copy can be restored

Settings: `/etc/junkyard/backup.conf` (see `backup.conf.example`); restic keys in `/root/.restic/*.env` (mode 600).
Without the restic repository password the copies can never be read: keep it outside the server too.

Tests (in a throwaway Docker-in-Docker container, never on the host):
`docker run --rm --privileged -v "$PWD":/t:ro docker:29-dind sh /t/test.sh` (21 checks: Postgres, MariaDB, a new
database found by itself, SQLite, volumes, hard links, retention, failure alerts, off-site copy and restore).
