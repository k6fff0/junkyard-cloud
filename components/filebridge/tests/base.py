import asyncio
import shutil
import tempfile
import unittest

from aiohttp.test_utils import TestClient, TestServer

from filebridge.bridge import Bridge
from filebridge.config import Config
from tests.fakes import OWNER, SESSION, TG_CHAT, TG_TOKEN, Fake

KEY = "k" * 32
FAST = dict(group_wait=0.2, wa_wait=0.3, wa_window=2.0, chain=0.6, text_wait=0.3, text_max=3.0, poll=0.05,
            archive_check_delay=0.1)


class BridgeTest(unittest.IsolatedAsyncioTestCase):
    """Starts the fake services and a bridge pointed at them."""
    settings = {}

    async def asyncSetUp(self):
        self.fake = Fake()
        self.fake_server = TestServer(self.fake.app)
        await self.fake_server.start_server()
        base = str(self.fake_server.make_url("")).rstrip("/")
        self.tmp = tempfile.mkdtemp()
        values = dict(bridge_key=KEY, data_dir=self.tmp, owner="Sam", lang="en",
                      waha_url=base, waha_key="waha-key", wa_session=SESSION, wa_owner=OWNER,
                      tg_token=TG_TOKEN, tg_chat=TG_CHAT, tg_api=base,
                      paperless_url=base, paperless_token="pl-token", stirling_url=base,
                      docs_url="https://docs.example.com", pdf_url="https://pdf.example.com",
                      openai_key="sk-test", openai_url=base + "/v1", **FAST)
        values.update(self.settings)
        self.cfg = Config(**values)
        self.bridge = Bridge(self.cfg)
        self.client = TestClient(TestServer(self.bridge.app()))
        await self.client.start_server()
        if self.cfg.stirling:          # the catalog loads in the background at start
            for _ in range(50):
                if self.bridge.catalog:
                    break
                await asyncio.sleep(0.02)

    async def asyncTearDown(self):
        await self.client.close()
        await self.fake_server.close()
        await asyncio.sleep(0)
        shutil.rmtree(self.tmp, ignore_errors=True)

    async def post(self, path, body, key=KEY):
        r = await self.client.post(path, json=body, headers={"X-Bridge-Key": key})
        return r.status, (await r.json() if r.status == 200 else None)

    async def wa(self, payload, delay=0.0):
        if delay:
            await asyncio.sleep(delay)
        return (await self.post("/wa-incoming", payload))[1]

    async def tool(self, action, arg1="", arg2=""):
        return (await self.post("/tool", {"action": action, "arg1": arg1, "arg2": arg2}))[1]

    async def settle(self, seconds=0.3):
        """Let background work (archive checks) finish."""
        await asyncio.sleep(seconds)
