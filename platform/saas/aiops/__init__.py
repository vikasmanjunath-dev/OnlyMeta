"""P3 AIOps facade: wires detection, incidents, recommendations and remediation into the engine through its hooks.
Nothing here can block ingest: the engine counts and skips a failing hook."""
import json
import statistics
from collections import deque
import time
from pathlib import Path
from typing import Optional

from saas.aiops.baseline import METRICS, Detector, Trend, describe, signal_weights
from saas.aiops.correlate import COLLECTOR_PREFIX, SECURITY_PREFIX, Graph
from saas.aiops import learn as learner
from saas.aiops.ask import Ask
from saas.aiops.multivar import JointDetector, describe_joint
from saas.aiops.incidents import IncidentManager
from saas.aiops.maintenance import Maintenance
from saas.aiops.webhooks import Webhooks
from saas.aiops.recommend import recommend
from saas.aiops.remediate import Remediator, load_policy
from saas.health import RANK
from saas.topology import topology

ROOT = Path(__file__).resolve().parent.parent.parent


class AIOps:
    def __init__(self, engine, settings, bus, audit, threaded: bool = True):
        self.eng, self.s, self.bus, self.th = engine, settings, bus, settings.th
        self.det, self.trend = Detector(self.th), Trend(self.th)
        self._graphs: dict = {}
        self.insights: dict = {}                                   # tenant -> node -> metric -> forecast
        self._cur: dict = {}
        sc = self.th["aiops"].get("security", {})
        self.sec_n, self.sec_win, self.sec_clear = int(sc.get("burst_n", 5)), float(sc.get("window_s", 60)), float(sc.get("clear_s", 90))
        self.sec: dict = {}                                  # (tenant, key id) -> deque[(ts, reason)]
        self.draft_after = float(self.th["aiops"].get("draft_after_s", 8))
        self.maint = Maintenance(engine.store_of, audit)
        self.webhooks = Webhooks(ROOT / "contracts/webhooks.yaml", engine.store_of, audit, threaded)
        self.joint = JointDetector(self.th, self.det.sigma_eff)
        self.ask = Ask(self)
        self.inc = IncidentManager(self.th, bus, audit, engine.store_of, self.graph)
        self.inc.on_open.append(lambda t, i, ctx=None: self.webhooks.emit(t, "incident_opened", {"incident": self._wh(t, i)}))
        self.inc.on_resolve.append(lambda t, i: self.webhooks.emit(t, "incident_resolved", {"incident": self._wh(t, i)}))
        self.rem = Remediator(self.th, load_policy(ROOT / "contracts/remediation_policy.yaml"), bus, audit, engine.store_of, self.graph, self.det, self.inc,
                              settings.offline_s, list(settings.tenants))
        self._drafted: dict = {}
        engine.analysers.append(self.analyse)
        engine.hooks["evaluated"].append(self.on_evaluated)
        engine.hooks["stale"].append(self.on_stale)
        engine.hooks["tick"].append(self.on_tick)

    def graph(self, tenant: str) -> Graph:
        if tenant not in self._graphs:
            topo = topology(tenant)
            for r in self.eng.store_of(tenant).q("SELECT up, dep FROM learned_edges WHERE tenant_id=? AND decision='accepted'", (tenant,)):   # admin-approved learned edges
                for n in (r["up"], r["dep"]):
                    topo.setdefault(n, {"label": n[:12], "depends_on": []})
                if r["up"] not in topo[r["dep"]]["depends_on"]:
                    topo[r["dep"]]["depends_on"].append(r["up"])
            self._graphs[tenant] = Graph(topo)
        return self._graphs[tenant]

    # ---------------------------------------------------------------- learned topology
    def learned_topology(self, tenant: str, now: float) -> dict:
        """Suggested dependency edges with their evidence, each marked with the admin's decision (if any)."""
        st, cfg = self.eng.store_of(tenant), learner.settings(self.th["aiops"].get("learn"))
        rows = st.q("SELECT node,event_ts,cpu,mem,latency_ms,packet_loss,bandwidth_mbps FROM events WHERE tenant_id=? AND event_ts>=? ORDER BY node,event_ts LIMIT 300000",
                    (tenant, now - cfg["lookback_s"]))
        series: dict = {}
        for r in rows:
            series.setdefault(r["node"], []).append(r)
        topo = topology(tenant)
        out = learner.learn(series, topo, cfg, self.det.sigma_eff)
        dec = {(r["up"], r["dep"]): r for r in st.q("SELECT up,dep,decision,actor,ts FROM learned_edges WHERE tenant_id=?", (tenant,))}
        g = self.graph(tenant)
        for e in out["edges"]:
            d = dec.get((e["up"], e["dep"]))
            e["decision"], e["decided_by"], e["decided_ts"] = (d["decision"], d["actor"], d["ts"]) if d else (None, None, None)
            e["up_label"], e["dep_label"] = g.name(e["up"]), g.name(e["dep"])
        for u in out["undirected"]:
            u["labels"] = [g.name(n) for n in u["nodes"]]
        for u in out["declared"]:
            u["up_label"], u["dep_label"] = g.name(u["up"]), g.name(u["dep"])
        out["episodes"] = {g.name(n): c for n, c in out["episodes"].items()}
        out["nodes"] = len(series)
        out["applied"] = [{"up": u, "dep": d, "up_label": g.name(u), "dep_label": g.name(d), "actor": r["actor"], "ts": r["ts"]} for (u, d), r in sorted(dec.items()) if r["decision"] == "accepted"]
        return out

    def decide_edge(self, tenant: str, up: str, dep: str, decision: str, actor: str, now: float, ip: str = "") -> dict:
        """accept / reject / revoke one learned edge. Only an accepted edge changes root-cause analysis."""
        st = self.eng.store_of(tenant)
        if decision not in ("accept", "reject", "revoke"):
            raise ValueError("decision must be accept, reject or revoke")
        for n in (up, dep):
            if not st.one("SELECT 1 x FROM node_state WHERE tenant_id=? AND node=?", (tenant, n)):
                raise LookupError("unknown node")
        ev = None
        if decision == "accept":
            declared = {n: set(v["depends_on"]) for n, v in topology(tenant).items()}
            for r in st.q("SELECT up,dep FROM learned_edges WHERE tenant_id=? AND decision='accepted'", (tenant,)):
                declared.setdefault(r["dep"], set()).add(r["up"])
            if learner.would_cycle(declared, up, dep):
                raise ValueError("that edge would create a dependency cycle")
            ev = next((e for e in self.learned_topology(tenant, now)["edges"] if e["up"] == up and e["dep"] == dep), None)
            if not ev:
                raise ValueError("no current evidence for that edge")
        with st.tx() as c:
            if decision == "revoke":
                c.execute("DELETE FROM learned_edges WHERE tenant_id=? AND up=? AND dep=?", (tenant, up, dep))
            else:
                c.execute("INSERT OR REPLACE INTO learned_edges(tenant_id,up,dep,decision,actor,ts,evidence) VALUES(?,?,?,?,?,?,?)",
                          (tenant, up, dep, "accepted" if decision == "accept" else "rejected", actor, now,
                           json.dumps({k: ev[k] for k in ("support", "forward", "reverse", "p", "lift", "lag_s", "status")}) if ev else None))
        self._graphs.pop(tenant, None)                                     # next analysis uses the new map
        g = self.graph(tenant)
        self.maint.audit.record(tenant, actor, f"topology_edge_{decision}", {"up": g.name(up), "dep": g.name(dep)}, ip)
        return {"up": up, "dep": dep, "decision": decision}

    # ---------------------------------------------------------------- hooks
    def analyse(self, tenant, sample, store):
        node, ts, m = sample["node"], sample["event_ts"], sample["metrics"]

        def loader():
            return list(reversed(store.q("SELECT cpu,mem,latency_ms,packet_loss,bandwidth_mbps FROM events WHERE tenant_id=? AND node=? AND event_ts<=? AND payload_id<>? "
                                         "ORDER BY event_ts DESC LIMIT ?", (tenant, node, ts, sample["payload_id"], self.det.window))))
        if (tenant, node) not in self.det.seeded:                  # first sight since start: close orphans, rebuild the baseline from history
            with store.tx() as c:
                c.execute("UPDATE anomalies SET state='closed', closed_ts=?, detail='closed at restart (detector state is rebuilt)' WHERE tenant_id=? AND node=? AND state='open'",
                          (time.time(), tenant, node))
        self.det.ensure_seeded(tenant, node, loader)
        if (tenant, node) not in self.joint.seeded:
            self.joint.seeded.add((tenant, node))
            self.joint.seed(tenant, node, loader())
        verdicts = self.det.observe(tenant, node, m, ts)
        wall, extra = time.time(), []
        st = self.det._ms(tenant, node)
        for v in verdicts:
            ms = st[v["metric"]]
            if v["opened"]:
                with store.tx() as c:
                    cur = c.execute("INSERT INTO anomalies(tenant_id,node,metric,onset_ts,detected_ts,value,mean,sigma,z,peak_z,replay,payload_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                                    (tenant, node, v["metric"], v["onset_ts"], wall, v["value"], v["mean"], v["sigma"], v["z"], abs(v["z"]), int(sample["is_replay"]), sample["payload_id"]))
                ms.anomaly_id = cur.lastrowid
                self.bus.publish(tenant, "anomaly", {"id": ms.anomaly_id, "node": node, "label": self.graph(tenant).name(node), "metric": v["metric"], "z": v["z"],
                                                     "value": v["value"], "baseline": round(v["mean"], 2), "state": "open", "ts": ts})
            elif v["closed"] and ms.anomaly_id:
                with store.tx() as c:
                    c.execute("UPDATE anomalies SET state='closed', closed_ts=?, kind=? WHERE id=? AND tenant_id=?",
                              (ts, "level_shift" if v["level_shift"] else "zscore", ms.anomaly_id, tenant))
                self.bus.publish(tenant, "anomaly", {"id": ms.anomaly_id, "node": node, "metric": v["metric"], "state": "closed", "level_shift": v["level_shift"], "ts": ts})
                ms.anomaly_id = None
            elif v["open"] and ms.anomaly_id and v.get("peak_z", 0) > 0:
                pass
            if v["open"] and METRICS[v["metric"]]["health"]:
                extra.append(("FAIR", describe(v)))
        jv = self.joint.observe(tenant, node, m, ts, uni_raw=any(v.get("raw") and v.get("warm") for v in verdicts), uni_open=any(v["open"] for v in verdicts))
        if jv:
            js = self.joint._st(tenant, node)
            if jv["opened"]:
                with store.tx() as c:
                    cur = c.execute("INSERT INTO anomalies(tenant_id,node,metric,kind,onset_ts,detected_ts,value,mean,sigma,z,peak_z,replay,payload_id,detail) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                    (tenant, node, "joint", "multivariate", jv["onset_ts"], wall, jv["value"], jv["mean"], jv["sigma"], jv["z"], abs(jv["z"]), int(sample["is_replay"]), sample["payload_id"],
                                     json.dumps({"contrib": jv["contrib"], "d2": jv["d2"], "threshold_d2": jv["threshold_d2"], "alpha": jv["alpha"]}, separators=(",", ":"))))
                js.anomaly_id = cur.lastrowid
                self.bus.publish(tenant, "anomaly", {"id": js.anomaly_id, "node": node, "label": self.graph(tenant).name(node), "metric": "joint", "z": jv["z"], "value": jv["value"],
                                                     "baseline": jv["mean"], "state": "open", "ts": ts, "contrib": jv["contrib"]})
            elif jv["closed"] and js.anomaly_id:
                with store.tx() as c:
                    c.execute("UPDATE anomalies SET state='closed', closed_ts=?, kind=? WHERE id=? AND tenant_id=?", (ts, "level_shift" if jv["level_shift"] else "multivariate", js.anomaly_id, tenant))
                self.bus.publish(tenant, "anomaly", {"id": js.anomaly_id, "node": node, "metric": "joint", "state": "closed", "level_shift": jv["level_shift"], "ts": ts})
                js.anomaly_id = None
            if jv["open"]:
                extra.append(("FAIR", describe_joint(jv)))
            verdicts = verdicts + [jv]
        for metric in self.trend.limits:
            fc = self.trend.add(tenant, node, metric, ts, m[metric])
            node_i = self.insights.setdefault(tenant, {}).setdefault(node, {})
            if fc:
                new = metric not in node_i
                node_i[metric] = {**fc, "ts": ts}
                if new:
                    self.bus.publish(tenant, "insight", {"node": node, "label": self.graph(tenant).name(node), **fc, "ts": ts})
            else:
                node_i.pop(metric, None)
        self._cur[(tenant, node)] = verdicts
        return extra

    def on_evaluated(self, ctx):
        tenant, node = ctx["tenant"], ctx["node"]
        verdicts = self._cur.pop((tenant, node), [])
        w = self.maint.active(tenant, node, ctx["ts"], ctx.get("wall"))
        if w:                                                                    # planned work: still scored and stored, no incident
            self.maint.note(tenant, w["id"])
            return
        iid = self.inc.observe(ctx, verdicts)
        if iid and any(v["open"] for v in verdicts):
            with ctx["store"].tx() as c:
                c.execute("UPDATE anomalies SET incident_id=? WHERE tenant_id=? AND node=? AND state='open' AND incident_id IS NULL", (iid, tenant, node))

    def on_stale(self, ctx):
        tenant, node, now = ctx["tenant"], ctx["node"], ctx["now"]
        store = self.eng.store_of(tenant)
        w = self.maint.active(tenant, node, now, now)
        if w and not self.inc._member_of(tenant, node):
            self.maint.note(tenant, w["id"])
            return
        ns = store.one("SELECT collector_id,last_seen_ts FROM node_state WHERE tenant_id=? AND node=?", (tenant, node))
        col = store.one("SELECT offline, offline_since FROM fleet_collectors WHERE tenant_id=? AND collector_id=?", (tenant, ns["collector_id"])) if ns and ns["collector_id"] else None
        self.inc.observe_stale(tenant, node, ns["last_seen_ts"] if ns else now, store, ns["collector_id"] if ns else None,
                               bool(col and col["offline"]), col["offline_since"] if col else None)

    def _wh(self, tenant: str, i: dict) -> dict:
        """The ONLY incident fields that leave the platform: no raw telemetry, no pseudonyms, no credentials."""
        return {"ref": f"INC-{i['id']}", "title": i["title"], "severity": i["severity"], "kind": i["kind"], "status": i["status"], "confidence": round(i["confidence"], 2),
                "root": self.graph(tenant).name(i["root_node"]), "summary": i["summary"], "detected_ts": i["detected_ts"], "resolved_ts": i.get("resolved_ts")}

    def security_event(self, tenant: str, kid: str, reason: str, ts: float):
        """A signed request from a REAL key id was rejected. A burst opens a security incident on that key; quiet closes it."""
        d = self.sec.setdefault((tenant, kid), deque(maxlen=200))
        d.append((ts, reason.split(" (")[0][:40]))
        while d and ts - d[0][0] > self.sec_win:
            d.popleft()
        if len(d) >= self.sec_n:
            why = ", ".join(sorted({r for _, r in d}))[:90]
            self.inc.security(tenant, kid, len(d), self.sec_win, why, d[0][0], ts, self.eng.store_of(tenant), "POOR" if len(d) >= 2 * self.sec_n else "FAIR")

    def on_tick(self, now):
        for (tenant, kid), d in list(self.sec.items()):
            if d and now - d[-1][0] > self.sec_clear:
                self.inc.security_clear(tenant, kid, now, self.eng.store_of(tenant))
                d.clear()
        for tenant in self.s.tenants:
            store = self.eng.store_of(tenant)
            for iid, inc in list(self.inc.open_for(tenant).items()):
                for n in [n for n in inc["members"] if n.startswith(COLLECTOR_PREFIX)]:
                    cid = n[len(COLLECTOR_PREFIX):]
                    row = store.one("SELECT offline FROM fleet_collectors WHERE tenant_id=? AND collector_id=?", (tenant, cid))
                    if row and not row["offline"]:
                        self.inc.collector_back(tenant, cid, now, store)
                self._draft(tenant, iid, now)
            for node, d in list(self.insights.get(tenant, {}).items()):
                for metric, fc in list(d.items()):
                    if now - fc["ts"] > 120:
                        d.pop(metric, None)
        self.rem.tick(now)

    # ---------------------------------------------------------------- recommendations and drafting
    def recommendations(self, tenant: str, iid: int) -> Optional[list]:
        v = self.inc.get(tenant, iid)
        if not v:
            return None
        store = self.eng.store_of(tenant)
        nm = {r["node"]: json.loads(r["metrics"] or "{}") for r in store.q("SELECT node,metrics FROM node_state WHERE tenant_id=?", (tenant,))}
        bl = {m["node"]: self.det.baseline(tenant, m["node"]) for m in v["members"] if not m["node"].startswith((COLLECTOR_PREFIX, SECURITY_PREFIX))}
        return recommend(v, self.graph(tenant), nm, bl, self.insights.get(tenant), history=self.history(tenant))

    def history(self, tenant: str) -> dict:
        """(action, node) and (action, None) -> (improved, verified runs), from this tenant's own verification verdicts. Observational."""
        h: dict = {}
        for r in self.eng.store_of(tenant).q("SELECT action, node, verdict FROM remediations WHERE tenant_id=? AND verdict IS NOT NULL", (tenant,)):
            v = (json.loads(r["verdict"]) or {}).get("verdict")
            if v not in ("improved", "no_effect", "worse"):
                continue
            for k in ((r["action"], r["node"]), (r["action"], None)):
                a, b = h.get(k, (0, 0))
                h[k] = (a + (v == "improved"), b + 1)
        return h

    def _draft(self, tenant: str, iid: int, now: float):
        inc = self.inc.open_for(tenant).get(iid)
        pol = self.rem.config(tenant)
        if not inc or not pol["auto_propose"] or pol["autonomy"] == "off" or now - inc["detected_ts"] < self.draft_after:
            return
        if self._drafted.get(iid) == inc["root_node"]:
            return
        store = self.eng.store_of(tenant)
        if self._drafted.get(iid) is None and store.one("SELECT 1 x FROM remediations WHERE tenant_id=? AND incident_id=? LIMIT 1", (tenant, iid)):
            self._drafted[iid] = inc["root_node"]
            return
        recs = [r for r in (self.recommendations(tenant, iid) or []) if r["node"] == inc["root_node"]]
        self._drafted[iid] = inc["root_node"]
        for old in self.rem.list(tenant, status="pending_approval", incident_id=iid):          # root changed: earlier drafts are superseded
            if old["proposer"] == "system" and old["node"] != inc["root_node"]:
                self.rem.cancel(tenant, old["id"], "system", now)
        for r in recs[:1]:
            if r["node"].startswith(COLLECTOR_PREFIX):
                continue
            try:
                self.rem.propose(tenant, r["node"], r["action"], now, params=None, incident_id=iid, proposer="system", confidence=r["confidence"], pattern=r["pattern"],
                                 rationale=r["rationale"], metric=r["metric"], severity=inc["peak_state"], auth=r["auth"])
            except Exception as e:                                                            # noqa: BLE001
                print("draft error:", type(e).__name__, e)

    def rebuild_baselines(self, tenant: str, actor: str, now: float, ip: str = "") -> int:
        """Forget the in-memory baselines of every node of a tenant; each one is re-learned from stored history (median/MAD trim, same
        path as after a restart) on its next sample. Used after a backfill, or before a demo to start from clean, warm baselines."""
        nodes = [r["node"] for r in self.eng.store_of(tenant).q("SELECT node FROM node_state WHERE tenant_id=?", (tenant,))]
        for n in nodes:
            self.det.forget(tenant, n)
            self.joint.forget(tenant, n)
        self.maint.audit.record(tenant, actor, "baselines_rebuilt", {"nodes": len(nodes)}, ip)
        return len(nodes)

    # ---------------------------------------------------------------- reads
    def anomalies(self, tenant: str, state: Optional[str] = None, limit: int = 100) -> list:
        sql, args = "SELECT * FROM anomalies WHERE tenant_id=? ", [tenant]
        if state in ("open", "closed"):
            sql, args = sql + "AND state=? ", args + [state]
        g = self.graph(tenant)
        rows = self.eng.store_of(tenant).q(sql + "ORDER BY id DESC LIMIT ?", args + [limit])
        for r in rows:
            r["label"], r["metric_label"] = g.name(r["node"]), ("metric pattern (joint)" if r["metric"] == "joint" else METRICS.get(r["metric"], {}).get("label", r["metric"]))
            r["detect_lag_s"] = round(r["detected_ts"] - r["onset_ts"], 2) if not r["replay"] and r["detected_ts"] >= r["onset_ts"] else None
        return rows

    def baselines(self, tenant: str, node: str) -> dict:
        return self.det.baseline(tenant, node)

    def joint_baselines(self, tenant: str) -> dict:
        """Per node: is the multivariate detector warm, and what limit does it use."""
        g = self.graph(tenant)
        return {r["node"]: {"label": g.name(r["node"]), **self.joint.baseline(tenant, r["node"])} for r in self.eng.store_of(tenant).q("SELECT node FROM node_state WHERE tenant_id=?", (tenant,))}

    def summary(self, tenant: str, now: float, window_s: float = 3600) -> dict:
        st = self.eng.store_of(tenant)
        rows = st.q("SELECT onset_ts, detected_ts, replay, kind FROM anomalies WHERE tenant_id=? AND detected_ts>=?", (tenant, now - window_s))
        raw = [r["detected_ts"] - r["onset_ts"] for r in rows if not r["replay"]]
        lag, skewed = [x for x in raw if x >= 0], sum(x < 0 for x in raw)           # a negative lag means the sample's own clock runs ahead of this server (skew, or an accelerated demo stream): not a measurement
        return {"window_s": window_s, "anomalies": len(rows), "open_now": st.one("SELECT COUNT(*) n FROM anomalies WHERE tenant_id=? AND state='open'", (tenant,))["n"],
                "level_shifts": sum(r["kind"] == "level_shift" for r in rows), "detect_lag_s": {"median": round(statistics.median(lag), 2) if lag else None, "max": round(max(lag), 2) if lag else None},
                "forecasts": [{"node": n, "label": self.graph(tenant).name(n), **fc} for n, d in self.insights.get(tenant, {}).items() for fc in d.values()],
                "incidents": self.inc.summary(tenant, now, window_s), "remediation": self.rem.summary(tenant, now, window_s),
                "slo": self.slo(tenant, lag, now, window_s, skewed)}

    def slo(self, tenant: str, lag: list, now: float, window_s: float, skewed: int = 0) -> dict:
        """Targets from thresholds.yaml, results measured from timestamps. A number with no data is None, never a flattering 100 %."""
        tg = self.th["aiops"].get("slo", {"mttd_s": 15, "mttr_s": 300, "noise_reduction_min_pct": 50})
        st = self.eng.store_of(tenant)
        res = [r["resolved_ts"] - r["first_ts"] for r in st.q("SELECT first_ts, resolved_ts FROM incidents WHERE tenant_id=? AND status='resolved' AND resolved_ts>=?", (tenant, now - window_s))]
        al = st.one("SELECT COUNT(*) n FROM alerts WHERE tenant_id=? AND kind<>'collector' AND first_ts>=?", (tenant, now - window_s))["n"]
        n_inc = st.one("SELECT COUNT(*) n FROM incidents WHERE tenant_id=? AND status<>'merged' AND last_ts>=?", (tenant, now - window_s))["n"]

        def q(xs, p):
            xs = sorted(xs)
            return round(xs[min(len(xs) - 1, int(p * len(xs)))], 1) if xs else None

        def within(xs, t):
            return round(100 * sum(x <= t for x in xs) / len(xs), 1) if xs else None
        red = round(100 * (1 - n_inc / al), 1) if al and n_inc <= al else None
        return {"targets": tg, "mttd": {"p50": q(lag, .5), "p95": q(lag, .95), "within_target_pct": within(lag, tg["mttd_s"]), "n": len(lag), "skewed": skewed},
                "mttr": {"p50": q(res, .5), "p95": q(res, .95), "within_target_pct": within(res, tg["mttr_s"]), "n": len(res)},
                "noise": {"alerts": al, "incidents": n_inc, "reduction_pct": red, "meets_target": None if red is None else red >= tg["noise_reduction_min_pct"]}}
