"""Incident lifecycle: open -> grow (members join) -> merge -> resolve. Persisted (restart-safe); every step is on a timeline."""
import json
import time
from typing import Optional

from saas.aiops.correlate import (COLLECTOR_PREFIX, PSEUDO, SECURITY_PREFIX, SEV_OF, Graph, anomaly_signals, incident_kind, narrate, primary_metric, rca,
                                  static_signals, title_of, to_json, worst_state)
from saas.health import RANK

BAD = RANK["FAIR"]


class IncidentManager:
    def __init__(self, th: dict, bus, audit, store_of, graph_of):
        self.th, self.cfg = th, th["aiops"]
        self.thr = float(th["constants"]["zscore_threshold"])
        self.window = float(th["constants"]["correlation_window_s"])
        self.hops = int(self.cfg["correlate_hops"])
        self.bus, self.audit, self.store_of, self.graph_of = bus, audit, store_of, graph_of
        self.open: dict = {}                                    # tenant -> {incident_id: incident dict}
        self.loaded: set = set()
        self.on_open = []                                       # callbacks: fn(tenant, incident) (recommendations / auto-propose)
        self.on_resolve = []
        self._written: dict = {}

    # ---------------------------------------------------------------- cache
    def _load(self, tenant: str):
        if tenant in self.loaded:
            return
        self.loaded.add(tenant)
        d = self.open.setdefault(tenant, {})
        for r in self.store_of(tenant).q("SELECT * FROM incidents WHERE tenant_id=? AND status='open'", (tenant,)):
            d[r["id"]] = self._hydrate(r)

    @staticmethod
    def _hydrate(r: dict) -> dict:
        r = dict(r)
        r["members"] = json.loads(r["members"] or "{}")
        r["explanation"] = json.loads(r["explanation"] or "{}")
        return r

    def open_for(self, tenant: str) -> dict:
        self._load(tenant)
        return self.open[tenant]

    def _extra_deps(self, members: dict) -> dict:
        """Nodes whose collector is itself an incident member depend on that collector (pseudo-node)."""
        ex = {}
        for n, m in members.items():
            cid = m.get("collector_id")
            if cid and COLLECTOR_PREFIX + cid in members and not n.startswith(COLLECTOR_PREFIX):
                ex[n] = [COLLECTOR_PREFIX + cid]
        return ex

    # ---------------------------------------------------------------- observe (called for every in-order sample)
    def observe(self, ctx: dict, verdicts: list) -> Optional[int]:
        tenant, node, state, ts = ctx["tenant"], ctx["node"], ctx["state"], ctx["ts"]
        inc = self._member_of(tenant, node)
        if RANK[state] >= BAD:
            sample = ctx["sample"]
            sig = static_signals(sample["metrics"], sample["auth_failures_60s"], sample["category"]) + anomaly_signals(verdicts)
            onsets = [s["onset_ts"] for s in sig if s.get("onset_ts")]
            return self._abnormal(ctx, node, state, sig, min(onsets + [ts]), sample.get("collector_id"), inc)
        if inc:
            self._recovered(ctx["store"], tenant, inc, node, state, ts)
            return inc["id"]
        return None

    def observe_stale(self, tenant: str, node: str, now: float, store, collector_id: Optional[str], collector_offline: bool, offline_since: Optional[float]):
        """The stale rule fired: the node is silent. If its collector is down, the collector is a member (and the likely root)."""
        inc = self._member_of(tenant, node)
        sig = [{"kind": "stale", "metric": "stale", "text": "no data"}]
        ctx = {"tenant": tenant, "store": store, "ts": now, "wall": now, "replay": False}
        if collector_offline and collector_id:
            cnode = COLLECTOR_PREFIX + collector_id
            cinc = self._member_of(tenant, cnode)
            self._abnormal(ctx, cnode, "POOR", [{"kind": "collector_offline", "metric": "collector_offline", "text": "collector offline"}],
                           offline_since or now, collector_id, cinc, force_join=node)
            inc = self._member_of(tenant, cnode)
        return self._abnormal(ctx, node, "POOR", sig, now, collector_id, inc, force_join=(COLLECTOR_PREFIX + collector_id) if collector_offline and collector_id else None)

    # ---------------------------------------------------------------- internals
    def _member_of(self, tenant: str, node: str) -> Optional[dict]:
        for inc in self.open_for(tenant).values():
            if node in inc["members"]:
                return inc
        return None

    def _abnormal(self, ctx, node, state, signals, onset, collector_id, inc, force_join: Optional[str] = None):
        tenant, ts, store = ctx["tenant"], ctx["ts"], ctx["store"]
        graph = self.graph_of(tenant)
        member = {"label": graph.name(node), "onset_ts": onset, "last_ts": ts, "state": state, "peak_state": state, "signals": signals,
                  "recovered_ts": None, "collector_id": collector_id}
        if inc is None:
            inc = self._find_joinable(tenant, node, onset, graph, force_join)
        if inc is None:
            return self._create(ctx, node, member, graph)
        old = inc["members"].get(node)
        changed_set = old is None
        if old:
            member["onset_ts"] = old["onset_ts"] if old.get("recovered_ts") is None else onset
            member["peak_state"] = max((old["peak_state"], state), key=lambda s: RANK[s])
            if old.get("recovered_ts") is not None:
                self._event(store, tenant, inc["id"], ts, "member_relapsed", {"node": node, "label": member["label"]})
        inc["members"][node] = member
        inc["last_ts"] = max(inc["last_ts"], ts)
        if changed_set:
            self._event(store, tenant, inc["id"], ts, "member_joined", {"node": node, "label": member["label"], "state": state,
                                                                       "signals": [s.get("text") or f"{s['metric']} {s.get('z')}σ" for s in signals][:4]})
        self._merge_bridged(ctx, inc, node, graph)
        self._reanalyse(ctx, inc, graph, structural=changed_set or (old and old["state"] != state))
        return inc["id"]

    def _find_joinable(self, tenant, node, onset, graph, force_join=None) -> Optional[dict]:
        best = None
        for inc in self.open_for(tenant).values():
            ok = False
            for m, mem in inc["members"].items():
                if mem.get("recovered_ts") is not None:
                    continue
                if force_join and m == force_join:
                    ok = True
                    break
                if node.startswith(PSEUDO) or m.startswith(PSEUDO):
                    continue
                if abs(onset - mem["onset_ts"]) <= self.window and graph.distance(node, m, self.hops) is not None:
                    ok = True
                    break
            if ok and (best is None or inc["id"] < best["id"]):
                best = inc
        return best

    def _merge_bridged(self, ctx, keep, node, graph):
        """The node just joined `keep`; any other open incident it also connects to is folded into the lower-numbered one."""
        tenant, store, ts = ctx["tenant"], ctx["store"], ctx["ts"]
        for oid, other in list(self.open_for(tenant).items()):
            if oid == keep["id"]:
                continue
            link = any(abs(keep["members"][node]["onset_ts"] - m["onset_ts"]) <= self.window and graph.distance(node, n, self.hops) is not None
                       for n, m in other["members"].items() if m.get("recovered_ts") is None and not n.startswith(PSEUDO))
            if not link:
                continue
            a, b = (keep, other) if keep["id"] < other["id"] else (other, keep)
            a["members"].update({n: m for n, m in b["members"].items() if n not in a["members"]})
            a["first_ts"] = min(a["first_ts"], b["first_ts"])
            a["last_ts"] = max(a["last_ts"], b["last_ts"])
            b["status"], b["resolved_ts"] = "merged", ts
            self._persist(store, tenant, b)
            self.open[tenant].pop(b["id"], None)
            self._event(store, tenant, a["id"], ts, "merged", {"from": b["id"]})
            self._event(store, tenant, b["id"], ts, "merged_into", {"into": a["id"]})
            self.bus.publish(tenant, "incident", {"id": b["id"], "status": "merged", "merged_into": a["id"], "ts": ts})
            if a is not keep:
                keep = a

    def _reopen(self, ctx, node, member, graph) -> Optional[int]:
        """Flap damping: the same root failing again soon after resolving is the SAME incident (reopened), not a new page."""
        tenant, store, ts = ctx["tenant"], ctx["store"], ctx["ts"]
        gap = float(self.cfg.get("reopen_within_s", 300))
        r = store.one("SELECT * FROM incidents WHERE tenant_id=? AND status='resolved' AND root_node=? AND resolved_ts>=? ORDER BY resolved_ts DESC LIMIT 1", (tenant, node, ts - gap))
        if not r:
            return None
        inc = self._hydrate(r)
        was = inc["resolved_ts"]
        inc["status"], inc["resolved_ts"] = "open", None
        inc["members"][node] = {**member, "peak_state": member["peak_state"]}
        inc["last_ts"] = max(inc["last_ts"], ts)
        self.open_for(tenant)[inc["id"]] = inc
        self._event(store, tenant, inc["id"], ts, "reopened", {"node": node, "label": member["label"], "after_s": round(ts - was, 1), "reason": "same root failed again within the flap window"})
        self._reanalyse(ctx, inc, graph, structural=True)
        self._publish(inc, "open")
        self._audit(tenant, "incident_reopened", inc, ts)
        return inc["id"]

    def _create(self, ctx, node, member, graph) -> int:
        tenant, store, ts = ctx["tenant"], ctx["store"], ctx["ts"]
        rid = self._reopen(ctx, node, member, graph)
        if rid:
            return rid
        inc = {"tenant_id": tenant, "kind": "performance", "status": "open", "severity": SEV_OF.get(member["state"], "high"), "root_node": node,
               "confidence": 0.0, "title": "", "summary": "", "members": {node: member}, "explanation": {}, "first_ts": member["onset_ts"],
               "last_ts": ts, "resolved_ts": None, "detected_ts": ctx.get("wall") or time.time(), "ack_by": None, "ack_ts": None, "peak_state": member["state"]}
        self._analyse(inc, graph)
        with store.tx() as c:
            cur = c.execute("INSERT INTO incidents(tenant_id,kind,status,severity,root_node,confidence,title,summary,members,explanation,first_ts,last_ts,"
                            "detected_ts,peak_state) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (tenant, inc["kind"], "open", inc["severity"], inc["root_node"], inc["confidence"], inc["title"], inc["summary"],
                             to_json(inc["members"]), to_json(inc["explanation"]), inc["first_ts"], inc["last_ts"], inc["detected_ts"], inc["peak_state"]))
        inc["id"] = cur.lastrowid
        self.open_for(tenant)[inc["id"]] = inc
        self._event(store, tenant, inc["id"], ts, "opened", {"root": node, "label": member["label"], "title": inc["title"]})
        self._link_alerts(store, tenant, inc)
        self._publish(inc, "open")
        self._audit(tenant, "incident_opened", inc, ts)
        for fn in self.on_open:
            try:
                fn(tenant, inc, ctx)
            except Exception as e:                                           # noqa: BLE001
                print("incident on_open error:", type(e).__name__, e)
        return inc["id"]

    def _analyse(self, inc: dict, graph: Graph):
        live = {n: m for n, m in inc["members"].items() if m.get("recovered_ts") is None} or inc["members"]
        ex = rca(live, graph, self.cfg, self.thr, self._extra_deps(live))
        ex["text"] = narrate(ex, graph, live)
        inc["explanation"], inc["root_node"], inc["confidence"] = ex, ex["root"], ex["confidence"]
        inc["title"], inc["summary"] = title_of(ex, live, graph), ex["text"]
        inc["kind"] = incident_kind(live, ex["root"])
        inc["peak_state"] = max((m["peak_state"] for m in inc["members"].values()), key=lambda s: RANK[s])
        inc["severity"] = SEV_OF.get(worst_state(live), "high")

    def _reanalyse(self, ctx, inc, graph, structural: bool):
        store, tenant, ts = ctx["store"], ctx["tenant"], ctx["ts"]
        before = (inc["root_node"], inc["severity"], round(inc["confidence"], 2))
        self._analyse(inc, graph)
        after = (inc["root_node"], inc["severity"], round(inc["confidence"], 2))
        if before[0] != after[0]:
            self._event(store, tenant, inc["id"], ts, "root_changed", {"from": before[0], "to": after[0], "label": graph.name(after[0]), "confidence": after[2]})
        if structural or before != after or ts - self._written.get(inc["id"], 0) > 10:
            self._persist(store, tenant, inc)
            self._written[inc["id"]] = ts
        if structural or before != after:
            self._link_alerts(store, tenant, inc)
            self._publish(inc, "update")

    def _recovered(self, store, tenant, inc, node, state, ts):
        mem = inc["members"].get(node)
        if not mem or mem.get("recovered_ts") is not None:
            return
        mem["recovered_ts"], mem["state"] = ts, state
        self._event(store, tenant, inc["id"], ts, "member_recovered", {"node": node, "label": mem["label"], "state": state})
        self._maybe_resolve(store, tenant, inc, ts)

    def security(self, tenant: str, kid: str, n: int, window_s: float, reasons: str, onset: float, now: float, store, level: str):
        """Abuse of a signing key (bad signature, replay, skew) as an incident of its own: it names the key, never a topology node."""
        node = SECURITY_PREFIX + kid
        sig = [{"kind": "security", "metric": "auth", "level": level, "value": n, "text": f"{n} rejected signed requests in {window_s:.0f} s on key {kid} ({reasons})"}]
        ctx = {"tenant": tenant, "store": store, "ts": now, "wall": now, "replay": False}
        return self._abnormal(ctx, node, level, sig, onset, None, self._member_of(tenant, node))

    def security_clear(self, tenant: str, kid: str, now: float, store):
        inc = self._member_of(tenant, SECURITY_PREFIX + kid)
        if inc:
            self._recovered(store, tenant, inc, SECURITY_PREFIX + kid, "EXCELLENT", now)

    def collector_back(self, tenant: str, collector_id: str, now: float, store):
        inc = self._member_of(tenant, COLLECTOR_PREFIX + collector_id)
        if inc:
            self._recovered(store, tenant, inc, COLLECTOR_PREFIX + collector_id, "EXCELLENT", now)

    def _maybe_resolve(self, store, tenant, inc, ts):
        if all(m.get("recovered_ts") is not None for m in inc["members"].values()):
            inc["status"], inc["resolved_ts"] = "resolved", ts
            self._persist(store, tenant, inc)
            self.open_for(tenant).pop(inc["id"], None)
            self._event(store, tenant, inc["id"], ts, "resolved", {"duration_s": round(ts - inc["first_ts"], 1)})
            self._publish(inc, "resolved")
            self._audit(tenant, "incident_resolved", inc, ts)
            for fn in self.on_resolve:
                try:
                    fn(tenant, inc)
                except Exception as e:                                       # noqa: BLE001
                    print("incident on_resolve error:", type(e).__name__, e)
        else:
            self._analyse(inc, self.graph_of(tenant))
            self._persist(store, tenant, inc)
            self._publish(inc, "update")

    # ---------------------------------------------------------------- persistence + events
    def _persist(self, store, tenant, inc):
        with store.tx() as c:
            c.execute("UPDATE incidents SET kind=?,status=?,severity=?,root_node=?,confidence=?,title=?,summary=?,members=?,explanation=?,first_ts=?,"
                      "last_ts=?,resolved_ts=?,peak_state=? WHERE id=? AND tenant_id=?",
                      (inc["kind"], inc["status"], inc["severity"], inc["root_node"], inc["confidence"], inc["title"], inc["summary"], to_json(inc["members"]),
                       to_json(inc["explanation"]), inc["first_ts"], inc["last_ts"], inc["resolved_ts"], inc["peak_state"], inc["id"], tenant))

    def _event(self, store, tenant, iid, ts, kind, detail):
        with store.tx() as c:
            c.execute("INSERT INTO incident_events(tenant_id,incident_id,ts,kind,detail) VALUES(?,?,?,?,?)", (tenant, iid, ts, kind, to_json(detail)))

    def event(self, tenant: str, iid: int, ts: float, kind: str, detail: dict):
        self._event(self.store_of(tenant), tenant, iid, ts, kind, detail)

    def _link_alerts(self, store, tenant, inc):
        """Alerts on member nodes point at their incident, so the alert list can say 'part of INC-7'."""
        nodes = [n for n in inc["members"] if not n.startswith(PSEUDO)]
        if nodes:
            with store.tx() as c:
                c.execute(f"UPDATE alerts SET incident_id=? WHERE tenant_id=? AND state='open' AND node IN ({','.join('?' * len(nodes))})", (inc["id"], tenant, *nodes))

    def _publish(self, inc, what):
        self.bus.publish(inc["tenant_id"], "incident", {"id": inc["id"], "what": what, "status": inc["status"], "severity": inc["severity"], "title": inc["title"],
                                                         "root_node": inc["root_node"], "root_label": inc["explanation"].get("root_label"),
                                                         "confidence": inc["confidence"], "kind": inc["kind"], "members": len(inc["members"]), "ts": inc["last_ts"]})

    def _audit(self, tenant, action, inc, ts):
        if self.audit:
            self.audit.record(tenant, "system", action, {"incident": inc["id"], "title": inc["title"], "severity": inc["severity"], "root": inc["explanation"].get("root_label"),
                                                         "members": len(inc["members"])}, now=ts)

    # ---------------------------------------------------------------- reads / actions
    def list(self, tenant: str, status: Optional[str] = None, limit: int = 50) -> list:
        store = self.store_of(tenant)
        sql, args = "SELECT * FROM incidents WHERE tenant_id=? ", [tenant]
        if status in ("open", "resolved", "merged"):
            sql, args = sql + "AND status=? ", args + [status]
        rows = [self._hydrate(r) for r in store.q(sql + "ORDER BY id DESC LIMIT ?", args + [limit])]
        return [self._view(r) for r in rows]

    def get(self, tenant: str, iid: int) -> Optional[dict]:
        r = self.store_of(tenant).one("SELECT * FROM incidents WHERE tenant_id=? AND id=?", (tenant, iid))
        if not r:
            return None
        live = self.open_for(tenant).get(iid)
        v = self._view(live if live else self._hydrate(r))
        v["timeline"] = [{**e, "detail": json.loads(e["detail"])} for e in self.store_of(tenant).q(
            "SELECT ts,kind,detail FROM incident_events WHERE tenant_id=? AND incident_id=? ORDER BY id", (tenant, iid))]
        return v

    def _view(self, r: dict) -> dict:
        g = self.graph_of(r["tenant_id"])
        members = [{"node": n, "label": m["label"] or g.name(n), "state": m["state"], "onset_ts": m["onset_ts"], "recovered": m.get("recovered_ts") is not None,
                    "signals": m["signals"], "role": next((c["role"] for c in r["explanation"].get("chain", []) if c["node"] == n), "member")}
                   for n, m in sorted(r["members"].items(), key=lambda kv: kv[1]["onset_ts"])]
        dur = (r["resolved_ts"] or r["last_ts"]) - r["first_ts"]
        return {"id": r["id"], "ref": f"INC-{r['id']}", "kind": r["kind"], "status": r["status"], "severity": r["severity"], "title": r["title"], "summary": r["summary"],
                "root_node": r["root_node"], "root_label": r["explanation"].get("root_label"), "confidence": r["confidence"], "members": members,
                "explanation": r["explanation"], "first_ts": r["first_ts"], "last_ts": r["last_ts"], "resolved_ts": r["resolved_ts"], "duration_s": round(dur, 1),
                "detected_ts": r["detected_ts"], "ack_by": r["ack_by"], "ack_ts": r["ack_ts"], "peak_state": r["peak_state"]}

    def ack(self, tenant: str, iid: int, who: str, now: float) -> bool:
        store = self.store_of(tenant)
        with store.tx() as c:
            ok = c.execute("UPDATE incidents SET ack_by=?, ack_ts=? WHERE id=? AND tenant_id=?", (who, now, iid, tenant)).rowcount > 0
        if ok:
            live = self.open_for(tenant).get(iid)
            if live:
                live["ack_by"], live["ack_ts"] = who, now
            self._event(store, tenant, iid, now, "acknowledged", {"by": who})
        return ok

    def summary(self, tenant: str, now: float, window_s: float = 3600) -> dict:
        """Measured, not claimed: counts, MTTR from timestamps, and how many alerts collapsed into incidents."""
        st = self.store_of(tenant)
        since = now - window_s
        inc = st.q("SELECT status, first_ts, resolved_ts, detected_ts, kind FROM incidents WHERE tenant_id=? AND last_ts>=?", (tenant, since))
        res = [r for r in inc if r["status"] == "resolved" and r["resolved_ts"]]
        alerts = st.one("SELECT COUNT(*) n FROM alerts WHERE tenant_id=? AND kind<>'collector' AND first_ts>=?", (tenant, since))["n"]
        linked = st.one("SELECT COUNT(*) n FROM alerts WHERE tenant_id=? AND incident_id IS NOT NULL AND first_ts>=?", (tenant, since))["n"]
        mem = [len(json.loads(r["members"])) for r in st.q("SELECT members FROM incidents WHERE tenant_id=? AND last_ts>=? AND status<>'merged'", (tenant, since))]
        return {"window_s": window_s, "open": sum(r["status"] == "open" for r in inc), "resolved": len(res), "merged": sum(r["status"] == "merged" for r in inc),
                "mttr_s": round(sum(r["resolved_ts"] - r["first_ts"] for r in res) / len(res), 1) if res else None,
                "by_kind": {k: sum(r["kind"] == k for r in inc if r["status"] != "merged") for k in ("performance", "availability", "security")},
                "alerts_in_window": alerts, "alerts_linked_to_incident": linked, "avg_nodes_per_incident": round(sum(mem) / len(mem), 2) if mem else None}
