FROM python:3.14.10-slim
RUN pip install --no-cache-dir aiohttp==3.14.5 && useradd -u 10003 -M -s /usr/sbin/nologin app
WORKDIR /app
COPY bridge.py test_bridge.py ./
USER 10003
EXPOSE 8765
CMD ["python", "-u", "bridge.py"]
