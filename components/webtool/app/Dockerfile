FROM python:3.12-slim-bookworm
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright PYTHONUNBUFFERED=1 HOME=/tmp
RUN pip install --no-cache-dir playwright==1.63.0 "aiohttp>=3.9,<4" \
 && playwright install --with-deps --only-shell chromium \
 && rm -rf /var/lib/apt/lists/* \
 && useradd -u 10001 -M -s /usr/sbin/nologin app
COPY app.py test_webtool.py /app/
WORKDIR /app
USER 10001
CMD ["python", "/app/app.py"]
