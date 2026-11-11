#!/bin/sh
# Refuses secrets in the repository. Used as a git pre-commit hook (tools/install-hooks.sh) and in CI.
# Looks at the staged files (or every tracked file with --all) for real-looking keys and tokens.
set -eu
if [ "${1:-}" = "--all" ]; then FILES=$(git ls-files); else FILES=$(git diff --cached --name-only --diff-filter=ACM); fi
[ -n "$FILES" ] || exit 0
PATTERNS='sk-(proj-|svcacct-|admin-)?[A-Za-z0-9_-]{20,}|sk-ant-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|xox[abp]-[A-Za-z0-9-]{20,}|[0-9]{8,10}:AA[A-Za-z0-9_-]{30,}|eyJhbGciOi[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}|-----BEGIN [A-Z ]*PRIVATE KEY-----$|-----BEGIN [A-Z ]*PRIVATE KEY-----\\n[A-Za-z0-9+/]{20}|AC[0-9a-f]{32}'
found=0
for f in $FILES; do
  [ -f "$f" ] || continue
  if grep -I -n -E "$PATTERNS" "$f" >/tmp/jc-secret-hits.$$ 2>/dev/null; then
    echo "possible secret in $f:"; sed -E 's/(.{0,20}).*/  \1.../' /tmp/jc-secret-hits.$$
    found=1
  fi
done
rm -f /tmp/jc-secret-hits.$$
[ $found = 0 ] || { echo "commit refused: remove the secret (keep secrets in /etc/junkyard/secrets.json, never in git)"; exit 1; }
