"""python -m unittest test_mailwatch  (no mail server and no network needed)"""
import os
import tempfile
import unittest
from email.message import EmailMessage

TMP = tempfile.mkdtemp()
os.environ["DATA_DIR"] = TMP
import mailwatch as mw  # noqa: E402


def mail(subject="Hello", body="Your code is 482913", html=None, attach=None, sender="Bank <no-reply@bank.example>",
         to="me@example.com", msg_id="<1@bank.example>", unsubscribe=False):
    m = EmailMessage()
    m["From"], m["To"], m["Subject"], m["Message-ID"], m["Date"] = sender, to, subject, msg_id, "Tue, 10 Nov 2026 10:00:00 +0000"
    if unsubscribe:
        m["List-Unsubscribe"] = "<mailto:unsub@x.example>"
    if body is not None:
        m.set_content(body)
    if html:
        if body is None:
            m.set_content(html, subtype="html")
        else:
            m.add_alternative(html, subtype="html")
    if attach:
        m.add_attachment(b"%PDF", maintype="application", subtype="pdf", filename=attach)
    return m.as_bytes()


class Parse(unittest.TestCase):
    def test_plain_mail(self):
        p = mw.parse(mail(sender="Bank Alerts <No-Reply@Bank.example>", to="me@example.com, Other <o@example.com>"))
        self.assertEqual((p["from_name"], p["from_addr"]), ("Bank Alerts", "no-reply@bank.example"))
        self.assertEqual(p["to"], ["me@example.com", "o@example.com"])
        self.assertEqual(p["text"], "Your code is 482913")
        self.assertFalse(p["list_unsubscribe"])

    def test_html_only_mail_becomes_text_without_scripts(self):
        p = mw.parse(mail(body=None, html="<html><head><title>T</title><style>x{}</style></head><body>"
                                          "<p>Hi</p><script>steal()</script><div>Order shipped</div></body></html>"))
        self.assertIn("Hi", p["text"])
        self.assertIn("Order shipped", p["text"])
        self.assertNotIn("steal", p["text"])
        self.assertNotIn("x{}", p["text"])

    def test_attachments_are_listed_not_read(self):
        p = mw.parse(mail(attach="invoice-2026.pdf", unsubscribe=True))
        self.assertEqual(p["attachments"], ["invoice-2026.pdf"])
        self.assertTrue(p["list_unsubscribe"])

    def test_hidden_characters_and_length(self):
        p = mw.parse(mail(subject="Pay​ now‮", body="a" * 20000))
        self.assertEqual(p["subject"], "Pay now")
        self.assertEqual(len(p["text"]), mw.TEXT_LIMIT)

    def test_arabic_subject(self):
        self.assertEqual(mw.parse(mail(subject="رمز التحقق"))["subject"], "رمز التحقق")


class FakeImap:
    def __init__(self, mails):
        self.mails = mails            # uid -> raw

    def uid(self, cmd, *args):
        if cmd == "SEARCH":
            q = args[-1]
            uids = sorted(self.mails)
            if q.startswith("UID "):
                lo = int(q[4:].split(":")[0])
                uids = [u for u in uids if u >= lo] or [max(self.mails)]   # like IMAP: n:* returns the last one
            return "OK", [" ".join(map(str, uids)).encode()]
        if cmd == "FETCH":
            return "OK", [(b"1 (BODY[] {n}", self.mails[int(args[0])]), b")"]
        raise AssertionError(cmd)


class FetchNew(unittest.TestCase):
    def setUp(self):
        mw.state.clear()
        self.sent = []
        self._post = mw.post
        mw.post = lambda payload: self.sent.append(payload)

    def tearDown(self):
        mw.post = self._post

    def test_first_run_starts_from_now(self):
        box = FakeImap({1: mail(), 2: mail()})
        mw.fetch_new(box, "work", "v1")
        self.assertEqual(self.sent, [])                       # old mail is not news
        self.assertEqual(mw.state["work"], {"validity": "v1", "last": 2})

    def test_new_mail_is_sent_once_in_order(self):
        box = FakeImap({1: mail()})
        mw.fetch_new(box, "work", "v1")
        box.mails[2] = mail(subject="A", msg_id="<a@x>")
        box.mails[3] = mail(subject="B", msg_id=None)
        mw.fetch_new(box, "work", "v1")
        mw.fetch_new(box, "work", "v1")                       # nothing new: IMAP "3:*" returns 3 again
        self.assertEqual([m["subject"] for m in self.sent], ["A", "B"])
        self.assertEqual(self.sent[0]["type"], "mail")
        self.assertEqual(self.sent[1]["message_id"], "<uid-v1-3@work>")   # stable id when the mail has none

    def test_nothing_is_lost_when_n8n_is_down(self):
        box = FakeImap({1: mail()})
        mw.fetch_new(box, "work", "v1")
        box.mails[2] = mail(subject="Important")

        def down(payload):
            raise OSError("n8n is down")
        mw.post = down
        with self.assertRaises(OSError):
            mw.fetch_new(box, "work", "v1")
        self.assertEqual(mw.state["work"]["last"], 1)         # did not move past the unsent mail
        mw.post = lambda payload: self.sent.append(payload)
        mw.fetch_new(box, "work", "v1")
        self.assertEqual([m["subject"] for m in self.sent], ["Important"])

    def test_renumbered_mailbox_starts_again_from_now(self):
        box = FakeImap({1: mail(), 2: mail()})
        mw.fetch_new(box, "work", "v1")
        mw.fetch_new(box, "work", "v2")
        self.assertEqual(self.sent, [])
        self.assertEqual(mw.state["work"]["validity"], "v2")


if __name__ == "__main__":
    unittest.main()
