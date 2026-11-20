"""P4 judge layer: the Proof Board page, its collector-side evidence (scenario evidence, ledger, CORS), the calm demo feed and
priming, and the SaaS 'rebuild baselines' action. Browser behaviour is covered by `tools/demo.py boardcheck`."""
import asyncio
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from collector import scenarios  # noqa: E402
from collector.config import load_settings  # noqa: E402
from collector.main import create_app as collector_app  # noqa: E402
from collector.sources import CalmSource, make_sources  # noqa: E402
from saas.aiops.correlate import anomaly_signals  # noqa: E402
from test_p2_advanced import mk  # noqa: E402
from test_p3_aiops import CLEAN, N, warm  # noqa: E402
from test_saas import A, pl, send  # noqa: E402

FAKE = ["Hunter2", "ghp_FAKEFAKEFAKE1234", "sk-proj-9988221100"]
ORIGIN = {"Origin": "http://127.0.0.1:8000"}


@pytest.fixture
def col(tmp_path):
    s = load_settings(db_path=str(tmp_path / "c.db"), rebase=False, loop=False)
    app = collector_app(s)
    return TestClient(app), app.state.pipe


@pytest.fixture
def saas(tmp_path):
    c, app, login = mk(tmp_path, rate_limit_rps=100000)
    return c, app, login("alpha-admin", "alpha-demo-pass"), login


# ---------------------------------------------------------------- the page
def test_demo_page_and_root_redirect_to_console(saas):
    c, *_ = saas
    r = c.get("/demo")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    for claim in ("A secret never leaves", "A network cut loses nothing", "AIOps names the root cause", "Tenants and regions are isolated"):
        assert claim in r.text
    rr = c.get("/", follow_redirects=False)
    assert rr.status_code in (302, 307) and rr.headers["location"] == "/console"


def test_demo_page_carries_no_data_and_needs_no_session(saas):
    c, *_ = saas
    assert "tenant-alpha" not in c.get("/demo").text                    # static page: every number comes from authenticated APIs


# ---------------------------------------------------------------- collector evidence
def test_secret_scenario_returns_clean_outbound_evidence_only(col):
    c, pipe = col
    r = c.post("/api/chaos/scenario/secret", headers={"X-Chaos": "1", **ORIGIN}).json()
    assert r["secrets_seen_locally"] >= 1 and r["evidence"]
    for e in r["evidence"]:
        assert e["secrets_in_outbound"] == 0 and e["sha256"] and e["status"] in ("QUEUED", "SENT")
        assert not any(s in str(e["outbound"]) for s in FAKE)           # the raw side is never in the response
    assert not any(s in str(r) for s in FAKE)


def test_secret_scenario_uses_a_node_the_feed_keeps_alive():
    assert scenarios.build("secret")[0]["node"] == "app-01"             # a one-off node would go silent and hold an incident open


def test_ledger_has_ids_and_hashes_only_and_only_sent(col):
    c, pipe = col
    r = c.post("/api/chaos/scenario/cpu?ticks=2", headers={"X-Chaos": "1", **ORIGIN}).json()
    assert r["payloads_emitted"] >= 1
    assert c.get("/api/chaos/ledger", headers=ORIGIN).json() == []       # nothing acknowledged yet
    rows = pipe.egress.list(10)
    pipe.egress.mark([rows[0]["payload_id"]], "SENT", ack=True)
    led = c.get("/api/chaos/ledger", headers=ORIGIN).json()
    assert led == [{"payload_id": rows[0]["payload_id"], "sha256": rows[0]["sha256"]}]


def test_ledger_cors_only_for_the_allowed_origin(col):
    c, _ = col
    ok = c.get("/api/chaos/ledger", headers=ORIGIN)
    assert ok.headers.get("access-control-allow-origin") == ORIGIN["Origin"]
    assert c.get("/api/chaos/ledger", headers={"Origin": "https://evil.example"}).status_code == 403
    assert c.get("/api/egress-log").status_code == 200 and "access-control-allow-origin" not in c.get("/api/egress-log", headers=ORIGIN).headers   # raw stays unreadable cross-origin


def test_prime_scenario_emits_calm_history(col):
    c, _ = col
    r = c.post("/api/chaos/scenario/prime?ticks=8", headers={"X-Chaos": "1", **ORIGIN}).json()
    assert r["payloads_emitted"] >= 3 and r["blocked_at_boundary"] == 0


# ---------------------------------------------------------------- calm feed
def test_calm_source_is_healthy_deterministic_in_shape():
    async def go():
        src, stop, got = CalmSource(interval_s=0.01), asyncio.Event(), []
        async for ev in src.aevents(stop):
            got.append(ev)
            if len(got) == 9:
                stop.set()
        return got
    evs = asyncio.run(go())
    assert {e["node"] for e in evs} == {"app-01", "db-01", "net-01"}
    assert all(e["metrics"]["cpu"] < 60 and e["metrics"]["latency_ms"] < 60 and e["auth_failed"] == 0 for e in evs)
    ts = sorted({e["ts"] for e in evs})
    assert [(b - a).total_seconds() for a, b in zip(ts, ts[1:])] == [5.0, 5.0]       # virtual 5 s clock


def test_make_sources_knows_calm_and_scales_with_speed():
    src = make_sources(["calm"], lambda: None, speed=20.0)[0]
    assert isinstance(src, CalmSource) and src.interval_s == pytest.approx(0.25)
    with pytest.raises(ValueError):
        make_sources(["nope"], lambda: None)


# ---------------------------------------------------------------- SaaS
def test_incident_evidence_uses_the_peak_not_the_latest_sample():
    sig = anomaly_signals([{"open": True, "z": 0.4, "peak_z": 18.2, "metric": "latency_ms", "value": 31, "mean": 30, "sigma": 5}])[0]
    assert sig["z"] == 18.2 and sig["current_z"] == 0.4
    neg = anomaly_signals([{"open": True, "z": -0.2, "peak_z": 9.0, "metric": "cpu", "value": 1, "mean": 40, "sigma": 2}])[0]
    assert neg["z"] == -9.0                                              # direction kept


def test_rebuild_baselines_admin_only_audited_and_relearns(saas):
    c, app, ta, login = saas
    warm(c)
    node = N["db-01"]
    assert c.post("/api/aiops/baselines/rebuild").status_code == 401
    tv = login("alpha-viewer", "alpha-viewer-pass")
    assert c.post("/api/aiops/baselines/rebuild", headers=tv).status_code == 403
    r = c.post("/api/aiops/baselines/rebuild", headers=ta)
    assert r.status_code == 200 and r.json()["nodes"] == 3
    assert (("tenant-alpha", node) not in app.state.aiops.det.seeded)     # forgotten ...
    send(c, A, pl(node=node, age=1, cpu=41, latency_ms=20, packet_loss=0.1))
    b = c.get(f"/api/aiops/baselines/{node}", headers=ta).json()
    assert b["cpu"]["warm"] and b["cpu"]["n"] >= 30                      # ... and re-learned from stored history
    assert any(e["action"] == "baselines_rebuilt" for e in c.get("/api/audit?limit=50", headers=ta).json())
    assert len(CLEAN) >= 30


def test_rebuild_baselines_is_tenant_scoped(saas):
    c, app, ta, login = saas
    warm(c)
    tb = login("beta-admin", "beta-demo-pass")
    assert c.post("/api/aiops/baselines/rebuild", headers=tb).json()["nodes"] == 0       # beta has no nodes here; alpha's baselines untouched
    assert ("tenant-alpha", N["db-01"]) in app.state.aiops.det.seeded
