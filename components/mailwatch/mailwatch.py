"""mailwatch - watches IMAP inboxes and hands every new email to n8n.

One thread per mailbox. Opens INBOX read-only (EXAMINE), so nothing is ever marked as read.
Waits with IMAP IDLE (falls back to polling), remembers the last UID per mailbox, and only
moves forward after n8n accepted the email - so nothing is lost if n8n is down.
First start on a mailbox: starts from "now" (old emails are not sent).
"""
import email, email.policy, imaplib, json, os, re, socket, ssl, threading, time, traceback
import urllib.request
from email.utils import getaddresses, parseaddr
from html.parser import HTMLParser

ACCOUNTS_FILE = os.environ.get("ACCOUNTS_FILE", "/run/mailwatch/accounts.json")
DATA_DIR = os.environ.get("DATA_DIR", "/data")
STATE_FILE = os.path.join(DATA_DIR, "state.json")
STATUS_FILE = os.path.join(DATA_DIR, "status.json")
N8N_URL = os.environ.get("N8N_URL", "")
SECRET = os.environ.get("MAIL_SECRET", "")
IDLE_SECONDS = 9 * 60  # IDLE renewed well inside what routers and Gmail tolerate
MAX_FETCH = 1_500_000          # bytes per email (attachments beyond this are not needed)
TEXT_LIMIT = 8000
ALERT_AFTER = 30 * 60          # tell the owner if a mailbox is down this long

lock = threading.Lock()
state, status = {}, {}


def log(*a):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), *a, flush=True)


def load(path):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}


def save(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, path)


def set_status(name, **kw):
    with lock:
        status.setdefault(name, {}).update(kw)
        save(STATUS_FILE, status)


def post(payload):
    req = urllib.request.Request(N8N_URL, data=json.dumps(payload).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "X-Mail-Secret": SECRET})
    with urllib.request.urlopen(req, timeout=30) as r:
        if r.status >= 300:
            raise RuntimeError(f"n8n HTTP {r.status}")


# ---------- parsing ----------
HIDDEN = re.compile("[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f​-‏‪-‮⁠-⁩﻿]")


class Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.out, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "head", "title"):
            self.skip += 1
        if tag in ("br", "p", "div", "tr", "li", "h1", "h2", "h3", "table"):
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "head", "title") and self.skip:
            self.skip -= 1

    def handle_data(self, d):
        if not self.skip:
            self.out.append(d)


def html_text(h):
    p = Text()
    try:
        p.feed(h)
    except Exception:
        pass
    return "".join(p.out)


def clean(s, limit):
    s = HIDDEN.sub(" ", s or "")
    s = re.sub(r"[ \t\r\f\v ]+", " ", s)
    s = re.sub(r"\n\s*\n+", "\n", s)
    return s.strip()[:limit]


def parse(raw):
    m = email.message_from_bytes(raw, policy=email.policy.default)
    plain, html, files = [], [], []
    for part in m.walk():
        if part.is_multipart():
            continue
        disp = part.get_content_disposition()
        fn = part.get_filename()
        if disp == "attachment" or (fn and disp != "inline"):
            files.append(clean(fn or "file", 120))
            continue
        ctype = part.get_content_type()
        if ctype not in ("text/plain", "text/html"):
            continue
        try:
            body = part.get_content()
        except Exception:
            try:
                body = part.get_payload(decode=True).decode("utf-8", "replace")
            except Exception:
                continue
        (plain if ctype == "text/plain" else html).append(body)
    text = "\n".join(plain) if "".join(plain).strip() else html_text("\n".join(html))

    def h(name):
        try:
            return str(m.get(name, "") or "")
        except Exception:
            return ""

    fname, faddr = parseaddr(h("From"))
    # empty headers must be left out: since Python 3.13 one empty value makes getaddresses() return nothing
    to = [a for _, a in getaddresses([v for v in (h("To"), h("Cc"), h("Delivered-To")) if v]) if a]
    return {
        "message_id": clean(h("Message-ID"), 300),
        "date": clean(h("Date"), 100),
        "from_name": clean(fname, 200),
        "from_addr": clean(faddr, 200).lower(),
        "to": sorted(set(a.lower() for a in to))[:20],
        "subject": clean(h("Subject"), 300),
        "list_unsubscribe": bool(h("List-Unsubscribe")),
        "text": clean(text, TEXT_LIMIT),
        "attachments": files[:20],
    }


# ---------- one mailbox ----------
def keep_alive(sock):
    """Gmail says nothing during IDLE, and a router on the way forgets a silent connection: it
    died unseen and only showed as a timeout when IDLE ended (every ~26 minutes, 2026-11-04).
    TCP keepalive every 60 s keeps the path open and finds a dead one within about 2 minutes."""
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    for opt, value in (("TCP_KEEPIDLE", 60), ("TCP_KEEPINTVL", 20), ("TCP_KEEPCNT", 3)):
        if hasattr(socket, opt):
            sock.setsockopt(socket.IPPROTO_TCP, getattr(socket, opt), value)


def watch(acc):
    name = acc["name"]
    down_since, alerted, backoff = None, False, 10
    while True:
        m = None
        try:
            m = imaplib.IMAP4_SSL(acc["host"], int(acc.get("port", 993)), ssl_context=ssl.create_default_context(), timeout=60)
            keep_alive(m.sock)
            m.login(acc["user"], acc["password"])
            typ, _ = m.select("INBOX", readonly=True)
            if typ != "OK":
                raise RuntimeError("cannot open INBOX")
            validity = (m.response("UIDVALIDITY")[1] or [b""])[0].decode()
            if not validity:
                raise RuntimeError("no UIDVALIDITY")
            typ, caps = m.capability()
            idle_ok = b"IDLE" in (caps[0] or b"").upper().split()
            log(name, "connected", "IDLE" if idle_ok else "polling")
            if alerted:
                post({"type": "status", "account": name, "state": "back"})
            down_since, alerted, backoff = None, False, 10
            set_status(name, ok=True, error=None, connected=int(time.time()), idle=idle_ok)
            while True:
                fetch_new(m, name, validity)
                set_status(name, last_check=int(time.time()))
                if idle_ok:
                    with m.idle(duration=IDLE_SECONDS) as idler:
                        for typ, data in idler:
                            if typ in ("EXISTS", "RECENT"):
                                log(name, "idle event", typ)
                                break
                else:
                    time.sleep(60)
                    m.noop()
        except Exception as e:
            err = f"{type(e).__name__}: {str(e)[:200]}"
            log(name, "error", err)
            if not isinstance(e, (OSError, imaplib.IMAP4.abort, socket.timeout)):
                traceback.print_exc()
            set_status(name, ok=False, error=err, error_at=int(time.time()))
            down_since = down_since or time.time()
            if not alerted and time.time() - down_since > ALERT_AFTER:
                try:
                    post({"type": "status", "account": name, "state": "down", "error": err})
                    alerted = True
                except Exception:
                    pass
        finally:
            try:
                m and m.logout()
            except Exception:
                pass
        time.sleep(backoff)
        backoff = min(backoff * 2, 300)


def fetch_new(m, name, validity):
    # Note: STATUS on the selected mailbox can return stale numbers (Gmail does), so only UID SEARCH is used.
    with lock:
        st = state.get(name)
    if not st or st.get("validity") != validity:
        # first run (or the server renumbered the mailbox): start from now
        typ, data = m.uid("SEARCH", None, "ALL")
        uids = [int(u) for u in (data[0] or b"").split()]
        with lock:
            state[name] = {"validity": validity, "last": max(uids, default=0)}
            save(STATE_FILE, state)
        log(name, "starting from UID", state[name]["last"])
        return
    last = st["last"]
    typ, data = m.uid("SEARCH", None, f"UID {last + 1}:*")
    uids = sorted(int(u) for u in (data[0] or b"").split() if int(u) > last)
    for uid in uids:
        typ, resp = m.uid("FETCH", str(uid), f"(BODY.PEEK[]<0.{MAX_FETCH}>)")
        raw = next((p[1] for p in resp if isinstance(p, tuple)), None)
        if raw is not None:
            msg = parse(raw)
            msg["message_id"] = msg["message_id"] or f"<uid-{validity}-{uid}@{name}>"
            post({"type": "mail", "account": name, "uid": uid, **msg})
            log(name, "sent uid", uid)
        with lock:
            state[name]["last"] = uid
            save(STATE_FILE, state)


def main():
    global state, status
    if not N8N_URL or len(SECRET) < 24:
        raise SystemExit("N8N_URL and MAIL_SECRET (24+ random characters) must be set")
    state, status = load(STATE_FILE), load(STATUS_FILE)
    accounts = json.load(open(ACCOUNTS_FILE))
    for acc in accounts:
        threading.Thread(target=watch, args=(acc,), daemon=True, name=acc["name"]).start()
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
