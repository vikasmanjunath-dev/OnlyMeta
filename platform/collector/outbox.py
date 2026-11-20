"""SQLite outbox. Persist BEFORE send; mark ACKED only after the SaaS lists the id in accepted or duplicates;
REJECTED rows are parked and never retried. payload_id is created once at enqueue time, so a retry (including
after kill -9 or a lost ACK) is the same payload and the SaaS dedups it."""
import time

from collector.store import DB

SEV_RANK = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


class Outbox:
    def __init__(self, db: DB):
        self.db = db

    def enqueue(self, payload_id: str, event_time: str, severity: str = "info"):
        """Call inside db.tx() together with EgressLog.record."""
        self.db.conn.execute("INSERT OR IGNORE INTO outbox(payload_id,event_time,state,created_at,sev) VALUES(?,?, 'PENDING', ?, ?)",
                             (payload_id, event_time, time.time(), SEV_RANK.get(severity, 0)))

    def make_room(self, cap: int, incoming_sev: int):
        """Backpressure. Call inside db.tx() BEFORE enqueue. Returns ('ok', None) when there is room, ('shed', victim_id)
        after evicting the least important pending row (lowest severity, then oldest), or ('refuse', None) when the
        incoming payload is itself the least important. Nothing is ever dropped silently: the caller records DROPPED."""
        n = self.db.conn.execute("SELECT COUNT(*) FROM outbox WHERE state='PENDING'").fetchone()[0]
        if n < cap:
            return "ok", None
        v = self.db.conn.execute("SELECT payload_id, sev FROM outbox WHERE state='PENDING' ORDER BY sev, event_time, rowid LIMIT 1").fetchone()
        if v is None or incoming_sev < v["sev"]:
            return "refuse", None
        self.db.conn.execute("UPDATE outbox SET state='DROPPED', last_error='backpressure' WHERE payload_id=?", (v["payload_id"],))
        return "shed", v["payload_id"]

    def oldest_pending_age(self) -> float:
        r = self.db.q("SELECT MIN(created_at) m FROM outbox WHERE state='PENDING'")[0]["m"]
        return max(0.0, time.time() - r) if r else 0.0

    def claim_batch(self, n: int = 50):
        """Oldest event-time first. Rows stay PENDING until ACKed (crash-safe)."""
        return self.db.q("SELECT o.payload_id, o.event_time, e.json FROM outbox o JOIN egress e USING(payload_id) "
                         "WHERE o.state='PENDING' ORDER BY o.event_time, o.rowid LIMIT ?", (n,))

    def mark_acked(self, ids):
        with self.db.tx() as c:
            for pid in ids:
                c.execute("UPDATE outbox SET state='ACKED' WHERE payload_id=?", (pid,))

    def mark_rejected(self, pid: str, reason: str):
        with self.db.tx() as c:
            c.execute("UPDATE outbox SET state='REJECTED', last_error=? WHERE payload_id=?", (reason, pid))

    def note_failure(self, ids, err: str):
        with self.db.tx() as c:
            for pid in ids:
                c.execute("UPDATE outbox SET attempts=attempts+1, last_error=? WHERE payload_id=?", (err[:200], pid))

    def depth(self) -> int:
        return self.db.q("SELECT COUNT(*) n FROM outbox WHERE state='PENDING'")[0]["n"]

    def counts(self) -> dict:
        return {r["state"]: r["n"] for r in self.db.q("SELECT state, COUNT(*) n FROM outbox GROUP BY state")}

    def purge_acked(self, older_than_s: int = 3600) -> int:
        with self.db.lock:
            return self.db.conn.execute("DELETE FROM outbox WHERE state='ACKED' AND created_at < ?",
                                        (time.time() - older_than_s,)).rowcount
