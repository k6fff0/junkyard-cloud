# Step 3: domain and protection (Cloudflare)

The server makes one outgoing connection to Cloudflare (a named tunnel); Cloudflare sends each hostname down it.
No router port is opened, the home IP can change, and Cloudflare Access asks for an email code before any page
of the server loads.

## How you work with Cloudflare

Prefer the API with a token the owner creates for you (My Profile → API Tokens → Create Token → Custom):

| Permission | Why |
|---|---|
| Account · Cloudflare Tunnel · Edit | create the tunnel and its routes |
| Account · Access: Apps and Policies · Edit | Access applications and policies |
| Account · Access: Service Tokens · Edit | tokens for phone apps |
| Account · Access: Organizations, Identity Providers, and Groups · Edit | the email-code login method |
| Zone · DNS · Edit (their domain only) | one CNAME per service |
| Zone · Zone WAF · Edit (their domain only) | country rules for the few public services |

Store it as `cloudflare_api_token` in the secrets file. The API changes over time: **before each call, check
the endpoint and fields at developers.cloudflare.com/api**, then read the result back to prove it took effect.
If the owner prefers, give them the same steps in the dashboard (Zero Trust → Networks → Tunnels, and Zero
Trust → Access → Applications) and verify each one yourself with `curl -sI https://name.domain`.

**Their domain may already serve other things** (a website, mail). Never change or delete existing DNS records,
zone settings or rules; only add the records listed here, and before any rule change read the current rules
and merge, never replace them.

## 1. The tunnel

```
# cloudflared from Cloudflare's apt repository (see developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads)
API=https://api.cloudflare.com/client/v4; H="Authorization: Bearer $CF_TOKEN"
curl -s -X POST "$API/accounts/$ACCOUNT/cfd_tunnel" -H "$H" -H 'Content-Type: application/json' \
  -d '{"name":"<hostname>","config_src":"cloudflare"}'                      # -> result.id
curl -s "$API/accounts/$ACCOUNT/cfd_tunnel/$TUNNEL/token" -H "$H"           # -> the connector token
sudo cloudflared service install <connector token>                         # never echo the token into logs
systemctl is-active cloudflared
```

Routes (all of them in one PUT; the last rule must be the 404 catch-all):

```
curl -s -X PUT "$API/accounts/$ACCOUNT/cfd_tunnel/$TUNNEL/configurations" -H "$H" -H 'Content-Type: application/json' -d '{
 "config": {"ingress": [
   {"hostname": "home.DOMAIN",  "service": "http://localhost:3001"},
   {"hostname": "n8n.DOMAIN",   "service": "http://localhost:5678"},
   {"hostname": "photos.DOMAIN","service": "http://localhost:2283"},
   {"service": "http_status:404"}]}}'
```

One CNAME per hostname, proxied: `{"type":"CNAME","name":"photos","content":"<TUNNEL>.cfargotunnel.com","proxied":true}`
on `POST $API/zones/$ZONE/dns_records`.

Use the ports in `network.md`. Keep the full list of routes in `/root/JUNKYARD.md`.

## 2. Access (the email code in front of everything)

1. Login method: an identity provider of type `onetimepin` (the email code), if the account has none.
2. One reusable policy "Owner": `decision: allow`, include the owner's email (and anyone they named).
3. One self-hosted application "Home server" with every protected hostname as a destination, the policy above,
   only the email-code login, and a session of 720h (they log in about once a month per device).
4. Check from outside: `curl -sI https://photos.DOMAIN` must answer `302` to `*.cloudflareaccess.com`.

Phone apps that cannot show the email page (Immich, Karakeep) use a **service token**: create one
(`access/service_tokens`, valid one year; note the renewal date in the handover), add a policy with
`decision: non_identity` that includes it, and put `CF-Access-Client-Id` / `CF-Access-Client-Secret` in the
app's custom headers. Tell the owner where to paste them, step by step.

## 3. The few services that cannot sit behind Access

Some apps talk to the server without a browser, so the email page breaks them. Each gets another protection:

| Service | Why no Access | Protection instead |
|---|---|---|
| Vaultwarden | the Bitwarden apps | its own login and 2FA; a country rule (block outside the owner's countries); Access on `/admin` only |
| Jellyfin | TV and phone apps | its own login, lockout after 10 wrong passwords; country rule |
| voice bridge | Twilio must reach it | a long secret in the URL path; everything else is 403; no access log |
| n8n `/webhook/*` (only with Telegram or Twilio callbacks) | Telegram and Twilio call it | a bypass rule for that path only; every webhook checks a secret header |

Country rule (custom WAF rule on the zone; read the current rules first and add to them):
`(http.host in {"password.DOMAIN" "media.DOMAIN"} and not ip.src.country in {"XX" "YY"})` → block.

## 4. Done when

- `systemctl is-active cloudflared` is active and the tunnel shows healthy
- every hostname answers through the tunnel, protected ones with a `302` to Access
- the owner opened `https://home.DOMAIN` on their phone, received the code and saw the page (their test)
