"""Load test: N nodes x M collectors send signed batches to the SaaS. Reports throughput, request latency percentiles,
429s, rejects, and then verifies EVERY payload sent is stored exactly once (no loss, no duplicates).

  python3 tools/loadtest.py                         # in-process (no network): measures the app itself
  python3 tools/loadtest.py --nodes 200 --collectors 5 --rounds 20 --batch 50 --async-eval
  python3 tools/loadtest.py --url http://127.0.0.1:8000 --key dev-key-alpha --tenant tenant-alpha   # live server

Live mode respects the per-key rate limit (honours Retry-After); in-process mode lifts the limit to measure raw capacity."""
import argparse
import asyncio
import json
import math
import sys
import tempfile
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import httpx  # noqa: E402

from contracts.signing import sign  # noqa: E402


def pct(v, p):
    if not v:
        return None
    v = sorted(v)
    k = (len(v) - 1) * p / 100
    lo, hi = math.floor(k), math.ceil(k)
    return round(v[lo] + (v[hi] - v[lo]) * (k - lo), 4)


def payload(tenant, region, cid, node, age):
    now = datetime.now(timezone.utc)
    f = lambda d: d.isoformat(timespec="milliseconds").replace("+00:00", "Z")  # noqa: E731
    return {"payload_id": str(uuid.uuid4()), "tenant_id": tenant, "collector_id": cid, "region": region, "collector_version": "0.1.0",
            "config_status": "ok", "event_time": f(now - timedelta(seconds=age)), "source_tz": "Asia/Kolkata", "sent_at": f(now),
            "is_replay": False, "node_pseudonym": node, "event_category": "METRICS", "severity": "info",
            "metrics": {"cpu": 30 + (hash(node) % 40), "mem": 50.0, "disk": 60.0, "bandwidth_mbps": 100.0, "latency_ms": 20.0, "packet_loss": 0.1},
            "auth_failures_60s": 0, "auth_source_pseudonym": None}


async def run(a):
    app = None
    if a.url:
        client = httpx.AsyncClient(base_url=a.url, timeout=30)
        key, tenant, region = a.key, a.tenant, a.region
    else:
        from saas.app import create_app
        from saas.settings import load_settings
        s = load_settings(data_dir=tempfile.mkdtemp(prefix="cicada_load_"))
        s.rate_limit_rps = 1e6
        app = create_app(s, run_background=False)
        app.state.engine.sync_eval = not a.async_eval
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://saas", timeout=60)
        key, tenant, region = "dev-key-alpha", "tenant-alpha", "in"
    sent_ids, lat, codes, rejected, retried = [], [], {}, 0, 0
    sem = asyncio.Semaphore(a.concurrency)
    stop_drain = asyncio.Event()

    async def drainer():
        while not stop_drain.is_set():
            if not app.state.engine.drain(limit=64):
                await asyncio.sleep(0.005)
            else:
                await asyncio.sleep(0)

    async def post(items):
        nonlocal rejected, retried
        body = json.dumps({"batch": items}).encode()
        async with sem:
            for _ in range(8):
                t = time.perf_counter()
                r = await client.post("/ingest", content=body, headers={**sign(key, "POST", "/ingest", body), "Content-Type": "application/json"})
                dt = time.perf_counter() - t
                codes[r.status_code] = codes.get(r.status_code, 0) + 1
                if r.status_code == 429:
                    retried += 1
                    await asyncio.sleep(float(r.headers.get("Retry-After", 1)))
                    continue                                       # a retry needs a fresh signature (nonce): re-sign in the loop
                lat.append(dt)
                if r.status_code == 200:
                    j = r.json()
                    rejected += len(j["rejected"])
                    sent_ids.extend(items_ids(items, j))
                return
    items_ids = lambda items, j: [i["payload_id"] for i in items if i["payload_id"] in set(j["accepted"] + j["duplicates"])]  # noqa: E731

    nodes = [f"n-{i:010d}" for i in range(a.nodes)]
    cols = [f"col-load-{i + 1}" for i in range(a.collectors)]
    tasks = []
    for rd in range(a.rounds):
        for ci, cid in enumerate(cols):
            mine = nodes[ci::len(cols)]
            for k in range(0, len(mine), a.batch):
                tasks.append(post([payload(tenant, region, cid, n, 1.0) for n in mine[k:k + a.batch]]))
    dr = asyncio.create_task(drainer()) if (app and a.async_eval) else None
    t0 = time.perf_counter()
    await asyncio.gather(*tasks)
    wall = time.perf_counter() - t0
    if dr:
        t1 = time.perf_counter()
        while app.state.engine.pending:
            await asyncio.sleep(0.01)
        drain_s = time.perf_counter() - t1
        stop_drain.set()
        await dr
    else:
        drain_s = 0.0
    total = len(sent_ids)
    out = {"mode": "live" if a.url else "in-process" + (" async-eval" if a.async_eval else " sync-eval"),
           "nodes": a.nodes, "collectors": a.collectors, "rounds": a.rounds, "batch": a.batch, "payloads_acked": total,
           "wall_s": round(wall, 2), "payloads_per_s": round(total / wall, 1) if wall else None, "requests": len(lat),
           "request_ms": {"p50": round(pct(lat, 50) * 1000, 1), "p95": round(pct(lat, 95) * 1000, 1), "p99": round(pct(lat, 99) * 1000, 1)} if lat else None,
           "status_codes": codes, "retried_after_429": retried, "rejected": rejected}
    if app:
        out["drain_after_last_ack_s"] = round(drain_s, 2)
        st = app.state.engine.store_of(tenant)
        n = st.one("SELECT COUNT(*) n, COUNT(DISTINCT payload_id) d, SUM(evaluated_ts IS NOT NULL) e FROM events WHERE tenant_id=?", (tenant,))
        out["verify"] = {"stored": n["n"], "distinct": n["d"], "evaluated": n["e"], "acked": total,
                         "ok": n["n"] == n["d"] == total == n["e"] and rejected == 0}
    else:
        ids = await client.get("/api/ids", headers=sign(key, "GET", "/api/ids"))
        have = {x["payload_id"] for x in ids.json()} if ids.status_code == 200 else set()
        out["verify"] = {"acked": total, "found_in_saas": len(set(sent_ids) & have), "ok": set(sent_ids) <= have}
    await client.aclose()
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url")
    ap.add_argument("--key", default="dev-key-alpha")
    ap.add_argument("--tenant", default="tenant-alpha")
    ap.add_argument("--region", default="in")
    ap.add_argument("--nodes", type=int, default=100)
    ap.add_argument("--collectors", type=int, default=4)
    ap.add_argument("--rounds", type=int, default=10)
    ap.add_argument("--batch", type=int, default=25)
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--async-eval", action="store_true")
    r = asyncio.run(run(ap.parse_args()))
    print(json.dumps(r, indent=2))
    sys.exit(0 if r["verify"]["ok"] else 1)
