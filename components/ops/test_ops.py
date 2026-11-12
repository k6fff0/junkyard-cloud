"""python -m unittest test_ops  (no root, Docker or n8n needed)"""
import base64
import contextlib
import datetime
import importlib.machinery
import importlib.util
import io
import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
TMP = tempfile.mkdtemp()
os.environ.update(JC_OPS_CONFIG=os.path.join(TMP, "ops.json"), JC_OPS_STATE=os.path.join(TMP, "state"),
                  JC_OPS_LOG=os.path.join(TMP, "ops.log"))
loader = importlib.machinery.SourceFileLoader("jc_ops", os.path.join(HERE, "jc-ops"))
spec = importlib.util.spec_from_loader("jc_ops", loader)
ops = importlib.util.module_from_spec(spec)
loader.exec_module(ops)


def b64(obj):
    raw = obj if isinstance(obj, str) else json.dumps(obj)
    return base64.b64encode(raw.encode()).decode()


def later(minutes=60):
    return (datetime.datetime.now() + datetime.timedelta(minutes=minutes)).isoformat(timespec="minutes")


class Base(unittest.TestCase):
    def setUp(self):
        self.received, self.fail_notify, self.undelivered = [], False, False
        test = self

        class Notify(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if test.fail_notify or self.headers.get("X-Notify-Secret") != "s" * 32:
                    self.send_response(500)
                    self.end_headers()
                    return
                # like Notify Me: 200 with ok=false when no channel delivered (WhatsApp down)
                out = {"ok": False, "delivered": ""} if test.undelivered else {"ok": True, "delivered": "whatsapp"}
                if not test.undelivered:
                    test.received.append(body)
                raw = json.dumps(out).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), Notify)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        with open(os.path.join(TMP, "secret"), "w") as f:
            f.write("s" * 32 + "\n")
        self.write_config()
        with contextlib.suppress(FileNotFoundError):
            os.remove(ops.REMINDERS)

    def write_config(self, **extra):
        cfg = {"lang": "en", "restartable": ["homepage"], "disks": {"system": TMP},
               "default_channels": ["whatsapp"], "notify_url": "http://127.0.0.1:%d/" % self.srv.server_address[1],
               "notify_secret_file": os.path.join(TMP, "secret"), **extra}
        with open(ops.CONFIG, "w") as f:
            json.dump(cfg, f)

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()

    def say(self, *args, ssh=None):
        out = io.StringIO()
        old = os.environ.pop("SSH_ORIGINAL_COMMAND", None)
        if ssh is not None:
            os.environ["SSH_ORIGINAL_COMMAND"] = ssh
        try:
            with contextlib.redirect_stdout(out):
                ops.main(list(args))
        finally:
            os.environ.pop("SSH_ORIGINAL_COMMAND", None)
            if old is not None:
                os.environ["SSH_ORIGINAL_COMMAND"] = old
        return out.getvalue()


class Commands(Base):
    def test_only_fixed_actions(self):
        self.assertIn("REFUSED: unknown action", self.say("rm", "-rf", "/"))
        self.assertIn("REFUSED: bad characters", self.say("status;reboot"))
        self.assertIn("REFUSED: bad characters", self.say("ssh", ssh="cd /root ; status && reboot"))
        self.assertIn("REFUSED: bad characters", self.say("ssh", ssh="restart $(reboot)"))
        self.assertIn("REFUSED: unknown action", self.say("ssh", ssh="cd / ; status extra"))

    def test_ssh_prefix_from_n8n_is_removed(self):
        self.assertIn("no pending reminders", self.say("ssh", ssh="cd /home/x && remind_list"))
        self.assertIn("no pending reminders", self.say("ssh", ssh="cd / ; remind_list"))

    def test_restart_only_allowed_containers(self):
        self.assertIn("REFUSED: 'n8n' is not in the allowed list: homepage", self.say("restart", "n8n"))

    def test_status_reports_disks_without_a_shell(self):
        out = self.say("status")
        self.assertIn("disk system (%s):" % TMP, out)
        self.assertIn("containers:", out)


class Reminders(Base):
    def test_add_list_cancel(self):
        when = later()
        out = self.say("remind_add", when, b64({"text": "Call the bank", "channels": "whatsapp,call",
                                                 "repeat": "daily"}))
        self.assertIn("saved reminder #1 at %s via whatsapp, call, repeat daily: Call the bank" % when, out)
        self.assertIn("#1 %s via whatsapp, call, repeat daily: Call the bank" % when, self.say("remind_list"))
        self.assertIn("cancelled reminder #1", self.say("remind_cancel", "1"))
        self.assertIn("no pending reminders", self.say("remind_list"))
        self.assertIn("ERROR: no reminder with id 9", self.say("remind_cancel", "9"))

    def test_plain_text_uses_default_channels(self):
        self.assertIn("via whatsapp, repeat none: pay rent", self.say("remind_add", later(), b64("pay rent")))

    def test_checks(self):
        self.assertIn("in the past", self.say("remind_add", "2001-01-01T10:00", b64("x")))
        self.assertIn("bad time or text", self.say("remind_add", "tomorrow", b64("x")))
        self.assertIn("unknown channel(s) pigeon", self.say("remind_add", later(), b64({"text": "x", "channels": ["pigeon"]})))
        self.assertIn("repeat must be one of", self.say("remind_add", later(), b64({"text": "x", "repeat": "hourly"})))
        self.assertIn("empty reminder text", self.say("remind_add", later(), b64({"text": " "})))

    def test_same_time_and_words_is_one_reminder(self):
        when = later()
        self.say("remind_add", when, b64("Doctor at 5!"))
        self.assertIn("DUPLICATE: reminder #1", self.say("remind_add", when, b64("doctor at 5")))
        self.assertIn("saved reminder #2", self.say("remind_add", later(120), b64("doctor at 5")))


class Firing(Base):
    def due(self, item):
        d = {"next_id": 2, "items": [{"id": 1, "channels": ["whatsapp"], "repeat": "none", **item}]}
        ops.save(d)

    def test_due_reminder_is_sent_then_removed(self):
        past = (datetime.datetime.now() - datetime.timedelta(minutes=1)).isoformat(timespec="minutes")
        self.due({"when": past, "text": "Take medicine"})
        self.say("fire-reminders")
        self.assertEqual(self.received, [{"title": "⏰ Reminder", "message": "Take medicine", "priority": "important",
                                          "channels": ["whatsapp"]}])
        self.assertEqual(ops.load()["items"], [])

    def test_repeating_reminder_moves_to_next_time(self):
        past = (datetime.datetime.now() - datetime.timedelta(days=2, minutes=1))
        self.due({"when": past.isoformat(timespec="minutes"), "text": "Water plants", "repeat": "daily"})
        self.say("fire-reminders")
        nxt = datetime.datetime.fromisoformat(ops.load()["items"][0]["when"])
        self.assertGreater(nxt, datetime.datetime.now())
        self.assertLessEqual(nxt - datetime.datetime.now(), datetime.timedelta(days=1))
        self.assertEqual(len(self.received), 1)                 # missed days are not sent one by one

    def test_kept_when_n8n_is_down(self):
        past = (datetime.datetime.now() - datetime.timedelta(minutes=1)).isoformat(timespec="minutes")
        self.due({"when": past, "text": "Important"})
        self.fail_notify = True
        self.say("fire-reminders")
        self.assertEqual(len(ops.load()["items"]), 1)
        self.fail_notify = False
        self.say("fire-reminders")
        self.assertEqual(ops.load()["items"], [])

    def test_kept_when_no_channel_delivered(self):
        past = (datetime.datetime.now() - datetime.timedelta(minutes=1)).isoformat(timespec="minutes")
        self.due({"when": past, "text": "Call the bank"})
        self.undelivered = True                      # n8n took it, but WhatsApp was down
        self.say("fire-reminders")
        self.assertEqual(len(ops.load()["items"]), 1)
        self.assertIn("not delivered", open(ops.LOG, encoding="utf-8").read())
        self.undelivered = False
        self.say("fire-reminders")
        self.assertEqual(ops.load()["items"], [])

    def test_title_in_owner_language(self):
        self.write_config(lang="ar")
        past = (datetime.datetime.now() - datetime.timedelta(minutes=1)).isoformat(timespec="minutes")
        self.due({"when": past, "text": "موعد"})
        self.say("fire-reminders")
        self.assertEqual(self.received[0]["title"], "⏰ تذكير")


if __name__ == "__main__":
    unittest.main()
