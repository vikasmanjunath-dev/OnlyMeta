"""Local SQLite (WAL) shared by raw store, egress log and outbox. Everything here stays in Tier 1."""
import json
import sqlite3
import threading
import time
from contextlib import contextmanager

SCHEMA = """
CREATE TABLE IF NOT EXISTS raw(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, node TEXT, line TEXT, stored_at REAL);
CREATE TABLE IF NOT EXISTS egress(
  payload_id TEXT PRIMARY KEY, created_at TEXT, status TEXT, json TEXT, sha256 TEXT,
  ack_at TEXT, matched_pattern TEXT, raw_id INTEGER);
CREATE TABLE IF NOT EXISTS outbox(
  payload_id TEXT PRIMARY KEY, event_time TEXT, state TEXT, attempts INTEGER DEFAULT 0,
  last_error TEXT, created_at REAL, sev INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS ix_outbox_state ON outbox(state, event_time);
CREATE INDEX IF NOT EXISTS ix_egress_created ON egress(created_at);
"""


class DB:
    def __init__(self, path: str):
        self.conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.executescript(SCHEMA)
        cols = {r[1] for r in self.conn.execute("PRAGMA table_info(outbox)")}
        if "sev" not in cols:                                   # migrate a database created before backpressure existed
            self.conn.execute("ALTER TABLE outbox ADD COLUMN sev INTEGER DEFAULT 0")
        self.lock = threading.RLock()

    @contextmanager
    def tx(self):
        with self.lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                yield self.conn
                self.conn.execute("COMMIT")
            except BaseException:
                self.conn.execute("ROLLBACK")
                raise

    def q(self, sql, args=()):
        with self.lock:
            return self.conn.execute(sql, args).fetchall()


class RawStore:
    """Raw lines, LOCAL ONLY. Retention-limited. Secrets are visible here by design (the proof panel)."""

    def __init__(self, db: DB, retention_s: int = 3600):
        self.db, self.retention_s = db, retention_s

    def insert(self, ev: dict) -> int:
        with self.db.lock:
            cur = self.db.conn.execute("INSERT INTO raw(ts,node,line,stored_at) VALUES(?,?,?,?)",
                                       (ev["ts"].isoformat(), ev["node"], json.dumps(ev["raw"]), time.time()))
            return cur.lastrowid

    def get(self, raw_id):
        r = self.db.q("SELECT * FROM raw WHERE id=?", (raw_id,))
        return json.loads(r[0]["line"]) if r else None

    def recent(self, limit=50):
        return [{"id": r["id"], "ts": r["ts"], "node": r["node"], "line": json.loads(r["line"])}
                for r in self.db.q("SELECT * FROM raw ORDER BY id DESC LIMIT ?", (limit,))]

    def purge(self, now: float | None = None) -> int:
        cutoff = (now or time.time()) - self.retention_s
        with self.db.lock:
            return self.db.conn.execute("DELETE FROM raw WHERE stored_at < ?", (cutoff,)).rowcount
