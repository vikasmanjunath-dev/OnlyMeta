"""End-to-end payload tracker. Every payload is stamped at each hop, so latency is MEASURED, not claimed:

  collected (event_time) -> sent (sent_at) -> received -> stored -> evaluated -> published (dashboard stream)

Hops: collect->send (window + outbox wait), network (send->receive), process (receive->published). The collector
and SaaS share a clock in the demo; across machines NTP skew shows up in the network hop (stated, not hidden)."""
import math
from typing import Optional

STAGES = ["collected", "sent", "received", "stored", "evaluated", "published"]
TARGET_P95_S = 10.0


def pct(vals: list, p: float) -> Optional[float]:
    if not vals:
        return None
    v = sorted(vals)
    k = (len(v) - 1) * p / 100
    lo, hi = math.floor(k), math.ceil(k)
    return round(v[lo] + (v[hi] - v[lo]) * (k - lo), 3)


def dist(vals: list) -> dict:
    return {"n": len(vals), "p50": pct(vals, 50), "p95": pct(vals, 95), "p99": pct(vals, 99),
            "max": round(max(vals), 3) if vals else None}


def summary(store, tenant: str, now: float, window_s: float = 600, target_s: float = TARGET_P95_S) -> dict:
    rows = store.q("SELECT event_ts,sent_ts,received_ts,stored_ts,evaluated_ts,published_ts,is_replay,dup_count FROM events "
                   "WHERE tenant_id=? AND received_ts>=?", (tenant, now - window_s))
    rej = store.one("SELECT COUNT(*) n FROM rejects WHERE tenant_id=? AND at>=?", (tenant, now - window_s))["n"]
    total_all = store.one("SELECT COUNT(*) n, COALESCE(SUM(dup_count),0) d FROM events WHERE tenant_id=?", (tenant,))
    live = [r for r in rows if not r["is_replay"]]
    replay = [r for r in rows if r["is_replay"]]

    def hop(rs, a, b):
        return [r[b] - r[a] for r in rs if r[a] is not None and r[b] is not None]
    hops = {"collect_to_send": dist(hop(live, "event_ts", "sent_ts")), "network": dist(hop(live, "sent_ts", "received_ts")),
            "process": dist(hop(live, "received_ts", "published_ts")), "event_to_received": dist(hop(live, "event_ts", "received_ts")),
            "event_to_published": dist(hop(live, "event_ts", "published_ts"))}
    p95 = hops["event_to_published"]["p95"]
    funnel = {"received": len(rows), "stored": sum(r["stored_ts"] is not None for r in rows),
              "evaluated": sum(r["evaluated_ts"] is not None for r in rows), "published": sum(r["published_ts"] is not None for r in rows)}
    return {"window_s": window_s, "funnel": funnel, "stuck": funnel["received"] - funnel["published"],
            "duplicates_absorbed": total_all["d"], "stored_total": total_all["n"], "rejected": rej,
            "live": len(live), "replayed": len(replay), "hops": hops,
            "replayed_event_to_published": dist(hop(replay, "event_ts", "published_ts")),
            "target": {"p95_s": target_s, "measured_p95_s": p95, "met": (p95 is not None and p95 <= target_s)}}


def clock_skew(store, tenant: str, now: float, warn_s: float = 2.0, n: int = 200) -> dict:
    """Estimate collector-vs-SaaS clock offset from the last n live events. recv - sent = network delay + offset and delay >= 0,
    so the MINIMUM over many samples is the tightest bound on the offset (the fastest packet saw the least queueing).
    offset < 0: collector clock is AHEAD. A large positive minimum is ambiguous (clock behind, or a genuinely slow link)."""
    d = [r["d"] for r in store.q("SELECT received_ts - sent_ts d FROM events WHERE tenant_id=? AND is_replay=0 AND sent_ts IS NOT NULL "
                                 "ORDER BY received_ts DESC LIMIT ?", (tenant, n))]
    if len(d) < 5:
        return {"samples": len(d), "estimate_s": None, "warn": False, "note": "need 5+ live events"}
    off = min(d)
    adj = [x - off for x in d] if abs(off) > warn_s else d
    warn = abs(off) > warn_s
    return {"samples": len(d), "estimate_s": round(off, 3), "network_p95_s": pct(d, 95), "network_p95_adjusted_s": pct(adj, 95), "warn": warn,
            "note": (("collector clock is AHEAD by ~%.1f s; fix NTP (latency hops are shifted)" % -off) if warn and off < 0 else
                     ("collector clock is BEHIND by ~%.1f s, or the link is slow; check NTP" % off) if warn else "clocks agree within tolerance")}


def lineage(store, tenant: str, payload_id: str) -> Optional[dict]:
    r = store.one("SELECT payload_id,node,category,severity,is_replay,sha256,dup_count,event_ts,sent_ts,received_ts,stored_ts,"
                  "evaluated_ts,published_ts FROM events WHERE tenant_id=? AND payload_id=?", (tenant, payload_id))
    if not r:
        return None
    ts = {"collected": r["event_ts"], "sent": r["sent_ts"], "received": r["received_ts"], "stored": r["stored_ts"],
          "evaluated": r["evaluated_ts"], "published": r["published_ts"]}
    prev, hops = None, []
    for st in STAGES:
        if ts[st] is not None and prev is not None:
            hops.append({"from": prev[0], "to": st, "ms": round((ts[st] - prev[1]) * 1000, 1)})
        if ts[st] is not None:
            prev = (st, ts[st])
    return {"payload_id": r["payload_id"], "node": r["node"], "category": r["category"], "severity": r["severity"],
            "is_replay": bool(r["is_replay"]), "sha256": r["sha256"], "duplicates_absorbed": r["dup_count"],
            "stages": ts, "hops": hops, "complete": all(v is not None for v in ts.values())}


def recent(store, tenant: str, limit: int = 30) -> list:
    rows = store.q("SELECT payload_id,node,category,severity,is_replay,dup_count,event_ts,received_ts,published_ts FROM events "
                   "WHERE tenant_id=? ORDER BY received_ts DESC LIMIT ?", (tenant, limit))
    for r in rows:
        r["latency_s"] = round(r["published_ts"] - r["event_ts"], 3) if r["published_ts"] else None
    return rows


def reconcile(store, tenant: str, claimed: list) -> dict:
    """claimed = [{payload_id, sha256}] the collector says it delivered. Exact set comparison, no sampling."""
    have = {r["payload_id"]: r["sha256"] for r in store.q("SELECT payload_id,sha256 FROM events WHERE tenant_id=?", (tenant,))}
    ids = [c["payload_id"] for c in claimed]
    missing = [c["payload_id"] for c in claimed if c["payload_id"] not in have]
    mismatch = [c["payload_id"] for c in claimed if c["payload_id"] in have and c.get("sha256") and have[c["payload_id"]] != c["sha256"]]
    dup_claims = len(ids) - len(set(ids))
    return {"claimed": len(ids), "stored": len(have), "missing": missing[:50], "missing_count": len(missing),
            "hash_mismatch": mismatch[:50], "hash_mismatch_count": len(mismatch), "duplicate_claims": dup_claims,
            "duplicates_stored": 0, "ok": not missing and not mismatch}
