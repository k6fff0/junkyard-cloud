"""python -m unittest test_bridge  (no phone, Twilio or OpenAI needed)

A whole call is simulated: a fake Twilio side talks to the bridge over a websocket, and a fake OpenAI
Realtime server answers with audio, a tool call, and the caller cutting in."""
import asyncio
import base64
import json
import unittest

from aiohttp import web, WSMsgType
from aiohttp.test_utils import TestClient, TestServer

import bridge as b

SECRET = "s" * 32


class FakeRealtime:
    """Plays the OpenAI side. `script` reacts to what the bridge sends."""

    def __init__(self):
        self.got = []
        self.ws = None
        self.ready = asyncio.Event()
        self.app = web.Application()
        self.app.router.add_get("/v1/realtime", self.handle)
        self.app.router.add_post("/webhook/assistant", self.n8n)
        self.n8n_requests = []

    async def n8n(self, req):
        self.n8n_requests.append((await req.json(), req.headers.get("X-Notify-Secret")))
        return web.json_response({"output": "You have the dentist at 5."})

    async def handle(self, req):
        self.model = req.query.get("model")
        self.auth = req.headers.get("Authorization")
        ws = web.WebSocketResponse()
        await ws.prepare(req)
        self.ws = ws
        self.ready.set()
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                self.got.append(json.loads(msg.data))
        return ws

    async def send(self, obj):
        await self.ws.send_json(obj)

    def types(self):
        return [m["type"] for m in self.got]

    async def wait_for(self, kind, n=1, timeout=3):
        for _ in range(int(timeout / 0.02)):
            if self.types().count(kind) >= n:
                return [m for m in self.got if m["type"] == kind]
            await asyncio.sleep(0.02)
        raise AssertionError("never got %s; got %s" % (kind, self.types()))


class Call(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.oa = FakeRealtime()
        self.oa_server = TestServer(self.oa.app)
        await self.oa_server.start_server()
        base = str(self.oa_server.make_url("")).rstrip("/")
        b.REALTIME_URL = base.replace("http", "ws", 1) + "/v1/realtime"
        b.N8N_URL = base + "/webhook/assistant"
        b.STREAM_SECRET, b.N8N_SECRET, b.OPENAI_API_KEY = SECRET, "n" * 32, "sk-test"
        b.ASSISTANT, b.OWNER, b.OWNER_CALL, b.LANGUAGE = "Juno", "Sam Lee", "Sam", "Egyptian Arabic"
        b.ALLOWED_CALLER, b.PUBLIC_HOST, b.BARGE_IN_MS = "+15550001111", "voice.example.com", 60
        self.client = TestClient(TestServer(b.make_app()))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        await self.oa_server.close()

    async def start_call(self, context="Your backup failed"):
        tw = await self.client.ws_connect("/stream/" + SECRET)
        await self.oa.ready.wait()
        await tw.send_json({"event": "start", "start": {"streamSid": "MZ1", "callSid": "CA1",
                                                         "customParameters": {"context": context}}})
        return tw

    async def next_from_bridge(self, tw, event):
        while True:
            msg = await asyncio.wait_for(tw.receive(), 3)
            d = json.loads(msg.data)
            if d["event"] == event:
                return d

    async def test_session_settings_and_opening(self):
        tw = await self.start_call()
        first = (await self.oa.wait_for("session.update"))[0]["session"]
        self.assertEqual(self.oa.model, "gpt-realtime-2.1-mini")
        self.assertEqual(self.oa.auth, "Bearer sk-test")
        self.assertIn("Your name is Juno. You are Sam Lee's personal assistant", first["instructions"])
        self.assertIn("Always speak Egyptian Arabic", first["instructions"])
        td = first["audio"]["input"]["turn_detection"]
        self.assertEqual((td["type"], td["interrupt_response"]), ("semantic_vad", False))
        self.assertEqual(first["audio"]["input"]["noise_reduction"], {"type": "near_field"})
        self.assertEqual(first["tools"][0]["name"], "ask_assistant")
        opening = (await self.oa.wait_for("response.create"))[0]["response"]["instructions"]
        self.assertEqual(opening, "Start the call: greet Sam briefly, then give them this message: Your backup failed")
        await tw.close()

    async def test_audio_flows_both_ways(self):
        tw = await self.start_call()
        await tw.send_json({"event": "media", "media": {"payload": "AAAA"}})
        self.assertEqual((await self.oa.wait_for("input_audio_buffer.append"))[0]["audio"], "AAAA")
        await self.oa.send({"type": "response.output_audio.delta", "item_id": "i1",
                            "delta": base64.b64encode(b"\xff" * 800).decode()})
        media = await self.next_from_bridge(tw, "media")
        self.assertEqual(media["streamSid"], "MZ1")
        await tw.close()

    async def test_tool_call_reaches_n8n_and_the_answer_goes_back(self):
        tw = await self.start_call()
        await self.oa.wait_for("response.create")
        await self.oa.send({"type": "response.output_item.done", "item": {
            "type": "function_call", "call_id": "c1", "arguments": json.dumps({"request": "what's today?"})}})
        out = (await self.oa.wait_for("conversation.item.create"))[0]["item"]
        self.assertEqual(out, {"type": "function_call_output", "call_id": "c1", "output": "You have the dentist at 5."})
        await self.oa.wait_for("response.create", n=2)                 # asks the model to say the answer
        self.assertEqual(self.oa.n8n_requests, [({"text": "what's today?", "channel": "voice"}, "n" * 32)])
        await tw.close()

    async def test_caller_cutting_in_stops_the_answer(self):
        tw = await self.start_call()
        await self.oa.wait_for("response.create")
        await self.oa.send({"type": "response.output_audio.delta", "item_id": "i1",
                            "delta": base64.b64encode(b"\xff" * 16000).decode()})   # 2 seconds of speech
        await self.next_from_bridge(tw, "media")
        await self.oa.send({"type": "input_audio_buffer.speech_started"})
        cancel = await self.oa.wait_for("response.cancel")
        self.assertEqual(len(cancel), 1)
        trunc = (await self.oa.wait_for("conversation.item.truncate"))[0]
        self.assertEqual(trunc["item_id"], "i1")
        self.assertLess(trunc["audio_end_ms"], 2000)                     # only what was heard
        self.assertEqual((await self.next_from_bridge(tw, "clear"))["streamSid"], "MZ1")
        await tw.close()

    async def test_a_cough_does_not_stop_the_answer(self):
        tw = await self.start_call()
        await self.oa.wait_for("response.create")
        await self.oa.send({"type": "response.output_audio.delta", "item_id": "i1",
                            "delta": base64.b64encode(b"\xff" * 16000).decode()})
        await self.next_from_bridge(tw, "media")
        await self.oa.send({"type": "input_audio_buffer.speech_started"})
        await self.oa.send({"type": "input_audio_buffer.speech_stopped"})   # shorter than BARGE_IN_MS
        await asyncio.sleep(0.2)
        self.assertNotIn("response.cancel", self.oa.types())
        await tw.close()

    async def test_wrong_secret(self):
        r = await self.client.get("/stream/wrong")
        self.assertEqual(r.status, 403)
        r = await self.client.post("/incoming/wrong", data={"From": "+15550001111"})
        self.assertEqual(r.status, 403)

    async def test_incoming_calls_only_from_the_owner(self):
        r = await self.client.post("/incoming/" + SECRET, data={"From": "+15559999999"})
        self.assertEqual(await r.text(), "<Response><Reject/></Response>")
        r = await self.client.post("/incoming/" + SECRET, data={"From": "+15550001111"})
        self.assertEqual(await r.text(), '<Response><Connect><Stream url="wss://voice.example.com/stream/%s"/>'
                                         '</Connect></Response>' % SECRET)


if __name__ == "__main__":
    unittest.main()
