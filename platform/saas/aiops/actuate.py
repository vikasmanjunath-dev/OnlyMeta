"""Real actuation (P8): the SaaS never executes anything itself. It queues a signed COMMAND; the customer's collector (inside their
boundary) fetches it over the already-authenticated channel, re-verifies it, executes it only if its owner switched the actuator on and
the action is in its local allow-list, and reports the result back.

  * two keys: tenant admin sets actuator=collector (SaaS side) AND the collector runs with ACTUATOR != off (customer side);
  * commands are signed at delivery with the polling collector's own key, expire after TTL_S, and are delivered at most once
    (a command whose outcome is unknown is never re-sent: a person checks, instead of the system acting twice);
  * the collector's capability list is its declaration of what it can do; the SaaS refuses to queue anything outside it;
  * nothing is queued when the collector has not been seen recently, so an approved action never fires 'later' on stale conditions."""
import json
from typing import Optional

from contracts.signing import command_sign
from saas.aiops.remediate import ACTIONS, INTERNAL, RemediationError

TTL_S = 60.0
FRESH_S = 15.0
KNOWN = set(ACTIONS) | INTERNAL
DONE = ("applied", "refused", "failed")


class CommandActuator:
    name = "collector"

    def __init__(self, store_of, audit, tenants: list):
        self.store_of, self.audit, self.tenants = store_of, audit, tenants
        self.caps: dict = {}                                   # tenant -> (ts, set(actions))
        self.on_result = None                                  # set by the Remediator: (tenant, cmd_row, now)

    # -------------------------------------------------------------- capabilities (what the collector declares it can do)
    def seen(self, tenant: str, caps, now: float) -> list:
        ok = sorted({c for c in caps if c in KNOWN})[:30]
        self.caps[tenant] = (now, set(ok))
        return ok

    def online(self, tenant: str, now: float) -> Optional[set]:
        ts, caps = self.caps.get(tenant, (0.0, set()))
        return caps if now - ts <= FRESH_S else None

    def status_of(self, tenant: str, now: float) -> dict:
        ts, caps = self.caps.get(tenant, (0.0, set()))
        return {"collector_seen_s_ago": round(now - ts, 1) if ts else None, "online": bool(ts and now - ts <= FRESH_S), "capabilities": sorted(caps)}

    # -------------------------------------------------------------- SaaS -> collector
    def apply(self, tenant: str, label: str, action: str, params: dict, now: float, rid: Optional[int] = None, **_) -> dict:
        caps = self.online(tenant, now)
        if caps is None:
            raise RemediationError(409, "the collector is not connected (no recent poll): nothing was queued")
        if action not in caps:
            raise RemediationError(409, f"the collector does not offer '{action}' (its actuator is off or the action is not in its allow-list): nothing was queued")
        with self.store_of(tenant).tx() as c:
            cur = c.execute("INSERT INTO commands(tenant_id,remediation_id,label,action,params,status,created_ts,exp_ts) VALUES(?,?,?,?,?,?,?,?)",
                            (tenant, rid, label, action, json.dumps(params or {}), "queued", now, now + TTL_S))
        return {"ok": True, "actuator": self.name, "ref": f"cmd-{cur.lastrowid}", "applied": {"action": action, "target": label, "params": params},
                "note": "queued for the collector, which re-verifies and executes it inside the customer's boundary, then reports back"}

    def deliver(self, tenant: str, kid: str, secret: str, now: float) -> list:
        """Called when the collector polls: expire stale rows, hand over queued ones (signed for THIS key), mark them sent. At most once."""
        st, out = self.store_of(tenant), []
        with st.tx() as c:
            c.execute("UPDATE commands SET status='expired', done_ts=? WHERE tenant_id=? AND status='queued' AND exp_ts<?", (now, tenant, now))
            c.execute("UPDATE commands SET status='unknown', done_ts=? WHERE tenant_id=? AND status='sent' AND exp_ts+30<?", (now, tenant, now))
            for r in c.execute("SELECT * FROM commands WHERE tenant_id=? AND status='queued' ORDER BY id LIMIT 10", (tenant,)).fetchall():
                params, exp = json.loads(r["params"] or "{}"), int(r["exp_ts"]) + 1
                out.append({"id": r["id"], "tenant": tenant, "kid": kid, "action": r["action"], "target": r["label"], "params": params, "exp": exp,
                            "sig": command_sign(secret, r["id"], tenant, kid, r["action"], r["label"], params, exp)})
                c.execute("UPDATE commands SET status='sent', sent_ts=?, kid=? WHERE id=?", (now, kid, r["id"]))
        return out

    # -------------------------------------------------------------- collector -> SaaS
    def result(self, tenant: str, cid: int, status: str, detail: dict, now: float) -> dict:
        if status not in DONE:
            raise RemediationError(422, f"status must be one of {DONE}")
        st = self.store_of(tenant)
        r = st.one("SELECT * FROM commands WHERE tenant_id=? AND id=?", (tenant, cid))
        if not r:
            raise RemediationError(404, "unknown command")
        if r["status"] != "sent":
            raise RemediationError(409, f"command is '{r['status']}', not awaiting a result")
        with st.tx() as c:
            c.execute("UPDATE commands SET status=?, done_ts=?, result=? WHERE id=? AND tenant_id=?", (status, now, json.dumps(detail)[:1500], cid, tenant))
        self.audit.record(tenant, f"collector:{r['kid']}", f"command_{status}", {"command": cid, "action": r["action"], "target": r["label"], "remediation": r["remediation_id"]}, None, now)
        row = st.one("SELECT * FROM commands WHERE tenant_id=? AND id=?", (tenant, cid))
        if self.on_result:
            self.on_result(tenant, row, now)
        return row

    def status(self, tenant: str, ref: str) -> Optional[dict]:
        if not str(ref).startswith("cmd-"):
            return None
        return self.store_of(tenant).one("SELECT id,status,created_ts,sent_ts,done_ts,result FROM commands WHERE tenant_id=? AND id=?", (tenant, int(str(ref)[4:])))

    def list(self, tenant: str, limit: int = 50) -> list:
        return [{**r, "params": json.loads(r["params"] or "{}"), "result": json.loads(r["result"]) if r["result"] else None}
                for r in self.store_of(tenant).q("SELECT id,remediation_id,label,action,params,status,created_ts,exp_ts,sent_ts,done_ts,result FROM commands WHERE tenant_id=? ORDER BY id DESC LIMIT ?",
                                                 (tenant, min(max(int(limit), 1), 200)))]


class ActuatorRouter:
    """Picks the actuator per tenant: simulation unless the tenant admin chose 'collector'."""
    def __init__(self, sim, cmd: CommandActuator, mode_of):
        self.sim, self.cmd, self.mode_of = sim, cmd, mode_of

    def real(self, tenant: str) -> bool:
        return self.mode_of(tenant) == "collector"

    def apply(self, tenant, label, action, params, now, **kw):
        return (self.cmd if self.real(tenant) else self.sim).apply(tenant, label, action, params, now, **kw)

    def status(self, tenant, ref):
        return self.cmd.status(tenant, ref)
