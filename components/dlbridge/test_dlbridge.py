"""python -m unittest test_dlbridge  (no network, no aria2, no yt-dlp needed)"""
import json
import os
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer

import dlbridge as d


def public(_host):
    pass


class Classify(unittest.TestCase):
    video = staticmethod(lambda u: "youtube.com/watch" in u or "youtu.be/" in u)

    def kind(self, url, kind="auto"):
        return d.classify(url, kind, self.video, public)[0]

    def test_routes(self):
        self.assertEqual(self.kind("magnet:?xt=urn:btih:abc&dn=x"), "torrent")
        self.assertEqual(self.kind("https://x.org/a/ubuntu.iso"), "file")
        self.assertEqual(self.kind("https://x.org/a/film.torrent"), "torrent")
        self.assertEqual(self.kind("https://www.youtube.com/watch?v=abc"), "video")
        self.assertEqual(self.kind("https://x.org/page"), "file")
        self.assertEqual(self.kind("https://www.youtube.com/watch?v=abc", "file"), "file")
        self.assertEqual(self.kind("https://www.youtube.com/watch?v=abc", "audio"), "audio")  # only when asked
        self.assertEqual(self.kind("https://youtu.be/abc"), "video")                         # "download this" = video

    def test_refuses(self):
        for bad in ("", "ftp://x.org/a", "file:///etc/passwd", "magnet:?dn=no-hash", "https://a b", "javascript:x"):
            with self.assertRaises(d.Refused, msg=bad):
                self.kind(bad)

    def test_internal_addresses_are_refused(self):
        for host in ("127.0.0.1", "10.1.2.3", "172.20.0.1", "192.168.1.1", "169.254.169.254"):
            with self.assertRaises(d.Refused):
                d.classify(f"http://{host}/x.zip", "auto", None)
        d.resolve_public("1.1.1.1")  # a public address passes


class FakeAria2:
    def __init__(self):
        self.active, self.stopped, self.calls = [], [], []

    def call(self, method, *params):
        self.calls.append((method, params))
        if method == "tellActive":
            return self.active
        if method == "tellStopped":
            return self.stopped
        if method == "tellWaiting":
            return []
        if method == "getGlobalStat":
            return getattr(self, "global_stat", {"numActive": "0", "numWaiting": "0", "downloadSpeed": "0"})
        if method == "addUri":
            return "0123456789abcdef"
        if method == "tellStatus":
            return {"gid": params[0], "status": "active", "totalLength": "1000", "completedLength": "10",
                    "files": [{"path": "/downloads/Files/ubuntu.iso"}]}
        return "OK"


def task(gid, status, total=100, done=100, bt=False, **kw):
    t = {"gid": gid, "status": status, "totalLength": str(total), "completedLength": str(done),
         "files": [{"path": f"{d.ROOT}/Files/{gid}.bin"}], "dir": f"{d.ROOT}/Files"}
    if bt:
        t["bittorrent"] = {"info": {"name": f"Show {gid}"}}
        t["dir"] = f"{d.ROOT}/Torrents"
    t.update(kw)
    return t


class WatcherTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.aria = FakeAria2()
        self.videos = d.Videos(self.tmp.name)
        self.sent = []
        self.now = 1_000_000.0
        self.w = d.Watcher(self.aria, self.videos, lambda t, m: self.sent.append((t, m)), root=self.tmp.name,
                           alert_bytes=10_000, state_path=os.path.join(self.tmp.name, "state.json"),
                           clock=lambda: self.now)

    def tearDown(self):
        self.tmp.cleanup()

    def test_old_results_after_a_restart_are_not_sent(self):
        self.aria.stopped = [task("a" * 16, "complete")]
        self.w.check_downloads()
        self.assertEqual(self.sent, [])

    def test_finished_failed_and_seeding_are_sent_once(self):
        self.w.check_downloads()  # primed, nothing yet
        self.aria.stopped = [task("1" * 16, "complete"), task("2" * 16, "error", errorMessage="404 Not Found"),
                             task("3" * 16, "complete", followedBy=["4" * 16])]
        self.aria.active = [task("5" * 16, "active", bt=True), task("6" * 16, "active", done=40)]
        self.w.check_downloads()
        self.w.check_downloads()
        titles = [t for t, _ in self.sent]
        self.assertEqual(titles, ["✅ Download finished", "✅ Download finished", "❌ Download failed"])
        text = "\n".join(m for _, m in self.sent)
        self.assertIn("Show 5555555555555555", text)            # a torrent, done and now seeding
        self.assertIn("Downloads/Torrents", text)
        self.assertIn("404 Not Found", text)
        self.assertNotIn("3333", text)                          # metadata step, not the download
        self.assertNotIn("6666", text)                          # still downloading

    def test_messages_in_the_owners_language(self):
        w = d.Watcher(self.aria, self.videos, lambda t, m: self.sent.append((t, m)), root=self.tmp.name,
                      state_path=os.path.join(self.tmp.name, "ar.json"), lang="ar")
        w.check_downloads()
        self.aria.stopped = [task("1" * 16, "complete"), task("2" * 16, "error")]
        w.check_downloads()
        self.assertEqual(self.sent[0], ("✅ اكتمل التحميل", "1111111111111111.bin\nالحجم: 100 B\nالمكان: Downloads/Files"))
        self.assertEqual(self.sent[1], ("❌ فشل التحميل", "2222222222222222.bin\nالسبب: غير معروف"))

    def test_locales_have_the_same_keys(self):
        self.assertEqual(set(d.messages("ar")), set(d.messages("en")))
        self.assertEqual(d.messages("xx")["done"], "✅ Download finished")

    def test_a_refusing_server_gets_fewer_connections_then_a_failure_message(self):
        self.w.check_downloads()
        uri = [{"uris": [{"uri": "https://x.org/a.iso"}], "path": f"{d.ROOT}/Files/a.iso"}]
        for i, conns in enumerate(["2", "1"]):
            self.aria.stopped = [task(str(i) * 16, "error", files=uri, errorMessage="status=429")]
            self.w.check_downloads()
            adds = [p for m, p in self.aria.calls if m == "addUri"]
            self.assertEqual(adds[-1][1]["max-connection-per-server"], conns)
            self.assertEqual(adds[-1][1]["dir"], f"{d.ROOT}/Files")
        self.assertEqual(self.sent, [])                         # retrying is not news
        self.aria.stopped = [task("9" * 16, "error", files=uri, errorMessage="status=429")]
        self.w.check_downloads()
        self.assertEqual([t for t, _ in self.sent], ["❌ Download failed"])

    def test_folder_alert_once_a_day_and_again_after_dropping(self):
        big = os.path.join(self.tmp.name, "Files", "big.bin")
        os.makedirs(os.path.dirname(big))
        with open(big, "wb") as f:
            f.write(b"x" * 20_000)
        self.w.check_usage()
        self.w.check_usage()
        self.assertEqual(len(self.sent), 1)
        self.assertIn("Downloads space", self.sent[0][0])
        self.now += 25 * 3600
        self.w.check_usage()
        self.assertEqual(len(self.sent), 2)
        os.remove(big)
        self.w.check_usage()
        self.assertEqual(self.w.state["alerted_at"], 0)


class FakeProc:
    def __init__(self, lines, code=0):
        self.stdout, self.code = iter(lines), code

    def wait(self):
        return self.code

    def poll(self):
        return self.code


class VideoTest(unittest.TestCase):
    def run_job(self, lines, code=0):
        with tempfile.TemporaryDirectory() as tmp:
            lines = [l.replace("{tmp}", tmp) for l in lines]
            with open(os.path.join(tmp, "merged.mp4"), "wb") as f:
                f.write(b"x" * 5000)
            seen = {}
            v = d.Videos(tmp, runner=lambda cmd, **kw: seen.setdefault("cmd", cmd) and FakeProc(lines, code))
            jid = v.add("https://youtu.be/abc")[2:]
            for _ in range(100):
                if v.jobs[jid]["status"] in ("complete", "error"):
                    break
                threading.Event().wait(0.02)
            return v.jobs[jid], seen["cmd"]

    def test_success(self):
        # picture (4000) then sound (1000): the size reported is the merged file's (5000)
        job, cmd = self.run_job(["TITLE فيلم تجربة", "PROG 4000 4000 NA 10", "PROG 1000 1000 NA 10",
                                 "FILE {tmp}/merged.mp4"])
        self.assertEqual((job["status"], job["name"]), ("complete", "فيلم تجربة"))
        self.assertEqual(job["total"], 5000)
        self.assertEqual(cmd[-2:], ["--", "https://youtu.be/abc"])  # the link can never be read as an option
        self.assertIn("--no-playlist", cmd)

    def test_failure_keeps_the_reason(self):
        job, _ = self.run_job(["ERROR: [youtube] abc: Video unavailable"], code=1)
        self.assertEqual(job["status"], "error")
        self.assertIn("Video unavailable", job["error"])


class VideoMessages(unittest.TestCase):
    """Videos are not in the panel: a start message with the whole size, then the end one."""

    def test_start_then_end_message_and_the_mp3_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            gate = threading.Event()
            mp3 = os.path.join(tmp, "Audio", "song [abc].mp3")

            class Proc:
                def __init__(self, cmd):
                    self.cmd = cmd
                    self.stdout = self.lines()

                def lines(self):
                    yield "TITLE أغنية"
                    yield "SIZE 9000000"
                    yield "PROG 1000 4000000 NA 10"
                    gate.wait(5)
                    with open(mp3, "wb") as f:
                        f.write(b"x" * 3000)
                    yield "FILE " + mp3

                def wait(self):
                    return 0

                def poll(self):
                    return 0

            seen = {}
            v = d.Videos(tmp, runner=lambda cmd, **kw: seen.setdefault("p", Proc(cmd)))
            sent = []
            w = d.Watcher(FakeAria2(), v, lambda t, m: sent.append((t, m)), root=tmp,
                          state_path=os.path.join(tmp, "state.json"))
            w.check_downloads()
            v.add("https://youtu.be/abc", audio=True)
            for _ in range(100):
                if v.items() and v.items()[0]["size"] != "0 B":
                    break
                threading.Event().wait(0.02)
            w.check_downloads()
            w.check_downloads()
            self.assertEqual(sent, [("⬇️ Started downloading the audio", "أغنية\nSize: 9.0 MB\nSaved in: Downloads/Audio")])
            gate.set()
            for _ in range(100):
                if v.items()[0]["status"] == "complete":
                    break
                threading.Event().wait(0.02)
            w.check_downloads()
            self.assertEqual(sent[1], ("✅ Finished downloading the audio", "أغنية\nSize: 3 KB\nSaved in: Downloads/Audio"))
            cmd = seen["p"].cmd
            self.assertEqual(cmd[cmd.index("--audio-format") + 1], "mp3")
            self.assertEqual(cmd[cmd.index("-P") + 1], os.path.join(tmp, "Audio"))

    def test_a_video_link_is_a_video_unless_the_sound_is_asked_for(self):
        with tempfile.TemporaryDirectory() as tmp:
            v = d.Videos(tmp)
            cmd = v.command({"kind": "video", "url": "https://youtu.be/abc"})
            self.assertIn("--merge-output-format", cmd)
            self.assertIn("temp:" + os.path.join(tmp, ".incoming"), cmd)  # pieces never inside Videos
            self.assertEqual(cmd[cmd.index("-o") + 1], "%(title).150B [%(id)s].%(ext)s")
            song = v.command({"kind": "audio", "url": "https://youtu.be/abc"})
            self.assertTrue(song[song.index("-o") + 1].startswith("%(uploader|YouTube).80B/"))  # album folder
            self.assertIn("%(uploader|YouTube)s:%(meta_album)s", song)
            self.assertNotIn("-x", cmd)
            self.assertEqual(cmd[cmd.index("-P") + 1], os.path.join(tmp, "Videos"))


class HttpTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        aria = self.aria = FakeAria2()
        videos = d.Videos(self.tmp.name)
        w = d.Watcher(aria, videos, lambda *a: None, root=self.tmp.name, state_path=os.path.join(self.tmp.name, "s"))
        svc = d.Service(aria, videos, w, lambda u: False, resolve=public)
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), d.make_handler(svc, key="k" * 32))
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.tmp.cleanup()

    def req(self, path, body=None, key="k" * 32):
        r = urllib.request.Request(self.base + path, data=json.dumps(body).encode() if body is not None else None,
                                   headers={"X-Bridge-Key": key, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(r) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_key_is_required(self):
        self.assertEqual(self.req("/list", key="wrong")[0], 401)
        self.assertEqual(self.req("/health", key="")[0], 200)

    def test_status_is_numbers_only_and_needs_no_key(self):
        self.aria.global_stat = {"numActive": "2", "numWaiting": "1", "downloadSpeed": "5000000"}
        code, out = self.req("/status", key="")
        self.assertEqual(code, 200)
        self.assertEqual(set(out), {"active", "waiting", "speed", "used", "free"})
        self.assertEqual((out["active"], out["speed"]), (2, "5.0 MB/s"))

    def test_add_a_file(self):
        code, out = self.req("/add", {"url": "https://releases.ubuntu.com/ubuntu.iso"})
        self.assertEqual(code, 200)
        self.assertEqual((out["kind"], out["name"], out["id"]), ("file", "ubuntu.iso", "a:0123456789abcdef"))

    def test_bad_link_and_bad_control_are_400(self):
        self.assertEqual(self.req("/add", {"url": "file:///etc/passwd"})[0], 400)
        self.assertEqual(self.req("/control", {"id": "a:../../x", "action": "pause"})[0], 400)
        self.assertEqual(self.req("/control", {"id": "a:0123456789abcdef", "action": "pause"}),
                         (200, {"ok": True, "id": "a:0123456789abcdef"}))

    def test_control_by_part_of_the_name(self):
        self.aria.active = [task("1" * 16, "active", done=10, files=[{"path": "/downloads/Files/Debian-13.iso"}]),
                            task("2" * 16, "active", done=10, files=[{"path": "/downloads/Files/ubuntu.iso"}]),
                            task("3" * 16, "active", done=10, files=[{"path": "/downloads/Files/ubuntu-server.iso"}])]
        self.assertEqual(self.req("/control", {"match": "debian", "action": "cancel"}),
                         (200, {"ok": True, "id": "a:" + "1" * 16}))
        self.assertIn(("remove", ("1" * 16,)), self.aria.calls)
        code, out = self.req("/control", {"match": "ubuntu", "action": "pause"})
        self.assertEqual((code, out["error"]), (400, "2 downloads match; say more of the name"))
        self.assertEqual(self.req("/control", {"match": "fedora", "action": "pause"})[0], 400)


if __name__ == "__main__":
    unittest.main()
