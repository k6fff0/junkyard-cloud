#!/bin/sh
# Installs the secret check as this clone's pre-commit hook.
cd "$(git rev-parse --show-toplevel)"
printf '#!/bin/sh\nexec sh tools/check-secrets.sh\n' > .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit
echo "pre-commit secret check installed"
