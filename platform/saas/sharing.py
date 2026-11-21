"""Share links: a revocable, expiring, read-only window onto one tenant, for people with no login.
kind=status   -> live health of the tenant's nodes + open incidents (a status page)
kind=incident -> one incident's story (timeline, root cause, what was done), for a manager or a customer
Only a SHA-256 of the token is stored. The token carries its region so a lookup touches exactly one database.
Public views are sanitised: no user names, IPs, node ids, metric values, keys or approver identities."""
import hashlib
import secrets
import time
from typing import Optional

KINDS = {"status", "incident"}
MAX_TTL_H, DEFAULT_TTL_H = 24 * 90, 24 * 7


def _h(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class Shares:
    def __init__(self, store_of, region_store, audit, eng, ai, regions):
        self.store_of, self.region_store, self.audit, self.eng, self.ai, self.regions = store_of, region_store, audit, eng, ai, set(regions)

    def create(self, tenant, region, user, kind, target, label, ttl_h, now=None, ip=None) -> dict:
        now = now if now is not None else time.time()
        if kind not in KINDS:
            raise ValueError("kind must be status or incident")
        if kind == "incident":
            if not isinstance(target, int) or not self.ai.inc.get(tenant, target):
                raise ValueError("unknown incident")
        else:
            target = None
        ttl_h = min(max(float(ttl_h or DEFAULT_TTL_H), 0.1), MAX_TTL_H)
        token = f"{region}.{secrets.token_urlsafe(24)}"
        with self.store_of(tenant).tx() as c:
            cur = c.execute("INSERT INTO share_links(tenant_id,kind,target,token_hash,label,created_by,created_ts,expires_ts) VALUES(?,?,?,?,?,?,?,?)",
                            (tenant, kind, target, _h(token), (label or "")[:80], user, now, now + ttl_h * 3600))
            sid = cur.lastrowid
        self.audit.record(tenant, user, "share_created", {"id": sid, "kind": kind, "target": target, "expires_h": round(ttl_h, 1)}, ip, now=now)
        return {"id": sid, "token": token, "path": f"/s/{token}", "kind": kind, "expires_ts": now + ttl_h * 3600}

    def list(self, tenant, now=None) -> list:
        now = now if now is not None else time.time()
        rows = self.store_of(tenant).q("SELECT id,kind,target,label,created_by,created_ts,expires_ts,revoked_ts,views,last_view_ts FROM share_links "
                                       "WHERE tenant_id=? ORDER BY id DESC LIMIT 200", (tenant,))
        for r in rows:
            r["status"] = "revoked" if r["revoked_ts"] else "expired" if r["expires_ts"] <= now else "active"
        return rows

    def revoke(self, tenant, user, sid, now=None, ip=None) -> bool:
        now = now if now is not None else time.time()
        with self.store_of(tenant).tx() as c:
            n = c.execute("UPDATE share_links SET revoked_ts=? WHERE tenant_id=? AND id=? AND revoked_ts IS NULL", (now, tenant, sid)).rowcount
        if n:
            self.audit.record(tenant, user, "share_revoked", {"id": sid}, ip, now=now)
        return bool(n)

    def resolve(self, token: str, now=None) -> Optional[dict]:
        """token -> link row (and counts the view) or None. Same answer for unknown / revoked / expired: no oracle."""
        now = now if now is not None else time.time()
        region = token.split(".", 1)[0] if "." in token else ""
        if region not in self.regions or len(token) > 120:
            return None
        store = self.region_store(region)
        with store.tx() as c:
            row = c.execute("SELECT * FROM share_links WHERE token_hash=?", (_h(token),)).fetchone()
            if not row or row["revoked_ts"] or row["expires_ts"] <= now:
                return None
            c.execute("UPDATE share_links SET views=views+1,last_view_ts=? WHERE id=?", (now, row["id"]))
        return dict(row)

    # ---- sanitised public views
    def view(self, link: dict, now=None) -> dict:
        now = now if now is not None else time.time()
        t = link["tenant_id"]
        base = {"kind": link["kind"], "label": link["label"], "generated_ts": now, "expires_ts": link["expires_ts"]}
        if link["kind"] == "status":
            f, g = self.eng.fleet(t), self.ai.graph(t)
            nodes = sorted(({"name": g.name(n["node"]), "state": n["state"], "stale": n["stale"], "since_s": round(n["since_s"])} for n in f["nodes"]), key=lambda x: x["name"])
            open_inc = [{"ref": i["ref"], "title": i["title"], "severity": i["severity"], "kind": i["kind"], "started_ts": i["first_ts"]}
                        for i in self.ai.inc.list(t, "open", 20)]
            return {**base, "overall": f["overall"], "nodes": nodes, "incidents": open_inc}
        v = self.ai.inc.get(t, link["target"])
        if not v:
            return {**base, "error": "incident no longer available"}
        rems = [{"action": r["action"], "status": r["status"], "node": self.ai.graph(t).name(r["node"]) if str(r["node"]).startswith("n-") else r["node"],
                 "verdict": (r.get("verdict") or {}).get("verdict") if isinstance(r.get("verdict"), dict) else r.get("verdict")}
                for r in self.ai.rem.list(t, incident_id=v["id"])]
        tl = [{"ts": e["ts"], "kind": e["kind"]} for e in v.get("timeline", []) if e["kind"] in ("opened", "resolved", "remediation_executed", "remediation_verified", "remediation_rolled_back", "acked")]
        ex = v.get("explanation") or {}
        return {**base, "incident": {"ref": v["ref"], "title": v["title"], "summary": v["summary"], "kind": v["kind"], "severity": v["severity"], "status": v["status"],
                                     "root_cause": v["root_label"], "confidence": v["confidence"], "started_ts": v["first_ts"], "resolved_ts": v["resolved_ts"],
                                     "duration_s": v.get("age_s", v["duration_s"]), "explanation": ex.get("text", ""), "affected": [m["label"] for m in v["members"]],
                                     "actions": rems, "timeline": tl}}
