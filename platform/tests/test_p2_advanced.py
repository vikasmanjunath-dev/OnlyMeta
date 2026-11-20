"""P2 advancements: request signing, key rotation, sessions + roles, audit chain, alert-noise reduction, conflicts,
multi-collector, async evaluation queue + crash recovery, retention, clock skew, metrics."""
import json
import sqlite3
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from contracts.signing import key_id, sign  # noqa: E402
from saas.app import create_app  # noqa: E402
from saas.settings import load_settings  # noqa: E402
from test_saas import A, B, Col, M, pl, send, utc  # noqa: E402


def mk(tmp_path, **over):
    s = load_settings(data_dir=tmp_path)
    for k, v in over.items():
        setattr(s, k, v)
    app = create_app(s, run_background=False)
    c = TestClient(app)

    def login(u, p):
        r = c.post("/api/login", json={"username": u, "password": p})
        return {"Authorization": "Bearer " + r.json()["token"]} if r.status_code == 200 else None
    return c, app, login


@pytest.fixture
def env(tmp_path):
    c, app, login = mk(tmp_path)
    return c, app, login("alpha-admin", "alpha-demo-pass"), login


def raw_post(c, secret, body: bytes, path="/ingest", **sk):
    return c.post(path, content=body, headers={**sign(secret, "POST", path, body, **sk), "Content-Type": "application/json"})


BATCH = json.dumps({"batch": []}).encode()


# ---------------------------------------------------------------- signing
def test_signed_request_ok_and_key_never_sent(env):
    c, *_ = env
    h = sign("dev-key-alpha", "POST", "/ingest", BATCH)
    assert "dev-key-alpha" not in json.dumps(h) and set(h) == {"X-Key-Id", "X-Timestamp", "X-Nonce", "X-Signature"}
    assert raw_post(c, "dev-key-alpha", BATCH).status_code == 200


def test_tampered_body_wrong_path_wrong_method_rejected(env):
    c, *_ = env
    h = sign("dev-key-alpha", "POST", "/ingest", BATCH)
    assert c.post("/ingest", content=BATCH + b" ", headers=h).status_code == 401           # body changed after signing
    h = sign("dev-key-alpha", "POST", "/other", BATCH)
    assert c.post("/ingest", content=BATCH, headers=h).status_code == 401                  # signature bound to the path
    h = sign("dev-key-alpha", "GET", "/ingest", BATCH)
    assert c.post("/ingest", content=BATCH, headers=h).status_code == 401                  # ...and the method


def test_replay_of_captured_request_rejected(env):
    c, *_ = env
    h = sign("dev-key-alpha", "POST", "/ingest", BATCH)
    assert c.post("/ingest", content=BATCH, headers=h).status_code == 200
    r = c.post("/ingest", content=BATCH, headers=h)
    assert r.status_code == 401 and "replay" in r.json()["detail"]


def test_clock_skew_window(env):
    c, *_ = env
    now = int(time.time())
    for off in (-400, 400):
        r = raw_post(c, "dev-key-alpha", BATCH, ts=now + off)
        assert r.status_code == 401 and "NTP" in r.json()["detail"]
    assert raw_post(c, "dev-key-alpha", BATCH, ts=now + 200).status_code == 200              # inside the window, signed after start-up


def test_unknown_key_and_bad_signature_are_indistinguishable(env):
    c, *_ = env
    a = raw_post(c, "no-such-key", BATCH)
    h = sign("dev-key-alpha", "POST", "/ingest", BATCH)
    h["X-Signature"] = "0" * 64
    b = c.post("/ingest", content=BATCH, headers=h)
    assert (a.status_code, a.json()) == (b.status_code, b.json()) == (401, {"detail": "invalid credentials"})


def test_cross_tenant_signature_cannot_write_other_tenant(env):
    c, *_ = env
    r = send(c, A, pl(tenant="tenant-beta", region="eu")).json()                            # alpha's key, beta's payload
    assert r["accepted"] == [] and r["rejected"][0]["reason"] == "tenant_mismatch"


def test_legacy_plain_key_refused_by_default_allowed_when_enabled(tmp_path):
    c, app, _ = mk(tmp_path)
    assert c.post("/ingest", headers={"X-Collector-Key": "dev-key-alpha"}, json={"batch": []}).status_code == 401
    c2, _, _ = mk(tmp_path / "x", allow_legacy_key=True)
    assert c2.post("/ingest", headers={"X-Collector-Key": "dev-key-alpha"}, json={"batch": []}).status_code == 200


def test_rate_limit_429_with_retry_after(tmp_path):
    c, app, _ = mk(tmp_path, rate_limit_rps=2)
    codes = [A.post(c, "/ingest", {"batch": []}) for _ in range(8)]
    limited = [r for r in codes if r.status_code == 429]
    assert limited and int(limited[0].headers["Retry-After"]) >= 1
    assert codes[0].status_code == 200 and app.state.cauth.stats["rate_limited"] == len(limited)


def test_auth_failure_for_real_key_is_audited_and_throttled(env):
    c, app, ha, _ = env
    for _ in range(5):
        h = sign("dev-key-alpha", "POST", "/ingest", BATCH)
        h["X-Signature"] = "f" * 64
        c.post("/ingest", content=BATCH, headers=h)
    rows = [r for r in c.get("/api/audit", headers=ha).json() if r["action"] == "collector_auth_failed"]
    assert len(rows) == 1                                                                   # five failures, one row (60 s window)


# ---------------------------------------------------------------- key rotation
def test_rotate_grace_then_old_key_stops(env):
    c, app, ha, _ = env
    r = c.post("/api/keys/rotate", headers=ha).json()
    new = Col(r["key"])
    assert r["key"].startswith("ck_") and r["grace_s"] == 600
    assert send(c, new).status_code == 200 and send(c, A).status_code == 200               # both valid during grace
    keys = c.get("/api/keys", headers=ha).json()
    assert {k["status"] for k in keys} == {"active", "retiring"} and r["key"] not in json.dumps(keys)
    st = app.state.engine.store_of("tenant-alpha")
    st.conn.execute("UPDATE key_retirements SET expires_ts=?", (time.time() - 1,))
    assert send(c, A).status_code == 401 and send(c, new).status_code == 200               # old key ended, new continues


def test_revoke_is_immediate_and_last_key_protected(env):
    c, app, ha, _ = env
    only = c.get("/api/keys", headers=ha).json()[0]["key_id"]
    assert c.delete(f"/api/keys/{only}", headers=ha).status_code == 409                    # would lock everyone out
    new = Col(c.post("/api/keys/rotate", headers=ha).json()["key"])
    assert c.delete(f"/api/keys/{only}", headers=ha).status_code == 200
    assert send(c, A).status_code == 401 and send(c, new).status_code == 200
    assert c.delete("/api/keys/nope", headers=ha).status_code in (404, 409)


def test_keys_are_tenant_scoped(env):
    c, app, ha, login = env
    hb = login("beta-admin", "beta-demo-pass")
    kid_a = key_id("dev-key-alpha")
    assert c.delete(f"/api/keys/{kid_a}", headers=hb).status_code in (404, 409)
    assert send(c, A).status_code == 200
    assert kid_a not in json.dumps(c.get("/api/keys", headers=hb).json())


def test_rotated_secret_stored_only_for_hmac_and_chmod_600(env, tmp_path):
    c, app, ha, _ = env
    c.post("/api/keys/rotate", headers=ha)
    assert (Path(app.state.stores.by_region["in"].path).stat().st_mode & 0o777) == 0o600


# ---------------------------------------------------------------- sessions, roles, users
def test_session_survives_restart_and_logout_revokes(tmp_path):
    c, app, login = mk(tmp_path)
    h = login("alpha-admin", "alpha-demo-pass")
    c2 = TestClient(create_app(load_settings(data_dir=tmp_path), run_background=False))     # "restart"
    assert c2.get("/api/me", headers=h).json()["username"] == "alpha-admin"
    assert c2.post("/api/logout", headers=h).status_code == 200
    assert c2.get("/api/me", headers=h).status_code == 401 and c.get("/api/me", headers=h).status_code == 401


def test_session_token_is_hashed_at_rest(env, tmp_path):
    c, app, ha, _ = env
    tok = ha["Authorization"].split()[1]
    row = app.state.stores.by_region["in"].q("SELECT token_hash FROM sessions")[0]
    assert tok not in json.dumps(row) and tok.startswith("in.")


def test_viewer_can_read_not_change(env):
    c, app, ha, login = env
    hv = login("alpha-viewer", "alpha-viewer-pass")
    assert c.get("/api/fleet", headers=hv).status_code == 200
    for method, path in (("put", "/api/config"), ("post", "/api/keys/rotate"), ("get", "/api/audit"), ("get", "/api/users"), ("get", "/api/keys")):
        r = getattr(c, method)(path, headers=hv, **({"json": {"burst_threshold": 8}} if method == "put" else {}))
        assert r.status_code == 403, path


def test_user_management_rules(env):
    c, app, ha, login = env
    assert c.post("/api/users", headers=ha, json={"username": "kim", "password": "short", "role": "viewer"}).status_code == 422
    assert c.post("/api/users", headers=ha, json={"username": "kim", "password": "long-enough-pw", "role": "root"}).status_code == 422
    assert c.post("/api/users", headers=ha, json={"username": "kim", "password": "long-enough-pw", "role": "viewer"}).status_code == 200
    assert c.post("/api/users", headers=ha, json={"username": "kim", "password": "long-enough-pw", "role": "viewer"}).status_code == 409
    hk = login("kim", "long-enough-pw")
    assert c.get("/api/me", headers=hk).json()["role"] == "viewer"
    assert c.delete("/api/users/kim", headers=ha).status_code == 200
    assert c.get("/api/me", headers=hk).status_code == 401 and login("kim", "long-enough-pw") is None
    assert c.delete("/api/users/alpha-admin", headers=ha).status_code == 409                # last admin
    assert c.delete("/api/users/beta-admin", headers=ha).status_code == 404                 # other tenant: not visible


def test_password_change_revokes_other_sessions(env):
    c, app, ha, login = env
    other = login("alpha-admin", "alpha-demo-pass")
    assert c.post("/api/password", headers=ha, json={"old": "wrong", "new": "brand-new-password"}).status_code == 401
    assert c.post("/api/password", headers=ha, json={"old": "alpha-demo-pass", "new": "short"}).status_code == 422
    assert c.post("/api/password", headers=ha, json={"old": "alpha-demo-pass", "new": "brand-new-password"}).status_code == 200
    assert c.get("/api/me", headers=other).status_code == 401 and login("alpha-admin", "alpha-demo-pass") is None
    assert login("alpha-admin", "brand-new-password")


def test_login_failures_audited_once_per_window(env):
    c, app, ha, _ = env
    for _ in range(3):
        c.post("/api/login", json={"username": "alpha-viewer", "password": "nope"})
    c.post("/api/login", json={"username": "ghost", "password": "nope"})                    # unknown names are not logged (no spam)
    acts = [r["action"] for r in c.get("/api/audit", headers=ha).json()]
    assert acts.count("login_failed") == 1 and "ghost" not in json.dumps(c.get("/api/audit", headers=ha).json())


# ---------------------------------------------------------------- audit chain
def test_audit_chain_verifies_and_detects_tampering(env):
    c, app, ha, _ = env
    c.put("/api/config", headers=ha, json={"burst_threshold": 8})
    c.put("/api/config", headers=ha, json={"burst_threshold": 9})
    c.post("/api/keys/rotate", headers=ha)
    v = c.get("/api/audit/verify", headers=ha).json()
    assert v["ok"] and v["rows"] >= 4
    st = app.state.engine.store_of("tenant-alpha")
    mid = st.q("SELECT id FROM audit WHERE action='config_changed' ORDER BY id")[0]["id"]
    st.conn.execute("UPDATE audit SET detail='{}' WHERE id=?", (mid,))                      # attacker edits history
    bad = c.get("/api/audit/verify", headers=ha).json()
    assert bad == {"ok": False, "rows": bad["rows"], "first_bad_id": mid}


def test_audit_deleted_row_detected_and_tenant_isolated(env):
    c, app, ha, login = env
    c.put("/api/config", headers=ha, json={"burst_threshold": 8})
    c.put("/api/config", headers=ha, json={"burst_threshold": 9})
    st = app.state.engine.store_of("tenant-alpha")
    st.conn.execute("DELETE FROM audit WHERE id=(SELECT id FROM audit WHERE action='config_changed' ORDER BY id LIMIT 1)")
    assert not c.get("/api/audit/verify", headers=ha).json()["ok"]
    hb = login("beta-admin", "beta-demo-pass")
    assert c.get("/api/audit/verify", headers=hb).json()["ok"] and "config_changed" not in json.dumps(c.get("/api/audit", headers=hb).json())


# ---------------------------------------------------------------- alerts
def bad(c, n=1, **k):
    for _ in range(n):
        send(c, A, pl(age=0.5, packet_loss=12.0, **k))


def good(c, n=3):
    for _ in range(n):
        send(c, A, pl(age=0.5))


def test_alert_opens_once_resolves_on_recovery(env):
    c, app, ha, _ = env
    bad(c, 3)
    al = c.get("/api/alerts", headers=ha).json()
    assert len(al) == 1 and al[0]["state"] == "open" and al[0]["severity"] == "critical" and al[0]["kind"] == "state"
    good(c, 3)
    assert c.get("/api/alerts", headers=ha).json()[0]["state"] == "resolved"
    assert c.get("/api/alerts?state=open", headers=ha).json() == []


def test_cooldown_reopens_same_alert_and_noise_reduction(env):
    c, app, ha, _ = env
    bad(c); good(c); bad(c)                                                                 # POOR, recover, POOR again inside cool-down
    al = c.get("/api/alerts", headers=ha).json()
    assert len(al) == 1 and al[0]["count"] == 2 and al[0]["state"] == "open"
    s = c.get("/api/alerts/summary", headers=ha).json()
    assert s["alert_worthy_transitions"] == 2 and s["alerts_shown"] == 1 and s["noise_reduction_pct"] == 50.0


def test_numbers_do_not_make_a_new_signature():
    from saas.alerts import signature
    assert signature("n", "POOR", ["packet loss 12.0% > 10%"]) == signature("n", "POOR", ["packet loss 17.3% > 10%"])
    assert signature("n", "POOR", ["packet loss 12%"]) != signature("n", "FAIR", ["packet loss 12%"])
    assert signature("n", "POOR", ["packet loss 12%"]) != signature("m", "POOR", ["packet loss 12%"])


def test_flapping_becomes_one_alert(env):
    c, app, ha, _ = env
    for _ in range(3):
        bad(c); good(c)                                                                     # 6 transitions inside the flap window
    al = c.get("/api/alerts", headers=ha).json()
    kinds = sorted(a["kind"] for a in al)
    assert kinds.count("flapping") == 1 and len([a for a in al if a["state"] == "open"]) == 1
    flap = next(a for a in al if a["kind"] == "flapping")
    assert flap["state"] == "open" and "state changes" in flap["title"]
    eng = app.state.engine
    eng.alerts.close_quiet_flaps(eng.store_of("tenant-alpha"), "tenant-alpha", time.time() + 301)
    assert c.get("/api/alerts?state=open", headers=ha).json() == []


def test_ack_is_admin_only_tenant_scoped_and_audited(env):
    c, app, ha, login = env
    bad(c)
    aid = c.get("/api/alerts", headers=ha).json()[0]["id"]
    assert c.put(f"/api/alerts/{aid}/ack", headers=login("alpha-viewer", "alpha-viewer-pass")).status_code == 403
    assert c.put(f"/api/alerts/{aid}/ack", headers=login("beta-admin", "beta-demo-pass")).status_code == 404
    assert c.put(f"/api/alerts/{aid}/ack", headers=ha).status_code == 200
    a = c.get("/api/alerts", headers=ha).json()[0]
    assert a["ack_by"] == "alpha-admin" and a["state"] == "open"
    assert "alert_ack" in [r["action"] for r in c.get("/api/audit", headers=ha).json()]


def test_alerts_are_tenant_scoped(env):
    c, app, ha, login = env
    bad(c)
    hb = login("beta-admin", "beta-demo-pass")
    assert c.get("/api/alerts", headers=hb).json() == [] and c.get("/api/alerts/summary", headers=hb).json()["alerts_shown"] == 0


# ---------------------------------------------------------------- conflicts + schema versions
def test_same_id_different_content_is_a_conflict_never_overwritten(env):
    c, app, ha, _ = env
    p = pl(cpu=40.0)
    assert send(c, A, p).json()["accepted"]
    q = {**p, "metrics": {**p["metrics"], "cpu": 99.0}}
    r = send(c, A, q).json()
    assert r["accepted"] == [] and "payload_id_conflict" in r["rejected"][0]["reason"]
    st = app.state.engine.store_of("tenant-alpha")
    assert json.loads(st.one("SELECT payload_json FROM events")["payload_json"])["metrics"]["cpu"] == 40.0
    assert app.state.engine.counters["conflicts"] == 1
    assert "payload_id_conflict" in [x["action"] for x in c.get("/api/audit", headers=ha).json()]
    assert send(c, A, p).json()["duplicates"] == [p["payload_id"]]                          # the honest retry is still a plain duplicate


def test_sent_at_and_replay_flag_do_not_cause_conflicts(env):
    c, *_ = env
    p = pl()
    send(c, A, p)
    again = {**p, "sent_at": utc(__import__("datetime").datetime.now(__import__("datetime").timezone.utc)), "is_replay": True}
    assert send(c, A, again).json()["duplicates"] == [p["payload_id"]]


def test_schema_versions(env):
    c, app, ha, _ = env
    v1, v2, v3 = pl(), pl(), pl()
    v2["schema_version"] = 2
    v2["collector_health"] = {"queue_depth": 3, "oldest_pending_s": 1.5, "dropped_total": 0, "blocked_total": 2, "sampled_out_total": 0, "near_miss_total": 1}
    v3["schema_version"] = 3
    r = send(c, A, v1, v2, v3).json()
    assert len(r["accepted"]) == 2 and "unsupported_schema_version" in r["rejected"][0]["reason"]
    col = c.get("/api/collectors", headers=ha).json()[0]
    assert col["health"]["queue_depth"] == 3 and col["schema_version"] in (1, 2)


# ---------------------------------------------------------------- multi-collector
def pc(cid, node, **k):
    p = pl(node=node, **k)
    p["collector_id"] = cid
    return p


def test_two_collectors_only_the_silent_one_goes_offline(env):
    c, app, ha, _ = env
    send(c, A, pc("col-edge-1", "n-aaaaaaaaaa"), pc("col-edge-2", "n-bbbbbbbbbb"))
    eng, st, t0 = app.state.engine, app.state.engine.store_of("tenant-alpha"), time.time()
    st.conn.execute("UPDATE fleet_collectors SET last_seen_ts=? WHERE collector_id='col-edge-2'", (t0 + 30,))
    st.conn.execute("UPDATE node_state SET last_seen_ts=? WHERE collector_id='col-edge-2'", (t0 + 30,))
    made = eng.check_stale(t0 + 31)
    assert ("tenant-alpha", "col-edge-1", "offline") in made and not any(m[1] == "col-edge-2" for m in made)
    f = c.get("/api/fleet", headers=ha).json()
    by = {x["collector_id"]: x for x in f["collectors"]}
    assert by["col-edge-1"]["offline"] and not by["col-edge-2"]["offline"]
    nodes = {n["node"]: n for n in f["nodes"]}
    assert nodes["n-aaaaaaaaaa"]["state"] == "POOR" and "collector offline" in nodes["n-aaaaaaaaaa"]["reasons"][0]
    assert nodes["n-bbbbbbbbbb"]["state"] == "EXCELLENT"
    assert f["collector"]["collector_id"] == "col-edge-1" and f["overall"] == "POOR"        # P4 back-compat: worst/offline collector first
    al = c.get("/api/alerts", headers=ha).json()
    assert [a["kind"] for a in al].count("collector") == 1 and not any(a["node"] == "n-aaaaaaaaaa" for a in al)   # one alert, not one per node


def test_collector_returns_and_alert_resolves(env):
    c, app, ha, _ = env
    send(c, A, pc("col-edge-1", "n-aaaaaaaaaa", age=60))
    app.state.engine.check_stale(time.time() + 31)
    assert any(a["kind"] == "collector" and a["state"] == "open" for a in c.get("/api/alerts", headers=ha).json())
    send(c, A, pc("col-edge-1", "n-aaaaaaaaaa", age=1))
    assert all(a["state"] == "resolved" for a in c.get("/api/alerts", headers=ha).json() if a["kind"] == "collector")
    assert not c.get("/api/collectors", headers=ha).json()[0]["offline"]


def test_collector_id_validation_and_cap(env):
    c, *_ = env
    r = send(c, A, pc("BAD ID!", "n-aaaaaaaaaa")).json()
    assert "collector_id" in json.dumps(r["rejected"]) or "invalid_collector_id" in json.dumps(r["rejected"])
    assert len(send(c, A, *[pc(f"col-x{i}", "n-aaaaaaaaaa") for i in range(50)]).json()["accepted"]) == 50
    assert send(c, A, pc("col-x50", "n-aaaaaaaaaa")).json()["rejected"][0]["reason"] == "too_many_collectors"


# ---------------------------------------------------------------- async evaluation queue + recovery
def test_store_before_ack_evaluate_later(env):
    c, app, ha, _ = env
    eng = app.state.engine
    eng.sync_eval = False
    p = pl()
    assert send(c, A, p).json()["accepted"] == [p["payload_id"]]                            # ACKed
    t = c.get("/api/tracker", headers=ha).json()
    assert t["queue_depth"] == 1 and t["funnel"]["stored"] == 1 and t["funnel"]["published"] == 0 and t["stuck"] == 1
    assert c.get("/api/fleet", headers=ha).json()["nodes"] == []
    assert eng.drain() == 1
    t = c.get("/api/tracker", headers=ha).json()
    assert t["queue_depth"] == 0 and t["stuck"] == 0 and c.get("/api/fleet", headers=ha).json()["nodes"][0]["state"] == "EXCELLENT"


def test_crash_between_store_and_evaluate_loses_nothing(tmp_path):
    c, app, login = mk(tmp_path)
    ha = login("alpha-admin", "alpha-demo-pass")
    app.state.engine.sync_eval = False
    ps = [pl(age=3 - i * 0.1) for i in range(5)]
    assert len(send(c, A, *ps).json()["accepted"]) == 5                                     # ACKed, then the process "dies"
    c2 = TestClient(create_app(load_settings(data_dir=tmp_path), run_background=False))
    eng2 = c2.app.state.engine
    assert eng2.recover() == 5 and eng2.drain() == 5
    h2 = {"Authorization": "Bearer " + c2.post("/api/login", json={"username": "alpha-admin", "password": "alpha-demo-pass"}).json()["token"]}
    t = c2.get("/api/tracker", headers=h2).json()
    assert t["funnel"]["published"] == 5 and t["stuck"] == 0
    assert eng2.drain() == 0 and eng2.recover() == 0                                        # never evaluated twice


def test_drain_is_idempotent_and_ordered(env):
    c, app, ha, _ = env
    eng = app.state.engine
    eng.sync_eval = False
    p = pl()
    send(c, A, p)
    eng.pending.append(("tenant-alpha", p["payload_id"]))                                   # a racing duplicate queue entry
    assert eng.drain() == 1
    assert eng.counters["evaluated"] == 1


# ---------------------------------------------------------------- retention
def test_retention_purges_old_events_not_audit(tmp_path):
    c, app, login = mk(tmp_path, retention_s=3600)
    ha = login("alpha-admin", "alpha-demo-pass")
    send(c, A, pl(), pl(node="n-bbbbbbbbbb"))
    eng = app.state.engine
    assert eng.purge(time.time() + 10) == {"tenant-alpha": {"events": 0, "state_history": 0, "rejects": 0, "alerts": 0, "sessions": 0},
                                           "tenant-beta": {"events": 0, "state_history": 0, "rejects": 0, "alerts": 0, "sessions": 0}}
    out = eng.purge(time.time() + 7200)
    assert out["tenant-alpha"]["events"] == 2
    assert c.get("/api/tracker", headers=ha).json()["stored_total"] == 0
    acts = [r["action"] for r in c.get("/api/audit", headers=ha).json()]
    assert "retention_purge" in acts and "login" in acts and c.get("/api/audit/verify", headers=ha).json()["ok"]


# ---------------------------------------------------------------- clock skew
def test_clock_skew_detected_when_collector_ahead(env):
    from datetime import datetime, timedelta, timezone
    c, app, ha, _ = env
    for _ in range(8):
        p = pl()
        p["sent_at"] = utc(datetime.now(timezone.utc) + timedelta(seconds=12))
        send(c, A, p)
    k = c.get("/api/tracker", headers=ha).json()["clock"]
    assert k["warn"] and -13 < k["estimate_s"] < -11 and "AHEAD" in k["note"]
    assert k["network_p95_adjusted_s"] < 1


def test_clock_ok_and_insufficient_samples(env):
    c, app, ha, _ = env
    assert c.get("/api/tracker", headers=ha).json()["clock"]["estimate_s"] is None
    for _ in range(8):
        send(c, A, pl())
    k = c.get("/api/tracker", headers=ha).json()["clock"]
    assert not k["warn"] and k["note"].startswith("clocks agree")


# ---------------------------------------------------------------- metrics
def test_metrics_access_and_scope(tmp_path):
    c, app, login = mk(tmp_path, metrics_token="op-secret-token")
    ha, hv = login("alpha-admin", "alpha-demo-pass"), login("alpha-viewer", "alpha-viewer-pass")
    send(c, A, pl(packet_loss=12.0))
    assert c.get("/metrics").status_code == 401 and c.get("/metrics", headers=hv).status_code == 401
    assert c.get("/metrics", headers={"Authorization": "Bearer wrong"}).status_code == 401
    mine = c.get("/metrics", headers=ha).text
    assert 'tenant="tenant-alpha"' in mine and "tenant-beta" not in mine and "cicada_ingest_total" not in mine
    assert 'cicada_nodes{tenant="tenant-alpha",state="POOR"} 1' in mine and 'cicada_alerts_open{tenant="tenant-alpha"} 1' in mine
    ops = c.get("/metrics", headers={"Authorization": "Bearer op-secret-token"}).text
    assert 'tenant="tenant-beta"' in ops and 'cicada_ingest_total{outcome="accepted"} 1' in ops and "cicada_eval_queue_depth 0" in ops
    assert "# TYPE cicada_nodes gauge" in ops


def test_healthz_lists_schema_versions(env):
    c, *_ = env
    assert c.get("/healthz").json()["schema_versions"] == [1, 2]


# ---------------------------------------------------------------- hardening round 2
def test_request_captured_before_restart_cannot_be_replayed_after(tmp_path):
    c, app, _ = mk(tmp_path)
    old = sign("dev-key-alpha", "POST", "/ingest", BATCH, ts=int(time.time()) - 5)          # captured before the restart
    time.sleep(0.01)
    c2 = TestClient(create_app(load_settings(data_dir=tmp_path), run_background=False))     # restart: nonce cache is empty
    r = c2.post("/ingest", content=BATCH, headers=old)
    assert r.status_code == 401 and "restarted" in r.json()["detail"]
    assert raw_post(c2, "dev-key-alpha", BATCH).status_code == 200                          # a fresh signature is fine


def test_rotated_secret_encrypted_at_rest_and_still_verifies(tmp_path):
    c, app, login = mk(tmp_path)
    ha = login("alpha-admin", "alpha-demo-pass")
    new = c.post("/api/keys/rotate", headers=ha).json()["key"]
    raw = sqlite3.connect(tmp_path / "saas_in.db").execute("SELECT secret FROM api_keys").fetchone()[0]
    assert raw.startswith("enc:") and new not in raw
    assert (tmp_path / "saas.kek").stat().st_mode & 0o777 == 0o600
    assert send(c, Col(new)).status_code == 200
    c2 = TestClient(create_app(load_settings(data_dir=tmp_path), run_background=False))     # restart reuses the same KEK
    assert send(c2, Col(new)).status_code == 200


def test_wrong_kek_makes_rotated_key_unusable_not_a_crash(tmp_path, monkeypatch):
    c, app, login = mk(tmp_path)
    new = c.post("/api/keys/rotate", headers=login("alpha-admin", "alpha-demo-pass")).json()["key"]
    from cryptography.fernet import Fernet
    monkeypatch.setenv("SAAS_KEK", Fernet.generate_key().decode())
    c2 = TestClient(create_app(load_settings(data_dir=tmp_path), run_background=False))
    assert send(c2, Col(new)).status_code == 401 and send(c2, A).status_code == 200


def test_folded_repeats_consistent_with_noise_reduction(env):
    c, app, ha, _ = env
    bad(c); good(c); bad(c)
    s = c.get("/api/alerts/summary", headers=ha).json()
    assert s["folded_repeats"] == s["alert_worthy_transitions"] - s["alerts_shown"]
