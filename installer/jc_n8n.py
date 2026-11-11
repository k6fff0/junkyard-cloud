#!/usr/bin/env python3
"""Installs the assistant into n8n: credentials, the archive's types and fields, and every workflow, wired together.

  jc_n8n.py bootstrap --n8n URL --email E --password-file F --out KEYFILE
        first start of a fresh n8n: creates the owner account and an API key (saved to KEYFILE, mode 600)
  jc_n8n.py render  --config C --out DIR
        writes the final workflows to DIR without touching anything (to review them)
  jc_n8n.py install --config C --secrets S [--state STATE]
        creates or updates everything; safe to run again (ids are kept in STATE)
  jc_n8n.py status  --config C --secrets S [--state STATE]

Python 3.9+ standard library only. The config holds no secrets; secrets live in their own file (mode 600).
See config.example.json and secrets.example.json.
"""
import argparse
import copy
import http.cookiejar
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
WF_DIR = os.path.join(os.path.dirname(HERE), "workflows")
CHANNEL_HELP = {"whatsapp": "whatsapp", "telegram": "telegram", "email": "email",
                "call": "call (a voice reads the text)", "ai_call": "ai_call (a live call with you)"}
APP_NAME = {"whatsapp": "WhatsApp", "telegram": "Telegram"}
UNSAFE = re.compile(r"['\"\\`{}\n\r]")


class Fail(Exception):
    pass


# ---------------------------------------------------------------- files
def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_private(path, data):
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, path)


def templates():
    out = {}
    folder = os.path.join(WF_DIR, "templates")
    for f in sorted(os.listdir(folder)):
        if f.endswith(".json"):
            w = load_json(os.path.join(folder, f))
            out[w["name"]] = w
    return out


# ---------------------------------------------------------------- settings
def modules(cfg):
    manifest = load_json(os.path.join(WF_DIR, "manifest.json"))["modules"]
    on = {"core"} | {m for m, v in (cfg.get("modules") or {}).items() if v}
    unknown = on - set(manifest)
    if unknown:
        raise Fail("unknown modules: %s" % ", ".join(sorted(unknown)))
    for m in sorted(on):
        missing = [r for r in manifest[m]["requires"] if r not in on]
        if missing:
            raise Fail("module %s needs %s" % (m, ", ".join(missing)))
    if not on & {"whatsapp", "telegram"}:
        raise Fail("turn on at least one chat: whatsapp or telegram")
    return on, manifest


def check_text(name, value):
    if UNSAFE.search(value or ""):
        raise Fail("%s must not contain quotes, backslashes, braces or line breaks: %r" % (name, value))
    return value


def values(cfg, on, locale):
    """Every __JC_x__ / __JS:x__ value, computed once from the config."""
    main = cfg.get("main_channel") or ("whatsapp" if "whatsapp" in on else "telegram")
    if main not in on:
        raise Fail("main_channel %s is not turned on" % main)
    chats = [c for c in ("whatsapp", "telegram") if c in on]
    text = chats + (["email"] if "email" in on else [])
    channels = text + (["call", "ai_call"] if "calls" in on else [])
    important = [main] + (["email"] if "email" in on else [])
    emergency = [main] + [c for c in text if c != main] + (["call"] if "calls" in on else [])
    owner, urls, models = cfg["owner"], cfg.get("urls") or {}, cfg.get("models") or {}
    wa, tg, calls, email = cfg.get("whatsapp") or {}, cfg.get("telegram") or {}, cfg.get("calls") or {}, cfg.get("email") or {}
    from_addr = re.search(r"<([^>]+)>", email.get("from", "")) or re.match(r"(\S+@\S+)", email.get("from", ""))
    from_name = email.get("from", "").split("<")[0].strip() if "<" in email.get("from", "") else ""
    v = {
        "OWNER": check_text("owner.name", owner["name"]),
        "OWNER_CALL": check_text("owner.call", owner.get("call") or owner["name"]),
        "ASSISTANT": check_text("assistant.name", cfg["assistant"]["name"]),
        "LANG": cfg.get("lang", "en"), "LANGUAGE": locale["language_name"],
        "STYLE": check_text("style", cfg.get("style") or locale["language_name"]),
        "FORMAL": check_text("formal", cfg.get("formal") or locale["language_name"]),
        "TZ": check_text("tz", cfg["tz"]),
        "MAIN_APP": APP_NAME[main], "CH_MAIN": main, "CH_IMPORTANT": ",".join(important),
        "CH_ALL_TEXT": ",".join(text), "CH_CALL": ",".join(important + (["call"] if "calls" in on else [])),
        "CH_REMINDER": " + ".join(important), "CHANNEL_HELP": ", ".join(CHANNEL_HELP[c] for c in channels),
        "PRIO_NORMAL": main, "PRIO_IMPORTANT": " + ".join(important), "PRIO_EMERGENCY": " + ".join(emergency),
        "WAHA_URL": wa.get("waha_url", "http://waha:3000"), "WA_SESSION": wa.get("session", "default"),
        "WA_CHAT": "%s@c.us" % re.sub(r"\D", "", wa.get("owner_phone", "")),
        "TG_CHAT": str(tg.get("chat_id", "")),
        "EMAIL_FROM": email.get("from", ""), "EMAIL_TO": email.get("to", ""),
        "TWILIO_FROM": calls.get("twilio_from", ""), "OWNER_PHONE": calls.get("owner_phone", ""),
        "TTS_LANG": locale["tts"]["language"], "TTS_VOICE": locale["tts"]["voice"],
        "OPENAI_URL": (cfg.get("openai_url") or "https://api.openai.com/v1").rstrip("/"),
        "MODEL_MAIN": models.get("main", "gpt-6-luna"), "MODEL_SMALL": models.get("small", "gpt-5-nano"),
        "MODEL_TRANSCRIBE": models.get("transcribe", "gpt-4o-mini-transcribe"),
        "FILEBRIDGE_URL": urls.get("filebridge", "http://filebridge:8790"),
        "WEBTOOL_URL": urls.get("webtool", ""), "DLBRIDGE_URL": urls.get("dlbridge", ""),
        "KARAKEEP_URL": urls.get("karakeep", ""), "PAPERLESS_URL": urls.get("paperless", "http://paperless:8000"),
        "DOCS_URL": urls.get("docs", ""), "LINKS_URL": urls.get("links", ""), "DOWNLOADS_URL": urls.get("downloads", ""),
        "FILES_URL": urls.get("files", ""),
        "RESTARTABLE": ", ".join(cfg.get("restartable") or []) or "(none)",
        "DOC_TYPES": ", ".join(locale["doc_types"]),
        "DOCTYPE_INVOICE": locale["doc_type_invoice"],
    }
    for k in ("WAHA_URL", "TG_CHAT", "EMAIL_TO", "TWILIO_FROM", "OWNER_PHONE", "OPENAI_URL", "MODEL_MAIN", "MODEL_SMALL",
              "MODEL_TRANSCRIBE", "FILEBRIDGE_URL", "WEBTOOL_URL", "DLBRIDGE_URL", "KARAKEEP_URL", "PAPERLESS_URL",
              "DOCS_URL", "LINKS_URL", "DOWNLOADS_URL", "FILES_URL", "WA_SESSION"):
        check_text(k.lower(), v[k])
    js = {
        "ASSISTANT": v["ASSISTANT"], "CHANNELS": channels, "CHAT_CHANNELS": chats,
        "PRIORITY_CHANNELS": {"normal": [main], "important": important, "emergency": emergency},
        "DAYS": locale["days"], "MAIL_ALIASES": [a.lower() for a in cfg.get("mail_aliases") or []],
        "CALL_MONITORS": cfg.get("call_monitors") or [],
        "EMAIL_FROM_ADDR": (from_addr.group(1).lower() if from_addr else ""), "EMAIL_FROM_NAME": from_name,
    }
    return v, js


def render_prompt(path, on, v):
    """<!-- if:module --> ... <!-- end --> (nested), then __JC_x__ values."""
    text = open(path, encoding="utf-8").read()
    out, stack = [], [True]
    for part in re.split(r"(<!-- if:[a-z]+ -->|<!-- end -->)", text):
        m = re.fullmatch(r"<!-- if:([a-z]+) -->", part)
        if m:
            stack.append(stack[-1] and m.group(1) in on)
        elif part == "<!-- end -->":
            stack.pop()
            if not stack:
                raise Fail("unbalanced <!-- end --> in %s" % path)
        elif stack[-1]:
            out.append(part)
    if len(stack) != 1:
        raise Fail("unclosed <!-- if --> in %s" % path)
    text = re.sub(r"\n{3,}", "\n\n", "".join(out)).strip() + "\n"
    return re.sub(r"__JC_([A-Z_]+)__", lambda m: v[m.group(1)], text)


def prompts(cfg, on, v, locale):
    owner = cfg["owner"]
    clean = lambda s: str(s).replace("{{", "{ {").replace("}}", "} }")   # n8n would run {{ }} as code
    profile = "\n".join("- " + clean(x) for x in owner.get("profile") or []) or "- (no details given yet)"
    pv = dict(v, OWNER_PROFILE=profile)
    full = owner.get("full_name")
    pv["OWNER_FULLNAME_NOTE"] = (("The owner's full name is %s; documents in that name are the owner's own." % clean(full))
                                 if full else "")
    pv["FAMILY"] = clean(owner.get("family") or "")
    pv["MAIL_CONTEXT"] = clean(owner.get("mail_context") or "no extra details.")
    p = os.path.join(WF_DIR, "prompts")
    return {"PROMPT": render_prompt(os.path.join(p, "assistant.md"), on, pv),
            "DOCS_PROMPT": render_prompt(os.path.join(p, "document.md"), on, pv),
            "MAIL_PROMPT": render_prompt(os.path.join(p, "mail.md"), on, pv)}


# ---------------------------------------------------------------- rendering
def strip_modules(wfs, on, manifest):
    keep = {}
    off = [m for m in manifest if m not in on]
    gone_wf = {w for m in off for w in manifest[m].get("workflows", [])}
    for name, w in wfs.items():
        if name in gone_wf:
            continue
        w = copy.deepcopy(w)
        drop = {n for m in off for n in manifest[m].get("nodes", {}).get(name, [])}
        missing = drop - {n["name"] for n in w["nodes"]}
        if missing:
            raise Fail("manifest names nodes that are not in %s: %s" % (name, ", ".join(sorted(missing))))
        w["nodes"] = [n for n in w["nodes"] if n["name"] not in drop]
        conns = {}
        for src, c in w["connections"].items():
            if src in drop:
                continue
            conns[src] = {k: [[e for e in o if e["node"] not in drop] for o in outs] for k, outs in c.items()}
        w["connections"] = conns
        keep[name] = w
    return keep


def substitute(obj, v, js, msgs, extra, wf_ids=None, cred_ids=None):
    def one(s):
        s = re.sub(r"__TJS:([a-z_]+)__", lambda m: json.dumps(msgs[m.group(1)], ensure_ascii=False), s)
        s = re.sub(r"__JS:([A-Z_]+)__", lambda m: json.dumps({**js, **extra}[m.group(1)], ensure_ascii=False), s)
        s = re.sub(r"__JC_([A-Z_]+)__", lambda m: str({**v, **extra}[m.group(1)]), s)
        if wf_ids is not None:
            s = re.sub(r"__WF:([^_]+)__", lambda m: wf_ids[m.group(1)], s)
        if cred_ids is not None:
            s = re.sub(r"__CRED:([^_]+)__", lambda m: cred_ids[m.group(1)], s)
        return re.sub("__NEWID__", lambda m: str(uuid.uuid4()), s)

    def walk(x):
        if isinstance(x, dict):
            return {k: walk(val) for k, val in x.items()}
        if isinstance(x, list):
            return [walk(val) for val in x]
        return one(x) if isinstance(x, str) else x
    return walk(obj)


NODE_REF = re.compile(r"\$\('([^']+)'\)")


def strings(x):
    if isinstance(x, dict):
        for v in x.values():
            yield from strings(v)
    elif isinstance(x, list):
        for v in x:
            yield from strings(v)
    elif isinstance(x, str):
        yield x


def plan(cfg, extra=None):
    """-> (workflows with values filled in except ids, the creation order, the credentials they use)."""
    on, manifest = modules(cfg)
    locale = load_json(os.path.join(WF_DIR, "locales", "en.json"))
    own = os.path.join(WF_DIR, "locales", "%s.json" % cfg.get("lang", "en"))
    if os.path.exists(own):
        mine = load_json(own)
        msgs = {**locale["messages"], **mine.get("messages", {})}
        locale = {**locale, **mine, "messages": msgs}
    locale["messages"] = dict(locale["messages"], doc_type_other=locale["doc_type_other"])
    v, js = values(cfg, on, locale)
    extra = dict(extra or {})
    extra.update(prompts(cfg, on, v, locale))
    extra.setdefault("EXPIRY_FIELD", 0)
    extra.setdefault("TAG_TELEGRAM", 0)
    extra.setdefault("TAG_WHATSAPP", 0)
    # the stream link carries the voice bridge's secret: filled in by install from the secrets file
    extra.setdefault("VOICE_STREAM_URL", "wss://%s/stream/SECRET" % ((cfg.get("calls") or {}).get("voice_host") or "voice.example.com"))
    wfs = strip_modules(templates(), on, manifest)
    for name, w in wfs.items():   # a node that reads another node which a turned-off module removed
        have = {n["name"] for n in w["nodes"]}
        for n in w["nodes"]:
            for s in strings(n["parameters"]):
                for ref in NODE_REF.findall(s):
                    if ref not in have and "try {" not in s:
                        raise Fail("%s / %s reads node %r, which is not installed" % (name, n["name"], ref))
    wfs = {n: substitute(w, v, js, locale["messages"], extra) for n, w in wfs.items()}
    refs = {n: set(re.findall(r"__WF:([^_]+)__", json.dumps(w))) for n, w in wfs.items()}
    for n, r in refs.items():
        if r - set(wfs):
            raise Fail("%s calls workflows that are not installed: %s" % (n, ", ".join(sorted(r - set(wfs)))))
    order, done = [], set()
    while len(order) < len(wfs):
        ready = sorted(n for n in wfs if n not in done and refs[n] <= done)
        if not ready:
            raise Fail("workflows call each other in a circle: %s" % ", ".join(sorted(set(wfs) - done)))
        order += ready
        done |= set(ready)
    creds = sorted({m for w in wfs.values() for m in re.findall(r"__CRED:([^_]+)__", json.dumps(w))})
    return wfs, order, creds, on, locale


# ---------------------------------------------------------------- n8n
class N8n:
    def __init__(self, base, key=None):
        self.base, self.key = base.rstrip("/"), key
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def call(self, method, path, body=None, ok=(200, 201)):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json", "Accept": "application/json"})
        if self.key and path.startswith("/api/"):
            req.add_header("X-N8N-API-KEY", self.key)
        try:
            with self.opener.open(req, timeout=60) as r:
                raw = r.read()
                status = r.status
        except urllib.error.HTTPError as e:
            raw, status = e.read(), e.code
        try:
            out = json.loads(raw or b"{}")
        except ValueError:
            out = {"raw": raw[:300].decode(errors="replace")}
        if status not in ok:
            raise Fail("n8n %s %s -> %s: %s" % (method, path, status, json.dumps(out)[:400]))
        return out


def bootstrap(a):
    n = N8n(a.n8n)
    password = open(a.password_file, encoding="utf-8").read().strip()
    settings = n.call("GET", "/rest/settings")["data"]
    if settings["userManagement"].get("showSetupOnFirstLoad"):
        n.call("POST", "/rest/owner/setup", {"email": a.email, "firstName": a.first_name, "lastName": a.last_name,
                                              "password": password})
        print("owner account created")
    else:
        n.call("POST", "/rest/login", {"emailOrLdapLoginId": a.email, "password": password})
    scopes = ["workflow:create", "workflow:read", "workflow:update", "workflow:delete", "workflow:list",
              "workflow:activate", "workflow:deactivate", "credential:create", "credential:list", "credential:delete",
              "execution:read", "execution:list"]
    key = n.call("POST", "/rest/api-keys", {"label": "junkyard-installer", "expiresAt": None, "scopes": scopes})
    raw = key["data"].get("rawApiKey")
    if not raw:
        raise Fail("n8n did not return the API key")
    fd = os.open(a.out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(raw)
    print("API key saved to", a.out)


HEADERS = {"Notify secret": ("X-Notify-Secret", "notify_secret", ""), "Mail secret": ("X-Mail-Secret", "mail_secret", ""),
           "Filebridge key": ("X-Bridge-Key", "filebridge_key", ""), "Downloads key": ("X-Bridge-Key", "downloads_key", ""),
           "Webtool key": ("X-Webtool-Key", "webtool_key", ""), "WAHA key": ("X-Api-Key", "waha_key", ""),
           "Paperless token": ("Authorization", "paperless_token", "Token "),
           "Karakeep token": ("Authorization", "karakeep_token", "Bearer ")}


def credential(name, cfg, sec):
    def need(k):
        if not sec.get(k):
            raise Fail("secrets file has no %s (needed for credential %s)" % (k, name))
        return sec[k]
    if name in HEADERS:
        header, key, prefix = HEADERS[name]
        return "httpHeaderAuth", {"name": header, "value": prefix + need(key)}
    if name == "OpenAI":
        data = {"apiKey": need("openai_api_key")}
        if cfg.get("openai_url"):
            data["url"] = cfg["openai_url"].rstrip("/")
        return "openAiApi", data
    if name == "Assistant database":
        db = cfg["assistant_db"]
        return "postgres", {"host": db["host"], "port": int(db.get("port", 5432)), "database": db["database"],
                            "user": db["user"], "password": need("assistant_db_password"), "ssl": "disable"}
    if name == "Telegram bot":
        return "telegramApi", {"accessToken": need("telegram_token")}
    if name == "SMTP":
        s = need("smtp")
        return "smtp", {"user": s["user"], "password": s["password"], "host": s["host"], "port": int(s.get("port", 465)),
                        "secure": bool(s.get("secure", True))}
    if name == "Twilio":
        t = need("twilio")
        return "twilioApi", {"authType": "authToken", "accountSid": t["account_sid"], "authToken": t["auth_token"]}
    if name == "Server ops (restricted SSH)":
        o = cfg["ssh_ops"]
        return "sshPrivateKey", {"host": o["host"], "port": int(o.get("port", 22)), "username": o.get("user", "root"),
                                 "privateKey": need("ssh_ops_private_key")}
    raise Fail("no recipe for credential %s" % name)


# ---------------------------------------------------------------- Paperless (archive)
def http_json(method, url, token, body=None, ok=(200, 201)):
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None, method=method,
                                 headers={"Authorization": "Token " + token, "Content-Type": "application/json",
                                          "Accept": "application/json; version=7"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            status, raw = r.status, r.read()
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read()
    if status not in ok:
        raise Fail("archive %s %s -> %s: %s" % (method, url, status, raw[:300].decode(errors="replace")))
    return json.loads(raw or b"{}")


def ensure(base, token, kind, name, body):
    found = http_json("GET", "%s/api/%s/?name__iexact=%s" % (base, kind, urllib.parse.quote(name)), token)
    hits = [x for x in found.get("results") or [] if x["name"].lower() == name.lower()]
    if hits:
        return hits[0]["id"]
    return http_json("POST", "%s/api/%s/" % (base, kind), token, dict(body, name=name))["id"]


ASSISTANT_PERMS = ["view_document", "add_document", "change_document", "view_documenttype", "view_tag",
                   "view_customfield", "view_note", "add_note", "view_paperlesstask"]


def archive_setup(cfg, sec, locale, secrets_path):
    """Document types, the expiry date field, the chat tags, and a limited 'assistant' user for n8n and the file
    bridge (never the admin): every new document is shared with it, and n8n hears about it by webhook."""
    base = cfg["paperless_admin_url"].rstrip("/")
    admin = sec.get("paperless_admin_token") or ""
    if not admin:
        raise Fail("the archive needs paperless_admin_token in the secrets file (the admin's API token)")
    for t in locale["doc_types"]:
        ensure(base, admin, "document_types", t, {"matching_algorithm": 0})
    field = ensure(base, admin, "custom_fields", locale["expiry_field"], {"data_type": "date"})
    tags = {c: ensure(base, admin, "tags", n, {"matching_algorithm": 0})
            for c, n in (("telegram", "Telegram"), ("whatsapp", "WhatsApp"))}
    users = http_json("GET", base + "/api/users/?username__iexact=assistant", admin).get("results") or []
    if users:
        uid = users[0]["id"]
        if not sec.get("paperless_token"):
            raise Fail("the archive user 'assistant' exists but paperless_token is missing from the secrets file")
    else:
        password = uuid.uuid4().hex + uuid.uuid4().hex
        uid = http_json("POST", base + "/api/users/", admin, {"username": "assistant", "password": password,
                                                              "is_superuser": False, "is_staff": False,
                                                              "user_permissions": ASSISTANT_PERMS})["id"]
        req = urllib.request.Request(base + "/api/token/", method="POST",
                                     data=json.dumps({"username": "assistant", "password": password}).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            sec["paperless_token"] = json.loads(r.read())["token"]
        save_private(secrets_path, sec)
        print("archive: user 'assistant' created; its token was added to the secrets file (paperless_token)")
    flows = {w["name"]: w for w in http_json("GET", base + "/api/workflows/", admin).get("results") or []}
    added = {"type": 2, "sources": [1, 2, 3, 4], "matching_algorithm": 0, "match": "", "is_insensitive": True}
    wanted = {
        "Share new documents with the assistant": {"type": 1, "assign_view_users": [uid], "assign_change_users": [uid]},
        "Tell the assistant about new documents": {"type": 4, "webhook": {
            "url": cfg.get("paperless_webhook_url", "http://n8n:5678/webhook/paperless-added"),
            "use_params": True, "as_json": True, "params": {"doc_id": "{{ doc_id }}"}, "body": None,
            "headers": {"X-Notify-Secret": sec["notify_secret"]}, "include_document": False}},
    }
    for order, (name, action) in enumerate(wanted.items()):
        body = {"name": name, "order": order, "enabled": True, "triggers": [added], "actions": [action]}
        if name in flows:
            http_json("PUT", "%s/api/workflows/%s/" % (base, flows[name]["id"]), admin, body)
        else:
            http_json("POST", base + "/api/workflows/", admin, body)
    return {"EXPIRY_FIELD": field, "TAG_TELEGRAM": tags["telegram"], "TAG_WHATSAPP": tags["whatsapp"]}


# ---------------------------------------------------------------- install
def install(a):
    cfg, sec = load_json(a.config), load_json(a.secrets)
    state = load_json(a.state) if os.path.exists(a.state) else {"credentials": {}, "workflows": {}}
    on, _ = modules(cfg)
    extra = {}
    if "archive" in on:
        locale = load_json(os.path.join(WF_DIR, "locales", "%s.json" % cfg.get("lang", "en")))
        extra = archive_setup(cfg, sec, {**load_json(os.path.join(WF_DIR, "locales", "en.json")), **locale}, a.secrets)
        print("archive: types, expiry field %(EXPIRY_FIELD)s, tags %(TAG_TELEGRAM)s/%(TAG_WHATSAPP)s" % extra)
    if "calls" in on:
        host = (cfg.get("calls") or {}).get("voice_host")
        if not host or not sec.get("voice_stream_secret"):
            raise Fail("calls need calls.voice_host in the config and voice_stream_secret in the secrets file")
        extra["VOICE_STREAM_URL"] = "wss://%s/stream/%s" % (check_text("calls.voice_host", host), sec["voice_stream_secret"])
    wfs, order, creds, on, _ = plan(cfg, extra)
    n = N8n(cfg.get("n8n_url", "http://127.0.0.1:5678"), open(a.key_file).read().strip())
    existing = {c["id"] for c in n.call("GET", "/api/v1/credentials?limit=250").get("data", [])}
    for name in creds:
        if state["credentials"].get(name) in existing and not a.update_credentials:
            continue
        if state["credentials"].get(name) in existing:
            n.call("DELETE", "/api/v1/credentials/%s" % state["credentials"][name])
        ctype, data = credential(name, cfg, sec)
        state["credentials"][name] = n.call("POST", "/api/v1/credentials", {"name": name, "type": ctype, "data": data})["id"]
        save_private(a.state, state)
        print("credential:", name)
    have = {w["id"] for w in n.call("GET", "/api/v1/workflows?limit=250").get("data", [])}
    for name in order:
        w = substitute(wfs[name], {}, {}, {}, {}, state["workflows"], state["credentials"])
        body = {"name": w["name"], "nodes": w["nodes"], "connections": w["connections"], "settings": w["settings"]}
        wid = state["workflows"].get(name)
        if wid in have:
            n.call("PUT", "/api/v1/workflows/%s" % wid, body)
        else:
            wid = n.call("POST", "/api/v1/workflows", body)["id"]
            state["workflows"][name] = wid
            save_private(a.state, state)
        n.call("POST", "/api/v1/workflows/%s/activate" % wid)    # in n8n 2.x this also publishes the new version
        print("workflow: %-16s %s" % (name, wid))
    removed = [nm for nm in state["workflows"] if nm not in wfs]
    for nm in removed:   # a module that was turned off
        wid = state["workflows"].pop(nm)
        if wid in have:
            n.call("POST", "/api/v1/workflows/%s/deactivate" % wid, ok=(200, 201, 400))
            print("turned off:", nm)
    save_private(a.state, state)
    print("done: %d workflows, modules: %s" % (len(order), ", ".join(sorted(on))))


def status(a):
    cfg = load_json(a.config)
    state = load_json(a.state)
    n = N8n(cfg.get("n8n_url", "http://127.0.0.1:5678"), open(a.key_file).read().strip())
    live = {w["id"]: w for w in n.call("GET", "/api/v1/workflows?limit=250").get("data", [])}
    bad = 0
    for name, wid in sorted(state["workflows"].items()):
        w = live.get(wid)
        ok = bool(w and w.get("active"))
        bad += not ok
        print("%-16s %s" % (name, "active" if ok else "NOT ACTIVE" if w else "MISSING"))
    sys.exit(1 if bad else 0)


def render(a):
    cfg = load_json(a.config)
    wfs, order, creds, on, _ = plan(cfg)
    os.makedirs(a.out, exist_ok=True)
    for name in order:
        with open(os.path.join(a.out, re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") + ".json"), "w",
                  encoding="utf-8") as f:
            json.dump(wfs[name], f, ensure_ascii=False, indent=1)
    print("order:", " -> ".join(order))
    print("credentials:", ", ".join(creds))


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("bootstrap")
    b.add_argument("--n8n", default="http://127.0.0.1:5678")
    b.add_argument("--email", required=True)
    b.add_argument("--password-file", required=True)
    b.add_argument("--first-name", default="Owner")
    b.add_argument("--last-name", default="Server")
    b.add_argument("--out", required=True)
    for name in ("install", "status", "render"):
        s = sub.add_parser(name)
        s.add_argument("--config", required=True)
        if name != "render":
            s.add_argument("--secrets", required=name == "install")
            s.add_argument("--state", default="/etc/junkyard/n8n-state.json")
            s.add_argument("--key-file", default="/etc/junkyard/n8n-api-key")
        if name == "install":
            s.add_argument("--update-credentials", action="store_true", help="re-create credentials from the secrets file")
        if name == "render":
            s.add_argument("--out", required=True)
    a = p.parse_args(argv)
    try:
        {"bootstrap": bootstrap, "install": install, "status": status, "render": render}[a.cmd](a)
    except Fail as e:
        print("ERROR:", e, file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
