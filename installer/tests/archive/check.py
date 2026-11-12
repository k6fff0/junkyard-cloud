"""Runs the installer's archive setup twice against a real Paperless and checks it as the assistant user."""
import json
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
import jc_n8n  # noqa: E402

BASE = "http://127.0.0.1:18010"
work = sys.argv[1]
passed, failed = 0, []


def check(name, ok, detail=""):
    global passed
    if ok:
        passed += 1
        print("ok  ", name)
    else:
        failed.append(name)
        print("FAIL", name, detail)


def call(method, path, token, body=None, accept="application/json; version=9", form=None):
    headers = {"Authorization": "Token " + token, "Accept": accept}
    data = None
    if body is not None:
        data, headers["Content-Type"] = json.dumps(body).encode(), "application/json"
    if form is not None:
        data, headers["Content-Type"] = form
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:200]


req = urllib.request.Request(BASE + "/api/token/", method="POST", headers={"Content-Type": "application/json"},
                             data=json.dumps({"username": "admin", "password": "Admin-test-pass-123"}).encode())
admin = json.loads(urllib.request.urlopen(req, timeout=30).read())["token"]

# what broke the first real install: Paperless refuses old API versions
check("Paperless refuses API version 7 (the old installer's)", call("GET", "/api/tags/", admin,
      accept="application/json; version=7")[0] == 406)
# a tag the admin made before the installer ran (owned by the admin): the installer must share it
code, tag = call("POST", "/api/tags/", admin, {"name": "WhatsApp", "matching_algorithm": 0})
check("admin-owned tag made first", code == 201 and tag.get("owner") is not None, tag)

env = os.path.join(work, "filebridge.env")
with open(env, "w") as f:
    f.write("BRIDGE_KEY=x\nPAPERLESS_TOKEN=from secrets.json\n")
os.chmod(env, 0o600)
secrets = os.path.join(work, "secrets.json")
sec = {"paperless_admin_token": admin, "notify_secret": "notify-test-secret-0123456789abcdef"}
jc_n8n.save_private(secrets, sec)
cfg = {"paperless_admin_url": BASE, "filebridge_env": env}
locale = {**jc_n8n.load_json(os.path.join(jc_n8n.WF_DIR, "locales", "en.json")),
          **jc_n8n.load_json(os.path.join(jc_n8n.WF_DIR, "locales", "ar.json"))}
first = jc_n8n.archive_setup(cfg, sec, locale, secrets)
second = jc_n8n.archive_setup(cfg, jc_n8n.load_json(secrets), locale, secrets)
check("second run finds the same objects", first == second, (first, second))
token = jc_n8n.load_json(secrets).get("paperless_token", "")
check("assistant token saved", len(token) > 20)
check("file bridge env got the token, mode kept",
      "PAPERLESS_TOKEN=" + token in open(env).read().splitlines() and os.stat(env).st_mode & 0o777 == 0o600)
check("token line not repeated", open(env).read().count("PAPERLESS_TOKEN=") == 1)

code, tags = call("GET", "/api/tags/?page_size=100", token)
names = {t["name"] for t in tags.get("results", [])} if code == 200 else set()
check("assistant sees both chat tags", {"WhatsApp", "Telegram"} <= names, (code, names))
code, types = call("GET", "/api/document_types/?page_size=100", token)
check("assistant sees every document type", code == 200 and types["count"] == len(locale["doc_types"]),
      (code, types if code != 200 else types["count"]))
code, fields = call("GET", "/api/custom_fields/", token)
check("assistant sees the expiry field", code == 200 and first["EXPIRY_FIELD"] in [x["id"] for x in fields["results"]],
      (code, fields))
code, flows = call("GET", "/api/workflows/", admin)
check("both Paperless workflows exist once", code == 200 and sorted(w["name"] for w in flows["results"]) == [
      "Share new documents with the assistant", "Tell the assistant about new documents"], flows)

# the assistant uploads a document with the chat tag, exactly as the file bridge does
pdf = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj "
       b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n")
b = "jcboundary"
form = ("--%s\r\nContent-Disposition: form-data; name=\"tags\"\r\n\r\n%d\r\n" % (b, first["TAG_WHATSAPP"])).encode()
form += ("--%s\r\nContent-Disposition: form-data; name=\"document\"; filename=\"t.pdf\"\r\n"
         "Content-Type: application/pdf\r\n\r\n" % b).encode() + pdf + ("\r\n--%s--\r\n" % b).encode()
code, out = call("POST", "/api/documents/post_document/", token, form=(form, "multipart/form-data; boundary=" + b))
check("assistant can upload with the chat tag", code == 200, (code, out))

print("%d passed, %d failed" % (passed, len(failed)))
sys.exit(1 if failed else 0)
