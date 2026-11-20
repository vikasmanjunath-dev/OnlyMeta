"""Tamper-evident audit log. Each row stores sha256(prev_hash | tenant | ts | actor | action | detail | ip), so editing,
deleting or reordering any past row breaks every hash after it. verify() recomputes the chain."""
import hashlib
import json
import time
from typing import Optional

GENESIS = "0" * 64


def _h(prev: str, tenant: str, ts: float, actor: str, action: str, detail: str, ip: str) -> str:
    return hashlib.sha256("|".join([prev, tenant, f"{ts:.6f}", actor, action, detail, ip or ""]).encode()).hexdigest()


class AuditLog:
    def __init__(self, engine_store_of):
        self.store_of = engine_store_of
        self._throttle: dict = {}

    def record(self, tenant: str, actor: str, action: str, detail: Optional[dict] = None, ip: Optional[str] = None, now: Optional[float] = None):
        store, ts = self.store_of(tenant), now if now is not None else time.time()
        d = json.dumps(detail or {}, sort_keys=True, separators=(",", ":"))[:2000]
        with store.tx() as c:                                  # chain per tenant, appended atomically
            last = c.execute("SELECT hash FROM audit WHERE tenant_id=? ORDER BY id DESC LIMIT 1", (tenant,)).fetchone()
            prev = last["hash"] if last else GENESIS
            c.execute("INSERT INTO audit(tenant_id,ts,actor,action,detail,ip,prev_hash,hash) VALUES(?,?,?,?,?,?,?,?)",
                      (tenant, ts, actor, action, d, ip, prev, _h(prev, tenant, ts, actor, action, d, ip)))

    def record_throttled(self, tenant: str, actor: str, action: str, detail: dict, ip: Optional[str], every_s: float = 60, now: Optional[float] = None):
        """For noisy events (auth failures): at most one row per (tenant, actor, action, ip) per window, with a count."""
        now = now if now is not None else time.time()
        k = (tenant, actor, action, ip)
        t, n = self._throttle.get(k, (0.0, 0))
        if now - t < every_s:
            self._throttle[k] = (t, n + 1)
            return False
        self._throttle[k] = (now, 0)
        self.record(tenant, actor, action, {**detail, "suppressed_since_last": n}, ip, now)
        return True

    def rows(self, tenant: str, limit: int = 100) -> list:
        out = self.store_of(tenant).q("SELECT id,ts,actor,action,detail,ip,hash FROM audit WHERE tenant_id=? ORDER BY id DESC LIMIT ?", (tenant, limit))
        for r in out:
            r["detail"] = json.loads(r["detail"])
        return out

    def verify(self, tenant: str) -> dict:
        prev, n = GENESIS, 0
        for r in self.store_of(tenant).q("SELECT * FROM audit WHERE tenant_id=? ORDER BY id", (tenant,)):
            n += 1
            if r["prev_hash"] != prev or r["hash"] != _h(prev, tenant, r["ts"], r["actor"], r["action"], r["detail"], r["ip"]):
                return {"ok": False, "rows": n, "first_bad_id": r["id"]}
            prev = r["hash"]
        return {"ok": True, "rows": n, "head": prev}
