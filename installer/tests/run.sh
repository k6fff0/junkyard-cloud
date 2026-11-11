#!/bin/sh
# End-to-end test of the installer on a throwaway stack. Run on a Docker host from a copy of the repo:
#   sh installer/tests/run.sh
# Cleans up everything it started, even when a step fails.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../.." && pwd)
WORK=$(mktemp -d)
cleanup() {
  if [ "${KEEP:-}" = 1 ]; then echo "KEEP=1: stack left running, work files in $WORK"; return; fi
  cd "$HERE" && docker compose down -v --rmi local >/dev/null 2>&1 || true; rm -rf "$WORK" "$HERE/filebridge"; }
trap cleanup EXIT
cp -r "$REPO/components/filebridge" "$HERE/filebridge"
cd "$HERE"
docker compose up -d --build >/dev/null 2>&1
echo "waiting for n8n..."
for i in $(seq 1 120); do curl -s http://127.0.0.1:15679/rest/settings | grep -q '"data"' && break; sleep 2; done
docker compose exec -T db psql -q -U jc -d assistant < "$REPO/workflows/schema.sql"
docker compose exec -T db psql -q -U jc -d assistant < "$REPO/workflows/schema.sql" 2>/dev/null   # safe to run twice
printf 'Owner-pass-1234567890' > "$WORK/pw"
python3 "$REPO/installer/jc_n8n.py" bootstrap --n8n http://127.0.0.1:15679 --email owner@example.com \
  --password-file "$WORK/pw" --out "$WORK/key"
ssh-keygen -q -t ed25519 -N '' -f "$WORK/ops" >/dev/null
python3 "$HERE/make_config.py" "$WORK"
I="python3 $REPO/installer/jc_n8n.py"
$I install --config "$WORK/config.json" --secrets "$WORK/secrets.json" --state "$WORK/state.json" --key-file "$WORK/key"
echo "--- second run (must only update)"
$I install --config "$WORK/config.json" --secrets "$WORK/secrets.json" --state "$WORK/state.json" --key-file "$WORK/key" | tail -1
$I status --config "$WORK/config.json" --state "$WORK/state.json" --key-file "$WORK/key" > "$WORK/status.txt" || { cat "$WORK/status.txt"; exit 1; }
echo "all workflows active: $(wc -l < "$WORK/status.txt")"
python3 "$HERE/scenarios.py" "$WORK"
