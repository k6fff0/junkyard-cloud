"""dlbridge: the downloads bridge.

n8n calls this to start, list and control downloads; it sends links to aria2
(files, torrents, magnets) or to yt-dlp (YouTube and other video sites), and
tells the owner (through Notify Me) when something finishes or fails,
and when the downloads folder grows past ALERT_GB.

Endpoints (header X-Bridge-Key):
  POST /add      {"url": "...", "kind": "auto|file|torrent|video|audio"}  (audio: mp3, only when asked)
  GET  /list
  POST /control  {"id": "a:<gid>|v:<id>" or "match": "part of the name", "action": "pause|resume|cancel"}
  GET  /usage
  GET  /health   (no key)
"""
import base64
import hmac
import ipaddress
import json
import os
import re
import shutil
import socket
import subprocess
import threading
import time
import urllib.parse
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.environ.get("DOWNLOAD_ROOT", "/downloads")
DATA = os.environ.get("DATA_DIR", "/data")
KEY = os.environ.get("BRIDGE_KEY", "")
ARIA2_URL = os.environ.get("ARIA2_URL", "http://aria2:6800/jsonrpc")
ARIA2_SECRET = os.environ.get("ARIA2_SECRET", "")
NOTIFY_URL = os.environ.get("NOTIFY_URL", "")
NOTIFY_SECRET = os.environ.get("NOTIFY_SECRET", "")
NOTIFY_CHANNELS = os.environ.get("NOTIFY_CHANNELS", "")   # empty = Notify Me decides by priority
LANG_CODE = os.environ.get("LANG_CODE", "en")
ALERT_BYTES = int(float(os.environ.get("ALERT_GB", "500")) * 1e9)
VIDEO_JOBS = int(os.environ.get("VIDEO_JOBS", "2"))
FOLDERS = {"file": "Files", "torrent": "Torrents", "video": "Videos", "audio": "Audio"}
FALLBACK_CONNECTIONS = ["2", "1"]
FILE_EXT = re.compile(
    r"\.(zip|rar|7z|tar|gz|xz|bz2|iso|img|dmg|exe|msi|apk|ipa|deb|rpm|pkg|bin|pdf|epub|docx?|xlsx?|pptx?|"
    r"mp4|mkv|avi|mov|wmv|m4v|webm|ts|mp3|m4a|flac|wav|ogg|srt|ass|jpg|jpeg|png|gif|webp|torrent)$", re.I)


def messages(lang):
    """Texts the owner reads. English is the base; a locale file only overrides what it has."""
    here = os.path.join(os.path.dirname(os.path.abspath(__file__)), "locales")
    out = {}
    for code in ("en", lang):
        try:
            with open(os.path.join(here, code + ".json"), encoding="utf-8") as f:
                out.update(json.load(f))
        except OSError:
            pass
    return out


def log(msg):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), msg, flush=True)


def human(n):
    """Sizes the way disks are sold (1 GB = 1000 MB), so the 500 GB limit reads as 500."""
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1000 or unit == "TB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1000


# ---------------------------------------------------------------- links

class Refused(Exception):
    pass


def video_matcher():
    """yt-dlp's site list, without its catch-all extractor."""
    from yt_dlp.extractor import gen_extractor_classes
    extractors = [e for e in gen_extractor_classes() if e.ie_key() != "Generic"]
    return lambda url: any(e.suitable(url) for e in extractors)


def resolve_public(host):
    """Refuses names that point inside: the firewall drops them anyway,
    this only gives a clear answer instead of a timeout."""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        raise Refused("the address does not exist (DNS)")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise Refused("the link points to an internal address")


def classify(url, kind="auto", is_video=None, resolve=resolve_public):
    """Returns (kind, cleaned url)."""
    url = (url or "").strip()
    if not url or len(url) > 8000 or any(c in url for c in "\r\n\t "):
        raise Refused("send one link")
    if url.lower().startswith("magnet:?"):
        if "xt=urn:btih:" not in url.lower() and "xt=urn:btmh:" not in url.lower():
            raise Refused("not a valid magnet link")
        return "torrent", url
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise Refused("only http, https and magnet links")
    resolve(parts.hostname)
    if kind in ("file", "torrent", "video", "audio"):  # audio only when the owner asks for the sound
        return kind, url
    path = urllib.parse.unquote(parts.path)
    if path.lower().endswith(".torrent"):
        return "torrent", url
    if FILE_EXT.search(path):
        return "file", url
    if is_video and is_video(url):
        return "video", url
    return "file", url


# ---------------------------------------------------------------- aria2

class Aria2:
    def __init__(self, url=ARIA2_URL, secret=ARIA2_SECRET):
        self.url, self.secret = url, secret

    def call(self, method, *params):
        body = json.dumps({"jsonrpc": "2.0", "id": uuid.uuid4().hex, "method": "aria2." + method,
                           "params": ["token:" + self.secret, *params]}).encode()
        req = urllib.request.Request(self.url, data=body, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                out = json.loads(r.read())
        except urllib.error.HTTPError as e:
            out = json.loads(e.read() or b"{}")
        if "error" in out:
            raise RuntimeError(out["error"].get("message", "aria2 error"))
        return out["result"]


KEYS = ["gid", "status", "totalLength", "completedLength", "downloadSpeed", "uploadSpeed", "files",
        "bittorrent", "errorMessage", "followedBy", "dir", "infoHash", "numSeeders", "connections"]


def aria_name(t):
    bt = (t.get("bittorrent") or {}).get("info") or {}
    if bt.get("name"):
        return bt["name"]
    files = t.get("files") or []
    if files and files[0].get("path"):
        return os.path.basename(files[0]["path"])
    if files and files[0].get("uris"):
        return os.path.basename(urllib.parse.urlsplit(files[0]["uris"][0]["uri"]).path) or "file"
    return "[torrent metadata]" if t.get("infoHash") else "file"


def aria_item(t):
    total, done = int(t.get("totalLength") or 0), int(t.get("completedLength") or 0)
    status = t["status"]
    seeding = bool(t.get("bittorrent")) and status == "active" and total and done == total
    return {"id": "a:" + t["gid"], "kind": "torrent" if t.get("bittorrent") or t.get("infoHash") else "file",
            "name": aria_name(t), "status": "seeding" if seeding else status,
            "percent": round(done * 100 / total, 1) if total else 0, "size": human(total),
            "speed": human(int(t.get("downloadSpeed") or 0)) + "/s", "error": t.get("errorMessage") or ""}


# ---------------------------------------------------------------- yt-dlp

class Videos:
    """Video-site links, downloaded by yt-dlp itself: YouTube slows any other downloader to
    about half the speed (measured 2026-11-04: aria2 5.5 MB/s with 16 connections, yt-dlp
    about 12 MB/s), so these do not show in the aria2 panel. The owner is told when one starts
    (name and size) and when it ends, and the home page card counts them.
    A video is saved as one mp4 in Videos; the sound alone (only when asked for) as a
    320k mp3 in Audio."""
    PROGRESS = "download:PROG %(progress.downloaded_bytes)s %(progress.total_bytes)s %(progress.total_bytes_estimate)s %(progress.speed)s"

    def __init__(self, root, slots=VIDEO_JOBS, runner=subprocess.Popen):
        self.root, self.runner = root, runner
        self.jobs, self.lock = {}, threading.Lock()
        self.slots = threading.Semaphore(slots)

    def add(self, url, audio=False):
        jid = uuid.uuid4().hex[:10]
        with self.lock:
            self.jobs[jid] = {"id": "v:" + jid, "kind": "audio" if audio else "video", "url": url, "name": url,
                              "status": "waiting", "done": 0, "total": 0, "speed": 0, "path": "", "error": "",
                              "proc": None, "finished": 0, "expected": 0}
        threading.Thread(target=self._run, args=(jid,), daemon=True).start()
        return "v:" + jid

    def command(self, job):
        audio = job["kind"] == "audio"
        out = os.path.join(self.root, FOLDERS[job["kind"]])
        os.makedirs(out, exist_ok=True)
        # a song needs an album and an artist, or Jellyfin's music page (albums first) looks empty:
        # the channel is both, and the video's picture becomes the cover
        fmt = (["-f", "ba/b", "-x", "--audio-format", "mp3", "--audio-quality", "320K",
                "--parse-metadata", "%(uploader|YouTube)s:%(meta_album)s",
                "--parse-metadata", "%(uploader|YouTube)s:%(meta_album_artist)s",
                "--parse-metadata", "%(uploader|YouTube)s:%(meta_artist)s"] if audio else
               ["-f", "bv*+ba/b", "-S", "res,ext:mp4:m4a", "--merge-output-format", "mp4"])
        # the whole size (picture and sound) is printed first, for the start message
        # the picture, sound and half-made files stay in a hidden folder until the file is whole,
        # so Jellyfin (which watches Videos and Audio) never lists a piece
        # title, channel and picture go inside the file, so Jellyfin shows them instead of a bare name
        return ["yt-dlp", "--no-playlist", "--newline", "--progress", "--no-simulate", "--no-colors", *fmt,
                "--embed-metadata", "--embed-thumbnail", "--convert-thumbnails", "jpg",
                "--windows-filenames", "--no-mtime", "-P", out, "-P", "temp:" + os.path.join(self.root, ".incoming"),
                # songs go in a folder per channel: Jellyfin makes albums from folders, not from tags
                "-o", ("%(uploader|YouTube).80B/" if audio else "") + "%(title).150B [%(id)s].%(ext)s",
                "--print", "before_dl:TITLE %(title)s",
                "--print", "before_dl:SIZE %(filesize,filesize_approx|0)s",
                "--print", "after_move:FILE %(filepath)s",
                "--progress-template", self.PROGRESS, "--", job["url"]]

    def _run(self, jid):
        with self.slots:
            job = self.jobs[jid]
            if job["status"] == "removed":
                return
            job["status"] = "active"
            errors = []
            try:
                proc = self.runner(self.command(job), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            except OSError as e:
                job.update(status="error", error=str(e), finished=time.time())
                return
            job["proc"] = proc
            for line in proc.stdout:
                self._line(job, line.rstrip("\n"), errors)
            code = proc.wait()
            if job["status"] == "removed":
                return
            if code == 0 and job["path"]:
                # YouTube sends picture and sound apart; the real size is the finished file's
                try:
                    job["total"] = job["done"] = os.path.getsize(job["path"])
                except OSError:
                    pass
                job.update(status="complete", finished=time.time())
            else:
                job.update(status="error", finished=time.time(),
                           error=(errors[-1] if errors else f"yt-dlp exit {code}")[:300])

    @staticmethod
    def _line(job, line, errors):
        num = lambda s: int(float(s)) if s not in ("NA", "None", "") else 0
        if line.startswith("PROG "):
            parts = line.split(" ")
            job["done"], total, est, job["speed"] = num(parts[1]), num(parts[2]), num(parts[3]), num(parts[4])
            job["total"] = total or est or job["total"]
        elif line.startswith("TITLE "):
            job["name"] = line[6:]
        elif line.startswith("SIZE "):
            job["expected"] = num(line[5:].strip())
        elif line.startswith("FILE "):
            job["path"] = line[5:]
        elif line.startswith("ERROR:"):
            errors.append(line[6:].strip())

    def control(self, jid, action):
        job = self.jobs.get(jid)
        if not job:
            raise Refused("no such download")
        if action != "cancel":
            raise Refused("a video can only be cancelled, not paused")
        job.update(status="removed", finished=time.time())
        if job["proc"] and job["proc"].poll() is None:
            job["proc"].terminate()

    def items(self):
        with self.lock:
            jobs = list(self.jobs.values())
        out = []
        for j in jobs:
            if j["status"] == "removed":
                continue
            # while downloading, the percent is of the part in progress; the size is the whole
            size = j["total"] if j["status"] == "complete" else (j.get("expected") or j["total"])
            out.append({"id": j["id"], "kind": j["kind"], "name": j["name"], "status": j["status"],
                        "percent": round(j["done"] * 100 / j["total"], 1) if j["total"] else 0,
                        "size": human(size), "speed": human(j["speed"]) + "/s", "error": j["error"]})
        return out


# ---------------------------------------------------------------- watcher

class Watcher:
    """Tells the owner when downloads finish or fail, and when the folder is large."""

    def __init__(self, aria2, videos, notify, root=ROOT, alert_bytes=ALERT_BYTES,
                 state_path=os.path.join(DATA, "state.json"), clock=time.time, lang=LANG_CODE):
        self.aria2, self.videos, self.notify = aria2, videos, notify
        self.t = messages(lang)
        self.root, self.alert_bytes, self.state_path, self.clock = root, alert_bytes, state_path, clock
        try:
            with open(state_path) as f:
                self.state = json.load(f)
        except (OSError, ValueError):
            self.state = {}
        self.state.setdefault("notified", [])
        self.state.setdefault("alerted_at", 0)
        self.state.setdefault("retries", {})
        self.primed = False

    def save(self):
        self.state["notified"] = self.state["notified"][-1000:]
        self.state["retries"] = dict(list(self.state["retries"].items())[-200:])
        tmp = self.state_path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.state, f)
        os.replace(tmp, self.state_path)

    def seen(self, key):
        return key in self.state["notified"]

    def mark(self, key):
        self.state["notified"].append(key)

    def check_downloads(self):
        active = self.aria2.call("tellActive", KEYS)
        stopped = self.aria2.call("tellStopped", 0, 200, KEYS)
        if not self.primed:  # after a restart, old results are not news
            for t in stopped:
                if not self.seen(t["gid"]):
                    self.mark(t["gid"])
            self.primed = True
        changed = False
        for t in active + stopped:
            if self.seen(t["gid"]) or t.get("followedBy"):
                continue  # a magnet's metadata or a .torrent file: the real download follows
            total, done = int(t.get("totalLength") or 0), int(t.get("completedLength") or 0)
            finished = t["status"] == "complete" or (t.get("bittorrent") and total and done == total)
            if finished:
                folder = (t.get("dir") or "").rstrip("/")
                where = "Downloads/" + os.path.basename(folder) if folder.startswith(ROOT + "/") else "Downloads"
                self.notify(self.t["done"], self.body(aria_name(t), human(total), where))
            elif t["status"] == "error" and self.retry(t):
                pass
            elif t["status"] == "error":
                self.notify(self.t["failed"], self.why(aria_name(t), t.get("errorMessage")))
            else:
                continue
            self.mark(t["gid"])
            changed = True
        for j in self.videos.items():
            what, where = self.t[j["kind"]], "Downloads/" + FOLDERS[j["kind"]]
            if j["status"] == "active" and j["size"] != "0 B" and not self.seen("start-" + j["id"]):
                # videos do not show in the panel, so the owner is told they started, with the size
                self.notify(self.t["video_started"].format(what=what), self.body(j["name"], j["size"], where))
                self.mark("start-" + j["id"])
                changed = True
            if self.seen(j["id"]) or j["status"] not in ("complete", "error"):
                continue
            if j["status"] == "complete":
                self.notify(self.t["video_done"].format(what=what), self.body(j["name"], j["size"], where))
            else:
                self.notify(self.t["video_failed"].format(what=what), self.why(j["name"], j["error"]))
            self.mark(j["id"])
            changed = True
        if changed:
            self.save()

    def body(self, name, size, where):
        return f"{name}\n{self.t['size']}: {size}\n{self.t['where']}: {where}"

    def why(self, name, reason):
        return f"{name}\n{self.t['reason']}: {reason or self.t['unknown']}"

    def retry(self, t):
        """A plain download that failed (often a server refusing 8 connections with 429) is added
        again with fewer connections; aria2 carries on from the part already on disk."""
        if t.get("bittorrent"):
            return False
        uris = [u["uri"] for f in (t.get("files") or [])[:1] for u in f.get("uris", [])]
        if not uris:
            return False
        tries = self.state["retries"].get(uris[0], 0)
        if tries >= len(FALLBACK_CONNECTIONS):
            return False
        conns = FALLBACK_CONNECTIONS[tries]
        self.state["retries"][uris[0]] = tries + 1
        try:
            self.aria2.call("removeDownloadResult", t["gid"])
        except RuntimeError:
            pass
        self.aria2.call("addUri", [uris[0]], {"dir": t.get("dir") or self.root,
                                              "max-connection-per-server": conns, "split": conns})
        log(f"retry with {conns} connection(s): {aria_name(t)} ({t.get('errorMessage')})")
        return True

    def folder_bytes(self):
        total = 0
        for base, _, files in os.walk(self.root):
            for name in files:
                try:
                    st = os.lstat(os.path.join(base, name))
                    # space really taken on disk (sparse files count less); Windows has no st_blocks
                    total += st.st_blocks * 512 if hasattr(st, "st_blocks") else st.st_size
                except OSError:
                    pass
        return total

    def usage(self):
        return {"used": self.folder_bytes(), "free": shutil.disk_usage(self.root).free, "limit": self.alert_bytes}

    def check_usage(self):
        u = self.usage()
        now = self.clock()
        if u["used"] >= self.alert_bytes:
            if now - self.state["alerted_at"] >= 24 * 3600:
                self.notify(self.t["space_title"], self.t["space_body"].format(
                    used=human(u["used"]), limit=human(self.alert_bytes), free=human(u["free"])))
                self.state["alerted_at"] = now
                self.save()
        elif u["used"] < self.alert_bytes * 0.9 and self.state["alerted_at"]:
            self.state["alerted_at"] = 0  # below again: the next crossing alerts at once
            self.save()
        return u

    def loop(self):
        last_usage = 0
        while True:
            try:
                self.check_downloads()
            except Exception as e:  # aria2 restarting, network: try again next round
                log(f"watch: {e}")
            if time.time() - last_usage > 600:
                try:
                    self.check_usage()
                except Exception as e:
                    log(f"usage: {e}")
                last_usage = time.time()
            time.sleep(10)


def notify_me(title, message):
    note = {"title": title, "message": message, "priority": "normal"}
    if NOTIFY_CHANNELS:
        note["channels"] = NOTIFY_CHANNELS
    body = json.dumps(note).encode()
    req = urllib.request.Request(NOTIFY_URL, data=body, headers={
        "Content-Type": "application/json", "X-Notify-Secret": NOTIFY_SECRET})
    with urllib.request.urlopen(req, timeout=20) as r:
        r.read()
    log(f"notified: {title}")


# ---------------------------------------------------------------- service

class Service:
    def __init__(self, aria2, videos, watcher, is_video, resolve=resolve_public):
        self.aria2, self.videos, self.watcher = aria2, videos, watcher
        self.is_video, self.resolve = is_video, resolve

    def add(self, url, kind="auto"):
        kind, url = classify(url, kind or "auto", self.is_video, self.resolve)
        if kind in ("video", "audio"):
            return {"id": self.videos.add(url, audio=kind == "audio"), "kind": kind}
        folder = os.path.join(ROOT, FOLDERS[kind])
        gid = self.aria2.call("addUri", [url], {"dir": folder})
        name = ""
        for _ in range(6):  # the name is known once the server answers
            time.sleep(0.5)
            t = self.aria2.call("tellStatus", gid, KEYS)
            name = aria_name(t)
            if name not in ("file", "[torrent metadata]") or t["status"] in ("error", "complete"):
                break
        item = aria_item(t)
        return {"id": "a:" + gid, "kind": kind, "name": name, "size": item["size"], "status": item["status"],
                "error": item["error"]}

    def status(self):
        g = self.aria2.call("getGlobalStat")
        videos = [v for v in self.videos.items() if v["status"] in ("waiting", "active")]
        now = time.time()
        if now - getattr(self, "_usage_at", 0) > 60:  # walking the folder is not free
            self._usage, self._usage_at = self.watcher.usage(), now
        return {"active": int(g["numActive"]) + len(videos), "waiting": int(g["numWaiting"]),
                "speed": human(int(g["downloadSpeed"])) + "/s", "used": human(self._usage["used"]),
                "free": human(self._usage["free"])}

    def list(self):
        active = self.aria2.call("tellActive", KEYS)
        waiting = self.aria2.call("tellWaiting", 0, 50, KEYS)
        stopped = self.aria2.call("tellStopped", 0, 15, KEYS)
        items = [aria_item(t) for t in active + waiting + stopped if not t.get("followedBy")]
        return {"items": self.videos.items() + items}

    def control(self, did, action, match=None):
        """Acts on one download, named by its id or by part of its name ("debian"), so the owner
        can say which one in their own words without a list first."""
        if not did and match:
            m = str(match).strip().lower()
            if len(m) < 2:
                raise Refused("say more of the name")
            live = [x for x in self.list()["items"]
                    if x["status"] in ("active", "waiting", "paused", "seeding") and m in x["name"].lower()]
            if not live:
                raise Refused("no running download matches that name")
            if len(live) > 1:
                raise Refused(f"{len(live)} downloads match; say more of the name")
            did = live[0]["id"]
        if not isinstance(did, str) or ":" not in did:
            raise Refused("unknown id")
        src, ref = did.split(":", 1)
        if src == "v":
            self.videos.control(ref, action)
            return {"ok": True, "id": did}
        method = {"pause": "pause", "resume": "unpause", "cancel": "remove"}.get(action)
        if not method or not re.fullmatch(r"[0-9a-f]{16}", ref):
            raise Refused("unknown action or id")
        self.aria2.call(method, ref)
        return {"ok": True, "id": did}


def make_handler(service, key=KEY):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def send(self, code, obj):
            body = json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def authorized(self):
            given = self.headers.get("X-Bridge-Key", "")
            return bool(key) and hmac.compare_digest(given.encode(), key.encode())

        def body(self):
            n = int(self.headers.get("Content-Length") or 0)
            if n > 64 * 1024:
                raise Refused("request too large")
            return json.loads(self.rfile.read(n) or b"{}")

        def route(self, method):
            if self.path == "/health":
                return self.send(200, {"ok": True})
            if self.path == "/status" and method == "GET":
                # numbers only, no names: the home page card reads this without a key
                try:
                    return self.send(200, service.status())
                except Exception as e:
                    log(f"status: {e}")
                    return self.send(502, {"error": "aria2 not answering"})
            if not self.authorized():
                return self.send(401, {"error": "unauthorized"})
            try:
                if method == "POST" and self.path == "/add":
                    b = self.body()
                    log(f"add {b.get('kind', 'auto')} {str(b.get('url'))[:200]}")
                    return self.send(200, service.add(b.get("url"), b.get("kind", "auto")))
                if method == "GET" and self.path == "/list":
                    return self.send(200, service.list())
                if method == "POST" and self.path == "/control":
                    b = self.body()
                    log(f"control {b.get('action')} {b.get('id') or b.get('match')}")
                    return self.send(200, service.control(b.get("id"), b.get("action"), b.get("match")))
                if method == "GET" and self.path == "/usage":
                    u = service.watcher.usage()
                    return self.send(200, {k: human(v) for k, v in u.items()} | {"used_bytes": u["used"]})
                return self.send(404, {"error": "not found"})
            except Refused as e:
                return self.send(400, {"error": str(e)})
            except (ValueError, json.JSONDecodeError):
                return self.send(400, {"error": "bad request"})
            except Exception as e:
                log(f"error: {e}")
                return self.send(502, {"error": str(e)[:300]})

        def do_GET(self):
            self.route("GET")

        def do_POST(self):
            self.route("POST")

    return Handler


def main():
    for folder in FOLDERS.values():
        os.makedirs(os.path.join(ROOT, folder), exist_ok=True)
        # Jellyfin does not watch a library folder that is empty when it starts ("inaccessible or
        # empty, skipping"), so a first song or film never showed. A hidden file keeps each one
        # non-empty; Jellyfin itself ignores hidden files.
        keep = os.path.join(ROOT, folder, ".keep")
        if not os.path.exists(keep):
            open(keep, "w").close()
    aria2, videos = Aria2(), Videos(ROOT)
    watcher = Watcher(aria2, videos, notify_me)
    threading.Thread(target=watcher.loop, daemon=True).start()
    service = Service(aria2, videos, watcher, video_matcher())
    server = ThreadingHTTPServer(("0.0.0.0", 8790), make_handler(service))
    server.daemon_threads = True
    log("dlbridge on :8790")
    server.serve_forever()


if __name__ == "__main__":
    main()
