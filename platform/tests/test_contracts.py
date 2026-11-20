"""Phase 1 contract tests: prove the allow-list, redaction and sample stream before anyone builds on them."""
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from collector.payload import build_payload  # noqa: E402
from collector.redact import find_secrets, pseudo, scan_outbound, scrub  # noqa: E402
from contracts.schema import ALLOWED_COLLECTOR_HEALTH, ALLOWED_METRICS, ALLOWED_TOP_LEVEL, Metrics, Payload  # noqa: E402

KEY = b"test-tenant-key"
STREAM = [json.loads(l) for l in (ROOT / "contracts/sample_stream.jsonl").read_text().splitlines()]
FAKE_SECRETS = ["sk-proj-9988221100aa", "Summer@2026", "ghp_FAKEFAKEFAKE1234", "FAKEFAKE.TOKEN.VALUE12345"]


def _payloads():
    """Rolling 60 s failed-login counter per node, then build every payload."""
    out, win = [], {}
    for raw in STREAM:
        t = datetime.strptime(raw["ts"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        w = win.setdefault(raw["node"], [])
        w.append((t, raw["auth_failed_count"]))
        w[:] = [(a, c) for a, c in w if (t - a).total_seconds() <= 60]
        n = sum(c for _, c in w)
        out.append((raw, build_payload(raw, tenant_id="tenant-alpha", region="in", source_tz="Asia/Kolkata",
                                       collector_id="col-alpha-01", tenant_key=KEY, auth_failures_60s=n)))
    return out


# ---------- sample stream ----------
def test_stream_has_60_events_and_fake_secrets():
    assert len(STREAM) == 60
    blob = json.dumps(STREAM)
    for s in FAKE_SECRETS:
        assert s in blob


def test_stream_covers_scenarios():
    assert any(r["auth_failed_count"] for r in STREAM)                      # failed logins
    assert any(r["node"] == "net-01" and r["latency_ms"] > 250 for r in STREAM)   # latency spike
    assert any(r["node"] == "db-01" and r["cpu_percent"] > 85 for r in STREAM)    # cpu incident


# ---------- schema (structural allow-list) ----------
def test_payload_rejects_unknown_field():
    _, p = _payloads()[0]
    d = json.loads(p.model_dump_json())
    d["raw_log"] = "Failed login for root"
    with pytest.raises(ValidationError):
        Payload(**d)


def test_metrics_rejects_unknown_field():
    with pytest.raises(ValidationError):
        Metrics(cpu=1, mem=1, disk=1, bandwidth_mbps=1, latency_ms=1, packet_loss=0, hostname="x")


def test_allow_list_is_exactly_the_documented_fields():
    assert ALLOWED_TOP_LEVEL == {
        "payload_id", "tenant_id", "collector_id", "region", "collector_version", "config_status", "event_time",
        "source_tz", "sent_at", "is_replay", "node_pseudonym", "event_category", "severity", "metrics",
        "auth_failures_60s", "auth_source_pseudonym", "schema_version", "collector_health"}
    assert ALLOWED_COLLECTOR_HEALTH == {"queue_depth", "oldest_pending_s", "dropped_total", "blocked_total",
                                        "sampled_out_total", "near_miss_total"}
    assert ALLOWED_METRICS == {"cpu", "mem", "disk", "bandwidth_mbps", "latency_ms", "packet_loss"}


# ---------- nothing sensitive leaves ----------
def test_no_secret_hostname_or_ip_in_any_outbound_payload():
    for raw, p in _payloads():
        j = p.model_dump_json()
        for s in FAKE_SECRETS + [raw["host"], raw["src_ip"], raw["user"], raw["raw_log"]]:
            assert s not in j, (s, j)
        assert scan_outbound(j) == []


def test_failed_login_burst_summarised_as_count_only():
    ps = [p for _, p in _payloads() if p.event_category == "SECURITY_BURST"]
    assert ps, "burst must be detected"
    assert max(p.auth_failures_60s for p in ps) >= 10
    assert all(p.auth_source_pseudonym.startswith("n-") for p in ps)


# ---------- redaction ----------
@pytest.mark.parametrize("text", [
    "key sk-proj-9988221100aa used", "password=Summer@2026", "token=ghp_FAKEFAKEFAKE1234",
    "Authorization: Bearer FAKEFAKE.TOKEN.VALUE12345", 'api_key": "sk-abcdefgh12345"', "pwd: hunter2hunter2",
    "AKIAABCDEFGHIJKLMNOP"])
def test_scrub_catches_secrets(text):
    assert find_secrets(text)
    assert "[REDACTED]" in scrub(text)


@pytest.mark.parametrize("text", [
    str(uuid.uuid4()), "2026-11-20T10:00:00Z", "1.0.0", "n-8f3a1b9c2d", "Failed login for root from 192.168.1.50",
    "auth_failures_60s: 14"])
def test_scrub_ignores_near_misses(text):
    assert find_secrets(text) == []


def test_pseudonym_is_keyed_stable_and_not_reversible_by_plain_hash():
    a, b = pseudo("db-01", KEY), pseudo("db-01", KEY)
    assert a == b and a.startswith("n-") and len(a) == 12
    assert pseudo("db-01", b"other-tenant-key") != a            # different tenant => different pseudonym
    import hashlib
    assert a != "n-" + hashlib.sha256(b"db-01").hexdigest()[:10]   # not a bare hash


# ---------- config contracts ----------
def test_config_files_parse_and_are_consistent():
    th = yaml.safe_load((ROOT / "contracts/thresholds.yaml").read_text())
    assert th["constants"]["offline_threshold_s"] < th["targets"]["offline_detection_s"]
    assert set(th["health_states"]) == {"EXCELLENT", "GOOD", "FAIR", "POOR"}
    tn = yaml.safe_load((ROOT / "contracts/tenants.yaml").read_text())["tenants"]
    assert {t["region"] for t in tn.values()} == {"in", "eu"}
    dm = yaml.safe_load((ROOT / "contracts/dependency_map.yaml").read_text())
    for tenant, graph in dm.items():
        assert tenant in tn
        for node, deps in graph.items():
            assert all(d in graph for d in deps), (tenant, node)


def test_collector_health_rejects_unknown_field_and_v1_payload_still_valid():
    from contracts.schema import CollectorHealth
    with pytest.raises(ValidationError):
        CollectorHealth(queue_depth=1, last_error="password=hunter2")
    p = Payload(payload_id="6f1f8f0e-1111-4222-8333-444455556666", tenant_id="t", collector_id="c", region="in",
                collector_version="0.1", config_status="ok", event_time="2026-11-20T10:00:00Z", source_tz="UTC",
                sent_at="2026-11-20T10:00:01Z", node_pseudonym="n-x", event_category="METRICS", severity="info",
                metrics=dict(cpu=1, mem=1, disk=1, bandwidth_mbps=1, latency_ms=1, packet_loss=0))
    assert p.schema_version == 1 and p.collector_health is None
