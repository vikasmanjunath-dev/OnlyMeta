"""Scenario injector: one command per judge scenario. Targets a running collector (default :8001).
  python3 tools/inject.py secret | outage --seconds 30 | bruteforce --n 15 | latency --ms 400 |
                          cpu --pct 95 | incident | dup --n 3 | ooo | servicedown | config --burst 8 --saas http://127.0.0.1:8000
python3 tools/inject.py fault --node db-01 | clear | leak   (calm source: sustained fault, clear it, fake-secret proof)
Events are in the stream's raw format with timestamps = now (fake credentials only)."""
import argparse
import json
import random
import time
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from collector.scenarios import ev  # noqa: E402,F401  (one definition of the demo events)


def post(base, path, body=None):
    data = json.dumps(body).encode() if body is not None else b""
    req = urllib.request.Request(base + path, data=data, method="POST", headers={"Content-Type": "application/json", "X-Chaos": "1"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def ticks(base, n, make, every=5):
    for i in range(n):
        post(base, "/api/inject", make(i))
        if i < n - 1:
            time.sleep(every)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scenario", choices="secret outage bruteforce latency cpu incident dup ooo servicedown config drift fault clear leak".split())
    ap.add_argument("--base", default="http://127.0.0.1:8001")
    ap.add_argument("--seconds", type=float, default=30)
    ap.add_argument("--n", type=int, default=15)
    ap.add_argument("--ms", type=float, default=400)
    ap.add_argument("--pct", type=float, default=95)
    ap.add_argument("--ticks", type=int, default=3)
    ap.add_argument("--burst", type=int, default=8)
    ap.add_argument("--node", default="db-01")
    ap.add_argument("--heal", type=int, default=0, help="fault: self-heal after N ticks (0 = until cleared or acted on)")
    ap.add_argument("--saas", default="http://127.0.0.1:8000")
    ap.add_argument("--tenant", default="tenant-alpha")
    a = ap.parse_args()
    b = a.base
    if a.scenario == "secret":
        print(post(b, "/api/inject", [ev("app-01", raw_log="deploy password=Hunter2 token=ghp_FAKEFAKEFAKE1234",
                                         api_key="sk-proj-9988221100")]))
    elif a.scenario == "fault":                                       # needs SOURCES=calm; sustained CPU saturation on --node
        print(post(b, f"/api/chaos/scenario/fault?node={a.node}&heal={a.heal}"))
    elif a.scenario == "clear":
        print(post(b, "/api/chaos/scenario/clearfault"))
    elif a.scenario == "leak":                                        # fake secrets through the real pipeline; prints what left the boundary
        r = post(b, "/api/chaos/scenario/secret")
        print({k: r.get(k) for k in ("payloads_emitted", "secrets_seen_locally", "blocked_at_boundary")}, "secrets in outbound:", sum(e.get("secrets_in_outbound", 0) for e in r.get("evidence", [])))
    elif a.scenario == "outage":
        print(post(b, f"/api/chaos/outage?seconds={a.seconds}"))
    elif a.scenario == "bruteforce":
        print(post(b, "/api/inject", [ev("db-01", src_ip="192.168.1.50", user="root", auth_failed_count=1,
                                         raw_log="Failed login for root from 192.168.1.50") for _ in range(a.n)]))
    elif a.scenario == "latency":
        ticks(b, a.ticks, lambda i: [ev("net-01", latency_ms=a.ms, packet_loss_pct=3.0), ev("app-01", latency_ms=a.ms * 0.7)])
    elif a.scenario == "cpu":
        ticks(b, a.ticks, lambda i: [ev("db-01", cpu_percent=a.pct)])
    elif a.scenario == "incident":
        ticks(b, a.ticks, lambda i: [ev("db-01", cpu_percent=92, mem_percent=91, latency_ms=120),
                                     ev("app-01", latency_ms=280, packet_loss_pct=2.5, cpu_percent=88)])
    elif a.scenario == "drift":
        ticks(b, a.ticks, lambda i: [ev("db-01", cpu_percent=42.0, mem_percent=62.2, latency_ms=43.0, packet_loss_pct=0.62, bandwidth_mbps=146.0)])
    elif a.scenario == "dup":
        print(post(b, f"/api/chaos/dup?n={a.n if a.n != 15 else 3}"))
    elif a.scenario == "servicedown":
        print(post(b, "/api/inject", [ev("db-01", raw_log="systemd: postgresql.service failed with result exit-code")]))
    elif a.scenario == "config":
        v = int(time.time())
        print(post(a.saas, f"/admin/config?tenant_id={a.tenant}",
                   {"config_version": v, "burst_threshold": a.burst, "fair_logins": 4, "node_silent_s": 20}))
    elif a.scenario == "ooo":
        late = datetime.now(timezone.utc) - timedelta(seconds=60)
        print(post(b, "/api/inject", [ev("app-01", ts=late, cpu_percent=41.0)]))


if __name__ == "__main__":
    main()
