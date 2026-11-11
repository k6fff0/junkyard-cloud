#!/bin/sh
# Tests jc-isolate inside a throwaway privileged container, never on the real server firewall:
#   docker run --rm --privileged -v "$PWD":/t:ro alpine:3.22 sh /t/test.sh
set -eu
apk add --no-cache iptables >/dev/null
iptables -N DOCKER-USER
export JC_ISOLATE_DIR=/tmp/conf
mkdir -p $JC_ISOLATE_DIR
cp /t/examples/*.conf $JC_ISOLATE_DIR/
J="sh /t/jc-isolate"
pass=0
ok() { pass=$((pass + 1)); }
no() { echo "FAIL: $*"; iptables -S; exit 1; }
count() { iptables -S "$1" | grep -c -- "$2" || true; }

# 1. downloads: the bridge container alone may reach n8n; running twice adds nothing
$J downloads >/dev/null && $J downloads >/dev/null
[ "$(count DOCKER-USER '-i br-downloads -j JC-DOWNLOADS')" = 1 ] && ok || no "one jump from DOCKER-USER"
[ "$(count JC-DOWNLOADS '-d 172.30.113.0/24 -j RETURN')" = 1 ] && ok || no "own network allowed"
[ "$(count JC-DOWNLOADS '-s 172.30.113.10/32 -p tcp -m conntrack --ctorigdst 172.17.0.1 --ctorigdstport 5678 -j RETURN')" = 1 ] && ok || no "bridge to n8n"
[ "$(count JC-DOWNLOADS '-j DROP')" = 10 ] && ok || no "10 private ranges dropped"
[ "$(iptables -S JC-DOWNLOADS | tail -1)" = "-A JC-DOWNLOADS -j RETURN" ] && ok || no "internet allowed last"
[ "$(count INPUT '-i br-downloads -m conntrack --ctstate NEW -j DROP')" = 1 ] && ok || no "server closed"
[ "$(count INPUT '-s 172.30.113.10/32 -i br-downloads -p tcp -m tcp --dport 5678')" = 1 ] && ok || no "n8n open for the bridge"
first=$(iptables -S INPUT | grep -n 'br-downloads' | head -1)
echo "$first" | grep -q ACCEPT && ok || no "the exception comes before the drop"

# 2. mailwatch: any of its containers may reach n8n
$J mailwatch >/dev/null
[ "$(count INPUT '-i br-mailwatch -p tcp -m tcp --dport 5678 -m conntrack --ctstate NEW -j ACCEPT')" = 1 ] && ok || no "mail to n8n"
[ "$(count JC-MAILWATCH '--ctorigdst 172.17.0.1 --ctorigdstport 5678 -j RETURN')" = 1 ] && ok || no "mail via DNAT"

# 3. webtool: no exception at all
$J webtool >/dev/null
[ "$(count INPUT '-i br-webtool .*ACCEPT')" = 0 ] && ok || no "web reader has no way to the server"
[ "$(count JC-WEBTOOL 'ctorigdst')" = 0 ] && ok || no "web reader has no exception"

# 4. bad settings are refused before any rule is written
printf 'BRIDGE="br-x;reboot"\n' > $JC_ISOLATE_DIR/bad1.conf
printf 'BRIDGE=br-x\nGATEWAY=172.30.9.1\nALLOW_HOST="172.30.9.5:56789x"\n' > $JC_ISOLATE_DIR/bad2.conf
printf 'BRIDGE=br-x\nALLOW_HOST="any:5678"\n' > $JC_ISOLATE_DIR/bad3.conf
for n in bad1 bad2 bad3 "../etc" missing; do
  if $J "$n" 2>/dev/null; then no "accepted bad settings: $n"; else ok; fi
done
iptables -S | grep -q 'br-x' && no "rules written for bad settings" || ok

# 5. without Docker's chain it stops with a clear reason
iptables -F DOCKER-USER
for c in JC-DOWNLOADS JC-MAILWATCH JC-WEBTOOL; do iptables -F $c; iptables -X $c; done
iptables -X DOCKER-USER
msg=$($J webtool 2>&1) && no "ran without DOCKER-USER" || true
echo "$msg" | grep -q "start Docker first" && ok || no "clear message: $msg"

echo "OK: $pass checks passed"
