"""Generate contracts/sample_stream.jsonl: 60 raw events (20 ticks x 3 nodes, 5 s apart).

Stand-in for the organizer stream until its spec arrives; only collector/adapter.py may know the real
format. Deterministic (seeded). Contains fake secrets, a failed-login burst, a latency spike on net-01
and a cascading CPU/latency incident on db-01 -> app-01, so every Phase 1/2 scenario has data.
All credentials below are FAKE.
"""
import json
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

random.seed(2026)
START = datetime(2026, 11, 20, 10, 0, 0, tzinfo=timezone.utc)
TENANT = "tenant-alpha"
NODES = {  # logical node -> (fqdn, base cpu, base latency ms)
    "app-01": ("prod-app-01.corp.local", 38, 40),
    "db-01": ("prod-db-01.corp.local", 45, 12),
    "net-01": ("edge-sw-01.corp.local", 20, 8),
}


def line(tick, node):
    fqdn, cpu0, lat0 = NODES[node]
    ts = START + timedelta(seconds=5 * tick)
    cpu = random.gauss(cpu0, 2.0)
    lat = random.gauss(lat0, 1.5)
    loss = max(0.0, random.gauss(0.1, 0.05))
    ev = {
        "ts": ts.strftime("%Y-%m-%dT%H:%M:%SZ"), "tenant": TENANT, "host": fqdn, "node": node,
        "src_ip": "10.20.%d.%d" % (random.randint(0, 3), random.randint(2, 250)),
        "user": "svc-monitor", "raw_log": f"{node} health check ok",
        "mem_percent": round(random.gauss(55, 1.5), 1), "disk_percent": round(random.gauss(60, 0.5), 1),
        "bandwidth_mbps": round(random.gauss(120, 8), 1), "auth_failed_count": 0,
    }
    # fake secrets in a raw log (scenario: raw log contains a secret)
    if node == "app-01" and tick == 6:
        ev["raw_log"] = "deploy hook called with password=Summer@2026 and token=ghp_FAKEFAKEFAKE1234"
        ev["api_key"] = "sk-proj-9988221100aa"
    if node == "app-01" and tick == 7:
        ev["raw_log"] = "Authorization: Bearer FAKEFAKE.TOKEN.VALUE12345 rejected"
    # failed-login burst on db-01 (ticks 9-13): 3 per sample = 15 in 25 s
    if node == "db-01" and 9 <= tick <= 13:
        ev["auth_failed_count"] = 3
        ev["user"] = "root"
        ev["src_ip"] = "192.168.1.50"
        ev["raw_log"] = "Failed login for root from 192.168.1.50"
    # latency spike on net-01 (ticks 14-16)
    if node == "net-01" and 14 <= tick <= 16:
        lat = random.gauss(310, 8)
        loss = random.gauss(3.0, 0.3)
    # cascading incident: db-01 CPU then app-01 latency (ticks 15-18)
    if node == "db-01" and 15 <= tick <= 18:
        cpu = random.gauss(92, 2)
        lat = random.gauss(120, 6)
    if node == "app-01" and 16 <= tick <= 19:
        lat = random.gauss(280, 10)
        cpu = random.gauss(66, 3)
    ev.update(cpu_percent=round(cpu, 1), latency_ms=round(lat, 1), packet_loss_pct=round(loss, 2))
    return ev


def main(out):
    rows = [line(t, n) for t in range(20) for n in NODES]
    assert len(rows) == 60
    Path(out).write_text("".join(json.dumps(r) + "\n" for r in rows))
    print(f"wrote {len(rows)} events to {out}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "contracts/sample_stream.jsonl")
