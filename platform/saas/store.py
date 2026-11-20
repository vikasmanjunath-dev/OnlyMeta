"""Per-region SQLite stores (data/saas_<region>.db). A tenant's rows live ONLY in its region's file: residency
is structural, not a filter. Every query takes tenant_id; there is no cross-tenant read path."""
import json
import os
import sqlite3
import threading
from contextlib import contextmanager

SCHEMA = """
CREATE TABLE IF NOT EXISTS events(
  tenant_id TEXT, payload_id TEXT, event_ts REAL, event_time TEXT, node TEXT, category TEXT, severity TEXT,
  cpu REAL, mem REAL, disk REAL, bandwidth_mbps REAL, latency_ms REAL, packet_loss REAL, auth_failures INT,
  is_replay INT, sha256 TEXT, payload_json TEXT,
  sent_ts REAL, received_ts REAL, stored_ts REAL, evaluated_ts REAL, published_ts REAL, dup_count INT DEFAULT 0,
  collector_id TEXT,
  PRIMARY KEY(tenant_id, payload_id));
CREATE INDEX IF NOT EXISTS ix_ev_node ON events(tenant_id, node, event_ts);
CREATE INDEX IF NOT EXISTS ix_ev_recv ON events(tenant_id, received_ts);
CREATE TABLE IF NOT EXISTS rejects(id INTEGER PRIMARY KEY AUTOINCREMENT, tenant_id TEXT, payload_id TEXT, reason TEXT, at REAL);
CREATE TABLE IF NOT EXISTS node_state(
  tenant_id TEXT, node TEXT, state TEXT, reasons TEXT, metrics TEXT, category TEXT, last_event_ts REAL, last_seen_ts REAL,
  recent TEXT, cpu_hi INT DEFAULT 0, stale INT DEFAULT 0, since_ts REAL, collector_id TEXT, PRIMARY KEY(tenant_id, node));
CREATE TABLE IF NOT EXISTS state_history(id INTEGER PRIMARY KEY AUTOINCREMENT, tenant_id TEXT, node TEXT, ts REAL,
  old TEXT, new TEXT, reasons TEXT);
CREATE TABLE IF NOT EXISTS collectors(tenant_id TEXT PRIMARY KEY, collector_id TEXT, version TEXT, config_status TEXT,
  last_seen_ts REAL, offline INT DEFAULT 0, offline_since REAL);
CREATE TABLE IF NOT EXISTS config(tenant_id TEXT PRIMARY KEY, version INT, doc TEXT);
CREATE INDEX IF NOT EXISTS ix_ev_eval ON events(evaluated_ts) WHERE evaluated_ts IS NULL;
CREATE TABLE IF NOT EXISTS fleet_collectors(
  tenant_id TEXT, collector_id TEXT, version TEXT, config_status TEXT, schema_version INT, first_seen_ts REAL, last_seen_ts REAL,
  offline INT DEFAULT 0, offline_since REAL, health TEXT, PRIMARY KEY(tenant_id, collector_id));
CREATE TABLE IF NOT EXISTS alerts(
  id INTEGER PRIMARY KEY AUTOINCREMENT, tenant_id TEXT, node TEXT, kind TEXT, signature TEXT, severity TEXT, title TEXT, reasons TEXT,
  first_ts REAL, last_ts REAL, count INT DEFAULT 1, state TEXT DEFAULT 'open', resolved_ts REAL, ack_by TEXT, ack_ts REAL, incident_id INTEGER);
CREATE INDEX IF NOT EXISTS ix_alert_open ON alerts(tenant_id, state, node);
CREATE TABLE IF NOT EXISTS anomalies(
  id INTEGER PRIMARY KEY AUTOINCREMENT, tenant_id TEXT, node TEXT, metric TEXT, kind TEXT DEFAULT 'zscore', onset_ts REAL, detected_ts REAL,
  value REAL, mean REAL, sigma REAL, z REAL, peak_z REAL, state TEXT DEFAULT 'open', closed_ts REAL, replay INT DEFAULT 0,
  payload_id TEXT, incident_id INTEGER, detail TEXT);
CREATE INDEX IF NOT EXISTS ix_anom ON anomalies(tenant_id, state, node);
CREATE TABLE IF NOT EXISTS incidents(
  id INTEGER PRIMARY KEY AUTOINCREMENT, tenant_id TEXT, kind TEXT, status TEXT DEFAULT 'open', severity TEXT, root_node TEXT,
  confidence REAL, title TEXT, summary TEXT, members TEXT, explanation TEXT, first_ts REAL, last_ts REAL, resolved_ts REAL,
  detected_ts REAL, ack_by TEXT, ack_ts REAL, peak_state TEXT);
CREATE INDEX IF NOT EXISTS ix_inc ON incidents(tenant_id, status);
CREATE TABLE IF NOT EXISTS incident_events(
  id INTEGER PRIMARY KEY AUTOINCREMENT, tenant_id TEXT, incident_id INTEGER, ts REAL, kind TEXT, detail TEXT);
CREATE INDEX IF NOT EXISTS ix_incev ON incident_events(tenant_id, incident_id);
CREATE TABLE IF NOT EXISTS remediations(
  id INTEGER PRIMARY KEY AUTOINCREMENT, tenant_id TEXT, incident_id INTEGER, node TEXT, action TEXT, params TEXT, status TEXT,
  risk TEXT, reversible INT, blast_radius INT, confidence REAL, policy TEXT, proposer TEXT, approvals TEXT, required_approvals INT DEFAULT 1,
  created_ts REAL, expires_ts REAL, executed_ts REAL, verify_due_ts REAL, verdict TEXT, rollback_of INTEGER, rolled_back_ts REAL,
  rationale TEXT, predicted TEXT, precondition TEXT, signature TEXT, pattern TEXT);
CREATE INDEX IF NOT EXISTS ix_rem ON remediations(tenant_id, status);
CREATE TABLE IF NOT EXISTS remediation_events(
  id INTEGER PRIMARY KEY AUTOINCREMENT, tenant_id TEXT, remediation_id INTEGER, ts REAL, actor TEXT, event TEXT, detail TEXT);
CREATE INDEX IF NOT EXISTS ix_remev ON remediation_events(tenant_id, remediation_id);
CREATE TABLE IF NOT EXISTS maintenance(id INTEGER PRIMARY KEY AUTOINCREMENT, tenant_id TEXT, node TEXT, label TEXT, start_ts REAL, end_ts REAL, reason TEXT,
  created_by TEXT, created_ts REAL, cancelled INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS webhook_log(id INTEGER PRIMARY KEY AUTOINCREMENT, tenant_id TEXT, hook TEXT, event TEXT, delivery_id TEXT, ts REAL, ok INT,
  http_status INT, attempts INT, error TEXT);
CREATE TABLE IF NOT EXISTS aiops_config(tenant_id TEXT PRIMARY KEY, doc TEXT, updated_ts REAL);
CREATE TABLE IF NOT EXISTS users(username TEXT PRIMARY KEY, tenant_id TEXT, role TEXT, salt BLOB, hash BLOB, disabled INT DEFAULT 0, created_ts REAL);
CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY, tenant_id TEXT, username TEXT, role TEXT, exp REAL, created_ts REAL);
CREATE TABLE IF NOT EXISTS api_keys(key_id TEXT PRIMARY KEY, tenant_id TEXT, secret TEXT, created_ts REAL, expires_ts REAL, revoked INT DEFAULT 0, label TEXT);
CREATE TABLE IF NOT EXISTS key_retirements(key_id TEXT PRIMARY KEY, tenant_id TEXT, expires_ts REAL, revoked INT DEFAULT 0);
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT, tenant_id TEXT, ts REAL, actor TEXT, action TEXT, detail TEXT, ip TEXT,
  prev_hash TEXT, hash TEXT);
CREATE INDEX IF NOT EXISTS ix_audit_t ON audit(tenant_id, id);
"""

MIGRATIONS = {"events": {"collector_id": "TEXT"}, "node_state": {"collector_id": "TEXT"}, "alerts": {"incident_id": "INTEGER"}}


class RegionStore:
    def __init__(self, path):
        self.path = str(path)
        self.conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.lock = threading.RLock()
        self._migrate()
        self.conn.executescript(SCHEMA)
        try:
            os.chmod(self.path, 0o600)                        # the file holds key material and password hashes
        except OSError:
            pass

    def _migrate(self):
        """Bring a database created by an older version up to date (additive columns only; never drops data)."""
        for table, cols in MIGRATIONS.items():
            have = {r[1] for r in self.conn.execute(f"PRAGMA table_info({table})")}
            if not have:
                continue                                       # fresh database: SCHEMA creates it complete
            for col, typ in cols.items():
                if col not in have:
                    self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")

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
            return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    def one(self, sql, args=()):
        r = self.q(sql, args)
        return r[0] if r else None


class Stores:
    def __init__(self, data_dir, regions):
        data_dir.mkdir(parents=True, exist_ok=True)
        self.by_region = {r: RegionStore(data_dir / f"saas_{r}.db") for r in sorted(regions)}

    def for_region(self, region) -> RegionStore:
        return self.by_region[region]

    def close(self):
        for s in self.by_region.values():
            s.conn.close()


def jl(x):
    return json.loads(x) if x else None
