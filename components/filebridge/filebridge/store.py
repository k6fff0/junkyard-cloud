"""Every file that passes through the bridge, with a short ref (f<id>), in SQLite.

direction: in (the owner sent it) | out (the bot sent it) | tmp (a step kept on the server) | txt (a text
           that is collecting files)
claim:     who handles an incoming WhatsApp file: auto | caption | text. NULL = nobody yet.
           For txt rows: open while collecting, closed after.
"""
import os
import re
import sqlite3
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
  id INTEGER PRIMARY KEY, ts REAL NOT NULL, direction TEXT NOT NULL, channel TEXT NOT NULL,
  file_id TEXT, wa_id TEXT, name TEXT NOT NULL DEFAULT '', mime TEXT NOT NULL DEFAULT '',
  size INTEGER NOT NULL DEFAULT 0, caption TEXT NOT NULL DEFAULT '', media_group TEXT, message_id INTEGER,
  claim TEXT);
CREATE INDEX IF NOT EXISTS files_wa_loose ON files (channel, direction, claim, ts);
CREATE INDEX IF NOT EXISTS files_group ON files (media_group);
CREATE INDEX IF NOT EXISTS files_wa_id ON files (wa_id);
CREATE TABLE IF NOT EXISTS archived (sha TEXT PRIMARY KEY, ts REAL NOT NULL, ref TEXT NOT NULL);
"""


class Store:
    def __init__(self, data_dir, keep_days=3):
        self.keep = os.path.join(data_dir, "keep")
        os.makedirs(self.keep, exist_ok=True)
        self.keep_seconds = keep_days * 86400
        self.db = sqlite3.connect(os.path.join(data_dir, "bridge.db"), check_same_thread=False)
        self.db.executescript(SCHEMA)
        self.db.commit()

    def close(self):
        self.db.close()

    # ---- files ----
    def remember(self, direction, channel, name="", mime="", size=0, caption="", file_id=None, wa_id=None,
                 group=None, message_id=None, data=None, claim=None):
        cur = self.db.execute(
            "INSERT INTO files (ts,direction,channel,file_id,wa_id,name,mime,size,caption,media_group,message_id,claim) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (time.time(), direction, channel, file_id, wa_id, name or "", mime or "", size or 0, caption or "",
             group, message_id, claim))
        self.db.commit()
        ref = "f%d" % cur.lastrowid
        if data is not None:   # keep a copy: WhatsApp files and intermediate results have no other source
            self.cleanup()
            with open(self._path(cur.lastrowid), "wb") as f:
                f.write(data)
        return ref

    def _path(self, i):
        return os.path.join(self.keep, "f%d.bin" % i)

    def cleanup(self):
        now = time.time()
        for f in os.listdir(self.keep):
            p = os.path.join(self.keep, f)
            if now - os.path.getmtime(p) > self.keep_seconds:
                os.remove(p)

    def get(self, ref):
        """-> dict or None for f<id>."""
        m = re.fullmatch(r"f(\d+)", (ref or "").strip())
        if not m:
            return None
        r = self.db.execute("SELECT id,file_id,name,mime,size,caption,ts FROM files WHERE id=?",
                            (int(m.group(1)),)).fetchone()
        if not r:
            return None
        return dict(zip(("id", "file_id", "name", "mime", "size", "caption", "ts"), r))

    def local(self, i):
        p = self._path(i)
        if os.path.exists(p):
            with open(p, "rb") as f:
                return f.read()
        return None

    def ts(self, i):
        return self.db.execute("SELECT ts FROM files WHERE id=?", (i,)).fetchone()[0]

    def recent(self, days=3, limit=15):
        return self.db.execute(
            "SELECT id,ts,direction,name,caption,channel,claim FROM files WHERE ts>? "
            "AND direction IN ('in','out') ORDER BY id DESC LIMIT ?", (time.time() - days * 86400, limit)).fetchall()

    def group(self, group):
        return self.db.execute("SELECT id,name,caption,mime FROM files WHERE media_group=? ORDER BY id",
                               (group,)).fetchall()

    def by_wa_id(self, short_id):
        for i, name, wa_id in self.db.execute(
                "SELECT id,name,wa_id FROM files WHERE channel='whatsapp' AND wa_id IS NOT NULL "
                "ORDER BY id DESC LIMIT 200"):
            if str(wa_id).split("_")[-1] == short_id:
                return i, name
        return None

    # ---- WhatsApp grouping ----
    def loose(self, since, captioned=None, images_only=False, from_id=None, before_id=None):
        """Incoming WhatsApp files that nobody handles yet."""
        q = "SELECT id,ts,name,caption FROM files WHERE channel='whatsapp' AND direction='in' AND claim IS NULL AND ts>=?"
        a = [since]
        if captioned is True:
            q += " AND caption!=''"
        elif captioned is False:
            q += " AND caption=''"
        if images_only:
            q += " AND mime LIKE 'image/%'"
        if from_id is not None:
            q += " AND id>=?"
            a.append(from_id)
        if before_id is not None:
            q += " AND id<?"
            a.append(before_id)
        return self.db.execute(q + " ORDER BY id", a).fetchall()

    def caption_group(self, mine, since):
        """A captioned file takes itself plus the loose files with no words that came just before it."""
        return self.db.execute(
            "SELECT id,name FROM files WHERE channel='whatsapp' AND direction='in' AND claim IS NULL "
            "AND (id=? OR (caption='' AND ts>?)) ORDER BY id", (mine, since)).fetchall()

    def claim(self, ids, who):
        """Atomically take files that nobody handles yet. Returns the ids actually taken."""
        got = {i for i in ids
               if self.db.execute("UPDATE files SET claim=? WHERE id=? AND claim IS NULL", (who, i)).rowcount}
        self.db.commit()
        return got

    def is_claimed(self, i):
        return self.db.execute("SELECT claim FROM files WHERE id=?", (i,)).fetchone()[0] is not None

    def set_claim(self, i, value):
        self.db.execute("UPDATE files SET claim=? WHERE id=?", (value, i))
        self.db.commit()

    def open_text_since(self, since):
        return self.db.execute("SELECT 1 FROM files WHERE channel='whatsapp' AND direction='txt' AND claim='open' "
                               "AND ts>=?", (since,)).fetchone() is not None

    # ---- duplicate guard for the archive ----
    def start_archiving(self, sha, ref, window=900):
        """None if this file may be archived now, else the ref already being archived.
        No await between the check and the insert, so two callers can never both pass."""
        hit = self.db.execute("SELECT ref, ts FROM archived WHERE sha=?", (sha,)).fetchone()
        if hit and time.time() - hit[1] < window:
            return hit[0]
        self.db.execute("INSERT OR REPLACE INTO archived (sha, ts, ref) VALUES (?,?,?)", (sha, time.time(), ref))
        self.db.commit()
        return None
