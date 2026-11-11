"""voice-bridge: phone calls with the assistant. Twilio Media Streams <-> OpenAI Realtime.

Twilio connects to /stream/<secret> (websocket, g711 u-law 8 kHz). Audio is relayed both ways to the
OpenAI Realtime API. The voice model chats directly; anything that needs memory or actions goes to the
n8n assistant through the ask_assistant tool, so a call can do everything a chat can.

GET  /stream/<secret>    Twilio Media Stream (calls the server places, and allowed incoming calls)
POST /incoming/<secret>  Twilio voice webhook for calls TO the Twilio number: only the owner is answered
GET  /health
`python bridge.py selftest` checks the session settings and that audio comes back, without a phone.
"""
import asyncio
import base64
import json
import logging
import os
import sys
import time
from xml.sax.saxutils import quoteattr

import aiohttp
from aiohttp import web

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
STREAM_SECRET = os.environ.get("STREAM_SECRET", "")
N8N_SECRET = os.environ.get("N8N_SECRET", "")
N8N_URL = os.environ.get("N8N_URL", "http://n8n:5678/webhook/assistant")
REALTIME_URL = os.environ.get("REALTIME_URL", "wss://api.openai.com/v1/realtime")
PUBLIC_HOST = os.environ.get("PUBLIC_HOST", "")          # e.g. voice.example.com (the tunnel name)
ALLOWED_CALLER = os.environ.get("ALLOWED_CALLER", "")    # the owner's number, +15551234567
MODEL = os.environ.get("REALTIME_MODEL", "gpt-realtime-2.1-mini")
VOICE = os.environ.get("REALTIME_VOICE", "marin")
MAX_CALL_SECONDS = int(os.environ.get("MAX_CALL_SECONDS", "600"))
ASSISTANT = os.environ.get("ASSISTANT_NAME", "the assistant")
OWNER = os.environ.get("OWNER_NAME", "the owner")
OWNER_CALL = os.environ.get("OWNER_CALL_NAME", "") or OWNER       # what the assistant calls the owner
LANGUAGE = os.environ.get("CALL_LANGUAGE", "English")             # e.g. "Egyptian Arabic", "English"
# Noise: a phone noise filter, end of turn by meaning, and the assistant keeps talking unless the owner
# really talks over it for BARGE_IN_MS (a cough, a door, the air conditioner or someone nearby won't cut it off).
NOISE_REDUCTION = os.environ.get("NOISE_REDUCTION", "near_field")
VAD_EAGERNESS = os.environ.get("VAD_EAGERNESS", "low")
BARGE_IN_MS = int(os.environ.get("BARGE_IN_MS", "700"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("bridge")


def instructions():
    return (
        f"Your name is {ASSISTANT}. You are {OWNER}'s personal assistant, and you are talking to them now "
        "on a phone call.\n"
        f"- Always speak {LANGUAGE}, in a natural and friendly voice. Call them \"{OWNER_CALL}\".\n"
        "- Keep answers short: one or two sentences. This is a call, not a lecture.\n"
        "- For anything that needs an action, information about the server, a notification, a reminder, the "
        "archive, or something remembered from earlier chats: say a short line like \"one second\", then use "
        f"the ask_assistant tool with the whole request in {OWNER_CALL}'s own words, and then tell them the "
        "result briefly.\n"
        "- Never say something was done unless the tool said it was done. If the tool failed, say so plainly.\n"
        "- Answer small talk yourself, without the tool.\n"
        "- When they say goodbye, say goodbye briefly.")


TOOLS = [{
    "type": "function",
    "name": "ask_assistant",
    "description": "Send a request to the assistant's brain on the owner's server. It has the long-term chat "
                   "memory and all the tools (reminders, archive, files, downloads, notifications, server). "
                   "Returns the answer as text.",
    "parameters": {
        "type": "object",
        "properties": {"request": {"type": "string", "description": "The full request, in the caller's own words."}},
        "required": ["request"],
    },
}]


def session_update():
    return {"type": "session.update", "session": {
        "type": "realtime",
        "instructions": instructions(),
        "output_modalities": ["audio"],
        "audio": {
            "input": {"format": {"type": "audio/pcmu"},
                      "noise_reduction": {"type": NOISE_REDUCTION} if NOISE_REDUCTION else None,
                      "turn_detection": {"type": "semantic_vad", "eagerness": VAD_EAGERNESS,
                                         "create_response": True, "interrupt_response": False}},
            "output": {"format": {"type": "audio/pcmu"}, "voice": VOICE},
        },
        "tools": TOOLS,
        "tool_choice": "auto",
    }}


def opening(context):
    if context:
        return f"Start the call: greet {OWNER_CALL} briefly, then give them this message: {context}"
    return f"Start the call: greet {OWNER_CALL} briefly and ask what they need."


def openai_ws(session):
    return session.ws_connect(REALTIME_URL + "?model=" + MODEL,
                              headers={"Authorization": "Bearer " + OPENAI_API_KEY}, heartbeat=20)


async def ask_assistant(session, request):
    try:
        async with session.post(N8N_URL, json={"text": request, "channel": "voice"},
                                headers={"X-Notify-Secret": N8N_SECRET},
                                timeout=aiohttp.ClientTimeout(total=60)) as r:
            if r.status != 200:
                return "ERROR: assistant returned HTTP %s" % r.status
            return (await r.json()).get("output") or "ERROR: empty answer"
    except Exception as e:  # reported to the model, which tells the caller
        return "ERROR: %r" % (e,)


async def handle_stream(request):
    if not STREAM_SECRET or request.match_info["secret"] != STREAM_SECRET:
        return web.Response(status=403)
    tw = web.WebSocketResponse()
    await tw.prepare(request)
    started = time.time()
    stream_sid = None
    tasks = set()
    async with aiohttp.ClientSession() as session:
        async with openai_ws(session) as oa:
            await oa.send_json(session_update())

            async def run_tool(call_id, args):
                try:
                    req = json.loads(args or "{}").get("request", "")
                except ValueError:
                    req = ""
                log.info("tool ask_assistant: %s", req)
                out = await ask_assistant(session, req)
                log.info("tool result: %s", out[:200])
                await oa.send_json({"type": "conversation.item.create",
                                    "item": {"type": "function_call_output", "call_id": call_id, "output": out}})
                await oa.send_json({"type": "response.create"})

            async def from_twilio():
                nonlocal stream_sid
                async for msg in tw:
                    if msg.type != aiohttp.WSMsgType.TEXT:
                        continue
                    d = json.loads(msg.data)
                    ev = d.get("event")
                    if ev == "start":
                        stream_sid = d["start"]["streamSid"]
                        ctx = (d["start"].get("customParameters") or {}).get("context", "")
                        log.info("call started %s context=%r", d["start"].get("callSid"), ctx)
                        await oa.send_json({"type": "response.create", "response": {"instructions": opening(ctx)}})
                    elif ev == "media":
                        await oa.send_json({"type": "input_audio_buffer.append", "audio": d["media"]["payload"]})
                    elif ev == "stop":
                        break
                    if time.time() - started > MAX_CALL_SECONDS:
                        log.info("max call length reached")
                        break

            # play_until: when the audio already sent to Twilio finishes playing (g711 = 8000 bytes/s).
            # The model makes audio faster than real time, so "response done" says nothing about what was heard.
            barge = {"task": None, "play_until": 0.0, "item": None, "item_start": 0.0, "item_ms": 0}

            async def barge_in():
                try:
                    await asyncio.sleep(BARGE_IN_MS / 1000)
                except asyncio.CancelledError:
                    return
                barge["task"] = None
                now = time.time()
                if now < barge["play_until"]:
                    log.info("barge-in: the caller talked over the assistant, stopping its answer")
                    await oa.send_json({"type": "response.cancel"})
                    await tw.send_json({"event": "clear", "streamSid": stream_sid})
                    if barge["item"]:   # tell the model how much of its answer was actually heard
                        heard = int(max(0, min(barge["item_ms"], (now - barge["item_start"]) * 1000)))
                        await oa.send_json({"type": "conversation.item.truncate", "item_id": barge["item"],
                                            "content_index": 0, "audio_end_ms": heard})
                    barge["play_until"] = now
                    barge["item"] = None

            async def from_openai():
                async for msg in oa:
                    if msg.type != aiohttp.WSMsgType.TEXT:
                        continue
                    d = json.loads(msg.data)
                    t = d.get("type")
                    if t in ("response.output_audio.delta", "response.audio.delta") and stream_sid:
                        await tw.send_json({"event": "media", "streamSid": stream_sid, "media": {"payload": d["delta"]}})
                        now = time.time()
                        secs = len(base64.b64decode(d["delta"])) / 8000.0
                        if d.get("item_id") != barge["item"]:
                            barge["item"] = d.get("item_id")
                            barge["item_start"] = max(now, barge["play_until"])
                            barge["item_ms"] = 0
                        barge["item_ms"] += int(secs * 1000)
                        barge["play_until"] = max(now, barge["play_until"]) + secs
                    elif t == "input_audio_buffer.speech_started" and stream_sid:
                        # maybe the caller is cutting in: stop only if the speech lasts BARGE_IN_MS
                        if barge["task"]:
                            barge["task"].cancel()
                        barge["task"] = asyncio.create_task(barge_in())
                    elif t == "input_audio_buffer.speech_stopped":
                        if barge["task"]:
                            barge["task"].cancel()
                            barge["task"] = None
                    elif t == "response.output_item.done" and d["item"].get("type") == "function_call":
                        task = asyncio.create_task(run_tool(d["item"]["call_id"], d["item"].get("arguments")))
                        tasks.add(task)
                        task.add_done_callback(tasks.discard)
                    elif t == "error":
                        log.error("openai error: %s", json.dumps(d.get("error"))[:500])

            done, pending = await asyncio.wait(
                [asyncio.create_task(from_twilio()), asyncio.create_task(from_openai())],
                return_when=asyncio.FIRST_COMPLETED)
            for p in list(pending) + list(tasks):
                p.cancel()
    await tw.close()
    log.info("call ended after %ds", time.time() - started)
    return tw


async def incoming(request):
    """Calls TO the Twilio number: only the owner's own number is answered."""
    if not STREAM_SECRET or request.match_info["secret"] != STREAM_SECRET:
        return web.Response(status=403)
    form = await request.post()
    caller = form.get("From", "")
    if not ALLOWED_CALLER or not PUBLIC_HOST or caller != ALLOWED_CALLER:
        log.info("rejected inbound call from %s", caller)
        return web.Response(text="<Response><Reject/></Response>", content_type="text/xml")
    url = "wss://%s/stream/%s" % (PUBLIC_HOST, STREAM_SECRET)
    return web.Response(text="<Response><Connect><Stream url=%s/></Connect></Response>" % quoteattr(url),
                        content_type="text/xml")


async def health(request):
    return web.Response(text="ok")


def make_app():
    app = web.Application()
    app.add_routes([web.get("/health", health), web.get("/stream/{secret}", handle_stream),
                    web.post("/incoming/{secret}", incoming)])
    return app


async def selftest():
    """No phone involved: checks the session settings are accepted and audio comes back."""
    async with aiohttp.ClientSession() as session:
        async with openai_ws(session) as oa:
            await oa.send_json(session_update())
            await oa.send_json({"type": "response.create", "response": {"instructions": opening("")}})
            audio = 0
            async for msg in oa:
                d = json.loads(msg.data)
                t = d.get("type")
                if t in ("response.output_audio.delta", "response.audio.delta"):
                    audio += len(d["delta"])
                elif t == "error":
                    print("ERROR", json.dumps(d["error"]))
                elif t == "session.updated":
                    a = d["session"].get("audio", {})
                    print("session.updated", d["session"].get("model"), json.dumps(a.get("output")),
                          json.dumps(a.get("input", {}).get("turn_detection")))
                elif t == "response.done":
                    print("response.done status=%s audio_b64_chars=%d" % (d["response"].get("status"), audio))
                    break


def check_settings():
    missing = [k for k, v in (("OPENAI_API_KEY", OPENAI_API_KEY), ("N8N_SECRET", N8N_SECRET)) if not v]
    if len(STREAM_SECRET) < 24:
        missing.append("STREAM_SECRET (24+ random characters)")
    if missing:
        raise SystemExit("missing settings: " + ", ".join(missing))


if __name__ == "__main__":
    check_settings()
    if len(sys.argv) > 1 and sys.argv[1] == "selftest":
        asyncio.run(selftest())
    else:
        web.run_app(make_app(), host="0.0.0.0", port=8765, access_log=None)
