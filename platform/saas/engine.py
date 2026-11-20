"""Ingest + evaluation engine. Deterministic (time is passed in) so it is fully testable.

ingest()  : validate -> residency -> dedup (PK) -> conflict check -> STORE (durable) -> ACK. Evaluation is queued.
drain()   : evaluate stored payloads (health, alerts, publish). Runs inline in tests, as a background worker in the
            server. If the process dies between store and evaluate, recover() re-queues every unevaluated row, so an
            acknowledged payload is never lost and never evaluated twice.
check_stale(): the stale-data rule (30 s of silence => POOR), per collector and per node.
purge()   : retention."""
import json
import re
import time
from collections import deque
from datetime import datetime
from typing import Callable, Optional

from pydantic import ValidationError

from contracts.hashing import canonical_hash
from contracts.schema import SUPPORTED_SCHEMA_VERSIONS, Payload
from saas.alerts import AlertManager
from saas.bus import Bus
from saas.health import RANK, STATES, classify, next_state
from saas.store import Stores, jl

FUTURE_TOLERANCE_S = 300
MAX_COLLECTORS_PER_TENANT = 50
COLLECTOR_ID = re.compile(r"^col-[a-z0-9][a-z0-9-]{0,40}$")


def _short_err(e: ValidationError) -> str:
    """Field and error type only: never echo submitted values back (they might be what we are rejecting)."""
    return "schema: " + "; ".join(f"{'.'.join(map(str, x['loc']))}:{x['type']}" for x in e.errors()[:3])


class Engine:
    def __init__(self, settings, stores: Stores, bus: Bus, sync_eval: bool = True):
        self.s, self.stores, self.bus, self.sync_eval = settings, stores, bus, sync_eval
        self.analysers: list[Callable] = []          # P3 hook: fn(tenant, sample: dict, store) -> [(state, reason)]
        # P3 hooks. A failing hook is counted and skipped: AIOps must never stall health evaluation.
        #   evaluated: fn(ctx) after every in-order sample.  stale: fn(ctx) when the stale rule fires.  tick: fn(now) from check_stale.
        self.hooks: dict[str, list] = {"evaluated": [], "stale": [], "tick": []}
        self.alerts = AlertManager(settings, bus)
        self.audit = None                            # set by the app
        self.pending: deque = deque()                # (tenant, payload_id) stored but not yet evaluated
        self.counters = {"batches": 0, "accepted": 0, "duplicates": 0, "rejected": 0, "conflicts": 0, "evaluated": 0, "hook_errors": 0}
        self._cids: dict[str, set] = {}

    def _run_hooks(self, kind: str, *args):
        for fn in self.hooks[kind]:
            try:
                fn(*args)
            except Exception as e:                                   # noqa: BLE001  (counted, never fatal)
                self.counters["hook_errors"] += 1
                print(f"hook {kind} error: {type(e).__name__}: {e}")

    def store_of(self, tenant: str):
        return self.stores.for_region(self.s.tenants[tenant]["region"])

    def _known_collectors(self, store, tenant) -> set:
        if tenant not in self._cids:
            self._cids[tenant] = {r["collector_id"] for r in store.q("SELECT collector_id FROM fleet_collectors WHERE tenant_id=?", (tenant,))}
        return self._cids[tenant]

    # ------------------------------------------------------------------ ingest
    def ingest(self, tenant: str, batch: list, now: Optional[float] = None) -> dict:
        recv = now if now is not None else time.time()
        region = self.s.tenants[tenant]["region"]
        store = self.store_of(tenant)
        acc, dup, rej, kept = [], [], [], []
        self.counters["batches"] += 1
        for item in batch:
            pid = item.get("payload_id", "?") if isinstance(item, dict) else "?"
            try:
                p = Payload(**item)
            except (ValidationError, TypeError) as e:
                rej.append(self._reject(store, tenant, str(pid), _short_err(e) if isinstance(e, ValidationError) else "schema: not an object", recv))
                continue
            why = self._policy(store, tenant, region, p, recv)
            if why:
                rej.append(self._reject(store, tenant, pid, why, recv))
                continue
            res = self._store_one(store, tenant, item, p, recv)
            if res == "conflict":
                self.counters["conflicts"] += 1
                if self.audit:
                    self.audit.record(tenant, "system", "payload_id_conflict", {"payload_id": str(p.payload_id), "collector_id": p.collector_id}, now=recv)
                rej.append(self._reject(store, tenant, pid, "payload_id_conflict (same id, different content)", recv))
                continue
            kept.append(p)
            (acc if res == "new" else dup).append(str(p.payload_id))
        self.counters["accepted"] += len(acc)
        self.counters["duplicates"] += len(dup)
        self.counters["rejected"] += len(rej)
        if kept:
            self._collectors_seen(store, tenant, kept, recv)
        if self.sync_eval:
            self.drain()
        return {"accepted": acc, "duplicates": dup, "rejected": rej}

    def _policy(self, store, tenant, region, p: Payload, recv: float) -> Optional[str]:
        if p.tenant_id != tenant:
            return "tenant_mismatch"
        if p.region != region:
            return "region_mismatch (data residency)"
        if p.schema_version not in SUPPORTED_SCHEMA_VERSIONS:
            return f"unsupported_schema_version (accepted: {list(SUPPORTED_SCHEMA_VERSIONS)})"
        if not COLLECTOR_ID.match(p.collector_id):
            return "invalid_collector_id"
        known = self._known_collectors(store, tenant)
        if p.collector_id not in known and len(known) >= MAX_COLLECTORS_PER_TENANT:
            return "too_many_collectors"
        if p.event_time.timestamp() - recv > FUTURE_TOLERANCE_S:
            return "event_time_in_future"
        return None

    def _reject(self, store, tenant, pid, reason, now):
        with store.tx() as c:
            c.execute("INSERT INTO rejects(tenant_id,payload_id,reason,at) VALUES(?,?,?,?)", (tenant, pid, reason, now))
        return {"id": pid, "reason": reason}

    def _store_one(self, store, tenant, item: dict, p: Payload, recv: float) -> str:
        m, pid, h = p.metrics, str(p.payload_id), canonical_hash(item)
        with store.tx() as c:
            cur = c.execute(
                "INSERT OR IGNORE INTO events(tenant_id,payload_id,event_ts,event_time,node,category,severity,cpu,mem,disk,"
                "bandwidth_mbps,latency_ms,packet_loss,auth_failures,is_replay,sha256,payload_json,sent_ts,received_ts,stored_ts,collector_id) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (tenant, pid, p.event_time.timestamp(), p.event_time.isoformat(), p.node_pseudonym, p.event_category, p.severity,
                 m.cpu, m.mem, m.disk, m.bandwidth_mbps, m.latency_ms, m.packet_loss, p.auth_failures_60s, int(p.is_replay),
                 h, json.dumps(item), p.sent_at.timestamp(), recv, time.time(), p.collector_id))
            if cur.rowcount == 0:
                old = c.execute("SELECT sha256 FROM events WHERE tenant_id=? AND payload_id=?", (tenant, pid)).fetchone()
                if old and old["sha256"] != h:                        # same id, different bytes: never overwrite, never ACK
                    return "conflict"
                c.execute("UPDATE events SET dup_count=dup_count+1 WHERE tenant_id=? AND payload_id=?", (tenant, pid))
                return "dup"                                           # idempotent: already stored, ACK again
        self.pending.append((tenant, pid))
        return "new"

    # ------------------------------------------------------------------ evaluation queue
    def drain(self, limit: Optional[int] = None) -> int:
        n = 0
        while self.pending and (limit is None or n < limit):
            tenant, pid = self.pending.popleft()
            store = self.store_of(tenant)
            row = store.one("SELECT payload_json, evaluated_ts FROM events WHERE tenant_id=? AND payload_id=?", (tenant, pid))
            if not row or row["evaluated_ts"] is not None:
                continue                                              # purged, or evaluated by a racing drain
            self._evaluate(store, tenant, Payload(**json.loads(row["payload_json"])), pid)
            self.counters["evaluated"] += 1
            n += 1
        return n

    def recover(self) -> int:
        """Start-up: re-queue anything stored but not yet evaluated (crash between store and evaluate)."""
        n = 0
        for tenant in self.s.tenants:
            for r in self.store_of(tenant).q("SELECT payload_id FROM events WHERE tenant_id=? AND evaluated_ts IS NULL ORDER BY received_ts, event_ts", (tenant,)):
                self.pending.append((tenant, r["payload_id"]))
                n += 1
        return n

    # ------------------------------------------------------------------ health
    def _evaluate(self, store, tenant: str, p: Payload, pid: str):
        node, ev_ts = p.node_pseudonym, p.event_time.timestamp()
        prev = store.one("SELECT * FROM node_state WHERE tenant_id=? AND node=?", (tenant, node))
        out_of_order = bool(prev and prev["last_event_ts"] is not None and ev_ts < prev["last_event_ts"])
        m = p.metrics.model_dump()
        if not out_of_order:
            streak = (prev["cpu_hi"] + 1 if prev else 1) if m["cpu"] > 95 else 0
            extra = []
            sample = {"node": node, "metrics": m, "auth_failures_60s": p.auth_failures_60s, "category": p.event_category,
                      "event_ts": ev_ts, "payload_id": pid, "is_replay": p.is_replay, "collector_id": p.collector_id,
                      "auth_source": p.auth_source_pseudonym}
            for fn in self.analysers:
                try:
                    extra += fn(tenant, sample, store) or []
                except Exception as e:                               # noqa: BLE001
                    self.counters["hook_errors"] += 1
                    print(f"analyser error: {type(e).__name__}: {e}")
            cand, reasons = classify(m, p.auth_failures_60s, p.event_category, streak, extra)
            recent = ((jl(prev["recent"]) if prev else []) + [cand])[-5:]
            was = prev["state"] if prev else None
            new = next_state(was, cand, recent)
            if new == was and cand != new:
                reasons = [f"recovering: {sum(RANK[c] < RANK[was] for c in recent[-3:])}/3 clean samples (held at {was})"]
            now = time.time()
            with store.tx() as c:
                c.execute("INSERT OR REPLACE INTO node_state(tenant_id,node,state,reasons,metrics,category,last_event_ts,last_seen_ts,"
                          "recent,cpu_hi,stale,since_ts,collector_id) VALUES(?,?,?,?,?,?,?,?,?,?,0,?,?)",
                          (tenant, node, new, json.dumps(reasons), json.dumps(m), p.event_category, ev_ts, now, json.dumps(recent), streak,
                           prev["since_ts"] if prev and new == was else now, p.collector_id))
                if new != was:
                    c.execute("INSERT INTO state_history(tenant_id,node,ts,old,new,reasons) VALUES(?,?,?,?,?,?)",
                              (tenant, node, now, was, new, json.dumps(reasons)))
            if new != was:
                self.bus.publish(tenant, "state", {"node": node, "old": was, "new": new, "reasons": reasons, "ts": now})
                self.alerts.on_transition(store, tenant, node, was, new, reasons, now)
            self._run_hooks("evaluated", {"tenant": tenant, "store": store, "node": node, "state": new, "was": was, "reasons": reasons,
                                          "sample": sample, "ts": ev_ts, "wall": now, "replay": p.is_replay, "changed": new != was})
        else:                                                      # old sample (replay): history only, never moves "now"
            with store.tx() as c:
                c.execute("UPDATE node_state SET last_seen_ts=?, stale=0 WHERE tenant_id=? AND node=?", (time.time(), tenant, node))
        evaluated = time.time()
        self.bus.publish(tenant, "sample", {"payload_id": pid, "node": node, "event_time": p.event_time.isoformat(),
                                            "category": p.event_category, "severity": p.severity, "metrics": m,
                                            "auth_failures_60s": p.auth_failures_60s, "is_replay": p.is_replay})
        published = time.time()
        with store.tx() as c:
            c.execute("UPDATE events SET evaluated_ts=?, published_ts=? WHERE tenant_id=? AND payload_id=?", (evaluated, published, tenant, pid))

    def _collectors_seen(self, store, tenant, kept: list, recv: float):
        latest: dict[str, Payload] = {}
        for p in kept:
            if p.collector_id not in latest or p.event_time >= latest[p.collector_id].event_time:
                latest[p.collector_id] = p
        for cid, p in latest.items():
            was = store.one("SELECT offline FROM fleet_collectors WHERE tenant_id=? AND collector_id=?", (tenant, cid))
            health = p.collector_health.model_dump() if p.collector_health else None
            with store.tx() as c:
                c.execute("INSERT INTO fleet_collectors(tenant_id,collector_id,version,config_status,schema_version,first_seen_ts,last_seen_ts,offline,health) "
                          "VALUES(?,?,?,?,?,?,?,0,?) ON CONFLICT(tenant_id,collector_id) DO UPDATE SET version=excluded.version, "
                          "config_status=excluded.config_status, schema_version=excluded.schema_version, last_seen_ts=excluded.last_seen_ts, "
                          "offline=0, offline_since=NULL, health=COALESCE(excluded.health, health)",
                          (tenant, cid, p.collector_version[:20], p.config_status, p.schema_version, recv, recv, json.dumps(health) if health else None))
            self._known_collectors(store, tenant).add(cid)
            if was and was["offline"]:
                self.alerts.on_collector(store, tenant, cid, False, 0, recv)
                self.bus.publish(tenant, "collector", {"collector_id": cid, "status": "online", "ts": recv})

    # ------------------------------------------------------------------ stale-data rule
    def check_stale(self, now: Optional[float] = None) -> list:
        """30 s without any payload from a collector => it is OFFLINE and its nodes are POOR; one node silent while its
        collector is alive is POOR too. Returns the transitions made: (tenant, who, what)."""
        now = now if now is not None else time.time()
        out = []
        for tenant in self.s.tenants:
            store = self.store_of(tenant)
            offline_ids = set()
            for col in store.q("SELECT * FROM fleet_collectors WHERE tenant_id=?", (tenant,)):
                silent = now - col["last_seen_ts"]
                if col["offline"]:
                    offline_ids.add(col["collector_id"])
                elif silent > self.s.offline_s:
                    with store.tx() as c:
                        c.execute("UPDATE fleet_collectors SET offline=1, offline_since=? WHERE tenant_id=? AND collector_id=?", (now, tenant, col["collector_id"]))
                    offline_ids.add(col["collector_id"])
                    self.alerts.on_collector(store, tenant, col["collector_id"], True, silent, now)
                    self.bus.publish(tenant, "collector", {"collector_id": col["collector_id"], "status": "offline", "silent_s": round(silent, 1), "ts": now})
                    out.append((tenant, col["collector_id"], "offline"))
            for n in store.q("SELECT * FROM node_state WHERE tenant_id=? AND stale=0", (tenant,)):
                silent = now - n["last_seen_ts"]
                if silent <= self.s.offline_s:
                    continue
                why = (f"collector offline: no data for {silent:.0f} s" if n["collector_id"] in offline_ids else f"no data from node for {silent:.0f} s")
                with store.tx() as c:
                    c.execute("UPDATE node_state SET state='POOR', reasons=?, stale=1, since_ts=?, recent='[]' WHERE tenant_id=? AND node=?",
                              (json.dumps([why]), now, tenant, n["node"]))
                    c.execute("INSERT INTO state_history(tenant_id,node,ts,old,new,reasons) VALUES(?,?,?,?,?,?)",
                              (tenant, n["node"], now, n["state"], "POOR", json.dumps([why])))
                self.bus.publish(tenant, "state", {"node": n["node"], "old": n["state"], "new": "POOR", "reasons": [why], "ts": now})
                if n["collector_id"] not in offline_ids:             # collector-level outage already has its own alert
                    self.alerts.on_transition(store, tenant, n["node"], n["state"], "POOR", [why], now)
                out.append((tenant, n["node"], "stale"))
            self.alerts.close_quiet_flaps(store, tenant, now)
        for kind_tenant, who, what in out:
            if what == "stale":
                self._run_hooks("stale", {"tenant": kind_tenant, "node": who, "now": now})
        self._run_hooks("tick", now)
        return out

    # ------------------------------------------------------------------ retention
    def purge(self, now: Optional[float] = None) -> dict:
        """Delete data past retention. Events (and so tracker lineage) after retention_s; derived history 7x longer.
        The audit log is never purged: it is the evidence."""
        now = now if now is not None else time.time()
        ev_cut, long_cut = now - self.s.retention_s, now - 7 * self.s.retention_s
        totals = {}
        for tenant in self.s.tenants:
            store = self.store_of(tenant)
            with store.tx() as c:
                n_ev = c.execute("DELETE FROM events WHERE tenant_id=? AND received_ts<?", (tenant, ev_cut)).rowcount
                n_sh = c.execute("DELETE FROM state_history WHERE tenant_id=? AND ts<?", (tenant, long_cut)).rowcount
                n_rj = c.execute("DELETE FROM rejects WHERE tenant_id=? AND at<?", (tenant, long_cut)).rowcount
                n_al = c.execute("DELETE FROM alerts WHERE tenant_id=? AND state='resolved' AND resolved_ts<?", (tenant, long_cut)).rowcount
                n_ss = c.execute("DELETE FROM sessions WHERE tenant_id=? AND exp<?", (tenant, now)).rowcount
            totals[tenant] = {"events": n_ev, "state_history": n_sh, "rejects": n_rj, "alerts": n_al, "sessions": n_ss}
            if self.audit and (n_ev or n_sh or n_rj or n_al):
                self.audit.record(tenant, "system", "retention_purge", totals[tenant], now=now)
            if n_ev > 5000:
                with store.lock:
                    store.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        return totals

    # ------------------------------------------------------------------ reads (always scoped by tenant)
    def fleet(self, tenant: str, now: Optional[float] = None) -> dict:
        now = now if now is not None else time.time()
        store = self.store_of(tenant)
        nodes = []
        for r in store.q("SELECT * FROM node_state WHERE tenant_id=? ORDER BY node", (tenant,)):
            nodes.append({"node": r["node"], "state": r["state"], "reasons": jl(r["reasons"]), "metrics": jl(r["metrics"]),
                          "category": r["category"], "stale": bool(r["stale"]), "age_s": round(now - r["last_seen_ts"], 1),
                          "collector_id": r["collector_id"],
                          "last_event_time": datetime.fromtimestamp(r["last_event_ts"]).astimezone().isoformat() if r["last_event_ts"] else None,
                          "since_s": round(now - r["since_ts"], 1)})
        cols = self.collectors(tenant, now)
        primary = next((c for c in cols if c["offline"]), cols[0] if cols else None)
        worst = max([RANK[n["state"]] for n in nodes] + ([RANK["POOR"]] if any(c["offline"] for c in cols) else []), default=None)
        return {"tenant_id": tenant, "region": self.s.tenants[tenant]["region"], "overall": STATES[worst] if worst is not None else None,
                "collector": primary, "collectors": cols, "nodes": nodes, "server_time": datetime.fromtimestamp(now).astimezone().isoformat()}

    def collectors(self, tenant: str, now: Optional[float] = None) -> list:
        now = now if now is not None else time.time()
        return [{"collector_id": c["collector_id"], "version": c["version"], "schema_version": c["schema_version"], "config_status": c["config_status"],
                 "offline": bool(c["offline"]), "silent_s": round(now - c["last_seen_ts"], 1), "first_seen_s_ago": round(now - c["first_seen_ts"], 1),
                 "health": jl(c["health"]), "nodes": self.store_of(tenant).one("SELECT COUNT(*) n FROM node_state WHERE tenant_id=? AND collector_id=?", (tenant, c["collector_id"]))["n"]}
                for c in self.store_of(tenant).q("SELECT * FROM fleet_collectors WHERE tenant_id=? ORDER BY collector_id", (tenant,))]

    def history(self, tenant: str, node: str, seconds: float = 900, limit: int = 600, now: Optional[float] = None) -> list:
        now = now if now is not None else time.time()
        rows = self.store_of(tenant).q(
            "SELECT payload_id,event_time,category,severity,cpu,mem,disk,bandwidth_mbps,latency_ms,packet_loss,auth_failures,is_replay "
            "FROM events WHERE tenant_id=? AND node=? AND event_ts>=? ORDER BY event_ts DESC LIMIT ?", (tenant, node, now - seconds, limit))
        return rows[::-1]

    def state_history(self, tenant: str, limit: int = 100) -> list:
        rows = self.store_of(tenant).q("SELECT node,ts,old,new,reasons FROM state_history WHERE tenant_id=? ORDER BY id DESC LIMIT ?", (tenant, limit))
        for r in rows:
            r["reasons"] = jl(r["reasons"])
        return rows
