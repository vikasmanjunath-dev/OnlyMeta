"""Collector service (Tier 1). Run:  TENANT=tenant-alpha python3 -m collector.main --port 8001
Binds to 127.0.0.1: the raw-data endpoints are LOCAL ONLY (customer-side UI)."""
import argparse
import asyncio
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import uvicorn
from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from collector.adapter import normalise
from collector.config import load_settings
from collector.pipeline import Pipeline
from collector.redact import find_secrets
from collector import scenarios
from collector.remote_config import ConfigPoller
from collector.sender import Sender

UI = Path(__file__).parent / "ui" / "index.html"
# Browsers on these origins may drive the chaos panel (the SaaS tracker page). Chaos routes return NO raw data, and every
# state-changing call needs the custom X-Chaos header, which forces a CORS preflight, so a random web page cannot trigger them.
CHAOS_ORIGINS = {o.strip() for o in os.getenv("CHAOS_ORIGINS", "http://127.0.0.1:8000,http://localhost:8000").split(",") if o.strip()}


def create_app(settings=None) -> FastAPI:
    s = settings or load_settings()
    pipe = Pipeline(s)
    sender = Sender(pipe.outbox, pipe.egress, s)
    poller = ConfigPoller(pipe, sender.client)
    stop = asyncio.Event()

    @asynccontextmanager
    async def lifespan(app):
        tasks = [asyncio.create_task(pipe.run_stream(stop)), asyncio.create_task(pipe.run_flusher(stop)),
                 asyncio.create_task(sender.run(stop)), asyncio.create_task(poller.run(stop))]
        yield
        stop.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        await sender.client.aclose()

    app = FastAPI(title=f"Collector {s.collector_id}", lifespan=lifespan)
    app.state.pipe, app.state.sender, app.state.settings, app.state.poller = pipe, sender, s, poller

    @app.middleware("http")
    async def chaos_guard(request: Request, call_next):
        if not request.url.path.startswith("/api/chaos/"):
            return await call_next(request)
        origin = request.headers.get("origin")
        ok = origin in CHAOS_ORIGINS
        cors = {"Access-Control-Allow-Origin": origin, "Vary": "Origin"} if ok else {}
        if request.method == "OPTIONS":
            if not ok:
                return Response(status_code=403)
            return Response(status_code=204, headers={**cors, "Access-Control-Allow-Methods": "GET, POST",
                                                      "Access-Control-Allow-Headers": "X-Chaos, Content-Type", "Access-Control-Max-Age": "600"})
        if origin and not ok:
            return JSONResponse({"detail": "origin not allowed"}, status_code=403)
        if request.method != "GET" and request.headers.get("x-chaos") != "1":
            return JSONResponse({"detail": "X-Chaos: 1 header required"}, status_code=403)
        resp = await call_next(request)
        resp.headers.update(cors)
        return resp

    @app.get("/", response_class=HTMLResponse)
    def ui():
        return UI.read_text()

    @app.get("/api/status")
    def status():
        src = getattr(pipe, "source", None)
        return {"tenant_id": s.tenant_id, "region": s.region, "collector_id": s.collector_id, "version": s.version,
                "mode": sender.mode, "config_status": s.config_status, "config_version": s.config_version,
                "config_error": poller.last_error, "nodes_down": sorted(pipe.agg.down), "queue_depth": pipe.outbox.depth(), "outbox": pipe.outbox.counts(),
                "outage_remaining_s": round(sender.outage_remaining, 1), "last_error": sender.last_error,
                "events_in": pipe.events_in, "payloads_out": pipe.payloads_out, "blocked": pipe.blocked,
                "sent": sender.sent_total, "duplicates_acked": sender.duplicates_total, "rejected": sender.rejected_total,
                "stream_malformed": sum(getattr(x, "malformed", 0) for x in pipe.sources) or getattr(src, "malformed", 0),
                "dropped": pipe.dropped, "sampled_out": pipe.sampled_out, "near_miss": pipe.near_miss,
                "near_miss_kinds": dict(pipe.near_miss_kinds), "unusable_events": pipe.agg.dropped_incomplete,
                "stable_every": s.stable_every, "outbox_max_rows": s.outbox_max_rows, "sources": list(s.sources), "utc_now": datetime.now(timezone.utc).isoformat()}

    @app.get("/api/egress-log")
    def egress_log(limit: int = 50):
        out = []
        for r in pipe.egress.list(min(limit, 200)):
            raw = pipe.raw.get(r["raw_id"]) if r["raw_id"] else None
            r["outbound"] = json.loads(r.pop("json"))
            r["raw"] = raw                                   # local only
            r["secrets_in_raw"] = find_secrets(json.dumps(raw)) if raw else []
            out.append(r)
        return out

    @app.get("/api/raw-recent")
    def raw_recent(limit: int = 50):
        return pipe.raw.recent(min(limit, 200))

    @app.post("/api/inject")
    def inject(events: list[dict] = Body(...)):
        """Scenario injector entry point (tools/inject.py). Events use the stream's raw format."""
        ids = []
        for line in events:
            try:
                ev = normalise(line)
            except (KeyError, ValueError, TypeError) as e:
                raise HTTPException(422, f"bad event: {e}")
            ids += pipe.process_event(ev)
        return {"emitted": ids}

    @app.get("/api/chaos/status")
    def chaos_status():
        """Everything the panel needs, nothing raw."""
        return {"mode": sender.mode, "queue_depth": pipe.outbox.depth(), "outage_remaining_s": round(sender.outage_remaining, 1),
                "sent": sender.sent_total, "duplicates_acked": sender.duplicates_total, "rejected": sender.rejected_total,
                "blocked": pipe.blocked, "dropped": pipe.dropped, "near_miss": pipe.near_miss, "sampled_out": pipe.sampled_out,
                "last_error": sender.last_error}

    @app.post("/api/chaos/scenario/{name}")
    async def scenario(name: str, n: int = 15, seconds: float = 30, kind: str = "tamper", ticks: int = 3):
        """One-click scenarios for the demo; each returns what the system did, so the panel can show proof."""
        if name == "drift":                                    # live: the running calm feed itself drifts, so the samples arrive in order, one per window
            live = next((x for x in pipe.sources if hasattr(x, "inject")), None)
            if live:
                live.inject("db-01", min(max(ticks, 1), 60), scenarios.DRIFT)
                return {"scenario": name, "mode": "live", "ticks": min(max(ticks, 1), 60), "payloads_emitted": min(max(ticks, 1), 60), "node": "db-01", "evidence": []}
        if name in scenarios.EVENT_SCENARIOS:
            before_nm, before_bl = pipe.near_miss, pipe.blocked
            ids = []
            for raw in scenarios.build(name, n=min(max(n, 1), 200), ticks=min(max(ticks, 1), 60)):
                ids += pipe.process_event(normalise(raw))
            ids += pipe.flush_all()
            keep, ev = set(ids[:5]), []
            for r in pipe.egress.list(50):                    # what crossed the boundary for these payloads; never the raw side
                if r["payload_id"] in keep:
                    ev.append({"payload_id": r["payload_id"], "status": r["status"], "sha256": r["sha256"], "matched_pattern": r["matched_pattern"],
                               "secrets_in_outbound": len(find_secrets(r["json"])), "outbound": json.loads(r["json"])})
            return {"scenario": name, "payloads_emitted": len(ids), "secrets_seen_locally": pipe.near_miss - before_nm,
                    "blocked_at_boundary": pipe.blocked - before_bl, "evidence": ev}
        if name == "outage":
            sender.start_outage(min(max(seconds, 1), 120))
            return {"scenario": name, "outage_s": seconds}
        if name == "clear":
            sender.clear_outage()
            return {"scenario": name}
        if name == "dup":
            return {"scenario": name, "duplicates_reported_by_saas": await sender.resend_last(min(max(n, 1), 50) if n != 15 else 3)}
        if name == "corrupt":
            return {"scenario": name, "kind": kind, "saas_response": await sender.send_corrupt(kind)}
        raise HTTPException(404, f"unknown scenario {name!r}")

    @app.get("/api/chaos/ledger")
    def ledger(limit: int = 2000):
        """What this collector says it delivered: ids and hashes only (no raw, no payload bodies). The SaaS reconciles it exactly."""
        return [{"payload_id": r["payload_id"], "sha256": r["sha256"]} for r in pipe.egress.list(min(max(limit, 1), 5000), status="SENT")]

    @app.post("/api/chaos/outage")
    def outage(seconds: float = 30):
        sender.start_outage(seconds)
        return {"outage_s": seconds}

    @app.post("/api/chaos/clear")
    def clear():
        sender.clear_outage()
        return {"ok": True}

    @app.post("/api/chaos/dup")
    async def dup(n: int = 3):
        return {"duplicates_reported_by_saas": await sender.resend_last(n)}

    return app


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8001)
    ap.add_argument("--host", default="127.0.0.1", help="keep 127.0.0.1: raw-data endpoints are local only (containers: 0.0.0.0 + a loopback-only port map)")
    a = ap.parse_args()
    uvicorn.run(create_app(), host=a.host, port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
