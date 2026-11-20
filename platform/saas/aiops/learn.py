"""Learned topology: which node deviates FIRST when things go wrong, over and over, is upstream of the nodes that follow it.

Pure and deterministic (no clock, no I/O): rows in, evidence out, so every edge can be re-derived and audited.
  1. per node, a robust baseline (median / MAD over the look-back) and its deviation episodes (|z| >= z for min_run samples);
  2. per node pair, episodes that co-occur within `window_s`; the one that starts earlier, consistently, is upstream;
  3. an edge needs `min_support` ordered co-occurrences, a sign-test p <= max_p, and a lift over chance >= min_lift;
  4. skip-level edges that a chain already explains are dropped (transitive reduction);
  5. every edge is compared with the declared map: confirmed / new / implied / contradicts.
Learned edges are only SUGGESTIONS. An admin accepts one (audited) before root-cause analysis uses it."""
import statistics
from math import comb
from typing import Callable, Optional

from saas.aiops.baseline import METRICS

DEFAULTS = {"window_s": 20.0, "episode_gap_s": 60.0, "z": 4.0, "min_run": 2, "bucket_s": 5.0, "tie_s": 2.0, "min_rows": 30,
            "min_support": 3, "max_p": 0.15, "min_lift": 2.5, "lookback_s": 21600}


def settings(cfg: Optional[dict]) -> dict:
    return {**DEFAULTS, **{k: v for k, v in (cfg or {}).items() if k in DEFAULTS}}


def sign_test_p(k: int, n: int) -> float:
    """One-sided P(at least k of n go the same way | no direction, p=0.5)."""
    return sum(comb(n, i) for i in range(k, n + 1)) / 2 ** n if n else 1.0


# ------------------------------------------------------------------------------------------------ episodes
def node_episodes(rows: list, cfg: dict, sigma_eff: Callable) -> list:
    """Onset times of this node's deviation episodes. rows: dicts with event_ts and the METRICS keys, ascending in time."""
    if len(rows) < cfg["min_rows"]:
        return []
    base = {}
    for m in METRICS:
        vals = [r[m] for r in rows if r.get(m) is not None]
        if len(vals) >= cfg["min_rows"]:
            med = statistics.median(vals)
            base[m] = (med, sigma_eff(m, med, 1.4826 * statistics.median(abs(v - med) for v in vals)))
    hot = [r["event_ts"] for r in rows if any(r.get(m) is not None and abs(r[m] - mu) / sg >= cfg["z"] for m, (mu, sg) in base.items())]
    runs, cur = [], []
    for t in hot:
        if cur and t - cur[-1] <= 2 * cfg["bucket_s"]:
            cur.append(t)
        else:
            runs.append(cur)
            cur = [t]
    runs.append(cur)
    onsets = []
    for run in runs:
        if len(run) < cfg["min_run"]:
            continue
        if onsets and run[0] - onsets[-1] < cfg["episode_gap_s"]:           # one incident, not two
            continue
        onsets.append(run[0])
    return onsets


# ------------------------------------------------------------------------------------------------ pairs
def pair_evidence(a: str, b: str, ea: list, eb: list, span: float, cfg: dict) -> Optional[dict]:
    """Evidence about the pair (a, b) from their episode onsets. Direction is reported as up -> dep (up starts first)."""
    W, tie = cfg["window_s"], cfg["tie_s"]
    fwd, rev, ties, lags = 0, 0, 0, []
    for ta in ea:
        tb = min(eb, key=lambda t: abs(t - ta), default=None)
        if tb is None or abs(tb - ta) > W:
            continue
        d = tb - ta                                                                    # > 0: a starts first
        if d > tie:
            fwd, lags = fwd + 1, lags + [d]
        elif d < -tie:
            rev, lags = rev + 1, lags + [-d]
        else:
            ties += 1
    co = fwd + rev + ties
    if not co:
        return None
    n = fwd + rev
    k = max(fwd, rev)
    up, dep = (a, b) if fwd >= rev else (b, a)
    expected = len(ea) * min(1.0, len(eb) * 2 * W / span) if span > 0 else float("inf")
    return {"up": up, "dep": dep, "support": n, "forward": k, "reverse": n - k, "ties": ties, "co_occurrences": co,
            "p": round(sign_test_p(k, n), 4), "lift": round(co / expected, 2) if expected else None,
            "lag_s": round(statistics.median(lags), 1) if lags else None, "episodes": {a: len(ea), b: len(eb)}}


def accepted(ev: dict, cfg: dict) -> bool:
    return ev["support"] >= cfg["min_support"] and ev["p"] <= cfg["max_p"] and (ev["lift"] is None or ev["lift"] >= cfg["min_lift"]) and ev["forward"] > ev["reverse"]


# ------------------------------------------------------------------------------------------------ graph helpers
def _reaches(adj: dict, a: str, b: str, skip: Optional[tuple] = None) -> bool:
    seen, stack = set(), [a]
    while stack:
        n = stack.pop()
        for m in adj.get(n, ()):
            if (n, m) == skip:
                continue
            if m == b:
                return True
            if m not in seen:
                seen.add(m)
                stack.append(m)
    return False


def would_cycle(deps: dict, up: str, dep: str) -> bool:
    """deps[x] = what x depends on. Adding 'dep depends on up' creates a cycle if up already (transitively) depends on dep."""
    adj = {n: set(v) for n, v in deps.items()}
    return up == dep or _reaches(adj, up, dep)


def declared_edges(topo: dict) -> set:
    return {(d, n) for n, v in topo.items() for d in v["depends_on"]}               # (up, dep)


# ------------------------------------------------------------------------------------------------ the learner
def learn(series: dict, topo: dict, cfg: Optional[dict], sigma_eff: Callable) -> dict:
    """series: {node: [row, ...]}. topo: the declared map (pseudonyms). -> edges with evidence, undirected pairs, declared-edge support."""
    cfg = settings(cfg)
    eps = {n: node_episodes(rows, cfg, sigma_eff) for n, rows in series.items()}
    times = [r["event_ts"] for rows in series.values() for r in rows]
    span = (max(times) - min(times)) if times else 0.0
    nodes = sorted(n for n in eps if eps[n])
    pairs = {}
    for i, a in enumerate(nodes):
        for b in nodes[i + 1:]:
            ev = pair_evidence(a, b, eps[a], eps[b], span, cfg)
            if ev:
                pairs[frozenset((a, b))] = ev
    keep = {k: v for k, v in pairs.items() if accepted(v, cfg)}
    adj: dict = {}
    for v in keep.values():
        adj.setdefault(v["up"], set()).add(v["dep"])
    indirect = []
    for v in list(keep.values()):                                                     # a chain already explains a skip-level edge
        if _reaches(adj, v["up"], v["dep"], skip=(v["up"], v["dep"])):
            indirect.append({**v, "reason": "explained by a longer chain"})
            adj[v["up"]].discard(v["dep"])
            del keep[frozenset((v["up"], v["dep"]))]
    decl = declared_edges(topo)
    ddeps = {n: set(v["depends_on"]) for n, v in topo.items()}
    dadj: dict = {}
    for up, dep in decl:
        dadj.setdefault(up, set()).add(dep)
    edges = []
    for v in sorted(keep.values(), key=lambda e: (e["up"], e["dep"])):
        if (v["up"], v["dep"]) in decl:
            status = "confirmed"
        elif (v["dep"], v["up"]) in decl:
            status = "contradicts"
        elif _reaches(dadj, v["up"], v["dep"]):
            status = "implied"
        else:
            status = "new"
        edges.append({**v, "status": status, "cycle": would_cycle(ddeps, v["up"], v["dep"]) if status != "confirmed" else False})
    undirected = [{"nodes": sorted(k), "co_occurrences": v["co_occurrences"], "ties": v["ties"], "support": v["support"],
                   "why": "start at the same time, so direction cannot be told" if v["support"] < cfg["min_support"] and v["ties"] else "not enough ordered evidence yet"}
                  for k, v in pairs.items() if k not in keep and not any(i["up"] in k and i["dep"] in k for i in indirect)]
    seen = {frozenset((e["up"], e["dep"])) for e in edges}
    unverified = []
    for up, dep in sorted(decl):
        ev = pairs.get(frozenset((up, dep)))
        unverified.append({"up": up, "dep": dep, "seen": frozenset((up, dep)) in seen, "co_occurrences": ev["co_occurrences"] if ev else 0})
    return {"params": cfg, "span_s": round(span, 1), "episodes": {n: len(v) for n, v in eps.items()}, "edges": edges, "indirect": indirect,
            "undirected": sorted(undirected, key=lambda x: x["nodes"]), "declared": unverified}
