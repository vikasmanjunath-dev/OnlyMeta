"""Maintenance windows: an admin tells the platform "this node (or everything) is being worked on until HH:MM".
Inside a window the node still reports and is still scored, but opens no incident and drafts no fix, so planned work does not page.
Windows are tenant-scoped, time-boxed (max 24 h), need a reason, and are audited when set and cancelled. Nothing is hidden: the count of
suppressed observations is shown next to the window."""
import time
from typing import Optional

MAX_S = 24 * 3600


class MaintenanceError(Exception):
    def __init__(self, status: int, msg: str):
        super().__init__(msg)
        self.status, self.message = status, msg


class Maintenance:
    def __init__(self, store_of, audit):
        self.store_of, self.audit = store_of, audit
        self.suppressed: dict = {}                       # (tenant, window id) -> observations ignored since start (in memory)
        self._cache: dict = {}                           # tenant -> (loaded_at, [rows])

    def _rows(self, tenant: str, now: float) -> list:
        at, rows = self._cache.get(tenant, (0, None))
        if rows is None or now - at > 2 or now < at:
            rows = self.store_of(tenant).q("SELECT * FROM maintenance WHERE tenant_id=? AND cancelled=0 AND end_ts>?", (tenant, now - 3600))
            self._cache[tenant] = (now, rows)
        return rows

    def add(self, tenant: str, node: Optional[str], label: str, start: float, end: float, reason: str, who: str, now: float, ip=None) -> dict:
        reason = (reason or "").strip()
        if len(reason) < 3:
            raise MaintenanceError(422, "give a reason (3+ characters)")
        if not (end > start) or end - start > MAX_S:
            raise MaintenanceError(422, "window must end after it starts and last at most 24 h")
        if end <= now:
            raise MaintenanceError(422, "window already over")
        with self.store_of(tenant).tx() as c:
            cur = c.execute("INSERT INTO maintenance(tenant_id,node,label,start_ts,end_ts,reason,created_by,created_ts,cancelled) VALUES(?,?,?,?,?,?,?,?,0)",
                            (tenant, node, label, start, end, reason[:200], who, now))
        self._cache.pop(tenant, None)
        self.audit.record(tenant, who, "maintenance_set", {"id": cur.lastrowid, "node": label, "start": start, "end": end, "reason": reason[:200]}, ip, now)
        return self.get(tenant, cur.lastrowid, now)

    def cancel(self, tenant: str, wid: int, who: str, now: float, ip=None) -> bool:
        with self.store_of(tenant).tx() as c:
            n = c.execute("UPDATE maintenance SET cancelled=1 WHERE tenant_id=? AND id=? AND cancelled=0", (tenant, wid)).rowcount
        self._cache.pop(tenant, None)
        if n:
            self.audit.record(tenant, who, "maintenance_cancelled", {"id": wid}, ip, now)
        return bool(n)

    def active(self, tenant: str, node: str, ts: float, now: Optional[float] = None) -> Optional[dict]:
        """The window covering `node` at event time `ts`, if any (a window with node NULL covers every node of the tenant)."""
        for r in self._rows(tenant, now if now is not None else time.time()):
            if r["start_ts"] <= ts <= r["end_ts"] and r["node"] in (None, node):
                return r
        return None

    def note(self, tenant: str, wid: int):
        self.suppressed[(tenant, wid)] = self.suppressed.get((tenant, wid), 0) + 1

    def _view(self, tenant: str, r: dict, now: float) -> dict:
        st = "cancelled" if r["cancelled"] else "scheduled" if now < r["start_ts"] else "active" if now <= r["end_ts"] else "ended"
        return {**r, "status": st, "suppressed": self.suppressed.get((tenant, r["id"]), 0)}

    def get(self, tenant: str, wid: int, now: float) -> Optional[dict]:
        r = self.store_of(tenant).one("SELECT * FROM maintenance WHERE tenant_id=? AND id=?", (tenant, wid))
        return self._view(tenant, r, now) if r else None

    def list(self, tenant: str, now: float, limit: int = 50) -> list:
        return [self._view(tenant, r, now) for r in self.store_of(tenant).q("SELECT * FROM maintenance WHERE tenant_id=? ORDER BY id DESC LIMIT ?", (tenant, limit))]
