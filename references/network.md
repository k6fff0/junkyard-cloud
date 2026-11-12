# Step 4: the network plan

One rule: a container can reach only what it needs. Three kinds of networks:

## The assistant network (`assistant`, 172.30.100.0/24, bridge `br-assistant`)

n8n, its Postgres, WAHA, filebridge, the voice bridge, Paperless (alias `paperless`) and Stirling-PDF (alias
`stirling`). They call each other by name (`http://n8n:5678`, `http://waha:3000`, `http://filebridge:8790`).
Created once:

```
docker network create --subnet 172.30.100.0/24 --gateway 172.30.100.1 \
  -o com.docker.network.bridge.name=br-assistant assistant
```

Compose files join it as an external network named `assistant`.

## Isolated networks (one per service that opens links or reads strangers' content)

| Network | Subnet | Bridge | Who | May reach |
|---|---|---|---|---|
| webtool | 172.30.110.0/24 | br-webtool | search engine, browser | internet only |
| mailwatch | 172.30.111.0/24 | br-mailwatch | mail watcher | internet, n8n |
| karakeep | 172.30.112.0/24 | br-karakeep | link library, its browser | internet only |
| downloads | 172.30.113.0/24 | br-downloads | aria2, yt-dlp bridge (.10) | internet; the bridge also n8n |
| jellyfin | 172.30.114.0/24 | br-jellyfin | media server | internet only |

The compose templates fix these subnets and bridge names. After starting each, enable its isolation:

```
sudo install -m 755 /opt/junkyard/src/components/isolate/jc-isolate /usr/local/sbin/
sudo install -m 644 /opt/junkyard/src/components/isolate/jc-isolate@.service /etc/systemd/system/
sudo install -d -m 755 /etc/junkyard/isolate
# one .conf per network, e.g. /etc/junkyard/isolate/downloads.conf (see components/isolate/examples)
sudo systemctl daemon-reload && sudo systemctl enable --now jc-isolate@downloads
```

Prove it from inside, every time (it must fail for the LAN and the server, and work for the internet):

```
docker run --rm --network downloads alpine:3.22 wget -q -T 5 -O /dev/null http://<router IP> && echo OPEN || echo blocked   # blocked
docker run --rm --network downloads alpine:3.22 wget -q -T 5 -O /dev/null https://example.com && echo OPEN || echo blocked  # OPEN
```

## How the pieces reach each other

- **The tunnel → a web service:** ports published on `127.0.0.1:<port>` only.
- **Other containers → a service on another network:** ports published on `172.17.0.1:<port>` (the `docker0`
  address, which always exists when Docker runs). n8n reaches the web tool at `http://172.17.0.1:8787`, the
  downloads bridge at `:8103`, the link library at `:3010`. The dashboard reads status from there too.
- **An isolated container → n8n:** n8n is also published on `172.17.0.1:5678`, and that one port is the
  exception in the network's `jc-isolate` file (`GATEWAY=172.17.0.1`, `ALLOW_HOST="any:5678"`, or the bridge's
  fixed IP instead of `any`).
- **Uptime Kuma and scripts on the server → n8n:** `http://127.0.0.1:5678/webhook/...`.
- **n8n → the server itself (jc-ops):** SSH to `172.17.0.1:22` with a key that can only run `jc-ops`.

## Ports used

| Port | Service | Bound to |
|---|---|---|
| 5678 | n8n | 127.0.0.1, 172.17.0.1 |
| 3000 | WAHA (never public) | 127.0.0.1 |
| 3001 | Homepage | 127.0.0.1 |
| 3002 | Uptime Kuma (host network) | 127.0.0.1 |
| 2283 | Immich | 127.0.0.1 |
| 3010 | Karakeep | 127.0.0.1, 172.17.0.1 |
| 8010 | Paperless | 127.0.0.1, 172.17.0.1 |
| 8085 | Stirling-PDF | 127.0.0.1 |
| 8096 | Jellyfin | 127.0.0.1, 172.17.0.1 (the dashboard dot) |
| 8102 / 8103 | downloads panel / bridge | 127.0.0.1 / 172.17.0.1 |
| 8222 | Vaultwarden | 127.0.0.1 |
| 8765 | voice bridge | 127.0.0.1 |
| 8787 | web tool | 172.17.0.1 |
| 8123 | Home Assistant (host network) | its own setting; ufw allows the LAN only |
| 8080 | File browser | 127.0.0.1 |

Before creating networks, check nothing else uses these subnets: `docker network inspect $(docker network ls -q) --format '{{.Name}} {{range .IPAM.Config}}{{.Subnet}}{{end}}'`.
