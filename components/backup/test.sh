#!/bin/sh
# Tests jc-backup for real inside a throwaway Docker-in-Docker container (never on the host):
#   docker run --rm --privileged -v "$PWD":/t:ro docker:29-dind sh /t/test.sh
set -eu
export DOCKER_HOST=unix:///var/run/docker.sock DOCKER_TLS_CERTDIR=
apk add --no-cache bash rsync python3 curl coreutils findutils util-linux iproute2 >/dev/null
dockerd >/var/log/dockerd.log 2>&1 &
for i in $(seq 1 60); do docker info >/dev/null 2>&1 && break; sleep 1; done
mkdir -p /usr/local/bin /etc/junkyard
cp /t/jc-backup /usr/local/bin/jc-backup && chmod 755 /usr/local/bin/jc-backup
printf '#!/bin/sh\necho "$1|$2|$3" >> /tmp/notified\n' > /usr/local/bin/jc-notify && chmod 755 /usr/local/bin/jc-notify
cat > /etc/junkyard/backup.conf <<'EOF'
BACKUP_ROOT=/backups
STATUS_DIR=/backups/status
KEEP_DAYS=3
REQUIRED_DBS="pg"
FILES="/opt"
MUST_HAVE="/opt/app"
EXCLUDE="*.log"
SKIP_VOLUMES="cachevol"
EOF
pass=0
ok() { pass=$((pass + 1)); echo "  ok   $1"; }
no() { echo "  FAIL $1"; tail -20 /backups/nightly/logs/backup.log 2>/dev/null; exit 1; }

docker run -d --name pg -v /srv/pg:/var/lib/postgresql/data -e POSTGRES_PASSWORD=pw postgres:16-alpine >/dev/null
docker run -d --name maria -v /srv/my:/var/lib/mysql -e MARIADB_ROOT_PASSWORD=rootpw -e MARIADB_DATABASE=shop \
  -e MARIADB_USER=shop -e MARIADB_PASSWORD=shoppw mariadb:11.8 >/dev/null
docker run -d --name app -v appvol:/data -v cachevol:/cache alpine:3.22 sh -c 'echo hello > /data/hello.txt; echo junk > /cache/x; sleep 1d' >/dev/null
docker run -d --name client postgres:16-alpine sleep 1d >/dev/null       # a postgres image with no database: not dumped
for i in $(seq 1 90); do
  docker exec pg pg_isready -q -U postgres 2>/dev/null && docker exec maria mariadb -ushop -pshoppw shop -e "select 1" >/dev/null 2>&1 && break
  sleep 2
done
docker exec pg psql -q -U postgres -c "CREATE TABLE notes(t text); INSERT INTO notes VALUES ('Ali owes 500');"
docker exec maria mariadb -ushop -pshoppw shop -e "CREATE TABLE orders(id int); INSERT INTO orders VALUES (42);"
mkdir -p /opt/app
python3 -c "import sqlite3; c=sqlite3.connect('/opt/app/vault.sqlite3'); c.execute('create table k(v)'); c.execute(\"insert into k values ('secret')\"); c.commit()"
echo "settings" > /opt/app/settings.txt
echo "noise" > /opt/app/debug.log

echo "jc-backup:"
for d in 2026-01-01 2026-01-02 2026-01-03 2026-01-04; do JC_DAY=$d jc-backup; done
N=/backups/nightly
[ "$(ls -1d $N/20??-??-?? | wc -l)" = 3 ] && [ ! -d $N/2026-01-01 ] && ok "keeps the newest 3 copies" || no "retention"
zcat $N/2026-01-04/databases/pg.sql.gz | grep -q "Ali owes 500" && ok "postgres dumped with its data" || no "postgres dump"
zcat $N/2026-01-04/databases/maria.sql.gz | tr -d '\n' | grep -q "INSERT INTO \`orders\` VALUES *(42)" && ok "mariadb dumped with its data" || no "mariadb dump"
[ ! -e $N/2026-01-04/databases/client.sql.gz ] && ok "a postgres image with no database is skipped" || no "client skipped"
python3 -c "import sqlite3; print(sqlite3.connect('$N/2026-01-04/sqlite/opt/app/vault.sqlite3').execute('select v from k').fetchone()[0])" | grep -q secret \
  && ok "sqlite copied while open" || no "sqlite copy"
[ -f $N/2026-01-04/files/opt/app/settings.txt ] && [ ! -e $N/2026-01-04/files/opt/app/debug.log ] && ok "files copied, excluded ones left out" || no "files"
[ ! -e $N/2026-01-04/files/srv ] && ok "raw database folders not copied" || no "raw db folders"
V=$(ls -1d $N/2026-01-04/files/docker-volumes/*appvol 2>/dev/null | head -1)
[ -n "$V" ] && grep -q hello "$V/hello.txt" && ok "docker volume copied" || no "volume"
! ls $N/2026-01-04/files/docker-volumes | grep -q cachevol && ok "cache volume skipped" || no "cache volume"
[ "$(stat -c %i $N/2026-01-03/files/opt/app/settings.txt)" = "$(stat -c %i $N/2026-01-04/files/opt/app/settings.txt)" ] \
  && ok "unchanged files are hard links (no extra space)" || no "hard links"
grep -q '"status":"OK"' /backups/status/nightly.json && ok "status card says OK" || no "status"
[ ! -e /tmp/notified ] && ok "no alert when all is well" || no "unexpected alert"

docker run -d --name newdb -v /srv/new:/var/lib/postgresql/data -e POSTGRES_PASSWORD=pw postgres:16-alpine >/dev/null
for i in $(seq 1 60); do docker exec newdb pg_isready -q -U postgres 2>/dev/null && break; sleep 2; done
sleep 3
JC_DAY=2026-01-05 jc-backup
[ -s $N/2026-01-05/databases/newdb.sql.gz ] && ok "a new database is found and dumped by itself" || no "new db"

docker stop pg >/dev/null
if JC_DAY=2026-01-06 jc-backup; then no "ran without a required database"; fi
grep -q '"status":"FAILED: database pg was not dumped' /backups/status/nightly.json && ok "missing required database fails the copy" || no "fail status"
grep -q "Nightly backup failed" /tmp/notified && ok "the owner is alerted" || no "alert"
[ "$(ls -1d $N/20??-??-?? | wc -l)" -ge 3 ] && [ -d $N/2026-01-05 ] && ok "older copies untouched after a failure" || no "kept after failure"

echo "jc-offsite:"
apk add --no-cache restic >/dev/null
for f in jc-offsite jc-backup-status; do cp /t/$f /usr/local/bin/$f && chmod 755 /usr/local/bin/$f; done
mkdir -p /root/.restic
printf 'export RESTIC_REPOSITORY=/repo
export RESTIC_PASSWORD=test-repo-password
' > /root/.restic/offsite.env
. /root/.restic/offsite.env && restic init -q
cat >> /etc/junkyard/backup.conf <<'EOF'
OFFSITE_ENV=/root/.restic/offsite.env
OFFSITE_PATHS="/backups/nightly /opt /does-not-exist"
OFFSITE_EXCLUDE="/opt/app/debug.log"
EOF
rm -f /tmp/notified
FORCE_CHECK=1 jc-offsite
grep -q '"status":"OK"' /backups/status/offsite.json && ok "off-site copy made and checked" || no "offsite status"
restic restore -q latest --target /tmp/restored --include /opt/app/settings.txt
cmp -s /tmp/restored/opt/app/settings.txt /opt/app/settings.txt && ok "a file comes back identical from the copy" || no "restore"
restic ls latest | grep -q "/opt/app/debug.log" && no "excluded file was copied" || ok "excluded files stay out"
[ ! -e /tmp/notified ] && ok "no alert when all is well" || no "unexpected alert"
printf 'export RESTIC_REPOSITORY=/nowhere
export RESTIC_PASSWORD=x
' > /root/.restic/offsite.env
jc-offsite || true
grep -q '"status":"FAILED' /backups/status/offsite.json && grep -q "Off-site backup" /tmp/notified   && ok "a broken off-site copy is reported" || no "offsite failure"
echo "OK: $pass checks passed"
