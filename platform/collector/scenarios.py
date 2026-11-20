"""Judge scenarios as raw events (stream format, fake credentials only). Shared by tools/inject.py and the
collector's chaos endpoints so the CLI and the one-click panel exercise exactly the same data."""
import random
from datetime import datetime, timedelta, timezone


def ev(node, ts=None, **kw):
    ts = ts or datetime.now(timezone.utc)
    base = {"ts": ts.strftime("%Y-%m-%dT%H:%M:%SZ"), "tenant": "tenant-alpha", "host": f"{node}.corp.local", "node": node,
            "src_ip": "10.20.1.5", "user": "svc-monitor", "raw_log": f"{node} health check ok",
            "cpu_percent": round(random.gauss(40, 2), 1), "mem_percent": 55.0, "disk_percent": 60.0,
            "bandwidth_mbps": 120.0, "latency_ms": round(random.gauss(30, 2), 1), "packet_loss_pct": 0.1, "auth_failed_count": 0}
    base.update(kw)
    return base


def _ticks(n, make, now, every=5):
    out = []
    for i in range(n):
        out += make(now - timedelta(seconds=every * (n - 1 - i)))
    return out


def build(name: str, n: int = 15, ms: float = 400, pct: float = 95, ticks: int = 3, now=None) -> list:
    now = now or datetime.now(timezone.utc)
    if name == "secret":
        return [ev("app-01", raw_log="deploy password=Hunter2 token=ghp_FAKEFAKEFAKE1234", api_key="sk-proj-9988221100")]
    if name == "bruteforce":
        return [ev("db-01", src_ip="192.168.1.50", user="root", auth_failed_count=1, raw_log="Failed login for root from 192.168.1.50") for _ in range(n)]
    if name == "servicedown":
        return [ev("db-01", raw_log="systemd: postgresql.service failed with result exit-code")]
    if name == "ooo":
        return [ev("app-01", ts=now - timedelta(seconds=60), cpu_percent=41.0)]
    if name == "cpu":
        return _ticks(ticks, lambda t: [ev("db-01", ts=t, cpu_percent=pct)], now)
    if name == "latency":
        return _ticks(ticks, lambda t: [ev("net-01", ts=t, latency_ms=ms, packet_loss_pct=3.0), ev("app-01", ts=t, latency_ms=ms * 0.7)], now)
    if name == "incident":
        return _ticks(ticks, lambda t: [ev("db-01", ts=t, cpu_percent=92, mem_percent=91, latency_ms=120),
                                        ev("app-01", ts=t, latency_ms=280, packet_loss_pct=2.5, cpu_percent=88)], now)
    if name == "prime":                       # calm back-dated history so detectors are warm before a demo (synthetic, replay-flagged)
        return _ticks(max(ticks, 1), lambda t: [ev(n, ts=t) for n in ("app-01", "db-01", "net-01")], now)
    raise KeyError(name)


EVENT_SCENARIOS = ("secret", "bruteforce", "servicedown", "ooo", "cpu", "latency", "incident", "prime")
