# dlbridge: the bridge between n8n and aria2, plus yt-dlp for video sites.
# yt-dlp needs a JavaScript runtime for YouTube (deno) and ffmpeg to join video and audio.
# To update yt-dlp when a site breaks: change YTDLP below, then
#   docker compose build bridge && docker compose up -d bridge
FROM python:3.14.10-slim
ARG DENO=v2.9.8
ARG YTDLP=2026.10.26
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg ca-certificates curl unzip \
 && cd /tmp \
 && curl -fsSLO https://github.com/denoland/deno/releases/download/${DENO}/deno-x86_64-unknown-linux-gnu.zip \
 && curl -fsSLO https://github.com/denoland/deno/releases/download/${DENO}/deno-x86_64-unknown-linux-gnu.zip.sha256sum \
 && sha256sum -c deno-x86_64-unknown-linux-gnu.zip.sha256sum \
 && unzip -q deno-x86_64-unknown-linux-gnu.zip -d /usr/local/bin && rm deno-* \
 && apt-get purge -y curl unzip && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir "yt-dlp[default]==${YTDLP}"
COPY dlbridge.py test_dlbridge.py /app/
COPY locales /app/locales
WORKDIR /app
USER 10001:10001
# TZ comes from the compose file (the owner's time zone)
ENV HOME=/data XDG_CACHE_HOME=/data/cache PYTHONUNBUFFERED=1
CMD ["python", "/app/dlbridge.py"]
