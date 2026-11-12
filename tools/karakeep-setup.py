#!/usr/bin/env python3
"""Makes the owner's Karakeep account and the API key the assistant uses, without a browser. Run on the server as
root while signups are still on (DISABLE_SIGNUPS=false), then turn signups off:

  sudo python3 /opt/junkyard/src/tools/karakeep-setup.py --email OWNER@EXAMPLE.COM --name "Owner"

The owner's password is karakeep_owner_password in the secrets file (made here if missing); the API key is saved
as karakeep_token. Nothing secret is printed. Safe to run again: an existing account is logged in, and a new key
is made only when karakeep_token is missing. Python 3.9+ standard library only.
"""
import argparse
import json
import os
import secrets
import string
import sys
import urllib.error
import urllib.request


def save(path, data):
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, path)


class Site:
    """Keeps cookies by hand: Karakeep's session cookie is Secure (its URL is https), and a cookie jar would never
    send it back to http://127.0.0.1."""
    def __init__(self, base):
        self.base, self.cookies = base.rstrip("/"), {}

    def post(self, path, body):
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "Origin": self.base})
        if self.cookies:
            req.add_header("Cookie", "; ".join("%s=%s" % kv for kv in self.cookies.items()))
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                status, raw, headers = r.status, r.read(), r.headers
        except urllib.error.HTTPError as e:
            status, raw, headers = e.code, e.read(), e.headers
        for c in headers.get_all("Set-Cookie") or []:
            name, _, value = c.split(";", 1)[0].partition("=")
            self.cookies[name.strip()] = value.strip()
        try:
            return status, json.loads(raw or b"{}")
        except ValueError:
            return status, {"raw": raw[:200].decode(errors="replace")}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--url", default="http://127.0.0.1:3010")
    p.add_argument("--email", required=True)
    p.add_argument("--name", default="Owner")
    p.add_argument("--secrets", default="/etc/junkyard/secrets.json")
    a = p.parse_args()
    sec = json.load(open(a.secrets, encoding="utf-8"))
    if not sec.get("karakeep_owner_password"):
        abc = string.ascii_letters + string.digits
        sec["karakeep_owner_password"] = "".join(secrets.choice(abc) for _ in range(28))
        save(a.secrets, sec)
    pw = sec["karakeep_owner_password"]
    site = Site(a.url)
    status, out = site.post("/api/auth/sign-up/email", {"email": a.email, "password": pw, "name": a.name})
    if status == 200:
        print("account created for", a.email)
    else:
        status, out = site.post("/api/auth/sign-in/email", {"email": a.email, "password": pw})
        if status != 200:
            sys.exit("could not sign up or sign in (%s): %s" % (status, json.dumps(out)[:200]))
        print("account exists, signed in")
    if sec.get("karakeep_token"):
        print("karakeep_token already in the secrets file: no new key")
        return
    status, out = site.post("/api/trpc/apiKeys.create", {"json": {"name": "assistant (n8n)"}})
    key = (((out.get("result") or {}).get("data") or {}).get("json") or {}).get("key") if status == 200 else None
    if not key:
        sys.exit("could not make the API key (%s): %s" % (status, json.dumps(out)[:200]))
    sec["karakeep_token"] = key
    save(a.secrets, sec)
    print("API key saved to the secrets file as karakeep_token")


if __name__ == "__main__":
    main()
