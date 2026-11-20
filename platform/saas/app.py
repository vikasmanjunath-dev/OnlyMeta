"""P2 SaaS (Tier 2): signed ingest, per-region stores, health, alerts, live stream, end-to-end tracker, audit.

Callers
  collectors  HMAC-signed requests (key id + signature; the key never travels). Replay-, skew- and rate-protected.
  people      username/password -> persistent session token (hash stored, revocable). viewer = read, admin = change.
Every read is scoped to the caller's tenant; no route takes a tenant id from the request.

Concurrency model: ingest, evaluation and reads run on the event loop (SQLite WAL, ms-scale). /ingest only STORES
before it ACKs; evaluation is drained by a background task, and recover() re-queues anything stored-but-unevaluated
after a crash, so an acknowledged payload is never lost."""
import asyncio
import hmac
import json
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, StreamingResponse

from collector.remote_config import validate
from contracts.schema import SUPPORTED_SCHEMA_VERSIONS
from saas import tracker
from saas.aiops import AIOps
from saas.aiops.maintenance import MaintenanceError
from saas.aiops.report import postmortem
from saas.aiops.remediate import ACTIONS, RemediationError, catalogue, simulate
from saas.audit import AuditLog
from saas.auth import AuthError, CollectorAuth, KeyService, UserService
from saas.bus import Bus
from saas.engine import Engine
from saas.health import RANK, STATES
from saas.settings import Settings, load_settings, regions
from saas.store import Stores, jl
from saas.topology import topology

UI = Path(__file__).parent / "ui"


def create_app(settings: Optional[Settings] = None, run_background: bool = True) -> FastAPI:
    s = settings or load_settings()
    stores, bus = Stores(s.data_dir, regions(s)), Bus()
    eng = Engine(s, stores, bus, sync_eval=not run_background)
    audit = AuditLog(eng.store_of)
    eng.audit = audit
    ai = AIOps(eng, s, bus, audit, threaded=run_background)
    users, keys = UserService(s, stores), KeyService(s, stores)
    cauth = CollectorAuth(s, keys)
    users.seed()
    started = time.time()

    @asynccontextmanager
    async def lifespan(app):
        stop = asyncio.Event()
        eng.recover()

        async def stale_loop():
            last_purge = 0.0
            while not stop.is_set():
                try:
                    eng.check_stale()
                    if time.time() - last_purge > 600:
                        eng.purge()
                        last_purge = time.time()
                except Exception as e:                                         # a failing sweep must not kill the loop
                    print("stale_loop error:", type(e).__name__)
                try:
                    await asyncio.wait_for(stop.wait(), timeout=s.stale_loop_s)
                except asyncio.TimeoutError:
                    pass

        async def drain_loop():
            while not stop.is_set():
                try:
                    n = eng.drain(limit=64)
                except Exception as e:
                    print("drain_loop error:", type(e).__name__)
                    n = 0
                if n:
                    await asyncio.sleep(0)                                     # yield to request handlers between chunks
                else:
                    try:
                        await asyncio.wait_for(stop.wait(), timeout=0.05)
                    except asyncio.TimeoutError:
                        pass
        tasks = [asyncio.create_task(stale_loop()), asyncio.create_task(drain_loop())] if run_background else []
        yield
        stop.set()
        for t in tasks:
            await t
        eng.drain()                                                            # finish what was acknowledged

    app = FastAPI(title="CICADA SaaS (Tier 2)", lifespan=lifespan)
    app.state.engine, app.state.settings, app.state.bus, app.state.stores = eng, s, bus, stores
    app.state.audit, app.state.users, app.state.keys, app.state.cauth = audit, users, keys, cauth
    app.state.aiops = ai
    if s.cors_origins:                                                         # browser dashboards on another origin
        app.add_middleware(CORSMiddleware, allow_origins=list(s.cors_origins), allow_methods=["GET", "POST", "PUT", "DELETE"],
                           allow_headers=["Authorization", "Content-Type"], max_age=600)

    @app.exception_handler(AuthError)
    async def _auth_error(request: Request, e: AuthError):
        h = {"Retry-After": str(max(1, int(e.retry_after + 0.999)))} if e.retry_after else {}
        return JSONResponse({"detail": e.message}, status_code=e.status, headers=h)

    def ip_of(request: Request) -> str:
        return request.client.host if request.client else ""

    # ------------------------------------------------------------------ people
    def user(request: Request, authorization: str = Header(default=""), token: str = Query(default="")) -> dict:
        tok = authorization.removeprefix("Bearer ").strip() or token            # ?token= only so EventSource can connect
        u = users.session(tok) if tok else None
        if not u:
            raise HTTPException(401, "login required")
        u["token"] = tok
        return u

    def admin(u: dict = Depends(user)) -> dict:
        if u["role"] != "admin":
            raise HTTPException(403, "admin only")
        return u

    @app.post("/api/login")
    async def login(request: Request, body: dict):
        name, pw = str(body.get("username", ""))[:80], str(body.get("password", ""))[:200]
        try:
            tok, u = users.login(name, pw, s.token_ttl_s)
        except AuthError as e:
            found = users.find(name)
            tenant = found["tenant_id"] if found else None
            if tenant:                                                          # only known accounts are logged (no spam by guessing names)
                audit.record_throttled(tenant, name, "login_failed", {"status": e.status}, ip_of(request))
            raise
        audit.record(u["tenant_id"], name, "login", {"role": u["role"]}, ip_of(request))
        return {"token": tok, "tenant_id": u["tenant_id"], "region": s.tenants[u["tenant_id"]]["region"], "role": u["role"], "username": name}

    @app.post("/api/logout")
    def logout(u: dict = Depends(user)):
        users.logout(u["token"])
        return {"ok": True}

    @app.get("/api/me")
    def me(u: dict = Depends(user)):
        return {"username": u["user"], "tenant_id": u["tenant"], "role": u["role"], "region": s.tenants[u["tenant"]]["region"]}

    @app.post("/api/password")
    def change_password(request: Request, body: dict, u: dict = Depends(user)):
        users.change_password(u["user"], str(body.get("old", "")), str(body.get("new", "")))
        audit.record(u["tenant"], u["user"], "password_changed", {}, ip_of(request))
        return {"ok": True, "note": "all sessions revoked; log in again"}

    @app.get("/api/users")
    def list_users(u: dict = Depends(admin)):
        return users.list(u["tenant"])

    @app.post("/api/users")
    def create_user(request: Request, body: dict, u: dict = Depends(admin)):
        name = str(body.get("username", ""))
        users.create(u["tenant"], name, str(body.get("password", "")), str(body.get("role", "viewer")))
        audit.record(u["tenant"], u["user"], "user_created", {"username": name, "role": body.get("role", "viewer")}, ip_of(request))
        return {"ok": True}

    @app.delete("/api/users/{username}")
    def disable_user(request: Request, username: str, u: dict = Depends(admin)):
        users.disable(u["tenant"], username)
        audit.record(u["tenant"], u["user"], "user_disabled", {"username": username}, ip_of(request))
        return {"ok": True}

    # ------------------------------------------------------------------ collector-facing (signed)
    async def collector(request: Request) -> tuple:
        body = await request.body()
        path = request.url.path + (("?" + request.url.query) if request.url.query else "")
        try:
            tenant, kid = cauth.authenticate(request.method, path, body, {k.lower(): v for k, v in request.headers.items()})
        except AuthError as e:
            if e.status == 401:
                audit_unknown(request, e)
            raise
        return tenant, kid, body

    def audit_unknown(request: Request, e: AuthError):
        kid = request.headers.get("x-key-id", "")
        found = keys.resolve(kid) if kid else None
        if found:                                                               # a real key failing: a security event for that tenant
            audit.record_throttled(found[0], f"key:{kid}", "collector_auth_failed", {"reason": e.message[:80], "path": request.url.path}, ip_of(request))
            ai.security_event(found[0], kid, e.message, time.time())

    @app.post("/ingest")
    async def ingest(request: Request):
        tenant, kid, body = await collector(request)
        if len(body) > s.max_body_bytes:
            raise HTTPException(413, "body too large")
        try:
            batch = json.loads(body).get("batch")
        except (ValueError, AttributeError):
            raise HTTPException(400, "expected {\"batch\": [...]}")
        if not isinstance(batch, list):
            raise HTTPException(400, "expected {\"batch\": [...]}")
        if len(batch) > s.max_batch:
            raise HTTPException(413, f"batch larger than {s.max_batch}")
        return eng.ingest(tenant, batch)

    @app.get("/collector/config")
    async def collector_config(request: Request):
        tenant, _, _ = await collector(request)
        row = eng.store_of(tenant).one("SELECT version, doc FROM config WHERE tenant_id=?", (tenant,))
        if not row:
            raise HTTPException(404, "no config")
        return {**jl(row["doc"]), "config_version": row["version"]}

    @app.get("/api/ids")
    async def ids(request: Request, authorization: str = Header(default="")):
        """Delivery reconciliation: a signing collector or a signed-in user lists ITS OWN tenant's stored ids + hashes."""
        if request.headers.get("x-key-id") or request.headers.get("x-collector-key"):
            tenant, _, _ = await collector(request)
        else:
            tenant = user(request, authorization, "")["tenant"]
        return [{"payload_id": r["payload_id"], "sha256": r["sha256"]}
                for r in eng.store_of(tenant).q("SELECT payload_id, sha256 FROM events WHERE tenant_id=?", (tenant,))]

    # ------------------------------------------------------------------ dashboard-facing (tenant from session only)
    @app.get("/api/fleet")
    def fleet(u: dict = Depends(user)):
        return eng.fleet(u["tenant"])

    @app.get("/api/collectors")
    def collectors(u: dict = Depends(user)):
        return eng.collectors(u["tenant"])

    @app.get("/api/nodes/{node}/history")
    def node_history(node: str, minutes: float = 15, limit: int = 600, u: dict = Depends(user)):
        return eng.history(u["tenant"], node, min(minutes, 120) * 60, min(limit, 2000))

    @app.get("/api/state-history")
    def state_history(limit: int = 100, u: dict = Depends(user)):
        return eng.state_history(u["tenant"], min(limit, 500))

    @app.get("/api/topology")
    def topo(u: dict = Depends(user)):
        return topology(u["tenant"])

    @app.get("/api/stream")
    async def stream(request: Request, u: dict = Depends(user)):
        q = bus.subscribe(u["tenant"])

        async def gen():
            try:
                yield f"event: hello\ndata: {json.dumps(eng.fleet(u['tenant']))}\n\n"
                while not await request.is_disconnected():
                    if users.session(u["token"]) is None:                       # logged out / revoked mid-stream
                        yield "event: bye\ndata: {}\n\n"
                        return
                    try:
                        m = await asyncio.wait_for(q.get(), timeout=15)
                        yield f"event: {m['type']}\ndata: {json.dumps(m['data'])}\n\n"
                    except asyncio.TimeoutError:
                        yield ": keep-alive\n\n"
            finally:
                bus.unsubscribe(u["tenant"], q)
        return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    @app.put("/api/config")
    async def put_config(request: Request, body: dict, u: dict = Depends(admin)):
        try:
            doc = validate(body)
        except ValueError as e:
            raise HTTPException(422, str(e))
        store = eng.store_of(u["tenant"])
        with store.tx() as c:
            ver = (c.execute("SELECT COALESCE(MAX(version),0) v FROM config WHERE tenant_id=?", (u["tenant"],)).fetchone()["v"]) + 1
            c.execute("INSERT OR REPLACE INTO config(tenant_id,version,doc) VALUES(?,?,?)", (u["tenant"], ver, json.dumps(doc)))
        audit.record(u["tenant"], u["user"], "config_changed", {"version": ver, "doc": doc}, ip_of(request))
        return {**doc, "config_version": ver}


    # ------------------------------------------------------------------ P3 AIOps: anomalies, incidents, remediation
    @app.exception_handler(RemediationError)
    async def _rem_error(request: Request, e: RemediationError):
        return JSONResponse({"detail": e.message}, status_code=e.status)

    @app.exception_handler(MaintenanceError)
    async def _mw_error(request: Request, e: MaintenanceError):
        return JSONResponse({"detail": e.message}, status_code=e.status)

    @app.get("/api/aiops/summary")
    def aiops_summary(window_s: float = 3600, u: dict = Depends(user)):
        return ai.summary(u["tenant"], time.time(), min(window_s, 86400))

    @app.get("/api/aiops/anomalies")
    def aiops_anomalies(state: Optional[str] = None, limit: int = 100, u: dict = Depends(user)):
        return ai.anomalies(u["tenant"], state, min(limit, 500))

    @app.get("/api/aiops/baselines/{node}")
    def aiops_baselines(node: str, u: dict = Depends(user)):
        if not eng.store_of(u["tenant"]).one("SELECT 1 x FROM node_state WHERE tenant_id=? AND node=?", (u["tenant"], node)):
            raise HTTPException(404, "unknown node")
        return ai.baselines(u["tenant"], node)

    @app.get("/api/incidents")
    def incidents(status: Optional[str] = None, limit: int = 50, u: dict = Depends(user)):
        return ai.inc.list(u["tenant"], status, min(limit, 200))

    @app.get("/api/incidents/{iid}")
    def incident(iid: int, u: dict = Depends(user)):
        v = ai.inc.get(u["tenant"], iid)
        if not v:
            raise HTTPException(404, "unknown incident")
        v["recommendations"] = ai.recommendations(u["tenant"], iid) if v["status"] == "open" else []
        v["remediations"] = ai.rem.list(u["tenant"], incident_id=iid)
        return v

    @app.get("/api/webhooks")
    def webhooks_list(u: dict = Depends(admin)):
        return {"hooks": ai.webhooks.listing(u["tenant"]), "problems": ai.webhooks.problems if u["tenant"] in ai.webhooks.hooks or ai.webhooks.problems else [],
                "log": ai.webhooks.log(u["tenant"], 30)}

    @app.post("/api/webhooks/{name}/test")
    def webhooks_test(name: str, request: Request, u: dict = Depends(admin)):
        n = ai.webhooks.emit(u["tenant"], "test", {"incident": {"ref": "INC-0", "title": "test delivery", "severity": "low", "kind": "test", "status": "open", "confidence": 1.0,
                                                          "root": "none", "summary": "connectivity test from the CICADA platform", "detected_ts": time.time(), "resolved_ts": None}}, only=name)
        if not n:
            raise HTTPException(404, "no such webhook for this tenant")
        audit.record(u["tenant"], u["user"], "webhook_test", {"hook": name}, ip_of(request))
        return {"queued": n}

    @app.get("/api/maintenance")
    def maintenance_list(u: dict = Depends(user)):
        return ai.maint.list(u["tenant"], time.time())

    @app.post("/api/maintenance")
    async def maintenance_add(request: Request, u: dict = Depends(admin)):
        b = await request.json()
        g, now = ai.graph(u["tenant"]), time.time()
        node = (b.get("node") or "").strip() or None
        pseud = None
        if node:
            pseud = next((p for p, lab in g.label.items() if lab == node or p == node), None)
            if not pseud:
                raise HTTPException(422, "unknown node (use its label, e.g. db-01, or leave empty for the whole tenant)")
        try:
            mins, delay = float(b.get("minutes", 30)), float(b.get("start_in_minutes", 0))
        except (TypeError, ValueError):
            raise HTTPException(422, "minutes must be a number")
        delay = max(delay, -60.0)                                                  # work already under way may be backdated, at most an hour
        return ai.maint.add(u["tenant"], pseud, g.label.get(pseud, "all nodes") if pseud else "all nodes", now + delay * 60, now + (delay + mins) * 60,
                            str(b.get("reason", "")), u["user"], now, ip_of(request))

    @app.delete("/api/maintenance/{wid}")
    def maintenance_cancel(wid: int, request: Request, u: dict = Depends(admin)):
        if not ai.maint.cancel(u["tenant"], wid, u["user"], time.time(), ip_of(request)):
            raise HTTPException(404, "no active window with that id")
        return {"ok": True}

    @app.get("/api/incidents/{iid}/report")
    def incident_report(iid: int, u: dict = Depends(user)):
        v = ai.inc.get(u["tenant"], iid)
        if not v:
            raise HTTPException(404, "unknown incident")
        v["remediations"] = ai.rem.list(u["tenant"], incident_id=iid)
        return PlainTextResponse(postmortem(v), media_type="text/markdown")

    @app.put("/api/incidents/{iid}/ack")
    def incident_ack(iid: int, request: Request, u: dict = Depends(admin)):
        if not ai.inc.ack(u["tenant"], iid, u["user"], time.time()):
            raise HTTPException(404, "unknown incident")
        audit.record(u["tenant"], u["user"], "incident_acked", {"incident": iid}, ip_of(request))
        return {"ok": True}

    @app.get("/api/remediation/catalogue")
    def rem_catalogue(u: dict = Depends(user)):
        return catalogue()

    @app.get("/api/remediation/config")
    def rem_config(u: dict = Depends(user)):
        return ai.rem.config(u["tenant"])

    @app.put("/api/remediation/config")
    def rem_config_put(request: Request, body: dict, u: dict = Depends(admin)):
        return ai.rem.put_config(u["tenant"], body, u["user"], time.time(), ip_of(request))

    @app.get("/api/remediation")
    def rem_list(status: Optional[str] = None, incident_id: Optional[int] = None, limit: int = 100, u: dict = Depends(user)):
        return ai.rem.list(u["tenant"], status, incident_id, min(limit, 300))

    @app.post("/api/remediation/policy/simulate")
    async def remediation_what_if(request: Request, u: dict = Depends(user)):
        b = await request.json()
        return ai.rem.what_if(u["tenant"], b.get("policy") or {}, time.time(), min(float(b.get("window_s", 86400)), 7 * 86400))

    @app.post("/api/remediation/simulate")
    def rem_simulate(body: dict, u: dict = Depends(user)):
        node, action = str(body.get("node", "")), str(body.get("action", ""))
        ns = eng.store_of(u["tenant"]).one("SELECT metrics FROM node_state WHERE tenant_id=? AND node=?", (u["tenant"], node))
        if not ns or action not in ACTIONS:
            raise HTTPException(404, "unknown node or action")
        floor = {k: v["mean"] for k, v in ai.baselines(u["tenant"], node).items() if v["warm"]}
        return simulate(action, json.loads(ns["metrics"]), int(body.get("auth", 0)), floor)

    @app.post("/api/remediation/propose")
    def rem_propose(request: Request, body: dict, u: dict = Depends(admin)):
        node, action, iid = str(body.get("node", "")), str(body.get("action", "")), body.get("incident_id")
        kw = {"confidence": 0.5, "pattern": "manual", "rationale": ["proposed by " + u["user"]], "metric": None, "auth": 0}
        if iid:
            rec = next((r for r in (ai.recommendations(u["tenant"], int(iid)) or []) if r["node"] == node and r["action"] == action), None)
            if rec:
                kw.update(confidence=rec["confidence"], pattern=rec["pattern"], rationale=rec["rationale"], metric=rec["metric"], auth=rec["auth"])
        return ai.rem.propose(u["tenant"], node, action, time.time(), params=body.get("params") if isinstance(body.get("params"), dict) else None,
                              incident_id=int(iid) if iid else None, proposer=u["user"], ip=ip_of(request), **kw)

    @app.get("/api/remediation/{rid}")
    def rem_get(rid: int, u: dict = Depends(user)):
        r = ai.rem.get(u["tenant"], rid)
        if not r:
            raise HTTPException(404, "unknown remediation")
        return r

    @app.post("/api/remediation/{rid}/approve")
    def rem_approve(rid: int, request: Request, body: Optional[dict] = None, u: dict = Depends(admin)):
        return ai.rem.approve(u["tenant"], rid, u["user"], time.time(), str((body or {}).get("note", "")), ip_of(request))

    @app.post("/api/remediation/{rid}/reject")
    def rem_reject(rid: int, request: Request, body: Optional[dict] = None, u: dict = Depends(admin)):
        return ai.rem.reject(u["tenant"], rid, u["user"], time.time(), str((body or {}).get("note", "")), ip_of(request))

    @app.post("/api/remediation/{rid}/cancel")
    def rem_cancel(rid: int, request: Request, u: dict = Depends(admin)):
        return ai.rem.cancel(u["tenant"], rid, u["user"], time.time(), ip_of(request))

    @app.post("/api/remediation/{rid}/rollback")
    def rem_rollback(rid: int, request: Request, body: Optional[dict] = None, u: dict = Depends(admin)):
        return ai.rem.rollback(u["tenant"], rid, u["user"], time.time(), str((body or {}).get("reason", "manual rollback")), ip_of(request))

    # ------------------------------------------------------------------ alerts
    @app.get("/api/alerts")
    def alerts(state: Optional[str] = None, limit: int = 100, u: dict = Depends(user)):
        return eng.alerts.list(eng.store_of(u["tenant"]), u["tenant"], state, min(limit, 500))

    @app.get("/api/alerts/summary")
    def alerts_summary(window_s: float = 3600, u: dict = Depends(user)):
        return eng.alerts.summary(eng.store_of(u["tenant"]), u["tenant"], time.time(), min(window_s, 86400 * 7))

    @app.put("/api/alerts/{alert_id}/ack")
    def ack_alert(request: Request, alert_id: int, u: dict = Depends(admin)):
        if not eng.alerts.ack(eng.store_of(u["tenant"]), u["tenant"], alert_id, u["user"], time.time()):
            raise HTTPException(404, "no such alert for this tenant")
        audit.record(u["tenant"], u["user"], "alert_ack", {"alert_id": alert_id}, ip_of(request))
        return {"ok": True}

    # ------------------------------------------------------------------ keys + audit (admin)
    @app.get("/api/keys")
    def list_keys(u: dict = Depends(admin)):
        return keys.list(u["tenant"])

    @app.post("/api/keys/rotate")
    def rotate_key(request: Request, u: dict = Depends(admin)):
        r = keys.rotate(u["tenant"], s.key_grace_s)
        audit.record(u["tenant"], u["user"], "key_rotated", {"new_key_id": r["key_id"], "grace_s": r["grace_s"]}, ip_of(request))
        return {**r, "note": "store this key now; it is shown once. Old keys stop working at old_keys_valid_until."}

    @app.delete("/api/keys/{key_id}")
    def revoke_key(request: Request, key_id: str, u: dict = Depends(admin)):
        keys.revoke(u["tenant"], key_id)
        audit.record(u["tenant"], u["user"], "key_revoked", {"key_id": key_id}, ip_of(request))
        return {"ok": True}

    @app.get("/api/audit")
    def audit_rows(limit: int = 100, u: dict = Depends(admin)):
        return audit.rows(u["tenant"], min(limit, 1000))

    @app.get("/api/audit/verify")
    def audit_verify(u: dict = Depends(admin)):
        return audit.verify(u["tenant"])

    # ------------------------------------------------------------------ end-to-end tracker
    @app.get("/api/tracker")
    def tracker_summary(window_s: float = 600, u: dict = Depends(user)):
        store, now = eng.store_of(u["tenant"]), time.time()
        out = tracker.summary(store, u["tenant"], now, min(window_s, 86400), s.th["targets"]["dashboard_latency_p95_s"])
        out["counters"] = dict(eng.counters)
        out["queue_depth"] = len(eng.pending)
        out["clock"] = tracker.clock_skew(store, u["tenant"], now, s.skew_warn_s)
        f = eng.fleet(u["tenant"])
        out["collector"], out["collectors"] = f["collector"], f["collectors"]
        return out

    @app.get("/api/tracker/recent")
    def tracker_recent(limit: int = 30, u: dict = Depends(user)):
        return tracker.recent(eng.store_of(u["tenant"]), u["tenant"], min(limit, 200))

    @app.get("/api/tracker/payload/{payload_id}")
    def tracker_payload(payload_id: str, u: dict = Depends(user)):
        r = tracker.lineage(eng.store_of(u["tenant"]), u["tenant"], payload_id)
        if not r:
            raise HTTPException(404, "unknown payload for this tenant")      # same answer for 'other tenant's' (no oracle)
        return r

    @app.post("/api/tracker/reconcile")
    async def tracker_reconcile(body: dict, u: dict = Depends(user)):
        claimed = body.get("sent")
        if not isinstance(claimed, list) or len(claimed) > 100_000 or not all(isinstance(c, dict) and "payload_id" in c for c in claimed):
            raise HTTPException(400, "expected {\"sent\": [{payload_id, sha256}]}")
        return tracker.reconcile(eng.store_of(u["tenant"]), u["tenant"], claimed)

    @app.get("/tracker", response_class=HTMLResponse)
    def tracker_page():
        return (UI / "tracker.html").read_text()

    # ------------------------------------------------------------------ ops
    @app.get("/healthz")
    def healthz():
        return {"ok": True, "regions": sorted(stores.by_region), "schema_versions": list(SUPPORTED_SCHEMA_VERSIONS)}

    @app.get("/metrics", response_class=PlainTextResponse)
    def metrics(request: Request, authorization: str = Header(default="")):
        """Prometheus text. METRICS_TOKEN -> everything (operator). An admin session -> only its own tenant's gauges."""
        tok = authorization.removeprefix("Bearer ").strip()
        operator = bool(s.metrics_token) and hmac.compare_digest(tok.encode(), s.metrics_token.encode())
        tenants = list(s.tenants)
        if not operator:
            u = users.session(tok) if tok else None
            if not u or u["role"] != "admin":
                raise HTTPException(401, "metrics need METRICS_TOKEN or an admin session")
            tenants = [u["tenant"]]
        L = []

        def g(name, help_, typ, rows):
            L.append(f"# HELP {name} {help_}\n# TYPE {name} {typ}")
            L.extend(f"{name}{{{','.join(f'{k}=\"{v}\"' for k, v in lab.items())}}} {val}" if lab else f"{name} {val}" for lab, val in rows)
        if operator:
            g("cicada_uptime_seconds", "process uptime", "gauge", [({}, round(time.time() - started, 1))])
            g("cicada_ingest_total", "payload outcomes", "counter", [({"outcome": k}, v) for k, v in eng.counters.items()])
            g("cicada_auth_total", "collector auth outcomes", "counter", [({"outcome": k}, v) for k, v in cauth.stats.items()])
            g("cicada_eval_queue_depth", "stored, not yet evaluated", "gauge", [({}, len(eng.pending))])
        nodes, offl, opens, evts = [], [], [], []
        for t in tenants:
            st = eng.store_of(t)
            by = {r["state"]: r["n"] for r in st.q("SELECT state, COUNT(*) n FROM node_state WHERE tenant_id=? GROUP BY state", (t,))}
            nodes += [({"tenant": t, "state": x}, by.get(x, 0)) for x in STATES]
            offl.append(({"tenant": t}, st.one("SELECT COUNT(*) n FROM fleet_collectors WHERE tenant_id=? AND offline=1", (t,))["n"]))
            opens.append(({"tenant": t}, st.one("SELECT COUNT(*) n FROM alerts WHERE tenant_id=? AND state='open'", (t,))["n"]))
            evts.append(({"tenant": t}, st.one("SELECT COUNT(*) n FROM events WHERE tenant_id=?", (t,))["n"]))
        g("cicada_nodes", "nodes by health state", "gauge", nodes)
        g("cicada_collectors_offline", "collectors with no data past the stale rule", "gauge", offl)
        g("cicada_alerts_open", "open alerts", "gauge", opens)
        g("cicada_events_stored", "events currently retained", "gauge", evts)
        inc_o, an_o, rem_s = [], [], []
        for t in tenants:
            st = eng.store_of(t)
            inc_o.append(({"tenant": t}, st.one("SELECT COUNT(*) n FROM incidents WHERE tenant_id=? AND status='open'", (t,))["n"]))
            an_o.append(({"tenant": t}, st.one("SELECT COUNT(*) n FROM anomalies WHERE tenant_id=? AND state='open'", (t,))["n"]))
            rem_s += [({"tenant": t, "status": r["status"]}, r["n"]) for r in st.q("SELECT status, COUNT(*) n FROM remediations WHERE tenant_id=? GROUP BY status", (t,))]
        g("cicada_incidents_open", "open incidents", "gauge", inc_o)
        g("cicada_anomalies_open", "open anomalies", "gauge", an_o)
        g("cicada_remediations", "remediation proposals by status", "gauge", rem_s)
        return "\n".join(L) + "\n"

    return app
