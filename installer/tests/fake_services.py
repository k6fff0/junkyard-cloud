"""Plays WAHA (WhatsApp) and the OpenAI API for the installer's end-to-end test, and records every call.

OpenAI behaviour (chat completions, also streamed):
- a tool result is in the conversation  -> a short final answer that quotes it ("Done: <tool result>")
- the owner's last message starts with "remember"           -> calls add_note with the rest of the sentence
- the owner's last message starts with "remind me"          -> calls list_reminders
- a json_schema response is asked for (mail triage)         -> {"category": "important", ...}
- anything else                                             -> "Hello from the fake model."
GET /_log returns everything received; POST /_reset clears it.
POST /_wa_down {"down": true} makes sendText answer 422 like an unpaired WAHA session (until /_reset).
"""
import json
import time

from aiohttp import web

LOG = []
STATE = {"wa_down": False}


def record(kind, body):
    LOG.append({"kind": kind, "at": time.time(), "body": body})


async def wa_text(req):
    if req.headers.get("X-Api-Key") != "waha-test-key":
        return web.json_response({"error": "bad key"}, status=401)
    b = await req.json()
    if STATE["wa_down"]:
        record("wa_text_refused", b)
        return web.json_response({"statusCode": 422, "message": "Session status is not as expected"}, status=422)
    record("wa_text", b)
    return web.json_response({"id": "true_%s_OUT%d" % (b.get("chatId"), len(LOG))})


async def wa_lid(req):
    return web.json_response({"lid": "999000111@lid", "pn": req.match_info["phone"] + "@c.us"})


def last_user(messages):
    for m in reversed(messages):
        if m.get("role") == "user":
            c = m.get("content")
            return c if isinstance(c, str) else " ".join(p.get("text", "") for p in c if isinstance(p, dict))
    return ""


def answer(body):
    msgs = body.get("messages") or []
    if (body.get("response_format") or {}).get("type") == "json_schema":
        return {"content": json.dumps({"category": "important", "otp_code": "", "summary": "A client asks for the invoice."})}
    tool_results = [m for m in msgs if m.get("role") == "tool"]
    if tool_results:
        return {"content": "Done: " + str(tool_results[-1].get("content"))[:300]}
    text = last_user(msgs).strip()
    low = text.lower()
    tools = {t["function"]["name"] for t in body.get("tools") or [] if t.get("type") == "function"}
    if "remember" in low and "add_note" in tools:
        fact = text[low.index("remember") + len("remember"):].strip(" :,")
        return {"tool": "add_note", "args": {"text": fact}}
    if "remind me" in low and "list_reminders" in tools:
        return {"tool": "list_reminders", "args": {}}
    return {"content": "Hello from the fake model."}


async def chat(req):
    body = await req.json()
    record("openai_chat", {"model": body.get("model"), "stream": body.get("stream"),
                           "tools": [t["function"]["name"] for t in body.get("tools") or [] if t.get("type") == "function"],
                           "last_user": last_user(body.get("messages") or [])[:500],
                           "system": next((m.get("content") for m in body.get("messages") or []
                                           if m.get("role") == "system" and isinstance(m.get("content"), str)), "")[:200]})
    a = answer(body)
    if "tool" in a:
        msg = {"role": "assistant", "content": None, "tool_calls": [{"id": "call_%d" % len(LOG), "type": "function",
               "function": {"name": a["tool"], "arguments": json.dumps(a["args"])}}]}
        finish = "tool_calls"
    else:
        msg = {"role": "assistant", "content": a["content"]}
        finish = "stop"
    base = {"id": "chatcmpl-%d" % len(LOG), "created": int(time.time()), "model": body.get("model") or "fake"}
    usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
    if not body.get("stream"):
        return web.json_response({**base, "object": "chat.completion", "usage": usage,
                                  "choices": [{"index": 0, "message": msg, "finish_reason": finish}]})
    resp = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
    await resp.prepare(req)

    async def send(delta, fin=None):
        chunk = {**base, "object": "chat.completion.chunk",
                 "choices": [{"index": 0, "delta": delta, "finish_reason": fin}]}
        await resp.write(("data: %s\n\n" % json.dumps(chunk)).encode())
    if "tool_calls" in msg:
        tc = msg["tool_calls"][0]
        await send({"role": "assistant", "tool_calls": [{"index": 0, "id": tc["id"], "type": "function",
                                                         "function": {"name": tc["function"]["name"], "arguments": ""}}]})
        await send({"tool_calls": [{"index": 0, "function": {"arguments": tc["function"]["arguments"]}}]})
    else:
        await send({"role": "assistant", "content": msg["content"]})
    await send({}, finish)
    await resp.write(("data: %s\n\n" % json.dumps({**base, "object": "chat.completion.chunk", "choices": [],
                                                    "usage": usage})).encode())
    await resp.write(b"data: [DONE]\n\n")
    return resp


def responses_view(body):
    """The Responses API (what n8n's agent uses) seen as chat messages, so answer() works for both."""
    msgs, tools = [], []
    for item in body.get("input") or []:
        t = item.get("type", "message")
        if t == "message":
            c = item.get("content")
            text = c if isinstance(c, str) else " ".join(p.get("text", "") for p in c or [] if isinstance(p, dict))
            msgs.append({"role": item.get("role"), "content": text})
        elif t == "function_call_output":
            msgs.append({"role": "tool", "content": item.get("output")})
    for tl in body.get("tools") or []:
        if tl.get("type") == "function":
            tools.append({"type": "function", "function": {"name": tl["name"]}})
    return {"messages": msgs, "tools": tools, "response_format": (body.get("text") or {}).get("format")}


async def responses(req):
    body = await req.json()
    view = responses_view(body)
    record("openai_chat", {"model": body.get("model"), "stream": body.get("stream"), "api": "responses",
                           "tools": [t["function"]["name"] for t in view["tools"]],
                           "last_user": last_user(view["messages"])[:500],
                           "system": next((m["content"] for m in view["messages"] if m["role"] == "system"), "")[:200]})
    a = answer(view)
    n = len(LOG)
    if "tool" in a:
        out = [{"type": "function_call", "id": "fc_%d" % n, "call_id": "call_%d" % n, "name": a["tool"],
                "arguments": json.dumps(a["args"]), "status": "completed"}]
        text = ""
    else:
        out = [{"type": "message", "id": "msg_%d" % n, "role": "assistant", "status": "completed",
                "content": [{"type": "output_text", "text": a["content"], "annotations": []}]}]
        text = a["content"]
    return web.json_response({"id": "resp_%d" % n, "object": "response", "created_at": int(time.time()),
                              "status": "completed", "model": body.get("model"), "output": out, "output_text": text,
                              "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}})


async def other(req):
    body = None
    if req.method == "POST":
        try:
            body = await req.json()
        except Exception:
            body = None
    record("unhandled", {"method": req.method, "path": req.path, "body": body})
    return web.json_response({"error": "not faked"}, status=404)


async def get_log(req):
    return web.json_response(LOG)


async def reset(req):
    LOG.clear()
    STATE["wa_down"] = False
    return web.json_response({"ok": True})


async def wa_down(req):
    STATE["wa_down"] = bool((await req.json()).get("down"))
    return web.json_response({"ok": True})


app = web.Application(client_max_size=50 * 1024 * 1024)
app.add_routes([web.post("/api/sendText", wa_text), web.get("/api/{session}/lids/pn/{phone}", wa_lid),
                web.post("/v1/chat/completions", chat), web.post("/v1/responses", responses), web.get("/_log", get_log), web.post("/_reset", reset),
                web.post("/_wa_down", wa_down),
                web.route("*", "/{tail:.*}", other)])
web.run_app(app, port=9000, access_log=None)
