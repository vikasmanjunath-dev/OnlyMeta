"""P6 multivariate anomalies: several metrics each a little off, together improbable (Mahalanobis distance, chi-square limit).
The detector in isolation (calibration, drift, broken correlation, no echo, level shift, seeding), then through the platform."""
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from saas.aiops.baseline import METRICS, Detector  # noqa: E402
from saas.aiops.multivar import KEYS, JointDetector, critical, describe_joint, invert  # noqa: E402
from test_p2_advanced import mk  # noqa: E402
from test_p3_aiops import N, TH, incs  # noqa: E402
from test_saas import A, B, pl, send  # noqa: E402

DET = Detector(TH)
SIG = DET.sigma_eff


def jd():
    return JointDetector(TH, SIG)


def vec(rnd, cpu=0.0, mem=0.0, lat=0.0, loss=0.0, bw=0.0, noise=True):
    g = (lambda s: rnd.gauss(0, s)) if noise else (lambda s: 0.0)
    return {"cpu": 40 + cpu + g(2), "mem": 55 + mem + g(2.75), "latency_ms": 30 + lat + g(5), "packet_loss": 0.1 + loss + abs(g(0.2)) * 0, "bandwidth_mbps": 120 + bw + g(10)}


def run(d, rnd, n, t0=0, uni=lambda m: (False, False), **shift):
    out = []
    for i in range(n):
        m = vec(rnd, **shift)
        raw, op = uni(m)
        out.append(d.observe("t", "n", m, t0 + 5 * i, raw, op))
    return out


# ---------------------------------------------------------------- the maths
def test_inverse_and_chi_square_limits():
    a = [[4.0, 1.0, 0.5], [1.0, 3.0, 0.2], [0.5, 0.2, 2.0]]
    inv = invert(a)
    prod = [[sum(a[i][k] * inv[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
    assert all(prod[i][j] == pytest.approx(1.0 if i == j else 0.0, abs=1e-9) for i in range(3) for j in range(3))
    assert invert([[1.0, 2.0], [2.0, 4.0]]) is None
    assert critical(0.001, 5) == 20.52 and critical(0.01, 4) == 13.28 and critical(0.123, 3) == 16.27


# ---------------------------------------------------------------- calibration
def test_quiet_on_calm_data_and_warms_up():
    d, rnd = jd(), random.Random(7)
    out = run(d, rnd, 3000)
    assert all(v is None for v in out[:40]) and out[41] is not None            # judges only once it has 40 clean samples
    assert not any(v and v["opened"] for v in out)
    assert sum(1 for v in out if v and v["raw"]) / 3000 < 0.005


def test_all_metrics_noisy_at_their_floor_is_calibrated():
    d, rnd = jd(), random.Random(11)
    n_raw, opened = 0, 0
    for i in range(4000):
        m = {"cpu": 40 + rnd.gauss(0, 2), "mem": 55 + rnd.gauss(0, 2.75), "latency_ms": 30 + rnd.gauss(0, 5), "packet_loss": 0.1 + rnd.gauss(0, 0.2), "bandwidth_mbps": 120 + rnd.gauss(0, 10)}
        v = d.observe("t", "n", m, 5 * i, False, False)
        if v:
            n_raw += v["raw"]
            opened += v["opened"]
    assert n_raw / 3960 < 0.004 and opened == 0                                # alpha = 0.001 per sample, and 3-of-4 confirmation on top


# ---------------------------------------------------------------- what it catches
def test_subtle_drift_trips_joint_but_no_single_metric():
    d, rnd, det = jd(), random.Random(3), Detector(TH)
    for i in range(80):
        m = vec(rnd)
        det.observe("t", "n", {"cpu": m["cpu"], "mem": m["mem"], "latency_ms": m["latency_ms"], "packet_loss": m["packet_loss"], "bandwidth_mbps": m["bandwidth_mbps"]}, 5 * i)
        d.observe("t", "n", m, 5 * i, False, False)
    first, uni_ever = None, False
    for i in range(80, 96):
        m = vec(rnd, cpu=2.0, mem=7.15, lat=13.0, loss=0.52, bw=26.0, noise=False)
        uv = det.observe("t", "n", m, 5 * i)
        uni_ever |= any(v["open"] for v in uv)
        v = d.observe("t", "n", m, 5 * i, any(x.get("raw") for x in uv), any(x["open"] for x in uv))
        if v["opened"] and first is None:
            first = (i - 80, v)
    assert first and first[0] <= 3                                              # confirmed within K samples of the drift starting
    assert not uni_ever and max(abs(z) for z in first[1]["contrib"].values()) < 3.0
    assert first[1]["onset_ts"] == 5 * 80 and "memory" in describe_joint(first[1])


def test_broken_correlation_is_caught():
    rnd = random.Random(5)
    d = jd()
    for i in range(150):                                                         # latency tracks cpu closely
        c = rnd.gauss(50, 10)
        d.observe("t", "n", {"cpu": c, "mem": 55.0, "latency_ms": 50 + (c - 50) + rnd.gauss(0, 1.5), "packet_loss": 0.1, "bandwidth_mbps": 120.0}, 5 * i, False, False)
    v = d.observe("t", "n", {"cpu": 65.0, "mem": 55.0, "latency_ms": 35.0, "packet_loss": 0.1, "bandwidth_mbps": 120.0}, 900, False, False)
    assert abs(v["contrib"]["cpu"]) < 2 and abs(v["contrib"]["latency_ms"]) < 2 and v["raw"] and v["d2"] > 3 * v["threshold_d2"]


def test_a_single_metric_anomaly_is_not_echoed_and_not_learned():
    d, rnd = jd(), random.Random(9)
    run(d, rnd, 60)
    n0 = d.baseline("t", "n")["n"]
    out = run(d, rnd, 10, t0=400, uni=lambda m: (True, True), cpu=40.0)           # cpu 80 %: the univariate detector owns this
    assert not any(v["opened"] for v in out if v) and d.baseline("t", "n")["n"] == n0


def test_opens_clears_and_marks_level_shift():
    d, rnd = jd(), random.Random(13)
    run(d, rnd, 60)
    out = run(d, rnd, 6, t0=400, mem=6.6, lat=12.0, loss=0.0, bw=26.0, cpu=2.0, noise=False) if False else None
    shift = dict(cpu=2.0, mem=6.6, lat=12.0, bw=26.0)
    out = [d.observe("t", "n", {**vec(rnd, **shift, noise=False), "packet_loss": 0.62}, 400 + 5 * i, False, False) for i in range(6)]
    assert [bool(v["opened"]) for v in out].count(True) == 1 and out[-1]["open"] and out[-1]["peak_z"] > 3
    calm = run(d, rnd, 4, t0=500)
    assert any(v["closed"] and not v["level_shift"] for v in calm) and not calm[-1]["open"]
    d2 = jd()
    run(d2, rnd, 60)
    seen = [d2.observe("t", "n", {**vec(rnd, **shift, noise=False), "packet_loss": 0.62}, 400 + 5 * i, False, False) for i in range(60)]
    assert any(v["level_shift"] for v in seen) and d2.baseline("t", "n")["level_shifts"] == 1


def test_seed_trims_an_old_fault_and_is_deterministic():
    rnd = random.Random(2)
    rows = [{**vec(rnd), "ts": i} for i in range(100)] + [{**vec(rnd, cpu=45, mem=30, lat=60, bw=-80, noise=False), "ts": 100 + i} for i in range(10)]
    a, b = jd(), jd()
    a.seed("t", "n", rows)
    b.seed("t", "n", rows)
    assert a.baseline("t", "n")["n"] == 100 and a.score(a._st("t", "n"), [40, 55, 30, 0.1, 120])[0] == b.score(b._st("t", "n"), [40, 55, 30, 0.1, 120])[0]


def test_disabled_is_silent():
    th = {**TH, "aiops": {**TH["aiops"], "joint": {"enabled": False}}}
    d = JointDetector(th, SIG)
    assert all(v is None for v in run(d, random.Random(1), 100))


# ---------------------------------------------------------------- the platform
def calm(c, node, ages, i0=0):
    for i, a in enumerate(ages):
        send(c, A, pl(node=N[node], age=a, cpu=40 + ((i + i0) % 3) * 0.7, latency_ms=20 + ((i + i0) % 2), packet_loss=0.1))


def drift(c, node, ages):
    for a in ages:
        send(c, A, pl(node=N[node], age=a, cpu=42.0, mem=62.2, latency_ms=33.0, packet_loss=0.62, bandwidth_mbps=126.0))


@pytest.fixture
def env(tmp_path):
    c, app, login = mk(tmp_path, rate_limit_rps=100000)
    return c, app, login("alpha-admin", "alpha-demo-pass"), login


def test_platform_raises_one_joint_anomaly_and_an_incident(env):
    c, app, h, login = env
    for n in ("app-01", "db-01", "net-01"):
        calm(c, n, list(range(700, 400, -5)))
    assert all(v["warm"] for v in c.get("/api/aiops/joint", headers=h).json().values())
    drift(c, "db-01", list(range(400, 370, -5)))
    an = c.get("/api/aiops/anomalies", headers=h, params={"state": "open"}).json()
    assert [(a["label"], a["metric"], a["kind"]) for a in an] == [("db-01", "joint", "multivariate")] and an[0]["metric_label"] == "metric pattern (joint)"
    (inc,) = incs(c, h, status="open")
    assert inc["root_label"] == "db-01" and "unusual combination" in inc["title"] and "no single metric out of range" in inc["summary"]
    calm(c, "db-01", list(range(370, 340, -5)))
    assert c.get("/api/aiops/anomalies", headers=h, params={"state": "open"}).json() == []
    closed = c.get("/api/aiops/anomalies", headers=h, params={"state": "closed"}).json()
    assert closed[0]["metric"] == "joint" and closed[0]["state"] == "closed"


def test_joint_state_is_per_tenant_and_rebuild_resets_it(env):
    c, app, h, login = env
    calm(c, "db-01", list(range(700, 400, -5)))
    assert c.get("/api/aiops/joint", headers=h).json()[N["db-01"]]["warm"]
    hb = login("beta-admin", "beta-demo-pass")
    assert c.get("/api/aiops/joint", headers=hb).json() == {}
    assert c.post("/api/aiops/baselines/rebuild", headers=h).status_code == 200
    assert app.state.aiops.joint.baseline("tenant-alpha", N["db-01"])["n"] == 0


def test_drift_scenario_shape():
    from collector import scenarios
    ev = scenarios.build("drift", ticks=4)
    assert "drift" in scenarios.EVENT_SCENARIOS and len(ev) == 4 and {e["node"] for e in ev} == {"db-01"}


def test_calm_source_drift_is_live_in_order_then_recovers():
    import asyncio
    from collector.scenarios import DRIFT
    from collector.sources import CalmSource

    async def take(n):
        src, stop, out = CalmSource(0.001), asyncio.Event(), []
        src.inject("db-01", 2, DRIFT)
        async for e in src.aevents(stop):
            out.append(e)
            if len(out) >= n:
                stop.set()
                break
        return out
    ev = asyncio.run(take(12))                                                  # 4 ticks x 3 nodes
    db = [e for e in ev if e["node"] == "db-01"]
    assert [round(e["metrics"]["mem"]) for e in db] == [62, 62, 55, 55] and db[0]["metrics"]["cpu"] == 42.0
    assert all(round(e["metrics"]["mem"]) == 55 for e in ev if e["node"] != "db-01")


def test_drift_endpoint_is_live_when_a_calm_feed_runs_and_backdated_otherwise(tmp_path):
    from fastapi.testclient import TestClient
    from collector.config import load_settings
    from collector.main import create_app
    from collector.sources import CalmSource
    s = load_settings(db_path=str(tmp_path / "c.db"), rebase=False, loop=False)
    app = create_app(s)
    c, pipe = TestClient(app), app.state.pipe
    h = {"X-Chaos": "1", "Origin": "http://127.0.0.1:8000"}
    r = c.post("/api/chaos/scenario/drift?ticks=4", headers=h).json()
    assert r["payloads_emitted"] >= 1 and "mode" not in r                           # no calm feed: back-dated events
    src = CalmSource()
    pipe.sources.append(src)
    r = c.post("/api/chaos/scenario/drift?ticks=4", headers=h).json()
    assert r["mode"] == "live" and src.drift["db-01"][0] == 4
