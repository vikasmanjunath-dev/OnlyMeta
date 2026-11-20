"""P1 advancements: secret detection + near-miss, text-derived signals, tail/syslog sources, backpressure,
adaptive sampling, self-health, request signing, chaos guard."""
import asyncio
import json
import socket
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from collector.adapter import failed_login_from_text, normalise  # noqa: E402
from collector.config import load_settings  # noqa: E402
from collector.main import create_app  # noqa: E402
from collector.pipeline import Pipeline  # noqa: E402
from collector.redact import high_entropy_tokens, scan_outbound, scrub, secret_summary  # noqa: E402
from collector.sources import SyslogSource, TailSource, make_sources, parse_line, parse_syslog, short_node  # noqa: E402
from contracts import signing  # noqa: E402

T0 = datetime(2026, 11, 20, 10, 0, 0, tzinfo=timezone.utc)


def line(node="app-01", dt=0, cpu=40.0, af=None, ip="10.0.0.9", raw_log="ok", **kw):
    d = {"ts": (T0 + timedelta(seconds=dt)).strftime("%Y-%m-%dT%H:%M:%SZ"), "node": node, "host": f"{node}.corp.local", "src_ip": ip,
         "user": "root", "raw_log": raw_log, "cpu_percent": cpu, "mem_percent": 50.0, "disk_percent": 60.0, "bandwidth_mbps": 100.0,
         "latency_ms": 20.0, "packet_loss_pct": 0.1}
    if af is not None:
        d["auth_failed_count"] = af
    d.update(kw)
    return d


def mk(tmp, **over):
    return Pipeline(load_settings(db_path=str(Path(tmp) / "c.db"), rebase=False, loop=False, **over))


# ---------------- secrets ----------------
@pytest.mark.parametrize("text,kind", [
    ("token ghp_FAKE1234abcd", "github_token"), ("github_pat_11ABCDEFG0123456789_abcdefghij", "github_pat"),
    ("xoxb-1234567890-abcdefghij", "slack_token"), ("key sk_live_abcdef123456", "stripe_key"),
    ("AIzaSyA-1234567890abcdefghijklmnopqrstu", "google_api_key"), ("-----BEGIN RSA PRIVATE KEY-----", "private_key_block"),
    ("AccountKey=abcdEFGH1234abcdEFGH1234==", "cloud_account_key"), ("postgres://admin:s3cr3t@10.0.0.1/db", "url_credentials"),
    ("Authorization: Bearer abcdefgh12345678", "bearer"), ("password=Summer@2026", "credential_assignment")])
def test_new_secret_patterns_detected_and_scrubbed(text, kind):
    assert kind in secret_summary(text)
    assert "[REDACTED]" in scrub(text)
    assert scan_outbound(json.dumps({"x": text}))                       # and the boundary would block it


def test_high_entropy_token_caught_but_hashes_uuids_and_timestamps_are_not():
    assert high_entropy_tokens("rand Zk39sLQe81xPwT7vNb4RuYh2CjA5gDfM")
    for benign in ["sha 9fceb02d0ae598e95dc970b74767f19372d61af8", "id 6f1f8f0e-1111-4222-8333-444455556666",
                   "2026-11-20T10:00:00.000Z Asia/Kolkata", "n-b7cd652869", "bandwidth_mbps latency_ms packet_loss_pct"]:
        assert high_entropy_tokens(benign) == [], benign


def test_overlapping_matches_count_once():
    assert sum(secret_summary("token=ghp_FAKE1234abcd").values()) == 1


def test_near_miss_counted_locally_and_nothing_on_the_wire(tmp_path):
    p = mk(tmp_path)
    p.process_event(normalise(line(raw_log="deploy password=Summer@2026 token=ghp_FAKEFAKEFAKE1234", api_key="sk-proj-9988221100aa")))
    p.process_event(normalise(line(dt=6)))
    p.flush_all()
    assert p.near_miss >= 2 and "credential_assignment" in p.near_miss_kinds
    wire = json.dumps([json.loads(r["json"]) for r in p.egress.list(50)])
    assert "Summer@2026" not in wire and "ghp_" not in wire and "sk-proj" not in wire
    assert p.health().near_miss_total == p.near_miss


# ---------------- text-derived signals ----------------
@pytest.mark.parametrize("text,ip", [
    ("Failed password for root from 192.168.1.50 port 22 ssh2", "192.168.1.50"),
    ("Failed password for invalid user admin from 10.1.1.1 port 4", "10.1.1.1"),
    ("Invalid user test from 172.16.0.9", "172.16.0.9"),
    ("pam_unix(sshd:auth): authentication failure; logname= uid=0 rhost=203.0.113.7", "203.0.113.7"),
    ("login failed src=198.51.100.2", "198.51.100.2"), ("all good", None), ("Accepted password for root from 1.2.3.4", None)])
def test_failed_login_from_text(text, ip):
    assert failed_login_from_text(text) == ip


def test_structured_count_wins_over_text_no_double_count():
    e = normalise(line(raw_log="Failed password for root from 192.168.1.50", af=3))
    assert e["auth_failed"] == 3
    assert normalise(line(raw_log="Failed password for root from 192.168.1.50"))["auth_failed"] == 1


def test_ten_text_failures_become_a_burst_without_any_structured_field(tmp_path):
    p = mk(tmp_path)
    for i in range(12):
        p.process_event(normalise(line(node="db-01", dt=i * 0.1, raw_log="Failed password for root from 192.168.1.50 port 22")))
    p.process_event(normalise(line(node="db-01", dt=6)))
    p.flush_all()
    rows = [json.loads(r["json"]) for r in p.egress.list(10)]
    assert any(r["event_category"] == "SECURITY_BURST" and r["auth_failures_60s"] == 12 for r in rows)
    assert "192.168.1.50" not in json.dumps(rows)


# ---------------- sources ----------------
def test_parse_syslog_5424_and_3164_and_node_shortening():
    d = parse_syslog("<34>1 2026-11-20T10:00:01Z prod-db-01.corp.local sshd 812 - - Failed password for root from 1.2.3.4")
    assert d["node"] == "prod-db-01" and d["ts"] == "2026-11-20T10:00:01Z" and "Failed password" in d["raw_log"]
    d = parse_syslog("<13>Nov 20 10:00:01 web-02 nginx[7]: upstream timed out", now=T0)
    assert d["node"] == "web-02" and d["ts"] == T0.isoformat()
    assert parse_syslog("not syslog at all") is None
    assert short_node("a.b.c") == "a" and short_node("") == "unknown"
    assert parse_line("   ") is None and parse_line('{"ts":"2026-11-20T10:00:00Z","node":"n"}')["node"] == "n"
    assert parse_line("plain text")["node"] == "local"
    with pytest.raises(ValueError):
        parse_line("{broken")


def collect(src, n, timeout=3.0, trigger=None):
    async def go():
        stop, out = asyncio.Event(), []

        async def reader():
            async for ev in src.aevents(stop):
                out.append(ev)
                if len(out) >= n:
                    stop.set()
        t = asyncio.create_task(reader())
        if trigger:
            await asyncio.sleep(0.3)
            await trigger()
        try:
            await asyncio.wait_for(t, timeout)
        except asyncio.TimeoutError:
            stop.set()
            await t
        return out
    return asyncio.run(go())


def test_tail_follows_appends_skips_history_handles_partial_line_rotation_truncate(tmp_path):
    f = tmp_path / "app.log"
    f.write_text(json.dumps(line(node="old")) + "\n")                      # history: skipped (from_start False)
    src = TailSource(str(f), poll_s=0.05)

    async def trig():
        with open(f, "a") as h:
            h.write(json.dumps(line(node="a")) + "\n" + json.dumps(line(node="b"))[:20])     # complete + partial line
            h.flush()
            await asyncio.sleep(0.2)
            h.write(json.dumps(line(node="b"))[20:] + "\n")                                    # partial completed
        await asyncio.sleep(0.2)
        f.rename(tmp_path / "app.log.1")                                                       # rotation
        f.write_text("Failed password for root from 1.2.3.4\n")
        await asyncio.sleep(0.3)
        f.write_text(json.dumps(line(node="c")) + "\n")                                       # truncate + rewrite
    evs = collect(src, 4, trigger=trig)
    nodes = [e["node"] for e in evs]
    assert nodes[:2] == ["a", "b"] and "old" not in nodes and len(evs) >= 3
    assert any(e["auth_failed"] == 1 for e in evs)                                             # text line from the rotated file


def test_tail_from_start_reads_history_and_counts_malformed(tmp_path):
    f = tmp_path / "x.log"
    f.write_text(json.dumps(line(node="h1")) + "\n{broken\n" + json.dumps(line(node="h2")) + "\n")
    src = TailSource(str(f), poll_s=0.05, from_start=True)
    assert [e["node"] for e in collect(src, 2)] == ["h1", "h2"] and src.malformed == 1


def test_syslog_udp_receives_parses_and_drops_junk_and_oversize():
    src = SyslogSource("127.0.0.1", 0)

    async def trig():
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        for _ in range(20):
            if src.port:
                break
            await asyncio.sleep(0.05)
        for msg in (b"garbage", b"x" * 9000, b"<34>1 2026-11-20T10:00:01Z web-01 sshd 1 - - Failed password for root from 9.9.9.9"):
            s.sendto(msg, ("127.0.0.1", src.port))
        s.close()
    evs = collect(src, 1, trigger=trig)
    assert evs and evs[0]["node"] == "web-01" and evs[0]["auth_failed"] == 1 and src.malformed >= 1


def test_make_sources_specs_and_unknown_fails_loudly():
    got = make_sources(["file", "tail:/tmp/x", "syslog:0.0.0.0:5514"], lambda: "F")
    assert got[0] == "F" and isinstance(got[1], TailSource) and isinstance(got[2], SyslogSource) and got[2].port == 5514
    with pytest.raises(ValueError):
        make_sources(["kafka:topic"], lambda: None)


def test_log_only_node_is_counted_unusable_not_invented(tmp_path):
    p = mk(tmp_path)
    p.process_event(normalise({"ts": T0.isoformat(), "node": "textonly", "raw_log": "Failed password for root from 1.2.3.4"}))
    p.flush_all()
    assert p.egress.list(10) == [] and p.agg.dropped_incomplete >= 1


# ---------------- backpressure ----------------
def feed_sev(p, n, **kw):
    ids = []
    for i in range(n):
        ids += p.process_event(normalise(line(node=f"n{i}", dt=0, **kw)))
    return ids + p.flush_all()


def test_cap_sheds_lowest_severity_first_and_records_everything(tmp_path):
    p = mk(tmp_path, outbox_max_rows=5)
    feed_sev(p, 5)                                                                   # 5 info payloads fill the queue
    assert p.outbox.depth() == 5
    crit = [x for x in (p.process_event(normalise(line(node=f"c{i}", dt=10, cpu=99, packet_loss_pct=12.0))) for i in range(3)) if x]
    p.flush_all()
    assert p.outbox.depth() == 5 and p.dropped == 3                                   # 3 info rows evicted for 3 critical ones
    st = {r["status"] for r in p.egress.list(50)}
    assert "DROPPED" in st
    rows = [json.loads(r["json"]) for r in p.egress.list(50, status="QUEUED")]
    assert sum(r["severity"] == "critical" for r in rows) == 3
    assert p.health().dropped_total == 3


def test_full_of_critical_refuses_info_newcomer_on_the_record(tmp_path):
    p = mk(tmp_path, outbox_max_rows=2)
    for i in range(2):
        p.process_event(normalise(line(node=f"c{i}", dt=0, cpu=99, packet_loss_pct=12.0)))
    p.flush_all()
    p.process_event(normalise(line(node="calm", dt=10)))
    p.flush_all()
    assert p.outbox.depth() == 2 and p.dropped == 1
    assert [r["status"] for r in p.egress.list(1)] == ["DROPPED"]


def test_old_outbox_db_is_migrated(tmp_path):
    import sqlite3
    db = tmp_path / "old.db"
    c = sqlite3.connect(db)
    c.executescript("CREATE TABLE outbox(payload_id TEXT PRIMARY KEY, event_time TEXT, state TEXT, attempts INTEGER DEFAULT 0, last_error TEXT, created_at REAL);")
    c.commit()
    c.close()
    from collector.store import DB
    DB(str(db))
    assert "sev" in {r[1] for r in sqlite3.connect(db).execute("PRAGMA table_info(outbox)")}


# ---------------- adaptive sampling ----------------
def test_adaptive_sampling_sends_every_nth_stable_sample_but_all_anomalies(tmp_path):
    p = mk(tmp_path, stable_every=3)
    for i in range(9):                                                                 # 9 stable windows for one node
        p.process_event(normalise(line(dt=i * 5)))
    p.flush_all()
    assert p.payloads_out == 4 and p.sampled_out == 5                                   # 1st (first) + every 3rd of the rest
    p2 = mk(tmp_path / "x" if (tmp_path / "x").mkdir() is None else tmp_path, stable_every=3)
    for i in range(6):
        p2.process_event(normalise(line(dt=i * 5, cpu=99 if i == 2 else 40)))           # one spike in the middle
    p2.flush_all()
    sent = [json.loads(r["json"]) for r in p2.egress.list(50)]
    assert any(r["metrics"]["cpu"] == 99 for r in sent)                                  # the anomaly is never skipped
    assert p2.sampled_out >= 1


def test_recovery_sample_after_anomaly_is_always_sent(tmp_path):
    p = mk(tmp_path, stable_every=4)
    for i, cpu in enumerate([40, 99, 40, 40, 40, 40]):
        p.process_event(normalise(line(dt=i * 5, cpu=cpu)))
    p.flush_all()
    cpus = sorted(json.loads(r["json"])["metrics"]["cpu"] for r in p.egress.list(50))
    assert cpus.count(40.0) >= 2 and 99.0 in cpus                                        # first + first-after-recovery


def test_stable_every_one_is_off(tmp_path):
    p = mk(tmp_path)
    for i in range(5):
        p.process_event(normalise(line(dt=i * 5)))
    p.flush_all()
    assert p.payloads_out == 5 and p.sampled_out == 0


# ---------------- self-health in payloads ----------------
def test_payload_carries_schema_v2_and_collector_health_without_text(tmp_path):
    p = mk(tmp_path)
    for i in range(3):
        p.process_event(normalise(line(dt=i * 5)))
    p.flush_all()
    d = json.loads(p.egress.list(1)[0]["json"])
    assert d["schema_version"] == 2 and set(d["collector_health"]) == {
        "queue_depth", "oldest_pending_s", "dropped_total", "blocked_total", "sampled_out_total", "near_miss_total"}
    assert all(isinstance(v, (int, float)) for v in d["collector_health"].values())
    assert scan_outbound(json.dumps(d)) == []


# ---------------- signing ----------------
def test_signature_roundtrip_and_every_tamper_fails():
    h = signing.sign("secret-key", "POST", "/ingest", b'{"batch":[]}', ts=1000, nonce="abc")
    ok = lambda **o: signing.verify(o.get("secret", "secret-key"), o.get("method", "POST"), o.get("path", "/ingest"),
                                    o.get("body", b'{"batch":[]}'), o.get("ts", "1000"), o.get("nonce", "abc"), h["X-Signature"])
    assert ok()
    for bad in (dict(secret="other"), dict(method="GET"), dict(path="/ingest?x=1"), dict(body=b'{"batch":[1]}'), dict(ts="1001"), dict(nonce="abd")):
        assert not ok(**bad), bad
    assert "secret-key" not in json.dumps(h) and h["X-Key-Id"] == signing.key_id("secret-key") != "secret-key"
    assert signing.sign("k", "GET", "/x")["X-Nonce"] != signing.sign("k", "GET", "/x")["X-Nonce"]


# ---------------- chaos guard ----------------
@pytest.fixture
def col(tmp_path):
    s = load_settings(db_path=str(tmp_path / "c.db"), rebase=False, loop=False)
    app = create_app(s)
    return TestClient(app), app


def test_chaos_needs_header_and_allowed_origin(col):
    c, app = col
    assert c.post("/api/chaos/outage?seconds=5").status_code == 403                                  # no X-Chaos
    assert c.post("/api/chaos/outage?seconds=5", headers={"X-Chaos": "1", "Origin": "http://evil.example"}).status_code == 403
    assert c.post("/api/chaos/outage?seconds=5", headers={"X-Chaos": "1"}).status_code == 200          # CLI/curl (no Origin)
    ok = {"X-Chaos": "1", "Origin": "http://127.0.0.1:8000"}
    r = c.post("/api/chaos/clear", headers=ok)
    assert r.status_code == 200 and r.headers["access-control-allow-origin"] == "http://127.0.0.1:8000"


def test_chaos_preflight_only_for_allowed_origin(col):
    c, _ = col
    r = c.options("/api/chaos/scenario/secret", headers={"Origin": "http://127.0.0.1:8000", "Access-Control-Request-Method": "POST"})
    assert r.status_code == 204 and "X-Chaos" in r.headers["access-control-allow-headers"]
    assert c.options("/api/chaos/scenario/secret", headers={"Origin": "http://evil.example"}).status_code == 403


def test_raw_endpoints_never_get_cors(col):
    c, _ = col
    r = c.get("/api/egress-log", headers={"Origin": "http://127.0.0.1:8000"})
    assert "access-control-allow-origin" not in r.headers                                              # raw data stays local


def test_chaos_secret_scenario_reports_proof_and_status_has_no_raw(col):
    c, app = col
    h = {"X-Chaos": "1"}
    r = c.post("/api/chaos/scenario/secret", headers=h).json()
    assert r["secrets_seen_locally"] >= 2 and r["blocked_at_boundary"] == 0
    st = c.get("/api/chaos/status").json()
    assert st["near_miss"] >= 2 and "Hunter2" not in json.dumps(st)
    assert c.post("/api/chaos/scenario/nope", headers=h).status_code == 404
    assert c.post("/api/chaos/scenario/bruteforce?n=12", headers=h).json()["payloads_emitted"] >= 1
    assert c.post("/api/chaos/scenario/servicedown", headers=h).json()["payloads_emitted"] >= 1


def test_remote_config_accepts_new_keys_with_safe_bounds():
    from collector.remote_config import validate
    assert validate({"stable_every": 3, "outbox_max_rows": 500}) == {"stable_every": 3, "outbox_max_rows": 500}
    for bad in ({"stable_every": 9}, {"stable_every": 0}, {"outbox_max_rows": 10}):
        with pytest.raises(ValueError):
            validate(bad)
