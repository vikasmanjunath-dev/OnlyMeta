"""P9 counterfactual verification: 'improved after the action' vs 'improved because of the action'. Pure estimator on synthetic shapes,
then the live verify path (caused / coincident), and the guarantee that a simulated action never gets credit for a recovery it did not make."""
import random
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from saas.aiops.counterfactual import attribute, theil_sen  # noqa: E402
from test_p3_aiops import N, env, warm  # noqa: E402,F401
from test_saas import A, pl, send  # noqa: E402

FLOOR, SIG = 40.0, 2.0
PRE, POST = list(range(-30, 1, 5)), list(range(5, 50, 5))


def mk(f, ts, seed=1):
    rnd = random.Random(seed)
    return [(t, round(f(t) + rnd.gauss(0, 1.0), 1)) for t in ts]


def run(pre_f, post_f, ctl=None, **kw):
    return attribute(mk(pre_f, kw.pop("pre", PRE)), mk(post_f, POST, 2), FLOOR, SIG, ctl, kw or None)


# ---------------------------------------------------------------- the estimator
def test_theil_sen_is_robust_to_an_outlier():
    b, a = theil_sen([0, 1, 2, 3, 4, 5, 6], [0, 1, 2, 3, 40, 5, 6])
    assert abs(b - 1.0) < 0.05 and abs(a) < 0.3


def test_a_step_that_follows_the_action_is_credited_to_it():
    r = run(lambda t: 96, lambda t: 42)
    assert r["verdict"] == "caused" and r["effect"] < -r["band"] and r["onset_lag_s"] is not None and r["onset_lag_s"] <= 10


@pytest.mark.parametrize("slope", [0.47, 0.93])
def test_a_recovery_already_under_way_is_not_credited(slope):
    r = run(lambda t: 96 - slope * (t + 30), lambda t: max(FLOOR, 96 - slope * (t + 30)))
    assert r["verdict"] == "coincident" and "does not credit the action" in r["explain"] and r["slope_per_s"] < 0


def test_peers_improving_too_means_fleet_wide_not_this_action():
    peers = [{"label": "db-01", "pre": mk(lambda t: 90, PRE, 3), "post": mk(lambda t: 45, POST, 4)}]
    r = run(lambda t: 96, lambda t: 42, peers)
    assert r["verdict"] == "fleet_wide" and "db-01" in r["explain"]


def test_flat_peers_do_not_block_credit():
    peers = [{"label": "db-01", "pre": mk(lambda t: 40, PRE, 3), "post": mk(lambda t: 40, POST, 4)}]
    r = run(lambda t: 96, lambda t: 42, peers)
    assert r["verdict"] == "caused" and r["controls"][0]["label"] == "db-01" and abs(r["controls"][0]["delta"]) < 3


def test_it_will_not_claim_credit_for_an_imagined_deterioration():
    r = run(lambda t: 70 + 0.8 * (t + 30), lambda t: 94 - 0.0 * t)                  # rising trend, then it merely holds near the worst value seen
    assert r["verdict"] != "caused"


def test_too_little_history_or_no_improvement_is_inconclusive_not_a_guess():
    assert run(lambda t: 96, lambda t: 42, pre=list(range(-10, 1, 5)))["verdict"] == "inconclusive"
    assert attribute(mk(lambda t: 96, PRE), mk(lambda t: 42, [5, 10]), FLOOR, SIG)["verdict"] == "inconclusive"
    assert run(lambda t: 96, lambda t: 95)["verdict"] == "inconclusive"


def test_only_the_unbroken_degraded_run_before_the_action_is_used():
    calm_then_fault = mk(lambda t: 40 if t < -15 else 96, PRE)                        # the node was healthy until 15 s before the action
    r = attribute(calm_then_fault, mk(lambda t: 42, POST, 2), FLOOR, SIG)
    assert r["verdict"] == "caused" and r["pre_n"] == 4 and abs(r["slope_per_s"]) < 0.2   # the calm samples did not fake an upward trend


def test_statement_of_assumptions_is_part_of_every_answer():
    r = run(lambda t: 96, lambda t: 42)
    assert len(r["assumptions"]) == 4 and "robust trend" in r["method"]


# ---------------------------------------------------------------- the live verify path
def incident_then_act(c, app, ha, pre_vals, post_vals):
    warm(c)
    ages = list(range(200, 200 - 5 * len(pre_vals), -5))
    for a, v in zip(ages, pre_vals):
        send(c, A, pl(node=N["app-01"], age=a, cpu=v, latency_ms=20.0, packet_loss=0.1))
    app.state.engine.check_stale(now=time.time() + 10)
    (r,) = [x for x in c.get("/api/remediation", headers=ha).json() if x["status"] == "pending_approval"]
    app.state.aiops.rem.doc["defaults"]["verify_after_s"] = 1
    ok = c.post("/api/remediation/%d/approve" % r["id"], headers=ha, json={}).json()
    assert ok["status"] == "executed", ok
    start = ages[-1] - 5
    for i, v in enumerate(post_vals):
        send(c, A, pl(node=N["app-01"], age=start - 5 * i, cpu=v, latency_ms=20.0, packet_loss=0.1))
    app.state.engine.check_stale(now=time.time() + 3)
    return c.get("/api/remediation/%d" % r["id"], headers=ha).json()


def test_live_verdict_credits_a_step_that_follows_the_action(env):
    c, app, ha, _ = env
    v = incident_then_act(c, app, ha, [92.0] * 7, [41.0, 40.5, 41.5, 40.0, 41.0, 40.0, 41.0, 40.5])
    a = v["verdict"]["attribution"]
    assert v["status"] == "verified" and v["verdict"]["verdict"] == "improved"
    assert a["verdict"] == "caused" and a["metric"] == "cpu" and "Counterfactual:" in v["verdict"]["note"] and "better than it would have been" in v["verdict"]["note"]
    s = app.state.aiops.rem.summary("tenant-alpha", time.time())
    assert s["credited"] == 1 and s["not_credited"] == 0


def test_live_verdict_refuses_credit_when_it_was_already_recovering(env):
    c, app, ha, _ = env
    ramp = [96 - 2.5 * i for i in range(7)]
    v = incident_then_act(c, app, ha, ramp, [max(41.0, 96 - 2.5 * i) for i in range(7, 16)])
    a = v["verdict"]["attribution"]
    assert v["verdict"]["verdict"] == "improved" and a["verdict"] == "coincident" and "does not credit the action" in v["verdict"]["note"]
    assert app.state.aiops.rem.summary("tenant-alpha", time.time())["not_credited"] == 1


def test_attribution_is_in_the_timeline_and_never_changes_the_original_verdict(env):
    c, app, ha, _ = env
    v = incident_then_act(c, app, ha, [92.0] * 7, [41.0] * 8)
    ev = [e for e in v["timeline"] if e["event"] == "verified"][0]["detail"]
    assert ev["attribution"] == "caused" and ev["verdict"] == "improved"


def test_a_peer_that_was_itself_treated_is_not_an_untreated_control(env):
    """app-01 recovers in the same window, but only because ITS OWN action ran: that must not make db-01's recovery 'fleet-wide'."""
    import json
    c, app, ha, _ = env
    warm(c)
    ages = list(range(200, 165, -5))
    for a in ages:
        send(c, A, pl(node=N["app-01"], age=a, cpu=92.0, latency_ms=20.0, packet_loss=0.1))
        send(c, A, pl(node=N["db-01"], age=a, cpu=92.0, latency_ms=20.0, packet_loss=0.1))
    app.state.engine.check_stale(now=time.time() + 10)
    (r,) = [x for x in c.get("/api/remediation", headers=ha).json() if x["status"] == "pending_approval" and x["label"] == "db-01"]
    st = app.state.engine.store_of("tenant-alpha")
    with st.tx() as cx:                                                                    # app-01 had its own action executed
        cx.execute("INSERT INTO remediations(tenant_id,node,action,params,status,created_ts,executed_ts,signature) VALUES(?,?,?,?,?,?,?,?)",
                   ("tenant-alpha", N["app-01"], "scale_out", "{}", "verified", time.time(), time.time(), "x|y"))
    app.state.aiops.rem.doc["defaults"]["verify_after_s"] = 1
    assert c.post("/api/remediation/%d/approve" % r["id"], headers=ha, json={}).json()["status"] == "executed"
    for i in range(8):
        send(c, A, pl(node=N["app-01"], age=160 - 5 * i, cpu=41.0, latency_ms=20.0, packet_loss=0.1))
        send(c, A, pl(node=N["db-01"], age=160 - 5 * i, cpu=41.0, latency_ms=20.0, packet_loss=0.1))
    app.state.engine.check_stale(now=time.time() + 3)
    a = c.get("/api/remediation/%d" % r["id"], headers=ha).json()["verdict"]["attribution"]
    assert a["verdict"] == "caused" and all(k["label"] != "app-01" for k in a["controls"])
