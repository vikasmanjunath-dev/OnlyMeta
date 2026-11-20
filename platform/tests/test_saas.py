"""P2 SaaS tests: auth, residency, dedup, health + stale rule, isolation, tracker, config, and a real
collector -> real SaaS run. Sync TestClient; time is passed explicitly where a rule depends on it."""
import json
import sqlite3
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from contracts.signing import sign  # noqa: E402
from saas.app import create_app  # noqa: E402
from saas.health import classify, next_state  # noqa: E402
from saas.settings import load_settings  # noqa: E402

class Col:
    """A collector holding an API key: every request is HMAC-signed, the key itself is never sent."""

    def __init__(self, secret):
        self.secret = secret

    def req(self, c, method, path, obj=None, raw=None):
        body = raw if raw is not None else (json.dumps(obj).encode() if obj is not None else b"")
        return c.request(method, path, content=body, headers={**sign(self.secret, method, path, body), "Content-Type": "application/json"})

    def get(self, c, path):
        return self.req(c, "GET", path)

    def post(self, c, path, obj=None, raw=None):
        return self.req(c, "POST", path, obj, raw)


A, B = Col("dev-key-alpha"), Col("dev-key-beta")
M = dict(cpu=40.0, mem=55.0, disk=60.0, bandwidth_mbps=100.0, latency_ms=20.0, packet_loss=0.1)


def utc(dt):
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def pl(tenant="tenant-alpha", region="in", node="n-aaaaaaaaaa", age=2.0, cat="METRICS", sev="info", auth=0, replay=False, **m):
    now = datetime.now(timezone.utc)
    return {"payload_id": str(uuid.uuid4()), "tenant_id": tenant, "collector_id": "col-alpha-01", "region": region,
            "collector_version": "0.1.0", "config_status": "ok", "event_time": utc(now - timedelta(seconds=age)),
            "source_tz": "Asia/Kolkata", "sent_at": utc(now - timedelta(seconds=age / 4)), "is_replay": replay,
            "node_pseudonym": node, "event_category": cat, "severity": sev, "metrics": {**M, **m},
            "auth_failures_60s": auth, "auth_source_pseudonym": None}


@pytest.fixture
def env(tmp_path):
    s = load_settings(data_dir=tmp_path)
    app = create_app(s, run_background=False)
    c = TestClient(app)

    def login(user, pw):
        r = c.post("/api/login", json={"username": user, "password": pw})
        return {"Authorization": "Bearer " + r.json()["token"]} if r.status_code == 200 else None
    app.state.login = login
    return c, app, login("alpha-admin", "alpha-demo-pass"), login("beta-admin", "beta-demo-pass"), tmp_path


def send(c, col, *items):
    return col.post(c, "/ingest", {"batch": list(items)})


# ---------------- auth ----------------
def test_ingest_requires_valid_key(env):
    c, *_ = env
    assert c.post("/ingest", json={"batch": []}).status_code == 401
    assert Col("nope").post(c, "/ingest", {"batch": []}).status_code == 401
    assert send(c, A).json() == {"accepted": [], "duplicates": [], "rejected": []}


def test_login_bad_password_and_throttle(env):
    c, app, *_ = env
    assert c.post("/api/login", json={"username": "alpha-admin", "password": "x"}).status_code == 401
    for _ in range(5):
        c.post("/api/login", json={"username": "alpha-admin", "password": "x"})
    assert c.post("/api/login", json={"username": "alpha-admin", "password": "alpha-demo-pass"}).status_code == 429


def test_dashboard_routes_need_login(env):
    c, *_ = env
    for p in ("/api/fleet", "/api/tracker", "/api/state-history", "/api/topology", "/api/tracker/recent"):
        assert c.get(p).status_code == 401


# ---------------- residency, tenant binding, schema ----------------
def test_wrong_region_and_tenant_rejected_never_stored(env):
    c, app, ha, hb, tmp = env
    r = send(c, A, pl(region="eu"), pl(tenant="tenant-beta", region="in")).json()
    assert r["accepted"] == [] and {x["reason"].split(" ")[0] for x in r["rejected"]} == {"region_mismatch", "tenant_mismatch"}
    assert A.get(c, "/api/ids").json() == []


def test_regional_files_hold_only_their_tenants_rows(env):
    c, app, ha, hb, tmp = env
    send(c, A, pl())
    send(c, B, pl(tenant="tenant-beta", region="eu"))
    rows = {r: sqlite3.connect(tmp / f"saas_{r}.db").execute("SELECT DISTINCT tenant_id FROM events").fetchall() for r in ("in", "eu")}
    assert rows == {"in": [("tenant-alpha",)], "eu": [("tenant-beta",)]}


def test_schema_extra_field_rejected_without_echoing_value(env):
    c, *_ = env
    bad = pl()
    bad["raw_log"] = "password=Hunter2"
    r = send(c, A, bad).json()
    assert r["accepted"] == [] and "raw_log" in r["rejected"][0]["reason"] and "Hunter2" not in json.dumps(r)


def test_future_event_time_and_limits(env):
    c, app, *_ = env
    assert send(c, A, pl(age=-3600)).json()["rejected"][0]["reason"] == "event_time_in_future"
    assert A.post(c, "/ingest", {"batch": [pl() for _ in range(501)]}).status_code == 413
    assert A.post(c, "/ingest", raw=b"not json").status_code == 400
    assert A.post(c, "/ingest", {"nope": 1}).status_code == 400


# ---------------- dedup / idempotency ----------------
def test_duplicate_is_acked_stored_once(env):
    c, app, ha, *_ = env
    p = pl()
    assert send(c, A, p).json()["accepted"] == [p["payload_id"]]
    r = send(c, A, p, p).json()
    assert r["accepted"] == [] and r["duplicates"] == [p["payload_id"]] * 2
    assert len(A.get(c, "/api/ids").json()) == 1
    assert c.get("/api/tracker", headers=ha).json()["duplicates_absorbed"] == 2


# ---------------- health ----------------
@pytest.mark.parametrize("kw,state", [
    (dict(), "EXCELLENT"), (dict(cpu=75), "GOOD"), (dict(cpu=90), "FAIR"), (dict(mem=95), "FAIR"), (dict(latency_ms=300), "FAIR"),
    (dict(packet_loss=1.5), "GOOD"), (dict(packet_loss=5), "FAIR"), (dict(packet_loss=11), "POOR"), (dict(auth=4), "GOOD"),
    (dict(auth=5), "FAIR"), (dict(auth=10), "POOR"), (dict(cat="SERVICE_DOWN"), "POOR")])
def test_classify_thresholds(kw, state):
    kw = dict(kw)
    auth, cat = kw.pop("auth", 0), kw.pop("cat", "METRICS")
    assert classify({**M, **kw}, auth, cat, 0)[0] == state


def test_cpu_over_95_is_fair_once_poor_after_three():
    assert classify({**M, "cpu": 97}, 0, "METRICS", 1)[0] == "FAIR"
    assert classify({**M, "cpu": 97}, 0, "METRICS", 3)[0] == "POOR"


def test_hysteresis_downgrade_now_upgrade_after_three_clean():
    assert next_state("EXCELLENT", "POOR", ["POOR"]) == "POOR"
    assert next_state("POOR", "EXCELLENT", ["EXCELLENT"]) == "POOR"
    assert next_state("POOR", "GOOD", ["POOR", "EXCELLENT", "GOOD"]) == "POOR"
    assert next_state("POOR", "GOOD", ["EXCELLENT", "GOOD", "EXCELLENT"]) == "GOOD"     # worst of the clean run


def test_fleet_state_end_to_end_and_history(env):
    c, app, ha, *_ = env
    send(c, A, pl(age=3))
    send(c, A, pl(age=2, packet_loss=12.0))
    fl = c.get("/api/fleet", headers=ha).json()
    assert fl["overall"] == "POOR" and fl["nodes"][0]["state"] == "POOR" and "packet loss" in fl["nodes"][0]["reasons"][0]
    h = c.get("/api/state-history", headers=ha).json()
    assert [(x["old"], x["new"]) for x in h][::-1] == [(None, "EXCELLENT"), ("EXCELLENT", "POOR")]
    for _ in range(2):
        send(c, A, pl(age=1))
    assert c.get("/api/fleet", headers=ha).json()["nodes"][0]["state"] == "POOR"            # only 2 clean so far
    assert "recovering" in c.get("/api/fleet", headers=ha).json()["nodes"][0]["reasons"][0]
    send(c, A, pl(age=0.5))
    assert c.get("/api/fleet", headers=ha).json()["nodes"][0]["state"] == "EXCELLENT"


def test_out_of_order_replay_does_not_move_current_state(env):
    c, app, ha, *_ = env
    send(c, A, pl(age=1))
    send(c, A, pl(age=120, packet_loss=15.0, replay=True))                                  # old bad sample arrives late
    assert c.get("/api/fleet", headers=ha).json()["nodes"][0]["state"] == "EXCELLENT"
    assert len(c.get("/api/nodes/n-aaaaaaaaaa/history", headers=ha).json()) == 2             # ...but is kept in history


# ---------------- stale-data rule ----------------
def test_silence_30s_is_poor_within_35s_and_recovers(env):
    c, app, ha, *_ = env
    eng = app.state.engine
    send(c, A, pl(age=60))                                                                  # last sample before the outage
    t0 = time.time()
    assert eng.check_stale(t0 + 25) == []                                                   # not yet
    made = eng.check_stale(t0 + 31)                                                         # 30 s rule + <= 5 s loop = 35 s
    assert ("tenant-alpha", "col-alpha-01", "offline") in made
    fl = c.get("/api/fleet", headers=ha).json()
    assert fl["overall"] == "POOR" and fl["collector"]["offline"] and "collector offline" in fl["nodes"][0]["reasons"][0]
    assert eng.check_stale(t0 + 40) == []                                                   # no repeat alerts
    for i in range(4):                                                                      # outage over: buffered + live data
        send(c, A, pl(age=4 - i))
    fl = c.get("/api/fleet", headers=ha).json()
    assert not fl["collector"]["offline"] and fl["nodes"][0]["state"] == "EXCELLENT" and not fl["nodes"][0]["stale"]


def test_one_silent_node_goes_poor_while_collector_alive(env):
    c, app, ha, *_ = env
    eng = app.state.engine
    send(c, A, pl(node="n-bbbbbbbbbb"), pl(node="n-cccccccccc"))
    t0 = time.time()
    time.sleep(0.01)
    send(c, A, pl(node="n-cccccccccc", age=0.1))
    # simulate b silent for 31 s while c keeps reporting: advance c's last_seen to t0+30
    store = eng.store_of("tenant-alpha")
    store.conn.execute("UPDATE node_state SET last_seen_ts=? WHERE node='n-cccccccccc'", (t0 + 30,))
    store.conn.execute("UPDATE fleet_collectors SET last_seen_ts=?", (t0 + 30,))
    eng.check_stale(t0 + 31)
    st = {n["node"]: n["state"] for n in c.get("/api/fleet", headers=ha).json()["nodes"]}
    assert st["n-bbbbbbbbbb"] == "POOR" and st["n-cccccccccc"] == "EXCELLENT"


# ---------------- isolation ----------------
def test_beta_cannot_see_alpha_anywhere(env):
    c, app, ha, hb, tmp = env
    pa = pl()
    send(c, A, pa)
    send(c, B, pl(tenant="tenant-beta", region="eu", node="n-bbbbbbbbbb"))
    fb = c.get("/api/fleet", headers=hb).json()
    assert fb["tenant_id"] == "tenant-beta" and [n["node"] for n in fb["nodes"]] == ["n-bbbbbbbbbb"]
    assert c.get(f"/api/tracker/payload/{pa['payload_id']}", headers=hb).status_code == 404
    assert c.get("/api/nodes/n-aaaaaaaaaa/history", headers=hb).json() == []
    assert c.get("/api/state-history", headers=hb).json()[0]["node"] == "n-bbbbbbbbbb"
    assert pa["payload_id"] not in json.dumps(c.get("/api/tracker/recent", headers=hb).json())
    assert pa["payload_id"] not in json.dumps(B.get(c, "/api/ids").json())
    r = c.post("/api/tracker/reconcile", headers=hb, json={"sent": [{"payload_id": pa["payload_id"]}]}).json()
    assert r["missing_count"] == 1                                                         # alpha's id does not exist for beta
    assert c.get("/api/tracker", headers=hb).json()["stored_total"] == 1
    assert c.get("/api/topology", headers=hb).json() and all(v["label"] in ("web-01", "db-02") for v in c.get("/api/topology", headers=hb).json().values())


# ---------------- tracker ----------------
def test_lineage_has_six_stages_and_hops(env):
    c, app, ha, *_ = env
    p = pl(age=3)
    send(c, A, p)
    l = c.get(f"/api/tracker/payload/{p['payload_id']}", headers=ha).json()
    assert l["complete"] and list(l["stages"]) == ["collected", "sent", "received", "stored", "evaluated", "published"]
    assert [h["to"] for h in l["hops"]] == ["sent", "received", "stored", "evaluated", "published"]
    assert all(h["ms"] >= 0 for h in l["hops"][1:])
    assert l["hops"][0]["ms"] == pytest.approx(2250, abs=400)                              # event 3 s ago, sent 0.75 s ago


def test_tracker_summary_measures_latency_and_target(env):
    c, app, ha, *_ = env
    for _ in range(20):
        send(c, A, pl(age=3.0))
    send(c, A, pl(age=300.0, replay=True))
    s = c.get("/api/tracker", headers=ha).json()
    assert s["funnel"] == {"received": 21, "stored": 21, "evaluated": 21, "published": 21} and s["stuck"] == 0
    assert s["live"] == 20 and s["replayed"] == 1
    assert 2.9 < s["hops"]["event_to_published"]["p95"] < 4.0 and s["target"]["met"]
    assert 299 < s["replayed_event_to_published"]["p50"] < 302                              # outage delay kept out of the live p95
    slow = pl(age=40.0)
    send(c, A, slow)
    send(c, A, *[pl(age=40.0) for _ in range(5)])
    assert not c.get("/api/tracker", headers=ha).json()["target"]["met"]


def test_reconcile_detects_missing_and_tamper(env):
    c, app, ha, *_ = env
    ps = [pl() for _ in range(3)]
    send(c, A, *ps)
    sent = A.get(c, "/api/ids").json()
    assert c.post("/api/tracker/reconcile", headers=ha, json={"sent": sent}).json()["ok"]
    bad = sent + [{"payload_id": str(uuid.uuid4()), "sha256": "0" * 64}]
    bad[0] = {**bad[0], "sha256": "f" * 64}
    r = c.post("/api/tracker/reconcile", headers=ha, json={"sent": bad}).json()
    assert not r["ok"] and r["missing_count"] == 1 and r["hash_mismatch_count"] == 1


def test_tracker_page_served(env):
    c, *_ = env
    assert "End-to-end tracker" in c.get("/tracker").text


# ---------------- config ----------------
def test_config_admin_put_collector_get(env):
    c, app, ha, *_ = env
    assert A.get(c, "/collector/config").status_code == 404
    assert c.put("/api/config", headers=ha, json={"burst_threshold": 8, "fair_logins": 4}).json()["config_version"] == 1
    assert c.put("/api/config", headers=ha, json={"burst_threshold": 9}).json()["config_version"] == 2
    got = A.get(c, "/collector/config").json()
    assert got == {"burst_threshold": 9, "config_version": 2}
    assert B.get(c, "/collector/config").status_code == 404                        # beta has its own (none)
    assert c.put("/api/config", headers=ha, json={"burst_threshold": 99999}).status_code == 422
    assert c.put("/api/config", json={"burst_threshold": 8}).status_code == 401


# ---------------- live stream bus ----------------
def test_bus_receives_sample_and_state_events(env):
    c, app, *_ = env
    q = app.state.bus.subscribe("tenant-alpha")
    qb = app.state.bus.subscribe("tenant-beta")
    send(c, A, pl(packet_loss=12.0))
    kinds = []
    while not q.empty():
        kinds.append(q.get_nowait()["type"])
    assert [k for k in kinds if k != "incident"] == ["state", "alert", "sample"] and "incident" in kinds and qb.empty()                                      # beta's stream sees nothing


def test_topology_in_pseudonyms_no_hostnames(env):
    c, app, ha, *_ = env
    t = c.get("/api/topology", headers=ha).json()
    assert len(t) == 3 and all(k.startswith("n-") for k in t)
    app_node = next(k for k, v in t.items() if v["label"] == "app-01")
    assert [t[d]["label"] for d in t[app_node]["depends_on"]] == ["db-01"]


# ---------------- real collector -> real SaaS ----------------
def test_real_collector_to_real_saas_end_to_end(env, tmp_path):
    import asyncio
    import httpx
    from collector.adapter import normalise
    from collector.config import load_settings as col_settings
    from collector.pipeline import Pipeline
    from collector.sender import Sender
    c, app, ha, *_ = env
    cs = col_settings(db_path=str(tmp_path / "col.db"), rebase=False, loop=False, saas_url="http://saas/ingest")
    pipe = Pipeline(cs)
    now = datetime.now(timezone.utc) - timedelta(seconds=40)
    for i in range(12):
        for node in ("app-01", "db-01"):
            pipe.process_event(normalise({"ts": (now + timedelta(seconds=i * 3)).strftime("%Y-%m-%dT%H:%M:%SZ"), "node": node,
                                          "src_ip": "10.0.0.9", "raw_log": "password=Summer@2026 ok", "cpu_percent": 40,
                                          "mem_percent": 50, "disk_percent": 60, "bandwidth_mbps": 90, "latency_ms": 20,
                                          "packet_loss_pct": 0.1, "auth_failed_count": 0}))
    pipe.flush_all()

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://saas") as cli:
            snd = Sender(pipe.outbox, pipe.egress, cs, cli)
            for _ in range(20):
                await snd.send_once()
                if not pipe.outbox.depth():
                    break
            return snd
    snd = asyncio.run(run())
    sent = [{"payload_id": r["payload_id"], "sha256": r["sha256"]} for r in pipe.egress.list(500, status="SENT")]
    assert sent and pipe.outbox.depth() == 0
    rec = c.post("/api/tracker/reconcile", headers=ha, json={"sent": sent}).json()
    assert rec["ok"] and rec["missing_count"] == 0 and rec["claimed"] == len(sent)
    assert "Summer@2026" not in json.dumps(app.state.engine.store_of("tenant-alpha").q("SELECT payload_json FROM events"))
    s = c.get("/api/tracker", headers=ha).json()
    assert s["stored_total"] == len(sent) and s["stuck"] == 0 and s["rejected"] == 0
