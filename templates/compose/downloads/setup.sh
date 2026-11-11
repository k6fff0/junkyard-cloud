#!/bin/sh
# Puts the AriaNg panel in ./web/ariang (checked by SHA-256) and makes it connect to aria2 by itself on first open.
# Safe to run again. Needs .env (ARIA2_SECRET).
set -eu
cd "$(dirname "$0")"
VERSION=1.3.15
SHA256=d2317e441966ad31f1e342cb6a6cc1c51808fb0a10cf6e39cb30b0517b3e7823
. ./.env
TMP=$(mktemp -d)
curl -fsSL -o "$TMP/ariang.zip" "https://github.com/mayswind/AriaNg/releases/download/$VERSION/AriaNg-$VERSION.zip"
echo "$SHA256  $TMP/ariang.zip" | sha256sum -c -
rm -rf web/ariang && mkdir -p web/ariang && (cd web/ariang && python3 -m zipfile -e "$TMP/ariang.zip" .)
rm -rf "$TMP"
# the panel is behind Access; this sets its RPC address and secret once per browser
SECRET_B64=$(printf '%s' "$ARIA2_SECRET" | base64 | tr -d '\n=' | tr '+/' '-_')
cat > web/ariang/jc-defaults.js <<JS
(function () {
  try {
    if (localStorage.getItem('jc.preset') !== '1') {
      localStorage.setItem('jc.preset', '1');
      location.hash = '#!/settings/rpc/set/https/' + location.hostname + '/443/jsonrpc/$SECRET_B64';
    }
  } catch (e) {}
})();
JS
grep -q jc-defaults.js web/ariang/index.html || sed -i 's|</head>|<script src="jc-defaults.js"></script></head>|' web/ariang/index.html
mkdir -p data/aria2 data/bridge
echo "AriaNg $VERSION ready"
