"""P1 collector tests: adapter, aggregation, egress hash, delivery guarantees (outage, kill -9, 500s, lost ACK), e2e."""
import asyncio
import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from collector.adapter import FileSource, normalise  # noqa: E402
from collector.aggregate import Aggregator, LoginWindow  # noqa: E402
from collector.config import load_settings  # noqa: E402
from collector.pipeline import Pipeline  # noqa: E402
from collector.redact import pseudo  # noqa: E402
from collector.sender import Sender  # noqa: E402
from contracts.hashing import canonical_hash  # noqa: E402
from tools import mock_saas  # noqa: E402
from tools.verify_delivery import verify  # noqa: E402

T0 = datetime(2026, 11, 20, 10, 0, 0, tzinfo=timezone.utc)
FAKE = ["sk-proj-9988221100aa", "Summer@2026", "ghp_FAKEFAKEFAKE1234"]


def line(node="app-01", dt=0, cpu=40.0, af=0, ip="10.0.0.9", raw_log="ok", **kw):
    d = {"ts": (T0 + timedelta(seconds=dt)).strftime("%Y-%m-%dT%H:%M:%SZ"), "node": node, "host": f"{node}.corp.local",
         "src_ip": ip, "user": "root", "raw_log": raw_log, "cpu_percent": cpu, "mem_percent": 50.0, "disk_percent": 60.0,
         "bandwidth_mbps": 100.0, "latency_ms": 20.0, "packet_loss_pct": 0.1, "auth_failed_count": af}
    d.update(kw)
    return d


def mk(tmp, **over):
    s = load_settings(db_path=str(Path(tmp) / "c.db"), rebase=False, loop=False, **over)
    return Pipeline(s)


def saas_client(db=":memory:", fail=None):
    """httpx client wired to the mock SaaS ASGI app; `fail(n)` may return a Response to inject faults."""
    app = mock_saas.create_app(db)
    asgi = httpx.ASGITransport(app=app)
    calls = {"n": 0}

    class T(httpx.AsyncBaseTransport):
        async def handle_async_request(self, req):
            calls["n"] += 1
            f = fail(calls["n"]) if fail else None
            if f == "lose_ack":
                await asgi.handle_async_request(req)
                raise httpx.ReadTimeout("ack lost")
            if isinstance(f, httpx.Response):
                return f
            if f == "down":
                raise httpx.ConnectError("down")
            return await asgi.handle_async_request(req)

    return httpx.AsyncClient(transport=T(), base_url="http://saas"), app


def sender_for(pipe, client):
    pipe.s.saas_url = "http://saas/ingest"
    return Sender(pipe.outbox, pipe.egress, pipe.s, client)


def drain(sender, max_iter=50):
    async def go():
        for _ in range(max_iter):
            await sender.send_once()
            if not sender.outbox.depth():
                return
    asyncio.run(go())


def saas_ids(app, tenant="tenant-alpha"):
    return app.state.db.execute("SELECT payload_id, sha256 FROM events WHERE tenant_id=?", (tenant,)).fetchall()


# ---------------- adapter ----------------
def test_adapter_missing_and_tz():
    ev = normalise({"ts": "2026-11-20T15:30:00+05:30", "node": "n1", "cpu_percent": 5})
    assert ev["ts"] == datetime(2026, 11, 20, 10, 0, tzinfo=timezone.utc)
    assert ev["metrics"]["mem"] is None and ev["metrics"]["cpu"] == 5.0
    assert normalise({"ts": 1790000000, "node": "n"})["ts"].tzinfo is not None
    assert normalise({"ts": "2026-11-20T10:00:00", "node": "n"})["ts"].tzinfo is not None   # naive -> UTC


def test_adapter_malformed_counted(tmp_path):
    p = tmp_path / "s.jsonl"
    p.write_text(json.dumps(line()) + "\nNOT JSON\n" + json.dumps({"node": "x"}) + "\n" + json.dumps(line(dt=5)) + "\n")
    src = FileSource(str(p))
    assert len(list(src.events())) == 2 and src.malformed == 2


# ---------------- login window ----------------
@pytest.mark.parametrize("n,expect", [(0, 0), (4, 4), (5, 5), (9, 9), (10, 10), (15, 15)])
def test_login_window_counts(n, expect):
    w = LoginWindow(60)
    for i in range(n):
        w.add(T0 + timedelta(seconds=i * 0.1), "n-a")
    assert w.snapshot(T0 + timedelta(seconds=5))[0] == expect


def test_login_window_two_sources_and_expiry():
    w = LoginWindow(60)
    for _ in range(3):
        w.add(T0, "n-a")
    for _ in range(7):
        w.add(T0 + timedelta(seconds=10), "n-b")
    total, top = w.snapshot(T0 + timedelta(seconds=20))
    assert (total, top) == (10, "n-b")
    assert w.snapshot(T0 + timedelta(seconds=60))[0] == 7        # a expired at exactly 60 s
    assert w.snapshot(T0 + timedelta(seconds=71))[0] == 0
    assert w.by_src == {}                                        # bounded memory


def test_login_window_bounded_under_flood():
    w = LoginWindow(60)
    for i in range(5000):
        w.add(T0 + timedelta(seconds=i), f"n-{i}")
    assert len(w.by_src) <= 61


# ---------------- aggregation ----------------
def test_aggregate_mean_and_window():
    a = Aggregator(lambda v: "n-x", 5)
    out = []
    for dt, cpu in [(0, 10), (1, 20), (2, 30), (5, 99)]:
        out += a.add(normalise(line(dt=dt, cpu=cpu)))
    assert len(out) == 1 and out[0].metrics["cpu"] == 20.0 and out[0].bucket == T0


def test_aggregate_late_event_emitted_separately():
    a = Aggregator(lambda v: "n-x", 5)
    for dt in (0, 5, 10):
        a.add(normalise(line(dt=dt)))
    late = a.add(normalise(line(dt=1, cpu=77)))
    assert len(late) == 1 and late[0].late and late[0].event_time == T0 + timedelta(seconds=1)


def test_aggregate_missing_metric_carries_forward_never_invents():
    a = Aggregator(lambda v: "n-x", 5)
    a.add(normalise(line(dt=0, cpu=33)))
    s1 = a.flush_all()
    assert s1[0].metrics["cpu"] == 33
    d = line(dt=5)
    del d["cpu_percent"]
    a.add(normalise(d))
    assert a.flush_all()[0].metrics["cpu"] == 33
    b = Aggregator(lambda v: "n-x", 5)
    d2 = line(dt=0)
    del d2["cpu_percent"]
    b.add(normalise(d2))
    assert b.flush_all() == [] and b.dropped_incomplete == 1       # nothing to carry: dropped, not invented


def test_burst_severity_end_to_end(tmp_path):
    p = mk(tmp_path)
    for i in range(12):
        p.process_event(normalise(line(node="db-01", dt=i * 0.1, af=1, ip="192.168.1.50")))
    p.process_event(normalise(line(node="db-01", dt=6)))
    p.flush_all()
    rows = [json.loads(r["json"]) for r in p.egress.list(10)]
    assert any(r["event_category"] == "SECURITY_BURST" and r["severity"] == "critical" and r["auth_failures_60s"] == 12 for r in rows)
    assert "192.168.1.50" not in json.dumps(rows)


# ---------------- egress hash ----------------
def test_egress_hash_matches_and_detects_tamper(tmp_path):
    p = mk(tmp_path)
    for i in range(20):
        p.process_event(normalise(line(dt=i * 5)))
    p.flush_all()
    rows = p.egress.list(100)
    assert len(rows) >= 19
    for r in rows:
        assert canonical_hash(json.loads(r["json"])) == r["sha256"]
    t = json.loads(rows[0]["json"])
    t["metrics"]["cpu"] = 1.234
    assert canonical_hash(t) != rows[0]["sha256"]


def test_hash_ignores_transport_fields(tmp_path):
    p = mk(tmp_path)
    p.process_event(normalise(line()))
    p.flush_all()
    r = p.egress.list(1)[0]
    d = json.loads(r["json"])
    d["sent_at"], d["is_replay"] = "2030-01-01T00:00:00Z", True
    assert canonical_hash(d) == r["sha256"]


# ---------------- delivery guarantees ----------------
def feed(p, n=10):
    for i in range(n):
        p.process_event(normalise(line(dt=i * 5, cpu=30 + i)))
    p.flush_all()


def test_happy_path_ids_match_and_hashes(tmp_path):
    p = mk(tmp_path)
    feed(p)
    client, app = saas_client()
    drain(sender_for(p, client))
    sent = p.egress.sent_ids()
    assert len(sent) == 10 and p.outbox.depth() == 0
    sent_h = {r["payload_id"]: r["sha256"] for r in p.egress.list(100)}
    missing, dups, mism = verify(sent_h, sent, saas_ids(app))
    assert (missing, dups, mism) == ([], [], [])


def test_outage_buffers_then_delivers_in_order(tmp_path):
    p = mk(tmp_path)
    feed(p)
    client, app = saas_client()
    s = sender_for(p, client)
    s.start_outage(60)
    asyncio.run(s.send_once())
    assert s.mode == "OFFLINE" and p.outbox.depth() == 10 and p.egress.sent_ids() == []
    s.clear_outage()
    drain(s)
    assert s.mode == "ONLINE" and p.outbox.depth() == 0 and len(saas_ids(app)) == 10
    ev = [json.loads(r[0]) for r in app.state.db.execute("SELECT payload_json FROM events")]
    assert all(e["is_replay"] for e in ev)                         # buffered > 10 s old => replay flag is true


def test_saas_down_then_up(tmp_path):
    p = mk(tmp_path)
    feed(p)
    state = {"down": True}
    client, app = saas_client(fail=lambda n: "down" if state["down"] else None)
    s = sender_for(p, client)
    for _ in range(3):
        asyncio.run(s.send_once())
    assert s.mode == "OFFLINE" and p.outbox.depth() == 10 and s.backoff() in (1, 2, 4, 5)
    state["down"] = False
    drain(s)
    assert len(saas_ids(app)) == 10


def test_kill9_simulated_reopen_db_resends_same_ids(tmp_path):
    p = mk(tmp_path)
    feed(p)
    before = {r["payload_id"] for r in p.outbox.claim_batch(100)}
    p.db.conn.close()                                               # process dies: nothing was ACKed
    p2 = Pipeline(load_settings(db_path=str(tmp_path / "c.db"), rebase=False, loop=False))
    after = {r["payload_id"] for r in p2.outbox.claim_batch(100)}
    assert before == after and len(after) == 10                     # persisted before send, same ids
    client, app = saas_client()
    drain(sender_for(p2, client))
    assert {r[0] for r in saas_ids(app)} == before


def test_server_500_retries_without_loss(tmp_path):
    p = mk(tmp_path)
    feed(p)
    client, app = saas_client(fail=lambda n: httpx.Response(500) if n <= 2 else None)
    s = sender_for(p, client)
    drain(s)
    assert len(saas_ids(app)) == 10 and s.failed_batches == 2


def test_lost_ack_then_resend_is_deduped_and_acked(tmp_path):
    p = mk(tmp_path)
    feed(p)
    client, app = saas_client(fail=lambda n: "lose_ack" if n == 1 else None)
    s = sender_for(p, client)
    drain(s)
    assert len(saas_ids(app)) == 10                                 # stored once
    assert s.duplicates_total == 10 and p.outbox.depth() == 0 and len(p.egress.sent_ids()) == 10


def test_rejected_is_parked_not_retried(tmp_path):
    p = mk(tmp_path, region="eu")                                   # wrong region for tenant-alpha => SaaS rejects
    feed(p, 3)
    client, app = saas_client()
    s = sender_for(p, client)
    drain(s)
    assert p.outbox.depth() == 0 and p.outbox.counts().get("REJECTED") == 3
    assert {r["status"] for r in p.egress.list(10)} == {"REJECTED"}
    assert saas_ids(app) == []


def test_wrong_api_key_is_offline_not_loss(tmp_path):
    p = mk(tmp_path, api_key="nope")
    feed(p, 2)
    client, _ = saas_client()
    s = sender_for(p, client)
    asyncio.run(s.send_once())
    assert s.mode == "OFFLINE" and p.outbox.depth() == 2 and "401" in s.last_error


def test_manual_duplicates_reported(tmp_path):
    p = mk(tmp_path)
    feed(p, 3)
    client, app = saas_client()
    s = sender_for(p, client)
    drain(s)
    assert asyncio.run(s.resend_last(3)) == 3
    assert len(saas_ids(app)) == 3


# ---------------- end to end: no secret / FQDN / IP on the wire ----------------
def test_no_leak_on_wire_and_replay_flag(tmp_path):
    p = mk(tmp_path)
    p.process_event(normalise(line(raw_log="deploy password=Summer@2026 token=ghp_FAKEFAKEFAKE1234 key=sk-proj-9988221100aa",
                                   api_key="sk-proj-9988221100aa", src_ip="203.0.113.77")))
    p.process_event(normalise(line(dt=6)))
    p.flush_all()
    client, app = saas_client()
    drain(sender_for(p, client))
    wire = " ".join(r[0] for r in app.state.db.execute("SELECT payload_json FROM events"))
    for bad in FAKE + ["corp.local", "203.0.113.77", "10.0.0.9", "root"]:
        assert bad not in wire
    assert "app-01" not in wire                                      # hostnames appear only as HMAC pseudonyms
    # raw stays local and still holds the secret (proves the panel can show it)
    assert any("Summer@2026" in json.dumps(r) for r in p.raw.recent(10))


def test_blocked_path_when_scanner_hits(tmp_path, monkeypatch):
    import collector.pipeline as pl
    monkeypatch.setattr(pl, "scan_outbound", lambda w: ["api_key"])
    p = mk(tmp_path)
    feed(p, 3)
    assert p.outbox.depth() == 0 and p.blocked == 3
    r = p.egress.list(5)[0]
    assert r["status"] == "BLOCKED" and r["matched_pattern"] == "api_key"


def test_pseudonyms_stable_and_tenant_specific():
    assert pseudo("10.0.0.9", b"k1") == pseudo("10.0.0.9", b"k1") != pseudo("10.0.0.9", b"k2")


def test_full_sample_stream_end_to_end(tmp_path):
    p = mk(tmp_path, stream_path=str(ROOT / "contracts/sample_stream.jsonl"))
    for ev in FileSource(p.s.stream_path).events():
        p.process_event(ev)
    p.flush_all()
    assert p.payloads_out >= 55 and p.blocked == 0
    client, app = saas_client()
    drain(sender_for(p, client), 200)
    sent_h = {r["payload_id"]: r["sha256"] for r in p.egress.list(500)}
    missing, dups, mism = verify(sent_h, p.egress.sent_ids(), saas_ids(app))
    assert (missing, dups, mism) == ([], [], []) and len(saas_ids(app)) == p.payloads_out


# ---------------- SERVICE_DOWN ----------------
def rows_of(p, n=200):
    return [json.loads(r["json"]) for r in p.egress.list(n)]


def test_silent_node_declared_service_down_once_then_recovers(tmp_path):
    p = mk(tmp_path)
    for i in range(4):                                              # app-01 and db-01 report every 5 s
        for n in ("app-01", "db-01"):
            p.process_event(normalise(line(node=n, dt=i * 5)))
    for i in range(4, 12):                                          # db-01 goes quiet, app-01 keeps going
        p.process_event(normalise(line(node="app-01", dt=i * 5)))
    down = [r for r in rows_of(p) if r["event_category"] == "SERVICE_DOWN"]
    assert len(down) == 1 and down[0]["severity"] == "critical"
    assert down[0]["node_pseudonym"] == pseudo("db-01", p.s.pseudo_key)
    p.process_event(normalise(line(node="db-01", dt=60)))           # back: no second alert, state cleared
    assert "db-01" not in p.agg.down
    assert len([r for r in rows_of(p) if r["event_category"] == "SERVICE_DOWN"]) == 1


def test_silence_checked_by_wall_clock_when_no_events_arrive(tmp_path):
    p = mk(tmp_path)
    p.process_event(normalise(line(node="net-01", dt=0)))
    p.flush_due(T0 + timedelta(seconds=10))
    assert not any(r["event_category"] == "SERVICE_DOWN" for r in rows_of(p))
    p.flush_due(T0 + timedelta(seconds=40))
    assert any(r["event_category"] == "SERVICE_DOWN" for r in rows_of(p))


def test_service_failure_log_flags_down_but_text_never_leaves(tmp_path):
    p = mk(tmp_path)
    p.process_event(normalise(line(node="db-01", dt=0, raw_log="systemd: postgresql.service failed password=Summer@2026")))
    p.process_event(normalise(line(node="db-01", dt=6)))
    p.flush_all()
    rows = rows_of(p)
    assert any(r["event_category"] == "SERVICE_DOWN" for r in rows)
    wire = json.dumps(rows)
    assert "postgresql" not in wire and "Summer@2026" not in wire


def test_old_replay_without_rebase_does_not_false_alarm(tmp_path):
    p = mk(tmp_path)                                                # rebase=False, events years old vs wall clock
    p.process_event(normalise(line(dt=0)))
    p.flush_due()                                                   # wall clock, no explicit now
    assert not any(r["event_category"] == "SERVICE_DOWN" for r in rows_of(p))


# ---------------- remote config ----------------
from collector.remote_config import ConfigPoller, config_url, validate  # noqa: E402


def test_config_url():
    assert config_url("http://localhost:8000/ingest") == "http://localhost:8000/collector/config"


def test_validate_bounds_and_unknown_keys():
    assert validate({"burst_threshold": 8, "fair_logins": 4, "evil": "rm -rf"}) == {"burst_threshold": 8, "fair_logins": 4}
    for bad in ({"burst_threshold": 0}, {"node_silent_s": "5"}, {"batch_size": True}, {"fair_logins": 9, "burst_threshold": 5}):
        with pytest.raises(ValueError):
            validate(bad)


def test_poll_applies_then_reports_ok_and_changes_behaviour(tmp_path):
    p = mk(tmp_path)
    client, app = saas_client()
    p.s.saas_url = "http://saas/ingest"
    cp = ConfigPoller(p, client)
    assert asyncio.run(cp.poll_once()) == "none"                    # 404: nothing to apply, status stays ok
    assert p.s.config_status == "ok"
    asyncio.run(client.post("/admin/config?tenant_id=tenant-alpha", json={"config_version": 7, "burst_threshold": 6,
                                                                          "fair_logins": 3, "node_silent_s": 20}))
    assert asyncio.run(cp.poll_once()) == "applied"
    assert (p.s.burst_threshold, p.s.fair_logins, p.agg.node_silent_s, p.s.config_version) == (6, 3, 20, 7)
    assert asyncio.run(cp.poll_once()) == "unchanged"
    for i in range(7):                                              # 7 failures now counts as a burst (was 10)
        p.process_event(normalise(line(node="db-01", dt=i * 0.1, af=1, ip="1.2.3.4")))
    p.process_event(normalise(line(node="db-01", dt=6)))
    assert any(r["event_category"] == "SECURITY_BURST" and r["config_status"] == "ok" for r in rows_of(p))


def test_bad_config_rejected_previous_values_kept_status_error(tmp_path):
    p = mk(tmp_path)
    cp = ConfigPoller(p)
    assert cp.apply({"config_version": 1, "burst_threshold": 8})
    assert not cp.apply({"config_version": 2, "burst_threshold": 9999})
    assert p.s.burst_threshold == 8 and p.s.config_status == "error" and "outside" in cp.last_error
    assert cp.apply({"config_version": 3, "burst_threshold": 12}) and p.s.config_status == "ok"


# ---------------- latency report ----------------
def test_latency_report_separates_live_and_replay(tmp_path):
    from tools.latency_report import collect, summarise
    p = mk(tmp_path)
    feed(p)
    client, app = saas_client()
    drain(sender_for(p, client))
    live, replay = collect(str(tmp_path / "c.db"))
    assert len(live) + len(replay) == 10 and replay                 # fixture events are minutes old => replay
    assert summarise([1, 2, 3, 9, 20], 10)["within_target_pct"] == 80.0
