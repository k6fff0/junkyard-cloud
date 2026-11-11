# aria2: the downloader (files with many connections, torrents, magnets).
FROM alpine:3.22
RUN apk add --no-cache aria2=1.37.0-r1 ca-certificates
COPY aria2.conf /etc/aria2.conf
USER 10001:10001
# The RPC secret comes from .env; the session file lets unfinished downloads resume after a restart.
ENTRYPOINT ["sh", "-c", "touch /data/aria2.session && exec aria2c --conf-path=/etc/aria2.conf --rpc-secret=\"$ARIA2_SECRET\""]
