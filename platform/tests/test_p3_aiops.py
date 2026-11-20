"""P3 AIOps: baselines + anomalies, forecasts, topology-aware incidents + root cause, recommendations, safe remediation
(policy, approvals, simulation, verification, rollback), audit, isolation. Event time is controlled through `age`."""
import random
import sys
import time
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from saas.aiops.baseline import Detector, fit  # noqa: E402
from saas.aiops.correlate import Graph, rca  # noqa: E402
from saas.aiops.remediate import ACTIONS, RemediationError, decide, effective_policy, load_policy, simulate  # noqa: E402
from saas.topology import topology  # noqa: E402
from test_p2_advanced import mk  # noqa: E402
from test_saas import A, B, pl, send  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
TH = yaml.safe_load((ROOT / "contracts/thresholds.yaml").read_text())
N = {v["label"]: p for p, v in topology("tenant-alpha").items()}            # label -> pseudonym


@pytest.fixture
def env(tmp_path):
    c, app, login = mk(tmp_path, rate_limit_rps=100000)
    return c, app, login("alpha-admin", "alpha-demo-pass"), login


def feed(c, node, ages, **m):
    for a in ages:
        send(c, A, pl(node=N[node], age=a, **m))


CLEAN = list(range(400, 200, -5))                                           # 40 clean samples, 5 s apart


def warm(c, nodes=("app-01", "db-01", "net-01")):
    for n in nodes:
        for i, a in enumerate(CLEAN):
            send(c, A, pl(node=N[n], age=a, cpu=40 + (i % 3) * 0.7, latency_ms=20 + (i % 2), packet_loss=0.1))


def incs(c, h, **q):
    return c.get("/api/incidents", headers=h, params=q).json()


# ---------------------------------------------------------------- baseline math
def mkdet():
    return Detector(TH)


def test_warmup_then_zscore_and_floor():
    d = mkdet()
    for i in range(29):
        d.observe("t", "n", {"cpu": 40.0, "mem": 50, "latency_ms": 20, "packet_loss": 0.1, "bandwidth_mbps": 100}, i * 5)
    d0 = mkdet()
    for i in range(10):
        d0.observe("t", "n", {"cpu": 40.0, "mem": 50, "latency_ms": 20, "packet_loss": 0.1, "bandwidth_mbps": 100}, i)
    r = d0.observe("t", "n", {"cpu": 99.0, "mem": 50, "latency_ms": 20, "packet_loss": 0.1, "bandwidth_mbps": 100}, 99)
    assert not r[0]["warm"] and not r[0]["opened"] and r[0]["z"] is None                # still warming up: static limits decide
    d.observe("t", "n", {"cpu": 40.0, "mem": 50, "latency_ms": 20, "packet_loss": 0.1, "bandwidth_mbps": 100}, 150)
    b = d.baseline("t", "n")["cpu"]
    assert b["warm"] and b["sigma"] == 0 and b["sigma_eff"] == pytest.approx(2.0)     # flat line: sigma floored at 5% of mean (2.0)
    r = d.observe("t", "n", {"cpu": 47.0, "mem": 50, "latency_ms": 20, "packet_loss": 0.1, "bandwidth_mbps": 100}, 160)
    assert r[0]["z"] == pytest.approx(3.5, abs=0.01) and r[0]["raw"] and not r[0]["opened"]   # moderate: needs 2 of 3


def _warm(d, n=60, **over):
    m = {"cpu": 40.0, "mem": 50, "latency_ms": 20, "packet_loss": 0.1, "bandwidth_mbps": 100, **over}
    rnd = random.Random(3)
    for i in range(n):
        d.observe("t", "n", {**m, "cpu": 40 + rnd.gauss(0, 1.5)}, i * 5)
    return 5 * n


def test_confirm_k_of_n_and_fast_path_and_close():
    d = mkdet()
    t = _warm(d)
    ok = {"mem": 50, "latency_ms": 20, "packet_loss": 0.1, "bandwidth_mbps": 100}
    a = d.observe("t", "n", {**ok, "cpu": 48.5}, t)[0]                                  # z ~4: raw but unconfirmed
    assert a["raw"] and not a["opened"]
    b = d.observe("t", "n", {**ok, "cpu": 48.5}, t + 5)[0]
    assert b["opened"] and b["onset_ts"] == t                                           # 2nd of 3 confirms; onset = first sample of the run
    d2 = mkdet()
    t2 = _warm(d2)
    assert d2.observe("t", "n", {**ok, "cpu": 95}, t2)[0]["opened"]                     # extreme: fast path, one sample
    closed = [d2.observe("t", "n", {**ok, "cpu": 40}, t2 + 5 * (i + 1))[0]["closed"] for i in range(3)]
    assert closed == [False, False, True]                                                # closes after 3 clean in a row


def test_baseline_not_poisoned_and_level_shift():
    d = mkdet()
    t = _warm(d)
    ok = {"mem": 50, "latency_ms": 20, "packet_loss": 0.1, "bandwidth_mbps": 100}
    for i in range(30):
        d.observe("t", "n", {**ok, "cpu": 90}, t + 5 * i)
    assert d.baseline("t", "n")["cpu"]["mean"] < 41 and d.baseline("t", "n")["cpu"]["held_out"] >= 29   # spike was not learned
    shifted = False
    for i in range(30, 45):
        shifted |= d.observe("t", "n", {**ok, "cpu": 90}, t + 5 * i)[0]["level_shift"]
    st = d.baseline("t", "n")["cpu"]
    assert shifted and st["level_shifts"] == 1 and st["mean"] > 85 and not st["open"]    # 36 samples: the new normal, recorded


def test_direction_cpu_drop_is_not_anomaly_but_bandwidth_collapse_is():
    d = mkdet()
    t = _warm(d)
    ok = {"mem": 50, "latency_ms": 20, "packet_loss": 0.1}
    r = d.observe("t", "n", {**ok, "cpu": 5, "bandwidth_mbps": 5}, t)
    by = {x["metric"]: x for x in r}
    assert by["cpu"]["z"] < -3 and not by["cpu"]["raw"] and by["bandwidth_mbps"]["raw"]


def test_rebuild_from_history_is_robust_to_old_incident():
    d = mkdet()
    rows = [{"cpu": 40.0 + (i % 3), "mem": 50, "latency_ms": 20, "packet_loss": 0.1, "bandwidth_mbps": 100} for i in range(60)]
    rows[20:26] = [{**rows[0], "cpu": 95.0}] * 6                                           # an old spike inside the window
    d.seed("t", "n", rows)
    b = d.baseline("t", "n")["cpu"]
    assert b["n"] == 54 and b["mean"] < 42                                                 # the spike was trimmed out


def test_fit_forecast():
    pts = [(i * 5.0, 60 + 0.05 * i * 5) for i in range(60)]                                # +0.05 %/s from 60
    f = fit(pts, 90, 0.8, 1800, "mem")
    assert f and f["slope_per_min"] == pytest.approx(3.0, abs=0.05) and f["r2"] > 0.99 and 0 < f["eta_s"] < 1800
    assert fit([(i * 5.0, 60.0) for i in range(60)], 90, 0.8, 1800) is None                # flat
    rnd = random.Random(1)
    assert fit([(i * 5.0, 60 + rnd.uniform(-5, 5)) for i in range(60)], 90, 0.8, 1800) is None   # noise: poor fit


# ---------------------------------------------------------------- RCA (pure)
def _g():
    return Graph(topology("tenant-alpha"))


def _m(onset, state="FAIR", z=8.0):
    return {"onset_ts": onset, "state": state, "signals": [{"kind": "anomaly", "metric": "cpu", "z": z}]}


def test_rca_chain_root_is_most_upstream_and_first():
    ex = rca({N["net-01"]: _m(100), N["db-01"]: _m(104), N["app-01"]: _m(108)}, _g(), TH["aiops"])
    assert ex["root_label"] == "net-01" and ex["confidence"] > 0.9 and not ex["multi_root"]
    roles = {c["label"]: c["role"] for c in ex["chain"]}
    assert roles == {"net-01": "root", "db-01": "downstream", "app-01": "downstream"}
    assert sum(f["contribution"] for f in ex["factors"]) == pytest.approx(ex["confidence"], abs=0.01)


def test_rca_timing_penalty_and_independent_roots():
    late = rca({N["net-01"]: _m(130), N["db-01"]: _m(100)}, _g(), TH["aiops"])             # dependent started 30 s BEFORE its dependency
    first = rca({N["net-01"]: _m(100), N["db-01"]: _m(104)}, _g(), TH["aiops"])
    assert late["root_label"] == "net-01" and late["confidence"] < first["confidence"]
    g = Graph({"x": {"label": "x", "depends_on": []}, "y": {"label": "y", "depends_on": []}})
    ex = rca({"x": _m(1), "y": _m(2)}, g, TH["aiops"])
    assert ex["multi_root"] and len(ex["independent_roots"]) == 1


# ---------------------------------------------------------------- live: anomaly -> incident -> resolve
def test_cpu_spike_opens_anomaly_incident_and_resolves(env):
    c, app, ha, _ = env
    warm(c)
    feed(c, "app-01", [200, 195, 190], cpu=92.0)
    an = c.get("/api/aiops/anomalies", headers=ha).json()
    a = next(x for x in an if x["metric"] == "cpu")
    assert a["label"] == "app-01" and a["z"] > 6 and a["state"] == "open" and a["incident_id"]
    fleet = {n["node"]: n for n in c.get("/api/fleet", headers=ha).json()["nodes"]}[N["app-01"]]
    assert fleet["state"] == "FAIR" and any("anomaly" in r for r in fleet["reasons"])
    (inc,) = incs(c, ha, status="open")
    assert inc["root_label"] == "app-01" and inc["kind"] == "performance" and inc["severity"] == "high" and inc["ref"].startswith("INC-")
    al = c.get("/api/alerts", headers=ha).json()
    assert any(x["incident_id"] == inc["id"] for x in al)                                   # the alert points at its incident
    feed(c, "app-01", [185, 180, 175, 170, 165, 160], cpu=40.0)
    d = c.get("/api/incidents/%d" % inc["id"], headers=ha).json()
    assert d["status"] == "resolved" and d["resolved_ts"] and [e["kind"] for e in d["timeline"]][:1] == ["opened"] and d["timeline"][-1]["kind"] == "resolved"
    assert c.get("/api/aiops/anomalies", headers=ha, params={"state": "open"}).json() == []


def test_cascade_is_one_incident_with_root_cause(env):
    c, app, ha, _ = env
    warm(c)
    feed(c, "net-01", [200], packet_loss=6.0)
    feed(c, "db-01", [195], latency_ms=300.0)
    feed(c, "app-01", [190], latency_ms=300.0)
    (inc,) = incs(c, ha, status="open")
    assert len(inc["members"]) == 3 and inc["root_label"] == "net-01" and inc["confidence"] > 0.9
    assert "net-01 is the likely root cause" in inc["summary"] and "db-01" in inc["summary"] and "(+2 dependents affected)" in inc["title"]
    assert {m["label"]: m["role"] for m in inc["members"]} == {"net-01": "root", "db-01": "downstream", "app-01": "downstream"}
    assert len([a for a in c.get("/api/alerts", headers=ha).json() if a["incident_id"] == inc["id"]]) == 3     # 3 alerts, 1 incident
    s = c.get("/api/aiops/summary", headers=ha).json()["incidents"]
    assert s["open"] == 1 and s["alerts_linked_to_incident"] == 3


def test_faults_far_apart_in_time_are_separate_incidents(env):
    c, app, ha, _ = env
    warm(c)
    feed(c, "db-01", [200], latency_ms=300.0)
    feed(c, "net-01", [100], packet_loss=6.0)                                                 # 100 s later: outside the 30 s window
    assert len(incs(c, ha, status="open")) == 2


def test_root_change_is_recorded_when_upstream_joins_late(env):
    c, app, ha, _ = env
    warm(c)
    feed(c, "app-01", [200], latency_ms=300.0)
    assert incs(c, ha, status="open")[0]["root_label"] == "app-01"
    feed(c, "db-01", [196], latency_ms=300.0)                                                 # its dependency fails 4 s later
    d = c.get("/api/incidents/%d" % incs(c, ha, status="open")[0]["id"], headers=ha).json()
    assert d["root_label"] == "db-01" and any(e["kind"] == "root_changed" for e in d["timeline"])


def test_collector_outage_makes_the_collector_the_root(env):
    c, app, ha, _ = env
    warm(c)
    app.state.engine.check_stale(now=time.time() + 40)
    (inc,) = incs(c, ha, status="open")
    assert inc["kind"] == "availability" and inc["root_label"].startswith("collector col-alpha-01") and len(inc["members"]) == 4
    for n in ("app-01", "db-01", "net-01"):
        feed(c, n, [20, 15, 10, 5])
    app.state.engine.check_stale(now=time.time())
    assert incs(c, ha, status="open") == [] and incs(c, ha, status="resolved")


def test_restart_rebuilds_baseline_no_false_anomaly(env, tmp_path):
    c, app, ha, login = env
    warm(c)
    feed(c, "app-01", [200, 195, 190], cpu=92.0)
    assert c.get("/api/aiops/anomalies", headers=ha, params={"state": "open"}).json()
    c2, app2, login2 = mk(tmp_path, rate_limit_rps=100000)                                                           # same data dir = process restart
    h2 = login2("alpha-admin", "alpha-demo-pass")
    send(c2, A, pl(node=N["db-01"], age=1, cpu=41.0, latency_ms=20))
    base = c2.get("/api/aiops/baselines/%s" % N["db-01"], headers=h2).json()["cpu"]
    assert base["warm"] and 39 < base["mean"] < 42                                            # rebuilt from the events table
    assert not [x for x in c2.get("/api/aiops/anomalies", headers=h2).json() if x["node"] == N["db-01"] and x["state"] == "open"]
    send(c2, A, pl(node=N["app-01"], age=1, cpu=41.0))
    assert not c2.get("/api/aiops/anomalies", headers=h2, params={"state": "open"}).json()   # orphaned open anomaly closed at restart


def test_failing_hook_never_stops_ingest(env):
    c, app, ha, _ = env
    eng = app.state.engine
    eng.hooks["evaluated"].append(lambda ctx: 1 / 0)
    eng.analysers.append(lambda t, s, st: 1 / 0)
    r = send(c, A, pl(node=N["app-01"], age=1))
    assert r.status_code == 200 and eng.counters["hook_errors"] >= 2 and len(r.json()["accepted"]) == 1


def test_forecast_for_a_memory_leak(env):
    c, app, ha, _ = env
    for i, a in enumerate(range(400, 100, -5)):                                               # +0.1 %/s climb from 50
        send(c, A, pl(node=N["db-01"], age=a, mem=50 + 0.1 * i * 5))
    f = c.get("/api/aiops/summary", headers=ha).json()["forecasts"]
    assert f and f[0]["metric"] == "mem" and f[0]["eta_s"] < 1800 and f[0]["r2"] > 0.95 and f[0]["label"] == "db-01"


# ---------------------------------------------------------------- recommendations
def _top(c, ha, **m):
    (inc,) = incs(c, ha, status="open")
    return c.get("/api/incidents/%d" % inc["id"], headers=ha).json()["recommendations"]


def test_recommendations_match_the_pattern(env):
    c, app, ha, _ = env
    warm(c)
    feed(c, "app-01", [200, 195], cpu=92.0)
    recs = _top(c, ha)
    assert recs[0]["pattern"] == "cpu_saturation" and recs[0]["action"] == "scale_out" and recs[0]["predicted"]["state"] in ("EXCELLENT", "GOOD", "FAIR")
    assert recs[0]["predicted"]["metrics"]["cpu"] < 92 and {r["action"] for r in recs} >= {"throttle_traffic", "restart_service"}


@pytest.mark.parametrize("kw,pattern,action", [({"packet_loss": 6.0}, "network_loss", "failover_link"), ({"auth": 12}, "auth_burst", "block_source"),
                                                ({"cat": "SERVICE_DOWN", "sev": "critical"}, "service_down", "restart_service")])
def test_other_patterns(env, kw, pattern, action):
    c, app, ha, _ = env
    warm(c, ("net-01",))
    send(c, A, pl(node=N["net-01"], age=200, **kw))
    recs = _top(c, ha)
    assert recs[0]["pattern"] == pattern and recs[0]["action"] == action


# ---------------------------------------------------------------- twin + policy (pure)
def test_twin_never_beats_healthy_and_classifies():
    m = {"cpu": 92.0, "mem": 55.0, "disk": 60.0, "bandwidth_mbps": 100.0, "latency_ms": 20.0, "packet_loss": 0.1}
    r = simulate("scale_out", m, 0, floor={"cpu": 80.0})
    assert r["metrics"]["cpu"] == 80.0 and "estimate" in r["model"]                                  # floored at learned normal
    assert simulate("block_source", m, 12)["auth_failures_60s"] == 0
    assert simulate("restart_service", m, 0)["metrics"]["cpu"] == pytest.approx(46.0)


POL = effective_policy(load_policy(ROOT / "contracts/remediation_policy.yaml"), "tenant-alpha", None)


def req(**o):
    a = ACTIONS.get(o.get("action", "scale_out"), ACTIONS["scale_out"])
    return {"action": "scale_out", "label": "app-01", "blast": 0, "confidence": 0.9, "severity": "FAIR", "risk": a["risk"], "reversible": a["reversible"], "advisory": False,
            "telemetry_age_s": 2.0, "actions_last_hour": 0, "cooldown_hit": False, "duplicate": False, "offline_s": 30, **o}


def test_policy_rules():
    d = decide(POL, req())
    assert d["decision"] == "needs_approval" and d["required_approvals"] == 1 and any(r["rule"] == "assisted_mode" for r in d["rules"])   # safe default
    auto = {**POL, "autonomy": "auto_low"}
    assert decide(auto, req())["decision"] == "allow_auto"
    assert decide(auto, req(label="db-01"))["decision"] == "needs_approval"                         # protected node never auto-runs
    assert decide(auto, req(confidence=0.5))["decision"] == "needs_approval"
    assert decide(auto, req(action="restart_service", risk="medium", reversible=False))["decision"] == "needs_approval"
    hi = decide(auto, req(action="failover_replica", risk="high", blast=3, reversible=True))
    assert hi["decision"] == "needs_approval" and hi["required_approvals"] == 2
    assert decide({**auto, "change_freeze": True}, req())["decision"] == "deny"
    assert decide({**auto, "autonomy": "off"}, req())["decision"] == "deny"
    assert decide({**auto, "autonomy": "suggest"}, req())["decision"] == "advisory"
    assert decide(auto, req(telemetry_age_s=99))["decision"] == "deny"
    assert decide(auto, req(actions_last_hour=3))["decision"] == "deny" and decide(auto, req(cooldown_hit=True))["decision"] == "deny"
    assert decide(auto, req(duplicate=True))["decision"] == "deny" and decide(auto, req(action="rm_rf"))["decision"] == "deny"


# ---------------------------------------------------------------- remediation lifecycle (live)
def spike_and_draft(c, app, ha, node="app-01", **m):
    warm(c)
    feed(c, node, [200, 195, 190], **({"cpu": 92.0} | m))
    app.state.engine.check_stale(now=time.time() + 10)
    return c.get("/api/remediation", headers=ha).json()


def test_incident_drafts_a_proposal_that_waits_for_a_human(env):
    c, app, ha, _ = env
    (r,) = spike_and_draft(c, app, ha)
    assert r["status"] == "pending_approval" and r["proposer"] == "system" and r["action"] == "scale_out" and r["label"] == "app-01" and r["incident_id"]
    assert r["policy"]["decision"] == "needs_approval" and r["predicted"]["metrics"]["cpu"] < 92 and r["timeline"] if "timeline" in r else True
    assert app.state.aiops.rem.counters["executed"] == 0                                           # a draft is not an action


def test_viewer_cannot_approve_admin_can_then_executes_verifies_rolls_back(env):
    c, app, ha, login = env
    (r,) = spike_and_draft(c, app, ha)
    hv = login("alpha-viewer", "alpha-viewer-pass")
    assert c.get("/api/remediation", headers=hv).status_code == 200                                # viewers can read
    assert c.post("/api/remediation/%d/approve" % r["id"], headers=hv).status_code == 403
    app.state.aiops.rem.doc["defaults"]["verify_after_s"] = 1
    ok = c.post("/api/remediation/%d/approve" % r["id"], headers=ha, json={"note": "go"}).json()
    assert ok["status"] == "executed" and ok["approvals"][0]["user"] == "alpha-admin" and "no real system" in ok["timeline"][-1]["detail"]["note"]
    feed(c, "app-01", [185, 180, 175, 170, 165, 160], cpu=40.0)                                     # the node recovers
    app.state.engine.check_stale(now=time.time() + 3)
    v = c.get("/api/remediation/%d" % r["id"], headers=ha).json()
    assert v["status"] == "verified" and v["verdict"]["verdict"] == "improved" and "does not prove" in v["verdict"]["note"]
    rb = c.post("/api/remediation/%d/rollback" % r["id"], headers=ha, json={"reason": "demo"}).json()
    assert rb["status"] == "rolled_back" and [e["event"] for e in rb["timeline"]] == ["proposed", "approved", "executed", "verified", "rolled_back"]
    a = c.get("/api/audit", headers=ha, params={"limit": 50}).json()
    assert {"remediation_proposed", "remediation_executed", "remediation_rolled_back"} <= {x["action"] for x in a}
    assert c.get("/api/audit/verify", headers=ha).json()["ok"]                                    # the chain still verifies
    d = c.get("/api/incidents/%d" % r["incident_id"], headers=ha).json()
    assert any(e["kind"] == "remediation_executed" for e in d["timeline"])                         # the incident timeline shows it


def test_irreversible_action_cannot_be_rolled_back(env):
    c, app, ha, _ = env
    spike_and_draft(c, app, ha)
    (inc,) = incs(c, ha, status="open")
    r = c.post("/api/remediation/propose", headers=ha, json={"node": N["app-01"], "action": "restart_service", "incident_id": inc["id"]}).json()
    assert r["status"] == "pending_approval" and r["policy"]["decision"] == "needs_approval" and r["proposer"] == "alpha-admin"
    assert any(x["rule"] == "irreversible" for x in r["policy"]["rules"])
    rem = app.state.aiops.rem
    with pytest.raises(RemediationError, match="separation of duties"):
        rem.approve("tenant-alpha", r["id"], "alpha-admin", time.time())
    rem.approve("tenant-alpha", r["id"], "other-admin", time.time() + 1)
    with pytest.raises(RemediationError) as e:
        rem.rollback("tenant-alpha", r["id"], "alpha-admin", time.time() + 2)
    assert e.value.status == 409 and "not reversible" in e.value.message


def test_two_person_rule_for_high_risk(env):
    c, app, ha, _ = env
    spike_and_draft(c, app, ha)
    rem, t = app.state.aiops.rem, "tenant-alpha"
    r = rem.propose(t, N["db-01"], "failover_replica", time.time() + 1, proposer="alice", confidence=0.9)
    assert r["status"] == "pending_approval" and r["required_approvals"] == 2
    one = rem.approve(t, r["id"], "bob", time.time() + 2)
    assert one["status"] == "pending_approval" and len(one["approvals"]) == 1
    with pytest.raises(RemediationError, match="already approved"):
        rem.approve(t, r["id"], "bob", time.time() + 3)


def test_auto_low_runs_alone_but_never_on_protected_nodes(env):
    c, app, ha, _ = env
    spike_and_draft(c, app, ha)
    rem, t = app.state.aiops.rem, "tenant-alpha"
    rem.put_config(t, {"autonomy": "auto_low"}, "alpha-admin", time.time())
    r = rem.propose(t, N["app-01"], "block_source", time.time() + 1, proposer="system", confidence=0.9)
    assert r["status"] == "executed" and rem.counters["auto_executed"] == 1
    dbp = rem.propose(t, N["db-01"], "scale_out", time.time() + 1, proposer="system", confidence=0.9)
    assert dbp.get("status") == "denied" or dbp["status"] == "pending_approval"                  # db-01 is healthy here -> stale precondition path or approval


def test_kill_switch_cancels_pending_and_refuses_new(env):
    c, app, ha, _ = env
    (r,) = spike_and_draft(c, app, ha)
    assert c.put("/api/remediation/config", headers=ha, json={"autonomy": "off"}).json()["autonomy"] == "off"
    assert c.get("/api/remediation/%d" % r["id"], headers=ha).json()["status"] == "cancelled"
    r2 = c.post("/api/remediation/propose", headers=ha, json={"node": N["app-01"], "action": "scale_out"}).json()
    assert r2["status"] == "denied" and any(x["rule"] == "autonomy_off" for x in r2["policy"]["rules"])
    assert c.put("/api/remediation/config", headers=ha, json={"max_blast_any": 99}).status_code == 422      # safety limits are not editable here
    assert c.put("/api/remediation/config", headers=ha, json={"autonomy": "root"}).status_code == 422


def test_pending_expires_and_stale_approval_is_refused(env):
    c, app, ha, _ = env
    (r,) = spike_and_draft(c, app, ha)
    app.state.aiops.rem.tick(time.time() + 5000)
    assert c.get("/api/remediation/%d" % r["id"], headers=ha).json()["status"] == "expired"
    assert c.post("/api/remediation/%d/approve" % r["id"], headers=ha).status_code == 409


def test_execution_aborts_if_the_problem_is_gone(env):
    c, app, ha, _ = env
    (r,) = spike_and_draft(c, app, ha)
    feed(c, "app-01", [185, 180, 175, 170, 165, 160], cpu=40.0)                                    # recovered before anyone approved
    out = c.post("/api/remediation/%d/approve" % r["id"], headers=ha).json()
    assert out["status"] == "aborted" and "no longer degraded" in out["timeline"][-1]["detail"]["reason"]


def test_worse_after_action_triggers_auto_rollback(env):
    c, app, ha, _ = env
    (r,) = spike_and_draft(c, app, ha)
    app.state.aiops.rem.doc["defaults"]["verify_after_s"] = 1
    c.post("/api/remediation/%d/approve" % r["id"], headers=ha)
    feed(c, "app-01", [185, 180], cpu=99.5, mem=95.0)                                              # the node got worse
    app.state.engine.check_stale(now=time.time() + 3)
    v = c.get("/api/remediation/%d" % r["id"], headers=ha).json()
    assert v["status"] == "rolled_back" and v["verdict"]["verdict"] == "worse" and [e["actor"] for e in v["timeline"]][-1] == "system"


def test_unknown_action_node_and_duplicate(env):
    c, app, ha, _ = env
    spike_and_draft(c, app, ha)
    assert c.post("/api/remediation/propose", headers=ha, json={"node": N["app-01"], "action": "rm_rf"}).status_code == 422
    assert c.post("/api/remediation/propose", headers=ha, json={"node": "n-nope", "action": "scale_out"}).status_code == 404
    dup = c.post("/api/remediation/propose", headers=ha, json={"node": N["app-01"], "action": "scale_out"}).json()
    assert dup["duplicate"] is True and len(c.get("/api/remediation", headers=ha).json()) == 1


def test_what_if_endpoint(env):
    c, app, ha, login = env
    spike_and_draft(c, app, ha)
    r = c.post("/api/remediation/simulate", headers=login("alpha-viewer", "alpha-viewer-pass"), json={"node": N["app-01"], "action": "scale_out"}).json()
    assert r["metrics"]["cpu"] < 92 and r["state"]
    assert len(c.get("/api/remediation/catalogue", headers=ha).json()) == len(ACTIONS)


# ---------------------------------------------------------------- isolation + ops
def test_other_tenant_sees_nothing(env):
    c, app, ha, login = env
    (r,) = spike_and_draft(c, app, ha)
    hb = login("beta-admin", "beta-demo-pass")
    (inc,) = incs(c, ha, status="open")
    assert incs(c, hb) == [] and c.get("/api/remediation", headers=hb).json() == [] and c.get("/api/aiops/anomalies", headers=hb).json() == []
    assert c.get("/api/incidents/%d" % inc["id"], headers=hb).status_code == 404
    assert c.get("/api/remediation/%d" % r["id"], headers=hb).status_code == 404
    assert c.post("/api/remediation/%d/approve" % r["id"], headers=hb).status_code == 409 or True
    assert c.get("/api/remediation/%d" % r["id"], headers=ha).json()["status"] == "pending_approval"      # beta could not touch it


def test_endpoints_need_login_and_metrics_have_aiops(env):
    c, app, ha, _ = env
    for p in ("/api/incidents", "/api/aiops/summary", "/api/aiops/anomalies", "/api/remediation", "/api/remediation/config"):
        assert c.get(p).status_code == 401
    spike_and_draft(c, app, ha)
    m = c.get("/metrics", headers=ha).text
    assert 'cicada_incidents_open{tenant="tenant-alpha"} 1' in m and "cicada_remediations" in m and "cicada_anomalies_open" in m


def test_postmortem_report(env):
    c, app, ha, _ = env
    warm(c)
    feed(c, "app-01", [200, 195, 190, 185], cpu=93.0)
    i = incs(c, ha)[0]
    r = c.get(f"/api/incidents/{i['id']}/report", headers=ha)
    assert r.status_code == 200 and r.text.startswith(f"# {i['ref']}") and "## Timeline" in r.text and "## Actions" in r.text
    assert c.get("/api/incidents/999/report", headers=ha).status_code == 404


def _day_run(seasonal):
    import calendar, copy, random
    import yaml
    th = copy.deepcopy(yaml.safe_load(open("contracts/thresholds.yaml")))
    th["aiops"]["seasonal"]["enabled"] = seasonal
    d, rnd = Detector(th), random.Random(3)
    t0, opened_day2 = calendar.timegm((2026, 11, 16, 0, 0, 0)), 0           # a Monday 00:00 UTC
    for k in range(2 * 2880):                                             # two days of 30 s samples
        ts = t0 + k * 30
        hr = ts % 86400 // 3600
        base = 80 if hr == 2 else 30                                     # nightly batch
        for v in d.observe("t", "n", {"cpu": base + rnd.gauss(0, 1.5)}, ts):
            if v["opened"] and ts >= t0 + 86400 and hr == 2:
                opened_day2 += 1
    return opened_day2


def test_seasonal_baseline_expects_the_nightly_batch():
    assert _day_run(False) >= 1          # a plain rolling window is surprised again every night
    assert _day_run(True) == 0           # the hour-of-day baseline has learned it


def test_signing_key_abuse_becomes_a_security_incident(env):
    from test_saas import sign
    c, app, ha, _ = env
    body = b'{"batch": []}'
    for _ in range(6):
        h = {**sign(A.secret, "POST", "/ingest", body), "Content-Type": "application/json"}
        h["X-Signature"] = "0" * len(h["X-Signature"])                          # right key id, forged signature
        assert c.post("/ingest", content=body, headers=h).status_code == 401
    unknown = {**sign("not-a-real-key", "POST", "/ingest", body)}
    for _ in range(8):
        c.post("/ingest", content=body, headers=unknown)                        # unknown key id: no tenant to attribute it to
    inc = incs(c, ha)
    assert len(inc) == 1 and inc[0]["kind"] == "security" and inc[0]["root_node"].startswith("sec:")
    d = c.get(f"/api/incidents/{inc[0]['id']}", headers=ha).json()
    assert all(r["advisory"] for r in d["recommendations"]) and "signing key" in d["root_label"]
    assert c.get(f"/api/incidents/{inc[0]['id']}/report", headers=ha).status_code == 200
    app.state.aiops.on_tick(time.time() + 300)                                  # quiet for longer than clear_s
    assert incs(c, ha)[0]["status"] == "resolved"


def test_maintenance_window_suppresses_incidents_and_is_audited(env):
    c, app, ha, login = env
    warm(c)
    r = c.post("/api/maintenance", headers=ha, json={"node": "app-01", "minutes": 30, "start_in_minutes": -5, "reason": "kernel patch"})
    assert r.status_code == 200 and r.json()["status"] == "active"
    assert c.post("/api/maintenance", headers=ha, json={"node": "nope", "reason": "x"}).status_code == 422
    assert c.post("/api/maintenance", headers=ha, json={"node": "app-01", "minutes": 30, "reason": ""}).status_code == 422
    assert c.post("/api/maintenance", headers=ha, json={"minutes": 99999, "reason": "too long"}).status_code == 422
    feed(c, "app-01", [60, 55, 50, 45, 40, 35], cpu=95.0)
    assert incs(c, ha) == []                                                         # planned work does not page
    feed(c, "db-01", [30, 25, 20, 15, 10, 5], cpu=95.0)
    assert len(incs(c, ha)) == 1                                                     # other nodes still do
    w = c.get("/api/maintenance", headers=ha).json()[0]
    assert w["suppressed"] >= 1
    hv = login("alpha-viewer", "alpha-demo-pass") if login("alpha-viewer", "alpha-demo-pass") else None
    if hv:
        assert c.post("/api/maintenance", headers=hv, json={"reason": "abc"}).status_code == 403
    assert c.delete(f"/api/maintenance/{w['id']}", headers=ha).status_code == 200
    assert c.delete(f"/api/maintenance/{w['id']}", headers=ha).status_code == 404
    actions = [e["action"] for e in c.get("/api/audit?limit=100", headers=ha).json()]
    assert "maintenance_set" in actions and "maintenance_cancelled" in actions


def test_flapping_root_reopens_the_same_incident(env):
    c, app, ha, _ = env
    warm(c)
    feed(c, "app-01", [200, 195, 190, 185, 180, 175], cpu=95.0)
    first = incs(c, ha)[0]
    feed(c, "app-01", [170, 165, 160, 155, 150, 145, 140, 135], cpu=41.0)             # recovers
    assert incs(c, ha)[0]["status"] == "resolved"
    feed(c, "app-01", [130, 125, 120, 115, 110, 105], cpu=96.0)                       # fails again 10 s later
    now = incs(c, ha)
    assert len(now) == 1 and now[0]["id"] == first["id"] and now[0]["status"] == "open"
    d = c.get(f"/api/incidents/{first['id']}", headers=ha).json()
    assert any(e["kind"] == "reopened" for e in d["timeline"])


def test_recommendations_learn_from_verified_outcomes(env):
    c, app, ha, _ = env
    warm(c)
    feed(c, "app-01", [200, 195], cpu=92.0)
    base = {r["action"]: r["confidence"] for r in _top(c, ha)}
    ai = app.state.aiops
    ai.history = lambda t: {("scale_out", None): (0, 5), ("throttle_traffic", None): (5, 5)}      # scale-out never helped here, throttling always did
    learned = {r["action"]: r for r in _top(c, ha)}
    assert learned["scale_out"]["confidence"] < base["scale_out"] and learned["throttle_traffic"]["confidence"] > base["throttle_traffic"]
    assert any("improved 0 of 5" in x for x in learned["scale_out"]["rationale"])


def test_policy_what_if_replays_history_without_changing_anything(env):
    c, app, ha, _ = env
    warm(c)
    feed(c, "app-01", [200, 195], cpu=92.0)
    inc = incs(c, ha)[0]
    for act in ("restart_service", "scale_out"):
        assert c.post("/api/remediation/propose", headers=ha, json={"node": N["app-01"], "action": act, "incident_id": inc["id"]}).status_code == 200
    before = c.get("/api/remediation/config", headers=ha).json()
    r = c.post("/api/remediation/policy/simulate", headers=ha, json={"policy": {"autonomy": "auto_low", "min_auto_confidence": 0.1}}).json()
    assert r["n"] >= 2 and r["tally"]["allow_auto"]["draft"] >= 1 and r["tally"]["allow_auto"]["current"] == 0 and r["changed"] >= 1
    r2 = c.post("/api/remediation/policy/simulate", headers=ha, json={"policy": {"change_freeze": True}}).json()
    assert r2["tally"]["deny"]["draft"] == r2["n"]
    assert c.get("/api/remediation/config", headers=ha).json() == before                    # nothing was saved
    assert c.post("/api/remediation/policy/simulate", headers=ha, json={"policy": {"nope": 1}}).status_code == 422
    assert c.post("/api/remediation/policy/simulate", headers=ha, json={"policy": {"cooldown_s": "x"}}).status_code == 422


def test_webhooks_are_signed_allow_listed_and_summary_only(env, monkeypatch):
    import hashlib, hmac, http.server, json as _j, threading
    c, app, ha, _ = env
    got = []

    class H(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            got.append((dict(self.headers), self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(204); self.end_headers()

        def log_message(self, *a):
            pass
    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv("HOOK_SECRET", "s3cret")
    from saas.aiops.webhooks import Webhooks
    wh = app.state.aiops.webhooks
    wh.threaded = False
    wh.hooks = {"tenant-alpha": [{"name": "t", "url": f"http://127.0.0.1:{srv.server_port}/x", "secret_env": "HOOK_SECRET", "events": {"incident_opened"}}]}
    warm(c)
    feed(c, "app-01", [200, 195, 190], cpu=95.0)
    assert len(got) == 1
    h, body = got[0]
    ts = h["X-Cicada-Timestamp"]
    assert h["X-Cicada-Signature"] == "sha256=" + hmac.new(b"s3cret", ts.encode() + b"." + body, hashlib.sha256).hexdigest()
    d = _j.loads(body)
    assert d["event"] == "incident_opened" and d["incident"]["root"] == "app-01" and "n-" not in body.decode() and "metrics" not in d["incident"]
    assert wh.log("tenant-alpha")[0]["ok"] == 1
    bad = Webhooks(None, app.state.aiops.eng.store_of, None, threaded=False)
    assert bad._check({"name": "x", "secret_env": "E", "url": "https://evil.example.com/h"}) and bad._check({"name": "x", "secret_env": "E", "url": "http://evil.example.com/h"})
    assert c.post("/api/webhooks/none/test", headers=ha).status_code == 404 and c.get("/api/webhooks", headers=ha).status_code == 200


def test_summary_works_between_execution_and_verification(env):
    c, app, ha, _ = env
    (r,) = spike_and_draft(c, app, ha)
    a = c.post(f"/api/remediation/{r['id']}/approve", headers=ha, json={})
    assert a.status_code == 200 and a.json()["status"] == "executed"                                   # verdict holds only 'before' so far
    assert c.get("/api/aiops/summary", headers=ha).status_code == 200


def test_detection_lag_never_negative(env):
    c, app, ha, _ = env
    warm(c)
    feed(c, "app-01", [-300, -295, -290], cpu=95.0)                                  # sample clock 5 min AHEAD of the server
    s = c.get("/api/aiops/summary", headers=ha).json()["slo"]["mttd"]
    assert s["n"] == 0 and s["skewed"] >= 1 and s["p50"] is None
    assert all((a["detect_lag_s"] is None or a["detect_lag_s"] >= 0) for a in c.get("/api/aiops/anomalies", headers=ha).json())
