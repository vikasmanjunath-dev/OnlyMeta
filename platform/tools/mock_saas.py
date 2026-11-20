"""Minimal stand-in for P2's SaaS so the collector can be developed and demoed alone. NOT the real SaaS.
Implements the /ingest contract: X-Collector-Key -> tenant, schema validation (extra=forbid), tenant/region check,
dedup on PRIMARY KEY (tenant_id, payload_id), response {accepted, duplicates, rejected}.
Run:  python3 tools/mock_saas.py --port 8000      (Ctrl+C = a real SaaS outage)"""
import argparse
import json
import sqlite3
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import uvicorn  # noqa: E402
import yaml  # noqa: E402
from fastapi import FastAPI, Header, HTTPException, Request  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from contracts.hashing import canonical_hash  # noqa: E402
from contracts.signing import key_id, verify  # noqa: E402
from contracts.schema import Payload  # noqa: E402


def create_app(db_path=":memory:") -> FastAPI:
    tenants = yaml.safe_load((ROOT / "contracts/tenants.yaml").read_text())["tenants"]
    import os
    keys = {os.getenv(t["key_env"], f"dev-key-{tid.split('-')[-1]}"): (tid, t["region"]) for tid, t in tenants.items()}
    by_id = {key_id(k): (k, *v) for k, v in keys.items()}

    def authed(request, body: bytes):
        """Accept a signed request (preferred) or the legacy X-Collector-Key header (old tools)."""
        kid = request.headers.get("x-key-id")
        if kid:
            if kid not in by_id:
                raise HTTPException(401, "bad key")
            secret, tenant, region = by_id[kid]
            path = request.url.path + (("?" + request.url.query) if request.url.query else "")
            if not verify(secret, request.method, path, body, request.headers.get("x-timestamp", ""), request.headers.get("x-nonce", ""),
                          request.headers.get("x-signature", "")):
                raise HTTPException(401, "bad signature")
            return tenant, region
        k = request.headers.get("x-collector-key", "")
        if k not in keys:
            raise HTTPException(401, "bad key")
        return keys[k]
    db = sqlite3.connect(db_path, check_same_thread=False)
    db.execute("CREATE TABLE IF NOT EXISTS events(tenant_id TEXT, payload_id TEXT, event_time TEXT, is_replay INT, "
               "sha256 TEXT, payload_json TEXT, PRIMARY KEY(tenant_id, payload_id))")
    lock = threading.Lock()
    app = FastAPI(title="mock SaaS")

    @app.post("/ingest")
    async def ingest(request: Request):
        raw = await request.body()
        tenant, region = authed(request, raw)
        batch = json.loads(raw).get("batch", [])
        acc, dup, rej = [], [], []
        for item in batch:
            pid = item.get("payload_id", "?")
            try:
                p = Payload(**item)
                if p.tenant_id != tenant:
                    raise ValueError("tenant_mismatch")
                if p.region != region:
                    raise ValueError("region_mismatch")
            except (ValidationError, ValueError) as e:
                rej.append({"id": pid, "reason": str(e)[:120]})
                continue
            with lock:
                cur = db.execute("INSERT OR IGNORE INTO events VALUES(?,?,?,?,?,?)",
                                 (tenant, pid, item["event_time"], int(p.is_replay), canonical_hash(item), json.dumps(item)))
                db.commit()
            (acc if cur.rowcount else dup).append(pid)
        return {"accepted": acc, "duplicates": dup, "rejected": rej}

    remote = {}   # tenant_id -> config document (dev stand-in for P2's per-tenant collector config)

    @app.get("/collector/config")
    async def collector_config(request: Request):
        tenant, _ = authed(request, b"")
        doc = remote.get(tenant)
        if doc is None:
            raise HTTPException(404, "no config")
        return doc

    @app.post("/admin/config")
    async def set_config(request: Request, tenant_id: str):
        remote[tenant_id] = await request.json()
        return remote[tenant_id]

    @app.get("/api/ids")
    def ids(tenant_id: str):
        with lock:
            rows = db.execute("SELECT payload_id, sha256 FROM events WHERE tenant_id=?", (tenant_id,)).fetchall()
        return [{"payload_id": a, "sha256": b} for a, b in rows]

    app.state.db = db
    return app


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--db", default=str(ROOT / "data/mock_saas.db"))
    a = ap.parse_args()
    uvicorn.run(create_app(a.db), host="127.0.0.1", port=a.port, log_level="warning")
