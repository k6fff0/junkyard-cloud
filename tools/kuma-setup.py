"""Sets Uptime Kuma up without a browser: the admin account, the assistant's webhook notification (default for
every monitor) and the monitors. Safe to run again: existing notifications and monitors (same name) are kept.

Kuma 2.x has no REST API for this; it speaks socket.io. Run it in a throwaway container on the host network:

  sudo docker run --rm --network host -v /opt/junkyard/src/tools:/t:ro -v /etc/junkyard:/j:ro \
    python:3.14.10-slim sh -c "pip install -q 'python-socketio[client]==5.13.0' && python /t/kuma-setup.py /j/kuma.json /j/secrets.json"

kuma.json (no secrets):
  {"url": "http://127.0.0.1:3002", "user": "admin", "notify_url": "http://127.0.0.1:5678/webhook/uptime",
   "monitors": [{"name": "Passwords", "url": "http://127.0.0.1:8222"}, ...]}
secrets.json: kuma_admin_password, notify_secret.
"""
import json
import sys
import threading
import time

import socketio

cfg, sec = (json.load(open(p)) for p in sys.argv[1:3])
NOTIFY_NAME = "Assistant (chat)"
lists = {"monitorList": None, "notificationList": None}
got = {k: threading.Event() for k in lists}

sio = socketio.Client(reconnection=False)


def keep(name):
    def handler(data):
        lists[name] = data
        got[name].set()
    return handler


for name in lists:
    sio.on(name, keep(name))


def emit_call(event, *args, timeout=30):
    """Kuma's handlers take several arguments and a callback; socketio.call sends them as a tuple."""
    box, done = {}, threading.Event()
    sio.emit(event, args, callback=lambda *r: (box.setdefault("r", r[0] if r else None), done.set()))
    if not done.wait(timeout):
        raise SystemExit("kuma %s: no answer" % event)
    r = box["r"]
    if isinstance(r, dict) and r.get("ok") is False:
        raise SystemExit("kuma %s failed: %s" % (event, r.get("msg")))
    return r


password = sec["kuma_admin_password"]
# A fresh Kuma accepts "setup" once; afterwards it answers ok=false, and we log in. Right after its first start
# the web page already answers while the socket does not yet: try again on a new connection until it does.
first = {}
for attempt in range(20):
    sio.connect(cfg["url"], transports=["websocket"], wait_timeout=30)
    done = threading.Event()
    sio.emit("setup", (cfg["user"], password), callback=lambda r: (first.update(r or {"ok": False}), done.set()))
    if done.wait(10):
        break
    sio.disconnect()
    time.sleep(5)
else:
    raise SystemExit("kuma at %s never answered" % cfg["url"])
print("admin account created" if first.get("ok") else "no new admin account (%s)" % first.get("msg"))
emit_call("login", {"username": cfg["user"], "password": password, "token": ""})
for name in got:
    if not got[name].wait(30):
        raise SystemExit("kuma did not send its %s" % name)

notes = {n["name"]: n["id"] for n in (lists["notificationList"] or [])}
if NOTIFY_NAME in notes:
    nid = notes[NOTIFY_NAME]
    print("notification exists:", NOTIFY_NAME)
else:
    r = emit_call("addNotification", {
        "name": NOTIFY_NAME, "type": "webhook", "isDefault": True, "applyExisting": True, "active": True,
        "webhookURL": cfg["notify_url"], "webhookContentType": "json",
        "webhookAdditionalHeaders": json.dumps({"X-Notify-Secret": sec["notify_secret"]})}, None)
    nid = r["id"]
    print("notification added:", NOTIFY_NAME)

have = {m["name"] for m in (lists["monitorList"] or {}).values()}
for m in cfg.get("monitors", []):
    if m["name"] in have:
        print("monitor exists:", m["name"])
        continue
    emit_call("add", {
        "type": "http", "name": m["name"], "url": m["url"], "method": "GET", "interval": 60, "retryInterval": 60,
        "maxretries": 2, "resendInterval": 0, "timeout": 48, "accepted_statuscodes": ["200-399"],
        "maxredirects": 10, "ignoreTls": False, "upsideDown": False, "expiryNotification": False,
        "notificationIDList": {str(nid): True}, "active": True, "conditions": []})
    print("monitor added:", m["name"])
sio.disconnect()
