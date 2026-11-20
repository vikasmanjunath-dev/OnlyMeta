"""Incident correlation and root-cause analysis (P3).

An INCIDENT is one thing a human should look at, however many nodes it touches. Alerts say "node X is FAIR"; an incident says
"net-01 is the likely root cause; db-01 and app-01 are suffering because they depend on it" and carries the evidence.

Joining:  a node that turns abnormal (state FAIR/POOR, or an open anomaly) joins an open incident when
          (a) it is within `correlate_hops` of a member in the dependency map, and
          (b) its onset is within `correlation_window_s` (30 s) of that member's onset.
          If it bridges two open incidents they are merged. Otherwise it opens a new one.
Root cause: among the abnormal members, a CANDIDATE has no abnormal dependency (nothing upstream of it is also broken).
          Score = w_coverage * (share of members it explains: those that depend on it, directly or transitively)
                + w_timing   * (share of those that started AT OR AFTER it: upstream faults come first)
                + w_strength * (how far out of normal the candidate's own signals are)
          The weights are in thresholds.yaml and are shown to the user as the weighted explanation. Several candidates with
          disjoint reach are reported as several independent causes (never forced into one story).
Collector outage: nodes that went silent together are explained by a pseudo-node `collector:<id>`, not by the topology.
Everything is derived from event times, so replayed or late data correlates by when things HAPPENED."""
import json
import math
from collections import deque
from typing import Optional

from saas.health import RANK

COLLECTOR_PREFIX = "collector:"
SECURITY_PREFIX = "sec:"                               # pseudo-node for abuse of one signing key (not a topology node)
PSEUDO = (COLLECTOR_PREFIX, SECURITY_PREFIX)
SEV_OF = {"POOR": "critical", "FAIR": "high"}


# ------------------------------------------------------------------------------------------------ graph
class Graph:
    """Dependency graph keyed by node pseudonym. depends_on[a] = nodes a needs (a is hurt when they are)."""

    def __init__(self, topo: Optional[dict] = None):
        self.label = {p: v["label"] for p, v in (topo or {}).items()}
        self.deps = {p: set(v["depends_on"]) for p, v in (topo or {}).items()}
        self._closure: dict = {}

    def name(self, node: str) -> str:
        if node.startswith(COLLECTOR_PREFIX):
            return "collector " + node[len(COLLECTOR_PREFIX):]
        if node.startswith(SECURITY_PREFIX):
            return "signing key " + node[len(SECURITY_PREFIX):]
        return self.label.get(node, node[:12])

    def upstream(self, node: str, extra: Optional[dict] = None) -> set:
        """Everything `node` depends on, transitively."""
        seen, q = set(), deque(self._direct(node, extra))
        while q:
            n = q.popleft()
            if n in seen:
                continue
            seen.add(n)
            q.extend(self._direct(n, extra))
        return seen

    def _direct(self, node, extra):
        return self.deps.get(node, set()) | set((extra or {}).get(node, ()))

    def dependents(self, node: str) -> set:
        """Everything that depends on `node`, transitively (the blast radius of touching it)."""
        out = set()
        for n in self.deps:
            if node in self.upstream(n):
                out.add(n)
        return out

    def distance(self, a: str, b: str, limit: int) -> Optional[int]:
        """Undirected hops between two nodes, or None if farther than `limit` / not connected."""
        if a == b:
            return 0
        adj: dict = {}
        for n, ds in self.deps.items():
            for d in ds:
                adj.setdefault(n, set()).add(d)
                adj.setdefault(d, set()).add(n)
        seen, q = {a}, deque([(a, 0)])
        while q:
            n, h = q.popleft()
            if h >= limit:
                continue
            for m in adj.get(n, ()):
                if m == b:
                    return h + 1
                if m not in seen:
                    seen.add(m)
                    q.append((m, h + 1))
        return None


# ------------------------------------------------------------------------------------------------ signals
def static_signals(m: dict, auth: int, category: str) -> list:
    """The fixed-limit evidence (same limits as health.py), as structured signals."""
    s = []
    if category == "SERVICE_DOWN":
        s.append({"kind": "static", "metric": "service", "level": "POOR", "value": 1, "text": "service down"})
    if category == "SECURITY_BURST" and auth < 5:
        s.append({"kind": "static", "metric": "auth", "level": "FAIR", "value": auth, "text": "security burst"})
    if m["packet_loss"] > 10:
        s.append({"kind": "static", "metric": "packet_loss", "level": "POOR", "value": m["packet_loss"], "text": f"packet loss {m['packet_loss']:.1f}% > 10%"})
    elif m["packet_loss"] > 2:
        s.append({"kind": "static", "metric": "packet_loss", "level": "FAIR", "value": m["packet_loss"], "text": f"packet loss {m['packet_loss']:.1f}% > 2%"})
    if auth >= 10:
        s.append({"kind": "static", "metric": "auth", "level": "POOR", "value": auth, "text": f"{auth} failed logins in 60 s (brute force)"})
    elif auth >= 5:
        s.append({"kind": "static", "metric": "auth", "level": "FAIR", "value": auth, "text": f"{auth} failed logins in 60 s"})
    if m["cpu"] > 95:
        s.append({"kind": "static", "metric": "cpu", "level": "POOR", "value": m["cpu"], "text": f"CPU {m['cpu']:.0f}% > 95%"})
    elif m["cpu"] > 85:
        s.append({"kind": "static", "metric": "cpu", "level": "FAIR", "value": m["cpu"], "text": f"CPU {m['cpu']:.0f}% > 85%"})
    if m["mem"] > 90:
        s.append({"kind": "static", "metric": "mem", "level": "FAIR", "value": m["mem"], "text": f"memory {m['mem']:.0f}% > 90%"})
    if m["latency_ms"] > 250:
        s.append({"kind": "static", "metric": "latency_ms", "level": "FAIR", "value": m["latency_ms"], "text": f"latency {m['latency_ms']:.0f} ms > 250 ms"})
    return s


def anomaly_signals(verdicts: list) -> list:
    out = []
    for v in verdicts or []:
        if v.get("open") and v.get("z") is not None:
            z = v["z"] if abs(v["z"]) >= (v.get("peak_z") or 0) else math.copysign(v["peak_z"], v["z"])      # evidence is the PEAK of the run, not the sample the calm feed just sent
            out.append({"kind": "anomaly", "metric": v["metric"], "z": round(z, 2), "current_z": round(v["z"], 2), "value": round(v["value"], 2), "baseline": round(v["mean"], 2),
                        "sigma": round(v["sigma"], 2), "onset_ts": v.get("onset_ts")})
    return out


HEADLINE = {"cpu": "CPU saturation", "mem": "memory pressure", "latency_ms": "latency degradation", "packet_loss": "packet loss",
            "auth": "failed-login burst", "service": "service down", "stale": "node silent", "bandwidth_mbps": "bandwidth anomaly",
            "collector_offline": "collector offline", "joint": "unusual combination of metrics"}


def primary_metric(signals: list) -> Optional[str]:
    """Which metric best names this node's problem: strongest anomaly, else the most severe static signal."""
    an = [s for s in signals if s["kind"] == "anomaly"]
    st = [s for s in signals if s["kind"] in ("static", "stale", "collector_offline")]
    order = {"service": 0, "collector_offline": 0, "stale": 1, "auth": 2, "packet_loss": 3, "cpu": 4, "mem": 5, "latency_ms": 6}
    if st and (not an or any(s["metric"] in ("service", "stale", "collector_offline") for s in st)):
        return min(st, key=lambda s: order.get(s["metric"], 9))["metric"]
    if an:
        return max(an, key=lambda s: abs(s["z"]))["metric"]
    return min(st, key=lambda s: order.get(s["metric"], 9))["metric"] if st else None


def strength(signals: list, state: str, thr: float) -> float:
    """0..1: how far out of normal this node is. Anomalies by z (6 sigma = 1.0), static signals by level, silence = 1.0."""
    best = 0.0
    for s in signals:
        if s["kind"] == "anomaly":
            best = max(best, min(1.0, abs(s["z"]) / (2 * thr)))
        elif s["kind"] in ("stale", "collector_offline"):
            best = max(best, 1.0)
        else:
            best = max(best, 1.0 if s.get("level") == "POOR" else 0.6)
    return round(best or (1.0 if state == "POOR" else 0.5), 3)


# ------------------------------------------------------------------------------------------------ root cause
def rca(members: dict, graph: Graph, cfg: dict, thr: float = 3.0, extra_deps: Optional[dict] = None) -> dict:
    """members: {node: {onset_ts, state, signals, ...}} -> the weighted explanation. Pure and deterministic."""
    w = cfg["rca_weights"]
    tol = float(cfg["timing_tolerance_s"])
    nodes = list(members)
    up = {n: graph.upstream(n, extra_deps) & set(nodes) for n in nodes}                 # abnormal things n depends on
    cands = [n for n in nodes if not up[n]]                                              # nothing abnormal upstream of it
    scored = []
    for c in cands:
        reach = [n for n in nodes if n != c and c in up[n]]
        cover = (len(reach) + 1) / len(nodes)
        later = [n for n in reach if members[n]["onset_ts"] >= members[c]["onset_ts"] - tol]
        timing = (len(later) / len(reach)) if reach else 1.0
        st = strength(members[c]["signals"], members[c]["state"], thr)
        score = w["coverage"] * cover + w["timing"] * timing + w["strength"] * st
        scored.append({"node": c, "score": round(score, 3), "reach": reach, "coverage": round(cover, 3), "timing": round(timing, 3),
                       "strength": st, "onset_ts": members[c]["onset_ts"]})
    scored.sort(key=lambda r: (-r["score"], r["onset_ts"], -r["strength"], r["node"]))
    top = scored[0]
    root = top["node"]
    roles = {}
    for n in nodes:
        roles[n] = "root" if n == root else ("downstream" if n in top["reach"] else "independent" if n in {r["node"] for r in scored} else "associated")
    other_roots = [r for r in scored[1:] if not set(r["reach"]) <= set(top["reach"]) or r["node"] not in top["reach"]]
    factors = [
        {"name": "coverage", "weight": w["coverage"], "value": top["coverage"], "contribution": round(w["coverage"] * top["coverage"], 3),
         "note": f"explains {len(top['reach'])} of {len(nodes) - 1} other affected node(s)" if len(nodes) > 1 else "only node affected"},
        {"name": "timing", "weight": w["timing"], "value": top["timing"], "contribution": round(w["timing"] * top["timing"], 3),
         "note": "upstream failed first" if top["reach"] and top["timing"] == 1.0 else ("some dependents started earlier" if top["reach"] else "no dependents to order")},
        {"name": "strength", "weight": w["strength"], "value": top["strength"], "contribution": round(w["strength"] * top["strength"], 3),
         "note": "how far its own signals are from normal"},
    ]
    chain = sorted(({"node": n, "label": graph.name(n), "role": roles[n], "onset_ts": members[n]["onset_ts"], "state": members[n]["state"],
                     "signals": members[n]["signals"]} for n in nodes), key=lambda r: (r["onset_ts"], r["node"]))
    return {"root": root, "root_label": graph.name(root), "confidence": top["score"], "factors": factors, "chain": chain,
            "independent_roots": [{"node": r["node"], "label": graph.name(r["node"]), "score": r["score"]} for r in other_roots],
            "multi_root": bool(other_roots), "weights": dict(w)}


def narrate(ex: dict, graph: Graph, members: dict) -> str:
    """The explanation as plain sentences. No model, no guessing: it only restates the evidence."""
    root = ex["root"]
    rl = ex["root_label"]
    sig = members[root]["signals"]
    pm = primary_metric(sig)
    what = HEADLINE.get(pm, "abnormal behaviour")
    first = next((s for s in sig if s["kind"] == "anomaly" and s["metric"] == pm), None)
    ev = (" (no single metric out of range, jointly improbable)" if pm == "joint" else f" ({abs(first['z']):.1f}σ above its baseline)") if first else ""
    down = [c for c in ex["chain"] if c["role"] == "downstream"]
    t0 = members[root]["onset_ts"]
    if len(members) == 1:
        txt = f"{rl}: {what}{ev}."
    else:
        lag = ""
        if down:
            lags = sorted(max(0.0, c["onset_ts"] - t0) for c in down)
            lag = f" {', '.join(c['label'] for c in down)}, which depend{'s' if len(down) == 1 else ''} on it, degraded {(f'{lags[0]:.0f}–{lags[-1]:.0f}' if round(lags[0])!=round(lags[-1]) else f'{lags[0]:.0f}')} s later." if lags[-1] > 0 else \
                  f" {', '.join(c['label'] for c in down)}, which depend{'s' if len(down) == 1 else ''} on it, degraded at the same time."
        txt = f"{rl} is the likely root cause ({ex['confidence'] * 100:.0f}% confidence): {what}{ev} began first.{lag}"
    if ex["multi_root"]:
        txt += " " + ", ".join(r["label"] for r in ex["independent_roots"]) + " also show problems that its failure does not explain (independent cause)."
    return txt


def incident_kind(members: dict, root: str) -> str:
    sig = members[root]["signals"]
    if any(s["kind"] == "collector_offline" for s in sig):
        return "availability"
    if any(s["metric"] in ("service", "stale") for s in sig):
        return "availability"
    if sig and all(s["metric"] == "auth" for s in sig):
        return "security"
    return "performance"


def title_of(ex: dict, members: dict, graph: Graph) -> str:
    root = ex["root"]
    pm = primary_metric(members[root]["signals"])
    n_down = sum(1 for c in ex["chain"] if c["role"] == "downstream")
    extra = f" (+{n_down} dependent{'s' if n_down != 1 else ''} affected)" if n_down else ""
    return f"{graph.name(root)}: {HEADLINE.get(pm, 'abnormal')}{extra}"


def to_json(x) -> str:
    return json.dumps(x, separators=(",", ":"), default=str)


def worst_state(members: dict) -> str:
    return max((m["state"] for m in members.values()), key=lambda s: RANK.get(s, 0), default="FAIR")
