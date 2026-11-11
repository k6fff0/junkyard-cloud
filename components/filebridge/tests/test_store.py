import os
import shutil
import tempfile
import time
import unittest

from filebridge.store import Store


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store = Store(self.tmp, keep_days=3)

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_file_has_one_owner(self):
        i = int(self.store.remember("in", "whatsapp", "a.jpg", "image/jpeg")[1:])
        self.assertEqual(self.store.claim([i], "text"), {i})
        self.assertEqual(self.store.claim([i], "auto"), set())       # the second handler gets nothing
        self.assertTrue(self.store.is_claimed(i))

    def test_archive_guard_blocks_the_same_file_for_15_minutes(self):
        self.assertIsNone(self.store.start_archiving("sha1", "f1"))
        self.assertEqual(self.store.start_archiving("sha1", "f2"), "f1")
        self.store.db.execute("UPDATE archived SET ts=?", (time.time() - 901,))
        self.assertIsNone(self.store.start_archiving("sha1", "f3"))

    def test_kept_copies_expire(self):
        ref = self.store.remember("in", "whatsapp", "a.pdf", data=b"x")
        i = int(ref[1:])
        self.assertEqual(self.store.local(i), b"x")
        old = time.time() - 4 * 86400
        os.utime(os.path.join(self.tmp, "keep", "f%d.bin" % i), (old, old))
        self.store.remember("in", "whatsapp", "b.pdf", data=b"y")        # any new copy cleans up
        self.assertIsNone(self.store.local(i))

    def test_loose_files_exclude_claimed_and_outgoing(self):
        a = int(self.store.remember("in", "whatsapp", "a.jpg", "image/jpeg")[1:])
        b = int(self.store.remember("in", "whatsapp", "b.pdf", "application/pdf", caption="hi")[1:])
        self.store.remember("out", "whatsapp", "c.pdf")
        self.store.claim([a], "auto")
        self.assertEqual([r[0] for r in self.store.loose(0)], [b])
        self.assertEqual(self.store.loose(0, captioned=False), [])
        self.assertEqual(self.store.loose(0, images_only=True), [])
