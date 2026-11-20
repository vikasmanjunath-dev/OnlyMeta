"""Alert-noise reduction. A health state change is an EVENT; an alert is something a human should look at once.

Rules (all measurable via summary()):
  * Only a move INTO fair/poor (or a collector going offline) can open an alert; a move back to good/excellent resolves it.
  * Fold: the same node + same signature (reasons with the numbers stripped, so "CPU 91%" and "CPU 93%" are one thing)
    while the alert is open, or within the cool-down after it closed, only bumps the count: no new alert.
  * Flap: N state changes on one node inside the flap window become ONE "flapping" alert; individual ones are folded
    into it until the node has been quiet for a window.
  * Acknowledged alerts keep folding repeats, so acknowledging does not re-open the noise.
Reduction % = 1 - alerts shown / alert-worthy transitions, over the same window."""
import json
import re
from typing import Optional

from saas.health import RANK

_NUM = re.compile(r"\d+(?:\.\d+)?")


def signature(node: str, state: str, reasons: list) -> str:
    """Stable identity of a problem: numbers are removed so a drifting value does not look like a new problem."""
    head = _NUM.sub("#", (reasons or ["?"])[0]).strip().lower()
    return f"{node}|{state}|{head}"


def _title(node: str, state: str, reasons: list) -> str:
    return f"{node[:14]} is {state}: {(reasons or ['?'])[0]}"


class AlertManager:
    def __init__(self, settings, bus):
        self.s, self.bus = settings, bus

    def on_transition(self, store, tenant: str, node: str, old: Optional[str], new: str, reasons: list, ts: float):
        """Called for EVERY state change (including ones that raise no alert) so flap detection sees them all."""
        bad = RANK[new] >= RANK["FAIR"]
        open_ = store.one("SELECT * FROM alerts WHERE tenant_id=? AND node=? AND state='open' ORDER BY id DESC LIMIT 1", (tenant, node))
        recent = store.one("SELECT COUNT(*) n FROM state_history WHERE tenant_id=? AND node=? AND ts>=?", (tenant, node, ts - self.s.flap_window_s))["n"]
        flapping = recent >= self.s.flap_transitions
        if flapping:
            return self._flap(store, tenant, node, open_, recent, ts)
        if open_ and open_["kind"] == "flapping":
            return self._fold(store, open_, ts)                                    # still inside a flap episode
        if not bad:
            if open_:
                self._resolve(store, tenant, open_, ts)
            return None
        sig = signature(node, new, reasons)
        if open_ and open_["signature"] == sig:
            return self._fold(store, open_, ts)
        if open_:                                                                  # same node, different problem: supersede
            self._resolve(store, tenant, open_, ts, superseded=True)
        last = store.one("SELECT * FROM alerts WHERE tenant_id=? AND signature=? AND state='resolved' AND resolved_ts>=? ORDER BY id DESC LIMIT 1",
                         (tenant, sig, ts - self.s.cooldown_s))
        if last:                                                                   # cool-down: re-open the same alert, do not page again
            with store.tx() as c:
                c.execute("UPDATE alerts SET state='open', resolved_ts=NULL, last_ts=?, count=count+1 WHERE id=?", (ts, last["id"]))
            return last["id"]
        return self._open(store, tenant, node, "state", sig, "critical" if new == "POOR" else "high", _title(node, new, reasons), reasons, ts)

    def on_collector(self, store, tenant: str, collector_id: str, offline: bool, silent_s: float, ts: float):
        node, sig = f"collector:{collector_id}", f"collector:{collector_id}|offline"
        open_ = store.one("SELECT * FROM alerts WHERE tenant_id=? AND node=? AND state='open'", (tenant, node))
        if offline:
            if open_:
                return self._fold(store, open_, ts)
            return self._open(store, tenant, node, "collector", sig, "critical", f"collector {collector_id} offline: no data for {silent_s:.0f} s",
                              [f"no data for {silent_s:.0f} s"], ts)
        if open_:
            self._resolve(store, tenant, open_, ts)

    # ---------------------------------------------------------------- internals
    def _open(self, store, tenant, node, kind, sig, sev, title, reasons, ts):
        with store.tx() as c:
            cur = c.execute("INSERT INTO alerts(tenant_id,node,kind,signature,severity,title,reasons,first_ts,last_ts) VALUES(?,?,?,?,?,?,?,?,?)",
                            (tenant, node, kind, sig, sev, title, json.dumps(reasons), ts, ts))
        self.bus.publish(tenant, "alert", {"id": cur.lastrowid, "node": node, "kind": kind, "severity": sev, "title": title, "state": "open", "ts": ts})
        return cur.lastrowid

    def _fold(self, store, row, ts):
        with store.tx() as c:
            c.execute("UPDATE alerts SET count=count+1, last_ts=? WHERE id=?", (ts, row["id"]))
        return row["id"]

    def _resolve(self, store, tenant, row, ts, superseded=False):
        with store.tx() as c:
            c.execute("UPDATE alerts SET state='resolved', resolved_ts=? WHERE id=?", (ts, row["id"]))
        self.bus.publish(tenant, "alert", {"id": row["id"], "node": row["node"], "state": "resolved", "superseded": superseded, "ts": ts})

    def _flap(self, store, tenant, node, open_, n, ts):
        if open_ and open_["kind"] == "flapping":
            return self._fold(store, open_, ts)
        if open_:
            self._resolve(store, tenant, open_, ts, superseded=True)
        return self._open(store, tenant, node, "flapping", f"{node}|flapping", "high", f"{node[:14]} is flapping: {n} state changes in {int(self.s.flap_window_s)} s",
                          [f"{n} state changes in {int(self.s.flap_window_s)} s"], ts)

    def close_quiet_flaps(self, store, tenant: str, now: float) -> int:
        """A flapping alert resolves once the node has been quiet for a full window."""
        n = 0
        for r in store.q("SELECT * FROM alerts WHERE tenant_id=? AND kind='flapping' AND state='open'", (tenant,)):
            if now - r["last_ts"] >= self.s.flap_window_s:
                self._resolve(store, tenant, r, now)
                n += 1
        return n

    # ---------------------------------------------------------------- reads
    def list(self, store, tenant: str, state: Optional[str] = None, limit: int = 100) -> list:
        sql, args = "SELECT * FROM alerts WHERE tenant_id=? ", [tenant]
        if state in ("open", "resolved"):
            sql, args = sql + "AND state=? ", args + [state]
        rows = store.q(sql + "ORDER BY id DESC LIMIT ?", args + [limit])
        for r in rows:
            r["reasons"] = json.loads(r["reasons"] or "[]")
        return rows

    def ack(self, store, tenant: str, alert_id: int, who: str, now: float) -> bool:
        with store.tx() as c:
            return c.execute("UPDATE alerts SET ack_by=?, ack_ts=? WHERE id=? AND tenant_id=?", (who, now, alert_id, tenant)).rowcount > 0

    def summary(self, store, tenant: str, now: float, window_s: float = 3600) -> dict:
        since = now - window_s
        worthy = store.one("SELECT COUNT(*) n FROM state_history WHERE tenant_id=? AND ts>=? AND new IN ('FAIR','POOR')", (tenant, since))["n"]
        coll = store.one("SELECT COUNT(*) n FROM alerts WHERE tenant_id=? AND kind='collector' AND first_ts>=?", (tenant, since))["n"]
        shown = store.one("SELECT COUNT(*) n, COALESCE(SUM(count-1),0) f FROM alerts WHERE tenant_id=? AND kind<>'collector' AND first_ts>=?", (tenant, since))
        opened = store.one("SELECT COUNT(*) n FROM alerts WHERE tenant_id=? AND state='open'", (tenant,))["n"]
        raw = worthy
        return {"window_s": window_s, "alert_worthy_transitions": raw, "alerts_shown": shown["n"], "folded_repeats": max(0, raw - shown["n"]),
                "collector_alerts": coll, "open_now": opened,
                "noise_reduction_pct": round(100 * (1 - shown["n"] / raw), 1) if raw else None}
