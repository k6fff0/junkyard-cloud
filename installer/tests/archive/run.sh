#!/bin/sh
# The installer's archive setup against a real Paperless (the pinned version), not a fake one:
#   sh installer/tests/archive/run.sh
# Proves that the limited assistant user can see and use what the installer made, and that the file bridge gets
# its token. Cleans up everything it started.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
WORK=$(mktemp -d)
cleanup() { cd "$HERE" && docker compose down -v >/dev/null 2>&1 || true; rm -rf "$WORK"; }
trap cleanup EXIT
cd "$HERE"
docker compose up -d >/dev/null 2>&1
echo "waiting for Paperless..."
for i in $(seq 1 150); do
  curl -sf -o /dev/null -X POST -d username=admin -d password=Admin-test-pass-123 http://127.0.0.1:18010/api/token/ && break
  sleep 2
done
python3 "$HERE/check.py" "$WORK"
