"""Safe remediation SIMULATION (P3): propose -> policy -> approve -> execute (simulated) -> verify -> rollback, all audited.

Nothing here touches a real system. The only actuator is `SimulatedActuator`; a real one (Ansible, a cloud API, a runbook webhook)
plugs into the same two-method interface and is roadmap, not built. What is real is everything around the action:
  * an ALLOW-LIST catalogue: an action not listed here cannot be proposed, whatever calls the API;
  * a declarative POLICY (contracts/remediation_policy.yaml) deciding auto / needs-approval / deny / advice-only, with every rule's
    verdict kept so a human sees WHY;
  * approvals by admins only, with separation of duties, two-person rule for high risk / wide blast radius, and a TTL so a stale
    approval cannot fire on changed conditions;
  * preconditions re-checked at execution (the problem must still exist; policy must still allow it);
  * a what-if "digital twin" that predicts the health state after the action (an ESTIMATE, labelled as such);
  * verification against what the node actually did afterwards (improved / no effect / worse), and automatic rollback if worse;
  * every step in the per-tenant tamper-evident audit chain and in the action's own timeline."""
import fnmatch
import json
import time
from typing import Optional

import yaml

from saas.aiops.correlate import to_json
from saas.health import RANK, classify

TERMINAL = {"denied", "rejected", "expired", "cancelled", "rolled_back", "aborted", "verified", "failed_verification"}
OPEN = {"advisory", "pending_approval", "approved", "executed"}
RISK_W = {"low": 1.0, "medium": 1.5, "high": 2.5}

# effect = multiplicative factor on a metric (what the twin predicts); disruptive = touches the nodes that depend on the target
ACTIONS = {
    "scale_out":         {"title": "Scale out (+1 replica)", "risk": "low", "reversible": True, "rollback": "scale_in", "disruptive": False,
                          "effect": {"cpu": 0.62, "mem": 0.80, "latency_ms": 0.75}, "params": {"replicas": 1}},
    "throttle_traffic":  {"title": "Throttle inbound traffic (-20%)", "risk": "medium", "reversible": True, "rollback": "unthrottle_traffic", "disruptive": False,
                          "effect": {"cpu": 0.80, "latency_ms": 0.80, "bandwidth_mbps": 0.80}, "params": {"percent": 20}},
    "failover_link":     {"title": "Fail over to the secondary link", "risk": "medium", "reversible": True, "rollback": "failback_link", "disruptive": True,
                          "effect": {"packet_loss": 0.10, "latency_ms": 0.60}, "params": {"link": "secondary"}},
    "restart_service":   {"title": "Rolling restart of the service", "risk": "medium", "reversible": False, "rollback": None, "disruptive": True,
                          "effect": {"cpu": 0.50, "mem": 0.55, "latency_ms": 0.50}, "params": {"strategy": "rolling"}},
    "block_source":      {"title": "Block the offending login source", "risk": "low", "reversible": True, "rollback": "unblock_source", "disruptive": False,
                          "effect": {"auth": 0.0}, "params": {"ttl_s": 3600}},
    "rate_limit_logins": {"title": "Rate-limit logins on this node", "risk": "low", "reversible": True, "rollback": "remove_login_limit", "disruptive": False,
                          "effect": {"auth": 0.2}, "params": {"per_minute": 3}},
    "force_mfa":         {"title": "Require MFA for all logins", "risk": "medium", "reversible": True, "rollback": "relax_mfa", "disruptive": False,
                          "effect": {"auth": 0.3}, "params": {}},
    "cleanup_logs":      {"title": "Delete rotated logs to free disk", "risk": "medium", "reversible": False, "rollback": None, "disruptive": False,
                          "effect": {"disk": 0.85}, "params": {"older_than_days": 7}},
    "failover_replica":  {"title": "Promote the standby replica", "risk": "high", "reversible": True, "rollback": "failback_replica", "disruptive": True,
                          "effect": {"cpu": 0.60, "latency_ms": 0.50}, "params": {"replica": "standby"}},
    "isolate_node":      {"title": "Isolate the node from the network", "risk": "high", "reversible": True, "rollback": "restore_node", "disruptive": True,
                          "effect": {}, "params": {}},
    "check_host":        {"title": "Investigate the host (no automated fix)", "risk": "low", "reversible": True, "rollback": None, "disruptive": False,
                          "effect": {}, "params": {}, "advisory": True},
}
INTERNAL = {"scale_in", "unthrottle_traffic", "failback_link", "unblock_source", "remove_login_limit", "relax_mfa", "failback_replica", "restore_node"}


class RemediationError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


def catalogue() -> list:
    return [{"action": k, "title": v["title"], "risk": v["risk"], "reversible": v["reversible"], "rollback": v["rollback"], "disruptive": v["disruptive"],
             "advisory": bool(v.get("advisory")), "default_params": v["params"]} for k, v in ACTIONS.items()]


# ------------------------------------------------------------------------------------------------ twin
def simulate(action: str, metrics: dict, auth: int = 0, floor: Optional[dict] = None) -> dict:
    """What-if: apply the action's effect factors to the node's current numbers and classify the result with the same health rules.
    A metric never drops below its learned normal (`floor`): a fix cannot make a node better than healthy. An estimate, not a measurement."""
    spec = ACTIONS[action]
    out, a2 = dict(metrics), auth
    for m, f in spec["effect"].items():
        if m == "auth":
            a2 = int(round(auth * f))
        elif m in out:
            lo = (floor or {}).get(m, 0.0)
            out[m] = round(max(lo, out[m] * f) if out[m] > lo else out[m], 2)
    state, reasons = classify(out, a2, "METRICS", 0)
    return {"metrics": out, "auth_failures_60s": a2, "state": state, "reasons": reasons[:2],
            "model": "multiplicative effect model v1: an estimate, not a measurement"}


# ------------------------------------------------------------------------------------------------ actuator
class SimulatedActuator:
    """The only actuator. It records that the action WOULD have been applied; no real system is contacted."""
    name = "simulation"

    def __init__(self):
        self.n = 0

    def apply(self, tenant: str, label: str, action: str, params: dict, now: float) -> dict:
        self.n += 1
        return {"ok": True, "actuator": self.name, "ref": f"sim-{self.n}", "applied": {"action": action, "target": label, "params": params},
                "note": "simulated: no real system was changed"}


# ------------------------------------------------------------------------------------------------ policy
def load_policy(path) -> dict:
    return yaml.safe_load(open(path)) or {}


def effective_policy(doc: dict, tenant: str, override: Optional[dict]) -> dict:
    p = {**doc["defaults"], **(doc.get("tenants", {}).get(tenant) or {}), **(override or {})}
    return p


EDITABLE = {"autonomy": {"off", "suggest", "assisted", "auto_low"}, "auto_propose": bool, "change_freeze": bool, "auto_rollback_on_worse": bool}
ORDER = {"deny": 3, "advisory": 2, "approval": 1, "allow": 0}


def decide(pol: dict, req: dict) -> dict:
    """req: action, label, blast, confidence, severity, risk, reversible, advisory, telemetry_age_s, actions_last_hour, cooldown_hit,
    duplicate, offline_s. Every rule that matters is evaluated and reported; the final decision is the most restrictive."""
    rules = []

    def r(rule, effect, text):
        rules.append({"rule": rule, "effect": effect, "text": text})
    a = req["action"]
    if a not in ACTIONS:
        r("allow_list", "deny", f"'{a}' is not in the action catalogue")
    if pol["change_freeze"]:
        r("change_freeze", "deny", "change freeze is on: no remediation is allowed")
    if pol["autonomy"] == "off":
        r("autonomy_off", "deny", "remediation is switched off for this tenant")
    elif pol["autonomy"] == "suggest":
        r("suggest_only", "advisory", "autonomy is 'suggest': advice only, nothing may be executed")
    if req.get("advisory"):
        r("advisory_action", "advisory", "this is guidance for a person; there is nothing to automate")
    if not req.get("advisory") and req["telemetry_age_s"] > req["offline_s"]:
        r("fresh_telemetry", "deny", f"no fresh data from the node for {req['telemetry_age_s']:.0f} s: an action could not be verified")
    if req["duplicate"]:
        r("duplicate", "deny", "an open proposal for the same node and action already exists")
    if req["cooldown_hit"]:
        r("cooldown", "deny", f"same action on this node ran within the last {pol['cooldown_s']} s")
    if req["actions_last_hour"] >= pol["max_actions_per_node_per_hour"]:
        r("rate_limit", "deny", f"{req['actions_last_hour']} actions on this node in the last hour (max {pol['max_actions_per_node_per_hour']})")
    wide = False
    if req["blast"] > pol["max_blast_any"]:
        wide = True
        r("blast_radius_wide", "approval", f"touches {req['blast']} dependent node(s) (> {pol['max_blast_any']}): two approvals")
    elif req["blast"] > pol["max_blast_auto"]:
        r("blast_radius", "approval", f"touches {req['blast']} dependent node(s): a human decides")
    if any(fnmatch.fnmatch(req["label"], pat) for pat in pol["protected_labels"]):
        r("protected_node", "approval", f"'{req['label']}' is a protected node: never auto-run")
    if not req["reversible"]:
        r("irreversible", "approval", "the action cannot be rolled back: a human must approve")
    if req["risk"] == "medium":
        r("risk_medium", "approval", "medium-risk action")
    elif req["risk"] == "high":
        r("risk_high", "approval", "high-risk action: two approvals")
    if req["confidence"] < pol["min_auto_confidence"]:
        r("low_confidence", "approval", f"confidence {req['confidence']:.2f} < {pol['min_auto_confidence']}")
    if pol["autonomy"] == "assisted":
        r("assisted_mode", "approval", "assisted mode: an admin approves every action")
    if not any(x["effect"] != "allow" for x in rules):
        r("auto_low_ok", "allow", "low-risk, reversible, confident and inside the blast limit: may run on its own")
    worst = max(rules, key=lambda x: ORDER[x["effect"]])["effect"]
    decision = {"deny": "deny", "advisory": "advisory", "approval": "needs_approval", "allow": "allow_auto"}[worst]
    need = 0
    if decision == "needs_approval":
        need = max(int(pol["risk_approvals"].get(req["risk"], 1)), 2 if wide else 1)
    return {"decision": decision, "required_approvals": need, "rules": rules, "autonomy": pol["autonomy"]}


# ------------------------------------------------------------------------------------------------ manager
class Remediator:
    def __init__(self, th: dict, policy_doc: dict, bus, audit, store_of, graph_of, detector, incidents, offline_s: float, tenants: list, actuator=None):
        self.th, self.tenants, self.doc, self.bus, self.audit, self.store_of, self.graph_of = th, tenants, policy_doc, bus, audit, store_of, graph_of
        self.det, self.incidents, self.offline_s = detector, incidents, offline_s
        self.actuator = actuator or SimulatedActuator()
        self.counters = {"proposed": 0, "executed": 0, "auto_executed": 0, "denied": 0, "rolled_back": 0, "expired": 0}

    # ---------------------------------------------------------------- config
    def config(self, tenant: str) -> dict:
        row = self.store_of(tenant).one("SELECT doc FROM aiops_config WHERE tenant_id=?", (tenant,))
        return effective_policy(self.doc, tenant, json.loads(row["doc"]) if row and row["doc"] else None)

    def put_config(self, tenant: str, patch: dict, who: str, now: float, ip: Optional[str] = None) -> dict:
        bad = [k for k in patch if k not in EDITABLE]
        if bad:
            raise RemediationError(422, f"not editable here: {bad} (editable: {sorted(EDITABLE)}); other limits live in contracts/remediation_policy.yaml")
        for k, v in patch.items():
            ok = (v in EDITABLE[k]) if isinstance(EDITABLE[k], set) else isinstance(v, bool)
            if not ok:
                raise RemediationError(422, f"invalid value for {k}")
        store = self.store_of(tenant)
        row = store.one("SELECT doc FROM aiops_config WHERE tenant_id=?", (tenant,))
        cur = {**(json.loads(row["doc"]) if row and row["doc"] else {}), **patch}
        with store.tx() as c:
            c.execute("INSERT OR REPLACE INTO aiops_config(tenant_id,doc,updated_ts) VALUES(?,?,?)", (tenant, json.dumps(cur), now))
        self.audit.record(tenant, who, "remediation_config_changed", {"patch": patch}, ip, now)
        if patch.get("autonomy") == "off" or patch.get("change_freeze"):                  # kill switch: nothing waits to fire
            for r in store.q("SELECT id FROM remediations WHERE tenant_id=? AND status IN ('pending_approval','approved','advisory')", (tenant,)):
                self._set(tenant, r["id"], "cancelled", who, "cancelled", {"reason": "kill switch (autonomy off / change freeze)"}, now)
        return self.config(tenant)

    # ---------------------------------------------------------------- policy what-if
    def what_if(self, tenant: str, override: dict, now: float, window_s: float = 86400) -> dict:
        """Replay this tenant's past proposals through a DRAFT policy and show what would have changed. Changes nothing, stores nothing.
        Any key of the policy may be tried (type-checked against the defaults), not only the few that are editable live."""
        base = self.doc["defaults"]
        for k, v in (override or {}).items():
            if k not in base:
                raise RemediationError(422, f"unknown policy key '{k}' (known: {sorted(base)})")
            if isinstance(base[k], bool) != isinstance(v, bool) or isinstance(base[k], (list, dict, str)) and type(v) is not type(base[k]) or isinstance(base[k], (int, float)) and not isinstance(base[k], bool) and (isinstance(v, bool) or not isinstance(v, (int, float))):
                raise RemediationError(422, f"invalid value for {k}")
        if override.get("autonomy") and override["autonomy"] not in EDITABLE["autonomy"]:
            raise RemediationError(422, "invalid value for autonomy")
        cur, new = self.config(tenant), {**self.config(tenant), **(override or {})}
        g, rows, out = self.graph_of(tenant), self.store_of(tenant).q("SELECT * FROM remediations WHERE tenant_id=? AND created_ts>=? AND proposer IS NOT NULL ORDER BY id DESC LIMIT 200", (tenant, now - window_s)), []
        tally = {"allow_auto": [0, 0], "needs_approval": [0, 0], "advisory": [0, 0], "deny": [0, 0]}
        for r in rows:
            req = {"action": r["action"], "label": g.name(r["node"]), "blast": r["blast_radius"] or 0, "confidence": r["confidence"] or 0.0, "severity": "high",
                   "risk": r["risk"], "reversible": bool(r["reversible"]), "advisory": bool(ACTIONS.get(r["action"], {}).get("advisory")), "telemetry_age_s": 0.0,
                   "actions_last_hour": 0, "cooldown_hit": False, "duplicate": False, "offline_s": self.offline_s}
            a, b = decide(cur, req), decide(new, req)
            tally[a["decision"]][0] += 1
            tally[b["decision"]][1] += 1
            out.append({"ref": f"REM-{r['id']}", "title": ACTIONS.get(r["action"], {}).get("title", r["action"]), "label": req["label"], "risk": r["risk"],
                        "confidence": r["confidence"], "current": a["decision"], "draft": b["decision"], "changed": a["decision"] != b["decision"],
                        "draft_approvals": b["required_approvals"], "why": [x["text"] for x in b["rules"] if x["effect"] != "allow"][:3]})
        return {"window_s": window_s, "n": len(out), "override": override, "tally": {k: {"current": v[0], "draft": v[1]} for k, v in tally.items()},
                "changed": sum(o["changed"] for o in out), "rows": out[:60],
                "note": "replay of past proposals under the draft policy; it assumes fresh telemetry, no cooldown and no duplicates. Nothing was changed."}

    # ---------------------------------------------------------------- reads
    def _hydrate(self, r: dict) -> dict:
        g = self.graph_of(r["tenant_id"])
        for k in ("params", "policy", "approvals", "verdict", "rationale", "predicted", "precondition"):
            r[k] = json.loads(r[k]) if r.get(k) else None
        r["ref"], r["label"], r["reversible"] = f"REM-{r['id']}", g.name(r["node"]), bool(r["reversible"])
        r["title"] = ACTIONS.get(r["action"], {}).get("title", r["action"])
        return r

    def get(self, tenant: str, rid: int) -> Optional[dict]:
        row = self.store_of(tenant).one("SELECT * FROM remediations WHERE tenant_id=? AND id=?", (tenant, rid))
        if not row:
            return None
        r = self._hydrate(row)
        r["timeline"] = [{**e, "detail": json.loads(e["detail"])} for e in self.store_of(tenant).q(
            "SELECT ts,actor,event,detail FROM remediation_events WHERE tenant_id=? AND remediation_id=? ORDER BY id", (tenant, rid))]
        return r

    def list(self, tenant: str, status: Optional[str] = None, incident_id: Optional[int] = None, limit: int = 100) -> list:
        sql, args = "SELECT * FROM remediations WHERE tenant_id=? ", [tenant]
        if status:
            sql, args = sql + "AND status=? ", args + [status]
        if incident_id:
            sql, args = sql + "AND incident_id=? ", args + [incident_id]
        return [self._hydrate(r) for r in self.store_of(tenant).q(sql + "ORDER BY id DESC LIMIT ?", args + [limit])]

    def summary(self, tenant: str, now: float, window_s: float = 3600) -> dict:
        st = self.store_of(tenant)
        rows = st.q("SELECT status, verdict, created_ts, executed_ts, proposer FROM remediations WHERE tenant_id=? AND created_ts>=?", (tenant, now - window_s))
        by = {}
        for r in rows:
            by[r["status"]] = by.get(r["status"], 0) + 1
        v = [x for x in ((json.loads(r["verdict"]) or {}).get("verdict") for r in rows if r["verdict"]) if x]
        return {"window_s": window_s, "total": len(rows), "by_status": by, "pending": by.get("pending_approval", 0),
                "verified_improved": v.count("improved"), "verified_no_effect": v.count("no_effect"), "verified_worse": v.count("worse"),
                "auto_executed": st.one("SELECT COUNT(*) n FROM remediation_events WHERE tenant_id=? AND event='executed' AND ts>=? AND detail LIKE '%\"auto\":true%'", (tenant, now - window_s))["n"],
                "config": self.config(tenant)}

    # ---------------------------------------------------------------- propose
    def _node(self, tenant, node):
        return self.store_of(tenant).one("SELECT * FROM node_state WHERE tenant_id=? AND node=?", (tenant, node))

    def propose(self, tenant: str, node: str, action: str, now: float, *, params: Optional[dict] = None, incident_id: Optional[int] = None,
                proposer: str = "system", confidence: float = 0.6, pattern: str = "", rationale: Optional[list] = None, metric: Optional[str] = None,
                severity: str = "FAIR", auth: int = 0, ip: Optional[str] = None) -> dict:
        human = proposer != "system"
        store, g = self.store_of(tenant), self.graph_of(tenant)
        if action not in ACTIONS:
            raise RemediationError(422, f"unknown action '{action}' (allow-list: {sorted(ACTIONS)})")
        ns = self._node(tenant, node)
        if not ns:
            raise RemediationError(404, "unknown node")
        spec = ACTIONS[action]
        pol = self.config(tenant)
        sig = f"{node}|{action}"
        dup = store.one("SELECT id FROM remediations WHERE tenant_id=? AND signature=? AND status IN ('advisory','pending_approval','approved','executed') ORDER BY id DESC LIMIT 1", (tenant, sig))
        if dup:
            return {**self.get(tenant, dup["id"]), "duplicate": True}
        last = store.one("SELECT executed_ts FROM remediations WHERE tenant_id=? AND signature=? AND executed_ts IS NOT NULL ORDER BY executed_ts DESC LIMIT 1", (tenant, sig))
        n_hour = store.one("SELECT COUNT(*) n FROM remediations WHERE tenant_id=? AND node=? AND executed_ts>=?", (tenant, node, now - 3600))["n"]
        blast = len(g.dependents(node)) if spec["disruptive"] else 0
        req = {"action": action, "label": g.name(node), "blast": blast, "confidence": confidence, "severity": severity, "risk": spec["risk"],
               "reversible": spec["reversible"], "advisory": bool(spec.get("advisory")), "telemetry_age_s": max(0.0, now - ns["last_seen_ts"]),
               "actions_last_hour": n_hour, "cooldown_hit": bool(last and now - last["executed_ts"] < pol["cooldown_s"]), "duplicate": False, "offline_s": self.offline_s}
        pdec = decide(pol, req)
        if pdec["decision"] == "deny" and not human:
            self.counters["denied"] += 1
            return {"id": None, "status": "denied", "policy": pdec, "stored": False}           # machine drafts that policy refuses are not stored
        m = json.loads(ns["metrics"] or "{}")
        floor = {k: v["mean"] for k, v in self.det.baseline(tenant, node).items() if v["warm"]}
        pred = simulate(action, m, auth, floor) if not spec.get("advisory") else None
        status = {"deny": "denied", "advisory": "advisory", "needs_approval": "pending_approval", "allow_auto": "approved"}[pdec["decision"]]
        p = {**spec["params"], **(params or {})}
        pre = {"min_state": "FAIR", "metric": metric, "value": m.get(metric) if metric else None, "incident_id": incident_id, "state": ns["state"]}
        ttl = float(pol["approval_ttl_s"])
        with store.tx() as c:
            cur = c.execute("INSERT INTO remediations(tenant_id,incident_id,node,action,params,status,risk,reversible,blast_radius,confidence,policy,proposer,approvals,"
                            "required_approvals,created_ts,expires_ts,rationale,predicted,precondition,signature,pattern) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (tenant, incident_id, node, action, json.dumps(p), status, spec["risk"], int(spec["reversible"]), blast, confidence, to_json(pdec), proposer, "[]",
                             pdec["required_approvals"], now, now + ttl, json.dumps(rationale or []), to_json(pred) if pred else None, to_json(pre), sig, pattern))
        rid = cur.lastrowid
        self.counters["proposed"] += 1
        if status == "denied":
            self.counters["denied"] += 1
        self._log(tenant, rid, proposer, "proposed", {"action": action, "node": g.name(node), "decision": pdec["decision"], "required_approvals": pdec["required_approvals"],
                                                      "rules": [x["rule"] for x in pdec["rules"] if x["effect"] != "allow"], "incident": incident_id}, now, ip, incident_id)
        self._publish(tenant, rid)
        if status == "approved":                                                                 # policy allows it to run on its own
            return self.execute(tenant, rid, "system", now, auto=True)
        return self.get(tenant, rid)

    # ---------------------------------------------------------------- approve / reject / cancel
    def _fresh(self, tenant, rid) -> dict:
        r = self.get(tenant, rid)
        if not r:
            raise RemediationError(404, "unknown remediation")
        return r

    def approve(self, tenant: str, rid: int, who: str, now: float, note: str = "", ip: Optional[str] = None) -> dict:
        r = self._fresh(tenant, rid)
        pol = self.config(tenant)
        if r["status"] != "pending_approval":
            raise RemediationError(409, f"cannot approve: status is {r['status']}")
        if now > r["expires_ts"]:
            self._set(tenant, rid, "expired", "system", "expired", {"reason": "approval window closed"}, now)
            raise RemediationError(409, "proposal expired: conditions may have changed; propose again")
        if pol["separation_of_duties"] and r["proposer"] == who:
            raise RemediationError(403, "separation of duties: the proposer cannot approve their own proposal")
        if any(a["user"] == who for a in r["approvals"]):
            raise RemediationError(409, "you have already approved this")
        appr = r["approvals"] + [{"user": who, "ts": now, "note": note[:200]}]
        with self.store_of(tenant).tx() as c:
            c.execute("UPDATE remediations SET approvals=? WHERE id=? AND tenant_id=?", (json.dumps(appr), rid, tenant))
        self._log(tenant, rid, who, "approved", {"approvals": len(appr), "required": r["required_approvals"], "note": note[:200]}, now, ip, r["incident_id"])
        if len(appr) >= r["required_approvals"]:
            self._set(tenant, rid, "approved", who, None, {}, now)
            return self.execute(tenant, rid, who, now)
        self._publish(tenant, rid)
        return self.get(tenant, rid)

    def reject(self, tenant: str, rid: int, who: str, now: float, note: str = "", ip: Optional[str] = None) -> dict:
        r = self._fresh(tenant, rid)
        if r["status"] not in ("pending_approval", "advisory"):
            raise RemediationError(409, f"cannot reject: status is {r['status']}")
        self._set(tenant, rid, "rejected", who, "rejected", {"note": note[:200]}, now, ip, r["incident_id"])
        return self.get(tenant, rid)

    def cancel(self, tenant: str, rid: int, who: str, now: float, ip: Optional[str] = None) -> dict:
        r = self._fresh(tenant, rid)
        if r["status"] not in ("pending_approval", "approved", "advisory"):
            raise RemediationError(409, f"cannot cancel: status is {r['status']}")
        self._set(tenant, rid, "cancelled", who, "cancelled", {}, now, ip, r["incident_id"])
        return self.get(tenant, rid)

    # ---------------------------------------------------------------- execute (simulated)
    def execute(self, tenant: str, rid: int, who: str, now: float, auto: bool = False, ip: Optional[str] = None) -> dict:
        r = self._fresh(tenant, rid)
        if r["status"] != "approved":
            raise RemediationError(409, f"cannot execute: status is {r['status']}")
        g, spec, pol = self.graph_of(tenant), ACTIONS[r["action"]], self.config(tenant)
        ns = self._node(tenant, r["node"])
        why = None
        if pol["change_freeze"] or pol["autonomy"] in ("off", "suggest"):
            why = "policy changed since approval (freeze / autonomy)"
        elif not ns or RANK[ns["state"]] < RANK["FAIR"]:
            why = "stale precondition: the node is no longer degraded, so the action is no longer needed"
        elif now - ns["last_seen_ts"] > self.offline_s:
            why = "no fresh telemetry from the node"
        if why:
            self._set(tenant, rid, "aborted", "system", "aborted", {"reason": why}, now, ip, r["incident_id"])
            return self.get(tenant, rid)
        res = self.actuator.apply(tenant, g.name(r["node"]), r["action"], r["params"], now)
        before = {"state": ns["state"], "metrics": json.loads(ns["metrics"] or "{}"), "ts": now, "event_ts": ns["last_event_ts"]}
        verdict = {"before": before, "actuator": res}
        with self.store_of(tenant).tx() as c:
            c.execute("UPDATE remediations SET status='executed', executed_ts=?, verify_due_ts=?, verdict=? WHERE id=? AND tenant_id=?",
                      (now, now + float(pol["verify_after_s"]), to_json(verdict), rid, tenant))
        self.counters["executed"] += 1
        if auto:
            self.counters["auto_executed"] += 1
        self._log(tenant, rid, who, "executed", {"actuator": res["actuator"], "ref": res["ref"], "auto": auto, "verify_in_s": pol["verify_after_s"],
                                                 "note": res["note"]}, now, ip, r["incident_id"])
        self._publish(tenant, rid)
        return self.get(tenant, rid)

    # ---------------------------------------------------------------- verify / rollback
    def verify(self, tenant: str, rid: int, now: float) -> dict:
        r = self._fresh(tenant, rid)
        if r["status"] != "executed":
            return r
        ns = self._node(tenant, r["node"])
        before = r["verdict"]["before"]
        after = {"state": ns["state"] if ns else None, "metrics": json.loads(ns["metrics"] or "{}") if ns else {}, "ts": now,
                 "stale": bool(ns and now - ns["last_seen_ts"] > self.offline_s)}
        metric = (r["precondition"] or {}).get("metric")
        verdict, note, frac = "no_effect", "no meaningful change in the node's health", None
        if after["stale"] or not ns:
            verdict, note = "no_effect", "no fresh telemetry after the action: cannot confirm"
        else:
            rb, ra = RANK[before["state"]], RANK[after["state"]]
            if metric and metric in before["metrics"] and metric in after["metrics"]:
                base = self.det.baseline(tenant, r["node"]).get(metric, {})
                norm = base.get("mean", 0.0) if base.get("warm") else 0.0
                excess = before["metrics"][metric] - norm
                if excess > 1e-9:
                    frac = round((before["metrics"][metric] - after["metrics"][metric]) / excess, 2)
            if ra < rb or (frac is not None and frac >= 0.5):
                verdict, note = "improved", "the node is healthier than before the action (observed; this does not prove the action caused it)"
            elif ra > rb or (frac is not None and frac <= -0.15):
                verdict, note = "worse", "the node is in worse shape than before the action"
        out = {**r["verdict"], "after": after, "verdict": verdict, "note": note, "excess_removed": frac, "verified_ts": now}
        status = "verified" if verdict == "improved" else "failed_verification"
        with self.store_of(tenant).tx() as c:
            c.execute("UPDATE remediations SET status=?, verdict=? WHERE id=? AND tenant_id=?", (status, to_json(out), rid, tenant))
        self._log(tenant, rid, "system", "verified", {"verdict": verdict, "excess_removed": frac, "state_before": before["state"], "state_after": after["state"]}, now, None, r["incident_id"])
        self._publish(tenant, rid)
        if verdict == "worse" and r["reversible"] and self.config(tenant)["auto_rollback_on_worse"]:
            return self.rollback(tenant, rid, "system", now, reason="auto: verification found the node worse")
        return self.get(tenant, rid)

    def rollback(self, tenant: str, rid: int, who: str, now: float, reason: str = "", ip: Optional[str] = None) -> dict:
        r = self._fresh(tenant, rid)
        spec = ACTIONS[r["action"]]
        if r["status"] not in ("executed", "verified", "failed_verification"):
            raise RemediationError(409, f"cannot roll back: status is {r['status']}")
        if not spec["reversible"] or not spec["rollback"]:
            raise RemediationError(409, "this action is not reversible (that is why it needed approval); no rollback exists")
        res = self.actuator.apply(tenant, self.graph_of(tenant).name(r["node"]), spec["rollback"], r["params"], now)
        with self.store_of(tenant).tx() as c:
            c.execute("UPDATE remediations SET status='rolled_back', rolled_back_ts=? WHERE id=? AND tenant_id=?", (now, rid, tenant))
        self.counters["rolled_back"] += 1
        self._log(tenant, rid, who, "rolled_back", {"rollback_action": spec["rollback"], "ref": res["ref"], "reason": reason[:200], "note": res["note"]}, now, ip, r["incident_id"])
        self._publish(tenant, rid)
        return self.get(tenant, rid)

    # ---------------------------------------------------------------- clock
    def tick(self, now: float):
        for tenant in list(self.tenants):
            st = self.store_of(tenant)
            for r in st.q("SELECT id FROM remediations WHERE tenant_id=? AND status IN ('pending_approval','advisory') AND expires_ts<=?", (tenant, now)):
                self._set(tenant, r["id"], "expired", "system", "expired", {"reason": "approval window closed"}, now)
                self.counters["expired"] += 1
            for r in st.q("SELECT id FROM remediations WHERE tenant_id=? AND status='executed' AND verify_due_ts<=?", (tenant, now)):
                try:
                    self.verify(tenant, r["id"], now)
                except Exception as e:                                                       # noqa: BLE001
                    print("verify error:", type(e).__name__, e)

    # ---------------------------------------------------------------- internals
    def _set(self, tenant, rid, status, who, event, detail, now, ip=None, incident_id=None):
        with self.store_of(tenant).tx() as c:
            c.execute("UPDATE remediations SET status=? WHERE id=? AND tenant_id=?", (status, rid, tenant))
        if event:
            self._log(tenant, rid, who, event, detail, now, ip, incident_id)
        self._publish(tenant, rid)

    def _log(self, tenant, rid, actor, event, detail, now, ip=None, incident_id=None):
        with self.store_of(tenant).tx() as c:
            c.execute("INSERT INTO remediation_events(tenant_id,remediation_id,ts,actor,event,detail) VALUES(?,?,?,?,?,?)", (tenant, rid, now, actor, event, to_json(detail)))
        self.audit.record(tenant, actor, f"remediation_{event}", {"id": rid, **{k: v for k, v in detail.items() if k != "rules"}}, ip, now)
        if incident_id:
            self.incidents.event(tenant, incident_id, now, f"remediation_{event}", {"remediation": rid, "actor": actor, **{k: v for k, v in detail.items() if k in ("action", "verdict", "reason", "decision")}})

    def _publish(self, tenant, rid):
        r = self.store_of(tenant).one("SELECT id,status,action,node,incident_id,risk,confidence FROM remediations WHERE id=? AND tenant_id=?", (rid, tenant))
        if r:
            self.bus.publish(tenant, "remediation", {**r, "ref": f"REM-{r['id']}", "label": self.graph_of(tenant).name(r["node"]), "ts": time.time()})
