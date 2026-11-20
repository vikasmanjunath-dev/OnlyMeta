"""Recommendation table: incident evidence -> ranked, explained, simulated fixes. Rule-based on purpose: every line is auditable."""
from typing import Optional

from saas.aiops.correlate import primary_metric
from saas.aiops.remediate import ACTIONS, RISK_W, simulate

# pattern -> [(action, prior, why)]. prior = how often this fix is the right first move (a judgement, shown, not hidden).
TABLE = {
    "cpu_saturation":      [("scale_out", .80, "add capacity: spreads the load"), ("throttle_traffic", .55, "shed 20% of inbound load while capacity is added"),
                            ("restart_service", .40, "clears a runaway process (last resort: not reversible)")],
    "memory_pressure":     [("restart_service", .70, "frees leaked memory with a rolling restart"), ("scale_out", .55, "more replicas dilute per-node memory")],
    "latency_degradation": [("scale_out", .65, "add capacity to cut queueing delay"), ("throttle_traffic", .50, "reduce load while latency recovers")],
    "network_loss":        [("failover_link", .80, "packet loss points at the link: move traffic to the secondary"), ("throttle_traffic", .35, "reduce load on a lossy link")],
    "auth_burst":          [("block_source", .80, "stop the offending source"), ("rate_limit_logins", .65, "slow guessing for everyone"), ("force_mfa", .55, "a guessed password alone no longer works")],
    "service_down":        [("restart_service", .75, "the service is down: restart it"), ("failover_replica", .45, "if restarts do not hold, promote the standby")],
    "disk_pressure":       [("cleanup_logs", .70, "rotated logs are the usual cause")],
    "node_silent":         [("check_host", .90, "no data: the host or its path may be down; the SaaS cannot fix that")],
    "collector_offline":   [("check_host", .90, "the collector stopped reporting: check its process and network path")],
}
TABLE["key_abuse"] = [("check_host", .75, "rotate or revoke this signing key (Audit & keys tab), then find where the rejected requests come from")]
HEAD = {"cpu": "cpu_saturation", "mem": "memory_pressure", "latency_ms": "latency_degradation", "packet_loss": "network_loss", "auth": "auth_burst",
        "service": "service_down", "stale": "node_silent", "collector_offline": "collector_offline"}


def pattern_of(signals: list) -> Optional[str]:
    return HEAD.get(primary_metric(signals))


def recommend(inc: dict, graph, node_metrics: dict, baselines: dict, insights: Optional[dict] = None, limit: int = 6, history: Optional[dict] = None) -> list:
    """One list for the incident: for each root / independent cause, the table's actions ranked by confidence x benefit / risk."""
    ex, out = inc["explanation"], []
    members = {m["node"]: m for m in inc["members"]}
    targets = [n for n, m in members.items() if m["role"] in ("root", "independent") and not m["recovered"]]
    for node in targets:
        m = members[node]
        pat = "key_abuse" if node.startswith("sec:") else pattern_of(m["signals"])
        if not pat:
            continue
        metrics = node_metrics.get(node) or {}
        floor = {k: v["mean"] for k, v in (baselines.get(node) or {}).items() if v.get("warm")}
        pm = primary_metric(m["signals"])
        auth = int(next((s["value"] for s in m["signals"] if s.get("metric") == "auth"), 0))
        n_down = sum(1 for c in ex.get("chain", []) if c["role"] == "downstream") if node == ex.get("root") else 0
        for action, prior, why in TABLE[pat]:
            spec = ACTIONS[action]
            conf = round(min(0.99, 0.45 * inc["confidence"] + 0.35 * prior + 0.2 * (m["signals"] and max((min(1.0, abs(s.get("z", 0)) / 6) if s["kind"] == "anomaly" else 0.8) for s in m["signals"]) or 0.5)), 2)
            if node.startswith(("collector:", "sec:")) or spec.get("advisory"):
                pred = None
            else:
                pred = simulate(action, metrics, auth, floor) if metrics else None
            rat = [f"{graph.name(node)}: {why}"]
            h = (history or {}).get((action, node)) or (history or {}).get((action, None))
            if h and h[1] >= 2:                                   # learned from this tenant's own verified outcomes (Laplace-smoothed)
                rate = (h[0] + 1) / (h[1] + 2)
                conf = round(min(0.99, conf * (0.8 + 0.4 * rate)), 2)
                rat.append(f"history: improved {h[0]} of {h[1]} verified runs here")
            if n_down:
                rat.append(f"fixing the root also relieves {n_down} dependent node(s)")
            fc = (insights or {}).get(node, {}).get(pm) if pm else None
            if fc:
                rat.append(f"forecast: {pm} reaches {fc['limit']:.0f} in about {fc['eta_s'] / 60:.0f} min at +{fc['slope_per_min']:.1f}/min")
            out.append({"id": f"{pat}:{action}:{node}", "pattern": pat, "node": node, "label": graph.name(node), "action": action, "title": spec["title"],
                        "risk": spec["risk"], "reversible": spec["reversible"], "advisory": bool(spec.get("advisory")) or node.startswith("sec:"), "confidence": conf, "metric": pm,
                        "rationale": rat, "predicted": pred, "auth": auth,
                        "rank_score": round(conf / RISK_W[spec["risk"]] * (1.0 + (0.25 if pred and pred["state"] in ("EXCELLENT", "GOOD") else 0)), 3)})
    out.sort(key=lambda r: (-r["rank_score"], r["action"]))
    return out[:limit]
