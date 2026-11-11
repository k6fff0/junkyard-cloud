"""One fake server that plays WAHA, Paperless-ngx, Stirling-PDF, Telegram and OpenAI, and records every call.
It is the WhatsApp simulator: tests post WAHA-shaped webhooks to the bridge and read what came out here."""
import hashlib
import io
import json
import zipfile

from aiohttp import web

OWNER = "15550001111"
OWNER_LID = "987654321@lid"
SESSION = "default"
TG_TOKEN = "123:fake"
TG_CHAT = "4242"


def openapi():
    multi = {"type": "array", "items": {"type": "string", "format": "binary"}}
    one = {"type": "string", "format": "binary"}

    def op(summary, file_field, props, required=()):
        return {"post": {"summary": summary, "requestBody": {"content": {"multipart/form-data": {"schema": {
            "type": "object", "properties": {file_field: props.pop("_file"), **props}, "required": list(required)}}}}}}
    return {
        "paths": {
            "/api/v1/general/merge-pdfs": op("Merge PDFs", "fileInput", {"_file": multi, "sortType": {
                "type": "string", "enum": ["orderProvided", "byFileName"], "default": "orderProvided"}},
                ["sortType"]),
            "/api/v1/convert/img/pdf": op("Images to PDF", "fileInput", {"_file": multi, "fitOption": {
                "type": "string"}}),
            "/api/v1/convert/pdf/img": op("PDF to images", "fileInput", {"_file": one, "dpi": {"type": "integer"}}),
            "/api/v1/security/add-password": op("Add password", "fileInput", {"_file": one, "password": {
                "type": "string", "description": "the   password"}}, ["password"]),
            "/api/v1/misc/compress-pdf": {"post": {"summary": "Compress", "requestBody": {"content": {
                "multipart/form-data": {"schema": {"$ref": "#/components/schemas/Compress"}}}}}},
            "/api/v1/convert/url/pdf": op("URL to PDF", "fileInput", {"_file": one}),
            "/api/v1/general/{id}/thing": op("templated", "fileInput", {"_file": one}),
        },
        "components": {"schemas": {"Compress": {"type": "object", "properties": {
            "fileInput": {"type": "string", "format": "binary"}, "optimizeLevel": {"type": "integer", "default": 2}},
            "required": []}}},
    }


class Fake:
    def __init__(self):
        self.wa_sent = []          # {"text"} or {"file": name, "caption"}
        self.wa_files = {}         # name -> bytes served by WAHA
        self.tg_sent = []
        self.tg_files = {}         # file_id -> (path, bytes)
        self.docs = []             # archive documents
        self.tags = {}
        self.stirling_calls = []   # (path, [file names], {fields})
        self.openai_calls = []
        self.task_status = "SUCCESS"
        self.lid_lookups = 0
        self.app = web.Application(client_max_size=200 * 1024 * 1024)
        r = self.app.router
        r.add_post("/api/sendText", self.wa_text)
        r.add_post("/api/sendFile", self.wa_file)
        r.add_get("/api/files/{name}", self.wa_get)
        r.add_get("/api/{session}/lids/pn/{phone}", self.wa_lid)
        r.add_get("/api/documents/", self.pl_search)
        r.add_post("/api/documents/post_document/", self.pl_post)
        r.add_get("/api/documents/{id}/download/", self.pl_download)
        r.add_get("/api/documents/{id}/", self.pl_doc)
        r.add_get("/api/tasks/", self.pl_tasks)
        r.add_get("/api/tags/", self.pl_tags)
        r.add_post("/api/tags/", self.pl_tag_new)
        r.add_get("/v1/api-docs", self.api_docs)
        r.add_post("/api/v1/{group}/{op:.+}", self.stirling)
        r.add_post("/bot%s/sendMessage" % TG_TOKEN, self.tg_text)
        r.add_post("/bot%s/sendDocument" % TG_TOKEN, self.tg_doc)
        r.add_get("/bot%s/getFile" % TG_TOKEN, self.tg_getfile)
        r.add_get("/file/bot%s/{path:.+}" % TG_TOKEN, self.tg_download)
        r.add_post("/v1/chat/completions", self.openai)

    async def api_docs(self, req):
        return web.json_response(openapi())

    # ---- WAHA ----
    async def wa_text(self, req):
        b = await req.json()
        assert req.headers.get("X-Api-Key") == "waha-key"
        assert b["chatId"] == OWNER + "@c.us" and b["session"] == SESSION
        self.wa_sent.append({"text": b["text"]})
        return web.json_response({"id": "true_%s@c.us_T%d" % (OWNER, len(self.wa_sent))})

    async def wa_file(self, req):
        b = await req.json()
        self.wa_sent.append({"file": b["file"]["filename"], "caption": b["caption"]})
        return web.json_response({"id": "true_%s@c.us_OUT%d" % (OWNER, len(self.wa_sent))})

    async def wa_get(self, req):
        if req.headers.get("X-Api-Key") != "waha-key":
            return web.Response(status=401)
        data = self.wa_files.get(req.match_info["name"])
        return web.Response(body=data) if data is not None else web.Response(status=404)

    async def wa_lid(self, req):
        self.lid_lookups += 1
        return web.json_response({"lid": OWNER_LID, "pn": req.match_info["phone"] + "@c.us"})

    # ---- Paperless ----
    async def pl_search(self, req):
        sha = req.query.get("checksum__iexact")
        hits = [{"id": d["id"], "title": d["title"]} for d in self.docs if d["sha"] == sha]
        return web.json_response({"results": hits})

    async def pl_post(self, req):
        assert req.headers.get("Authorization") == "Token pl-token"
        form = await req.post()
        f = form["document"]
        data = f.file.read()
        self.docs.append({"id": len(self.docs) + 1, "title": form["title"], "name": f.filename, "data": data,
                          "sha": hashlib.sha256(data).hexdigest(), "tags": [int(form["tags"])]})
        return web.Response(text='"task-%d"' % len(self.docs))

    async def pl_download(self, req):
        d = self.docs[int(req.match_info["id"]) - 1]
        return web.Response(body=d["data"], content_type="application/pdf",
                            headers={"Content-Disposition": "attachment; filename*=UTF-8''%s" % "%D8%B9%D9%82%D8%AF.pdf"})

    async def pl_doc(self, req):
        return web.json_response({"title": self.docs[int(req.match_info["id"]) - 1]["title"]})

    async def pl_tasks(self, req):
        return web.json_response([{"status": self.task_status, "result": "broken file"}])

    async def pl_tags(self, req):
        name = req.query.get("name__iexact", "").lower()
        return web.json_response({"results": [{"id": i, "name": n} for n, i in self.tags.items() if n.lower() == name]})

    async def pl_tag_new(self, req):
        b = await req.json()
        self.tags[b["name"]] = len(self.tags) + 10
        return web.json_response({"id": self.tags[b["name"]], "name": b["name"]}, status=201)

    # ---- Stirling ----
    async def stirling(self, req):
        path = "/api/v1/%s/%s" % (req.match_info["group"], req.match_info["op"])
        form = await req.post()
        names, fields = [], {}
        for k, v in form.items():
            if hasattr(v, "filename"):
                names.append(v.filename)
            else:
                fields[k] = v
        self.stirling_calls.append((path, names, fields))
        stem = names[0].rsplit(".", 1)[0] if names else "out"
        if path.endswith("pdf/img"):
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as z:
                z.writestr("page_2.jpg", b"img2")
                z.writestr("page_1.jpg", b"img1")
            return web.Response(body=buf.getvalue(), content_type="application/zip")
        body = ("%%PDF fake %s %s" % (path, ",".join(names))).encode()
        return web.Response(body=body, content_type="application/pdf",
                            headers={"Content-Disposition": 'attachment; filename="%s_done.pdf"' % stem})

    # ---- Telegram ----
    async def tg_text(self, req):
        b = await req.json()
        self.tg_sent.append({"text": b["text"]})
        return web.json_response({"ok": True})

    async def tg_doc(self, req):
        form = await req.post()
        self.tg_sent.append({"file": form["document"].filename, "caption": form["caption"]})
        return web.json_response({"ok": True, "result": {"message_id": 77, "document": {
            "file_id": "OUT%d" % len(self.tg_sent), "file_name": form["document"].filename,
            "mime_type": "application/pdf"}}})

    async def tg_getfile(self, req):
        fid = req.query["file_id"]
        if fid not in self.tg_files:
            return web.json_response({"ok": False})
        return web.json_response({"ok": True, "result": {"file_path": self.tg_files[fid][0]}})

    async def tg_download(self, req):
        for path, data in self.tg_files.values():
            if path == req.match_info["path"]:
                return web.Response(body=data)
        return web.Response(status=404)

    # ---- OpenAI ----
    async def openai(self, req):
        b = await req.json()
        self.openai_calls.append(b)
        return web.json_response({"choices": [{"message": {"content": "Passport page. Expires 2030-01-01."}}]})

    # ---- helpers ----
    def texts(self):
        return [m["text"] for m in self.wa_sent if "text" in m]


def wa(fake, msg_id, body="", file=None, mime=None, filename=None, sender=None, forwarded=False, kind=None,
       reply_to=None):
    """A WAHA 'message' webhook as WAHA sends it."""
    sender = sender or OWNER + "@c.us"
    message = {}
    p = {"id": "false_%s_%s" % (sender, msg_id), "from": sender, "fromMe": False, "body": body, "hasMedia": False}
    if file is not None:
        name = "m-%s" % msg_id
        fake.wa_files[name] = file
        p["hasMedia"] = True
        p["media"] = {"url": "http://localhost:3000/api/files/%s" % name, "mimetype": mime, "filename": filename}
        message["imageMessage" if (mime or "").startswith("image/") else "documentMessage"] = {}
    if kind:
        message[kind] = {}
    if forwarded:
        message.setdefault("extendedTextMessage", {})["contextInfo"] = {"isForwarded": True}
    if reply_to:
        p["replyTo"] = {"id": reply_to}
    p["_data"] = {"Message": message}
    return {"event": "message", "payload": p}
