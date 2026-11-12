"""The assistant's file tools, Telegram, settings and the operations catalog."""
import asyncio
import json
import unittest

from filebridge import catalog
from filebridge.config import Config
from filebridge.i18n import Messages
from tests.base import BridgeTest
from tests.fakes import TG_CHAT, openapi, wa

PDF = b"%PDF-1.4 x"


class ToolsTest(BridgeTest):
    async def test_catalog_hides_risky_operations(self):
        ops = self.bridge.catalog
        self.assertIn("general/merge-pdfs", ops)
        self.assertIn("misc/compress-pdf", ops)                # schema behind a $ref
        self.assertNotIn("convert/url/pdf", ops)                # would fetch from the network
        self.assertFalse(any("{" in k for k in ops))
        self.assertTrue(ops["general/merge-pdfs"]["multi"])

    async def test_ops_search(self):
        r = (await self.tool("ops", "password"))["result"]
        self.assertIn("security/add-password", r)
        self.assertIn("(required)", r)
        self.assertIn("No operation matches", (await self.tool("ops", "teleport"))["result"])

    async def test_run_merge_sends_result_on_whatsapp(self):
        await self.wa(wa(self.fake, 1, file=PDF, mime="application/pdf", filename="a.pdf"))
        self.bridge.store.db.execute("DELETE FROM archived")
        await self.wa(wa(self.fake, 2, file=PDF + b"2", mime="application/pdf", filename="b.pdf"))
        r = await self.tool("run", "general/merge-pdfs", json.dumps({"files": "f1 f2", "channel": "whatsapp"}))
        self.assertIn("Sent 1 file(s) to Sam on whatsapp", r["result"])
        call = [c for c in self.fake.stirling_calls if c[0].endswith("merge-pdfs")][0]
        self.assertEqual(call[1], ["a.pdf", "b.pdf"])
        self.assertEqual(call[2]["sortType"], "orderProvided")          # required default filled in
        self.assertEqual(self.fake.wa_sent[-1]["file"], "a_done.pdf")

    async def test_non_ascii_names_reach_stirling_as_ascii_and_come_back(self):
        await self.wa(wa(self.fake, 1, file=PDF, mime="application/pdf", filename="عقد الإيجار.pdf"))
        r = await self.tool("run", "misc/compress-pdf", json.dumps({"files": "f1", "send": False}))
        self.assertIn("Kept 1 file(s) on the server only", r["result"])
        self.assertTrue(self.fake.stirling_calls[-1][1][0].isascii())
        self.assertEqual(self.bridge.store.get("f2")["name"], "عقد الإيجار_done.pdf")

    async def test_run_checks_inputs(self):
        self.assertIn("No files given", (await self.tool("run", "misc/compress-pdf", "{}"))["result"])
        self.assertIn("Unknown operation", (await self.tool("run", "nope", "{}"))["result"])
        await self.wa(wa(self.fake, 1, file=PDF, mime="application/pdf", filename="a.pdf"))
        r = await self.tool("run", "security/add-password", json.dumps({"files": "f1"}))
        self.assertIn("Missing required parameters for security/add-password: password", r["result"])
        r = await self.tool("run", "misc/compress-pdf", json.dumps({"files": "f1 f1"}))
        self.assertIn("takes exactly one file", r["result"])

    async def test_recent_marks_auto_saved_files(self):
        await self.wa(wa(self.fake, 1, file=PDF, mime="application/pdf", filename="a.pdf"))
        r = (await self.tool("recent"))["result"]
        self.assertIn("in = Sam sent it", r)
        self.assertIn("f1 | in | whatsapp", r)
        self.assertIn("ALREADY SAVED", r)

    async def test_deliver_archive_document(self):
        await self.wa(wa(self.fake, 1, file=PDF, mime="application/pdf", filename="a.pdf"))
        r = await self.tool("deliver", "doc:1", json.dumps({"channel": "whatsapp"}))
        self.assertIn("Sent doc:1 to Sam on whatsapp", r["result"])
        self.assertEqual(self.fake.wa_sent[-1]["file"], "عقد.pdf")

    async def test_look_sends_pages_to_vision_model(self):
        await self.wa(wa(self.fake, 1, file=PDF + b" /Type /Page /Type /Page", mime="application/pdf",
                         filename="p.pdf"))
        r = await self.tool("look", "f1", json.dumps({"question": "when does it expire?"}))
        self.assertIn("Passport page", r["result"])
        call = self.fake.openai_calls[-1]
        self.assertEqual(call["model"], self.cfg.look_model)
        system = call["messages"][0]["content"]
        self.assertIn("Sam's personal assistant", system)
        self.assertIn("Write in English", system)
        images = [c for c in call["messages"][1]["content"] if c["type"] == "image_url"]
        self.assertEqual(len(images), 2)                       # 2 pages, ordered page_1, page_2

    async def test_render_returns_page_images(self):
        await self.wa(wa(self.fake, 1, file=PDF, mime="application/pdf", filename="p.pdf"))
        status, r = await self.post("/tool", {"action": "render", "arg1": "f1"})
        self.assertEqual(status, 200)
        self.assertTrue(r["images"][0].startswith("data:image/jpeg;base64,"))

    async def test_unknown_ref_fails_cleanly(self):
        self.assertIn("unknown file ref f99", (await self.tool("look", "f99"))["result"])

    async def test_health(self):
        r = await self.client.get("/health")
        j = await r.json()
        self.assertTrue(j["ok"] and j["whatsapp"] and j["telegram"] and j["archive"])
        self.assertGreater(j["operations"], 0)


class SlowStirlingTest(BridgeTest):
    """After a reboot Stirling took 4 minutes; the bridge gave up after 150 s and every file tool failed."""
    async def test_catalog_is_loaded_on_demand_and_never_given_up(self):
        self.bridge.catalog = {}
        self.fake.stirling_down = 1
        r = await self.tool("run", "convert/pdf/word", '{"ref":"f1"}')
        self.assertIn("not answering right now", r["result"])        # honest, not "Unknown operation"
        await self.tool("ops", "convert")                             # Stirling is up now: loaded on demand
        self.assertTrue(self.bridge.catalog)

    async def test_background_loader_keeps_trying(self):
        self.bridge.catalog = {}
        self.fake.stirling_down = 3
        await asyncio.wait_for(self.bridge.load_catalog(delay=0.01, longest=0.02), 5)
        self.assertTrue(self.bridge.catalog)


class TelegramTest(BridgeTest):
    async def tg(self, msg):
        msg.setdefault("chat", {"id": int(TG_CHAT)})
        return (await self.post("/incoming", {"message": msg}))[1]

    def file(self, fid, data, path):
        self.fake.tg_files[fid] = (path, data)

    async def test_document_with_no_caption_is_archived(self):
        self.file("F1", PDF, "documents/a.pdf")
        r = await self.tg({"message_id": 5, "document": {"file_id": "F1", "file_name": "a.pdf",
                                                           "mime_type": "application/pdf", "file_size": 10}})
        self.assertEqual(r["action"], "done")
        self.assertEqual(self.fake.docs[0]["tags"], [self.fake.tags["Telegram"]])
        self.assertIn("Saving it", self.fake.tg_sent[-1]["text"])

    async def test_album_with_no_caption_is_one_pdf(self):
        import asyncio
        for i in range(3):
            self.file("P%d" % i, b"jpg%d" % i, "photos/%d.jpg" % i)
        rs = await asyncio.gather(*[self.tg({"message_id": i, "media_group_id": "G", "photo": [
            {"file_id": "P%d" % i, "file_size": 4}]}) for i in range(3)])
        self.assertEqual(sorted(r["action"] for r in rs), ["done", "skip", "skip"])
        self.assertEqual(len(self.fake.docs), 1)

    async def test_caption_goes_to_assistant(self):
        r = await self.tg({"message_id": 1, "caption": "make it word", "document": {
            "file_id": "F", "file_name": "a.pdf", "mime_type": "application/pdf"}})
        self.assertEqual(r["action"], "agent")
        self.assertIn("file attached to this message: f1 (a.pdf)", r["text"])

    async def test_reply_to_file(self):
        r = await self.tg({"message_id": 2, "text": "compress it", "reply_to_message": {
            "message_id": 1, "document": {"file_id": "F", "file_name": "a.pdf"}}})
        self.assertIn("reply to file f1 (a.pdf)", r["text"])

    async def test_other_chats_are_ignored(self):
        r = await self.tg({"message_id": 1, "chat": {"id": 1}, "document": {"file_id": "F", "file_name": "a"}})
        self.assertEqual(r["action"], "skip")


class OnlyTelegramTest(BridgeTest):
    settings = {"waha_url": "", "waha_key": "", "wa_owner": ""}

    async def test_whatsapp_channel_falls_back_to_telegram(self):
        self.assertEqual(self.bridge.chan("whatsapp"), "telegram")
        self.assertEqual(self.bridge.chan(None), "telegram")


class UnitTest(unittest.TestCase):
    def test_config_needs_key_and_a_channel(self):
        with self.assertRaises(ValueError):
            Config.from_env({"BRIDGE_KEY": "short", "TG_TOKEN": "t", "TG_CHAT": "1"})
        with self.assertRaises(ValueError):
            Config.from_env({"BRIDGE_KEY": "x" * 32})
        cfg = Config.from_env({"BRIDGE_KEY": "x" * 32, "WAHA_URL": "http://waha:3000/", "WAHA_KEY": "k",
                               "WA_OWNER": "+1 (555) 000-1111", "WA_WAIT": "2.5"})
        self.assertEqual((cfg.wa_chat, cfg.waha_url, cfg.wa_wait, cfg.default_channel),
                         ("15550001111@c.us", "http://waha:3000", 2.5, "whatsapp"))

    def test_file_words(self):
        w = Messages("en").file_words
        self.assertTrue(w.search("Save these as one PDF"))
        self.assertTrue(w.search("والصور دي احفظها"))
        self.assertFalse(w.search("my password is wrong"))      # "word" only as a whole word
        self.assertFalse(w.search("call mom at 9"))

    def test_unknown_language_falls_back_to_english(self):
        self.assertTrue(Messages("xx")("video_not_archived").startswith("🎬 The archive"))
        self.assertEqual(Messages("xx").lang, "en")

    def test_locales_have_the_same_messages(self):
        self.assertEqual(set(Messages("ar").text), set(Messages("en").text))

    def test_catalog_parse_is_pure(self):
        ops = catalog.parse(openapi())
        self.assertEqual(ops["security/add-password"]["required"], ["password"])
        self.assertEqual(ops["security/add-password"]["params"]["password"]["desc"], "the password")
