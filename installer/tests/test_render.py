"""python -m unittest installer.tests.test_render   (from the repo root; no n8n needed)

The installer's own rules: modules, prompts, unsafe text, and leftovers."""
import copy
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import jc_n8n as j  # noqa: E402

BASE = j.load_json(os.path.join(os.path.dirname(j.HERE), "installer", "config.example.json"))


def cfg(**changes):
    c = copy.deepcopy(BASE)
    for k, v in changes.items():
        c[k] = v
    return c


def everything(w):
    return json.dumps(w, ensure_ascii=False)


class Render(unittest.TestCase):
    def test_no_token_is_left(self):
        wfs, order, creds, on, _ = j.plan(cfg())
        blob = "".join(everything(w) for w in wfs.values())
        self.assertNotRegex(blob, r"__(JC|JS|TJS)[_:]")
        self.assertEqual(len(order), len(wfs))

    def test_modules_decide_workflows_and_tools(self):
        wfs, _, creds, _, _ = j.plan(cfg(modules={"whatsapp": True}))
        self.assertEqual(set(wfs), {"Owner Message", "Notify Me", "Server Ops", "Guarded Action", "Assistant", "Notes",
                                    "Model Health", "WhatsApp In"})
        tools = {n["name"] for n in wfs["Assistant"]["nodes"] if n["type"].endswith("toolWorkflow")}
        self.assertIn("add_note", tools)
        self.assertNotIn("web_search", tools)
        self.assertNotIn("Telegram bot", creds)
        prompt = [n for n in wfs["Assistant"]["nodes"] if n["name"] == "Assistant"][0]["parameters"]["options"]["systemMessage"]
        self.assertNotIn("web_search", prompt)
        self.assertNotIn("archive", prompt.lower())
        self.assertNotIn("<!--", prompt)

    def test_archive_needs_files(self):
        with self.assertRaisesRegex(j.Fail, "archive needs files"):
            j.plan(cfg(modules={"whatsapp": True, "archive": True}))

    def test_a_chat_is_required(self):
        with self.assertRaisesRegex(j.Fail, "at least one chat"):
            j.plan(cfg(modules={"web": True}))

    def test_main_channel_must_be_on(self):
        with self.assertRaisesRegex(j.Fail, "main_channel telegram"):
            j.plan(cfg(modules={"whatsapp": True}, main_channel="telegram"))

    def test_unsafe_names_are_refused(self):
        bad = copy.deepcopy(BASE["owner"])
        bad["name"] = "Sam'); drop table x; --"
        with self.assertRaisesRegex(j.Fail, "owner.name"):
            j.plan(cfg(owner=bad))

    def test_profile_braces_cannot_run_as_code(self):
        o = copy.deepcopy(BASE["owner"])
        o["profile"] = ["likes {{ $env.SECRET }}"]
        wfs, *_ = j.plan(cfg(owner=o))
        prompt = [n for n in wfs["Assistant"]["nodes"] if n["name"] == "Assistant"][0]["parameters"]["options"]["systemMessage"]
        self.assertNotIn("{{ $env", prompt)

    def test_a_reference_to_a_removed_node_is_caught(self):
        templates = j.templates()
        a = templates["Assistant"]
        node = [n for n in a["nodes"] if n["name"] == "From Telegram?"][0]
        node["parameters"]["conditions"]["conditions"][0]["leftValue"] = "={{ $('Telegram Trigger').isExecuted }}"
        orig = j.templates
        j.templates = lambda: templates
        try:
            with self.assertRaisesRegex(j.Fail, "reads node 'Telegram Trigger'"):
                j.plan(cfg(modules={"whatsapp": True}))
        finally:
            j.templates = orig

    def test_arabic_messages_and_plural(self):
        c = cfg(lang="ar", modules=dict(BASE["modules"], calls=True),
                calls={"twilio_from": "+15550000000", "owner_phone": "+15550000001", "voice_host": "v.example.com"})
        wfs, *_ = j.plan(c)
        blob = everything(wfs["Docs Process"])
        self.assertIn("حُفظ المستند رقم", blob)
        self.assertIn("يومان", blob)                       # 2 days, in proper Arabic
        self.assertIn("Polly.Zeina", everything(wfs["Notify Me"]))   # the call reads in an Arabic voice
        self.assertIn("الأرجح أن رصيد OpenAI", everything(wfs["Model Health"]))

    def test_channels_follow_the_modules(self):
        wfs, *_ = j.plan(cfg(modules={"telegram": True}, main_channel="telegram",
                             telegram={"chat_id": "42"}))
        blob = everything(wfs["Notify Me"])
        self.assertIn('[\\"telegram\\"]', blob)
        self.assertNotIn("whatsapp", blob.lower().replace("whatsapp?", ""))


if __name__ == "__main__":
    unittest.main()
