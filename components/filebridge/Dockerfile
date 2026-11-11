# filebridge: WhatsApp/Telegram files <-> archive (Paperless-ngx) and file tools (Stirling-PDF) for n8n.
FROM python:3.14.10-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt && useradd -u 10002 -M -s /usr/sbin/nologin app
COPY filebridge /app/filebridge
WORKDIR /app
USER 10002
EXPOSE 8790
CMD ["python", "-m", "filebridge"]
