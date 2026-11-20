"""Measured event -> SaaS-ACK latency from the collector's own egress log (timestamps, not claims).
  python3 tools/latency_report.py --collector-db data/collector_alpha.db [--since-min 10]
latency = ack_at - event_time for SENT payloads. Replayed payloads (is_replay, sent after an outage) are reported
separately: their delay is the outage, not the pipeline. ACK time slightly over-states true arrival, so this is
conservative. Exit code 0 when live p95 <= target (default 10 s, thresholds.yaml targets.dashboard_latency_p95_s)."""
import argparse
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def pct(sorted_vals, p):
    if not sorted_vals:
        return float("nan")
    k = (len(sorted_vals) - 1) * p / 100
    lo, hi = int(k), min(int(k) + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (k - lo)


def collect(db_path, since_min=None):
    c = sqlite3.connect(db_path)
    rows = c.execute("SELECT json, ack_at FROM egress WHERE status='SENT' AND ack_at IS NOT NULL").fetchall()
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=since_min) if since_min else None
    live, replay = [], []
    for js, ack in rows:
        d = json.loads(js)
        ack_t = parse(ack)
        if cutoff and ack_t < cutoff:
            continue
        lat = (ack_t - parse(d["event_time"])).total_seconds()
        (replay if d.get("is_replay") else live).append(lat)
    return sorted(live), sorted(replay)


def summarise(vals, target):
    if not vals:
        return {"n": 0}
    return {"n": len(vals), "p50": round(pct(vals, 50), 2), "p95": round(pct(vals, 95), 2), "p99": round(pct(vals, 99), 2),
            "max": round(vals[-1], 2), "within_target_pct": round(100 * sum(v <= target for v in vals) / len(vals), 1)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--collector-db", required=True)
    ap.add_argument("--since-min", type=float)
    a = ap.parse_args()
    target = yaml.safe_load((ROOT / "contracts/thresholds.yaml").read_text())["targets"]["dashboard_latency_p95_s"]
    live, replay = collect(a.collector_db, a.since_min)
    sl, sr = summarise(live, target), summarise(replay, target)
    print(f"target: p95 <= {target} s (event time -> SaaS ACK)")
    print(f"live     {sl}")
    print(f"replayed {sr}   (delay includes the outage; excluded from the target)")
    ok = bool(live) and sl["p95"] <= target
    print("PASS" if ok else ("NO LIVE DATA" if not live else "FAIL"))
    sys.exit(0 if ok else 1)
