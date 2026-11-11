# jc-isolate (network isolation)

One script for every service that opens links or reads content from strangers: its Docker network may reach
the public internet only, never the home network, the router, the server itself or other containers, except
the exceptions written in its `/etc/junkyard/isolate/<name>.conf` (see `examples/`).

    install -m 755 jc-isolate /usr/local/sbin/
    install -m 644 jc-isolate@.service /etc/systemd/system/
    systemctl enable --now jc-isolate@downloads

The compose file must name the bridge (`driver_opts: com.docker.network.bridge.name: br-<name>`) and fix the
subnet, so the rules can point at it. The unit runs again whenever Docker restarts.

Tests (in a throwaway container, never on the real firewall):
`docker run --rm --privileged -v "$PWD":/t:ro alpine:3.22 sh /t/test.sh`
