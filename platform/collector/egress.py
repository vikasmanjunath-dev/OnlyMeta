"""Egress log: the exact JSON that crosses the boundary, with a canonical SHA-256 a judge can verify."""
from datetime import datetime, timezone

from collector.store import DB
from contracts.hashing import canonical_hash
import json


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class EgressLog:
    def __init__(self, db: DB):
        self.db = db

    def record(self, payload_id: str, status: str, payload_json: str, raw_id=None, matched=None):
        """Call inside db.tx() together with Outbox.enqueue so persist-before-send is atomic."""
        sha = canonical_hash(json.loads(payload_json))
        self.db.conn.execute(
            "INSERT INTO egress(payload_id,created_at,status,json,sha256,matched_pattern,raw_id) VALUES(?,?,?,?,?,?,?)",
            (payload_id, now_iso(), status, payload_json, sha, matched, raw_id))
        return sha

    def update_wire(self, payload_id: str, wire_json: str):
        """Replace stored JSON with the exact bytes about to be sent (sent_at / is_replay stamped)."""
        with self.db.lock:
            self.db.conn.execute("UPDATE egress SET json=? WHERE payload_id=?", (wire_json, payload_id))

    def mark(self, payload_ids, status: str, ack: bool = False):
        with self.db.tx() as c:
            for pid in payload_ids:
                c.execute("UPDATE egress SET status=?, ack_at=COALESCE(?, ack_at) WHERE payload_id=?",
                          (status, now_iso() if ack else None, pid))

    def mark_in_tx(self, payload_ids, status: str, why: str = None):
        """Same as mark() but for use INSIDE an open db.tx() (no nested transaction)."""
        for pid in payload_ids:
            self.db.conn.execute("UPDATE egress SET status=?, matched_pattern=COALESCE(?, matched_pattern) WHERE payload_id=?", (status, why, pid))

    def list(self, limit=50, status=None):
        sql = "SELECT * FROM egress " + ("WHERE status=? " if status else "") + "ORDER BY created_at DESC, rowid DESC LIMIT ?"
        rows = self.db.q(sql, ((status, limit) if status else (limit,)))
        return [dict(r) for r in rows]

    def sent_ids(self):
        return [r["payload_id"] for r in self.db.q("SELECT payload_id FROM egress WHERE status='SENT'")]
