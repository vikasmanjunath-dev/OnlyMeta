"""P5 learned topology: the pure learner (order of onsets -> dependency edges, with evidence), and the SaaS flow
(suggest -> admin accepts -> root-cause analysis uses it), including tenant isolation, cycles and the audit trail."""
import statistics
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from saas.aiops import learn as L  # noqa: E402
from saas.aiops.baseline import Detector  # noqa: E402
from saas.aiops.correlate import Graph  # noqa: E402
from test_p2_advanced import mk  # noqa: E402
from test_p3_aiops import CLEAN, N, TH, incs, warm  # noqa: E402
from test_saas import A, B, pl, send  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SIG = Detector(TH).sigma_eff
CFG = {}
TOPO = {"app": {"label": "app", "depends_on": ["db"]}, "db": {"label": "db", "depends_on": ["net"]}, "net": {"label": "net", "depends_on": []}}


def rows(offsets: dict, episodes=5, per=36, every=5, t0=1_000_000.0, hot=6, width=6):
    """Per node: calm samples with a deviation episode starting `offsets[node]` seconds after the episode's first tick (None: never)."""
    out = {n: [] for n in offsets}
    for e in range(episodes):
        for i in range(per):
            t = t0 + every * (e * per + i)
            for n, off in offsets.items():
                start = hot + (off or 0) / every
                bad = off is not None and start <= i < start + width
                out[n].append({"event_ts": t, "cpu": 90.0 if bad else 40.0 + (i % 3) * 0.5, "mem": 55.0, "latency_ms": 30.0 + (i % 2), "packet_loss": 0.1, "bandwidth_mbps": 120.0})
    return out


def edges(res):
    return {(e["up"], e["dep"]): e for e in res["edges"]}


# ---------------------------------------------------------------- the learner
def test_rediscovers_the_chain_and_drops_the_skip_edge():
    r = L.learn(rows({"net": 0, "db": 5, "app": 10}), TOPO, CFG, SIG)
    e = edges(r)
    assert set(e) == {("net", "db"), ("db", "app")}                                  # net->app is explained by the chain
    assert all(x["status"] == "confirmed" for x in e.values())
    assert e[("net", "db")]["support"] == 5 and e[("net", "db")]["p"] == pytest.approx(0.0312, abs=1e-4) and e[("net", "db")]["lag_s"] == 5
    assert [(i["up"], i["dep"]) for i in r["indirect"]] == [("net", "app")]
    assert all(d["seen"] for d in r["declared"])


def test_new_edge_when_the_map_does_not_know_it():
    r = L.learn(rows({"net": 0, "db": 5, "app": 10}), {}, CFG, SIG)
    assert {x["status"] for x in r["edges"]} == {"new"} and len(r["edges"]) == 2


def test_simultaneous_onsets_give_no_direction():
    r = L.learn(rows({"db": 0, "app": 0}), TOPO, CFG, SIG)
    assert r["edges"] == [] and r["undirected"][0]["ties"] == 5 and "same time" in r["undirected"][0]["why"]


def test_reverse_order_contradicts_the_declared_map():
    r = L.learn(rows({"app": 0, "db": 5}), TOPO, CFG, SIG)                           # app fails first, db follows: the map says the opposite
    (e,) = r["edges"]
    assert (e["up"], e["dep"], e["status"], e["cycle"]) == ("app", "db", "contradicts", True)


def test_too_little_evidence_is_not_an_edge():
    assert L.learn(rows({"net": 0, "db": 5}, episodes=2), TOPO, CFG, SIG)["edges"] == []


def test_unrelated_nodes_do_not_make_an_edge():
    r = L.learn(rows({"a": 0, "b": 90}), {}, CFG, SIG)                               # both fail every 180 s, but 90 s apart: never together
    assert r["edges"] == [] and r["undirected"] == []


def test_chance_overlap_is_not_enough():
    s = rows({"a": 0, "b": 15}, episodes=4, per=12)                                  # failures so frequent that overlap is expected by chance
    assert L.learn(s, {}, CFG, SIG)["edges"] == []


def test_sign_test_and_cycle_helpers():
    assert L.sign_test_p(3, 3) == 0.125 and L.sign_test_p(5, 5) == 0.03125 and L.sign_test_p(2, 4) == pytest.approx(0.6875)
    deps = {"app": {"db"}, "db": {"net"}}
    assert L.would_cycle(deps, "app", "net") and L.would_cycle(deps, "x", "x") and not L.would_cycle(deps, "net", "web")


def test_learner_is_deterministic():
    s = rows({"net": 0, "db": 5, "app": 10})
    assert L.learn(s, TOPO, CFG, SIG) == L.learn(s, TOPO, CFG, SIG)


# ---------------------------------------------------------------- the platform
EXTRA = "n-cache0000001"                                                             # a node the declared map has never heard of


def history(c, episodes=5, hours=2.0):
    """net-01 fails, db-01 follows 5 s later, EXTRA 10 s later (the map has no entry for it): older than the live samples, so history only."""
    base = hours * 3600
    for e in range(episodes):
        for i in range(36):
            age = base - 5 * (e * 36 + i)
            send(c, A, pl(node=N["net-01"], age=age, latency_ms=250 if 6 <= i < 12 else 21, packet_loss=4.0 if 6 <= i < 12 else 0.1))
            send(c, A, pl(node=N["db-01"], age=age, cpu=92 if 7 <= i < 13 else 40, latency_ms=21))
            send(c, A, pl(node=EXTRA, age=age, latency_ms=280 if 8 <= i < 14 else 21, cpu=40))


@pytest.fixture
def env(tmp_path):
    c, app, login = mk(tmp_path, rate_limit_rps=100000)
    h = login("alpha-admin", "alpha-demo-pass")
    warm(c, nodes=("app-01", "db-01", "net-01"))
    send(c, A, pl(node=EXTRA, age=3, latency_ms=21, cpu=40))
    history(c)
    return c, app, h, login


def learned(c, h):
    return c.get("/api/aiops/topology/learned", headers=h).json()


def test_platform_suggests_the_new_edge_and_confirms_the_declared_ones(env):
    c, app, h, login = env
    r = learned(c, h)
    e = {(x["up"], x["dep"]): x for x in r["edges"]}
    assert e[(N["net-01"], N["db-01"])]["status"] == "confirmed"
    new = e[(N["db-01"], EXTRA)]
    assert new["status"] == "new" and new["support"] == 5 and new["decision"] is None and new["dep_label"] == EXTRA[:12]
    assert r["applied"] == [] and any(d["seen"] for d in r["declared"])


def test_accepting_an_edge_is_admin_only_audited_and_changes_the_graph(env):
    c, app, h, login = env
    body = {"up": N["db-01"], "dep": EXTRA, "decision": "accept"}
    viewer = login("alpha-viewer", "alpha-view-pass") if login("alpha-viewer", "alpha-view-pass") else None
    if viewer:
        assert c.post("/api/aiops/topology/learned/decision", headers=viewer, json=body).status_code == 403
    assert c.post("/api/aiops/topology/learned/decision", headers=h, json=body).status_code == 200
    r = learned(c, h)
    assert [(a["up"], a["dep"]) for a in r["applied"]] == [(N["db-01"], EXTRA)]
    g = app.state.aiops.graph("tenant-alpha")
    assert N["db-01"] in g.upstream(EXTRA) and N["net-01"] in g.upstream(EXTRA)       # now part of the chain
    audit = c.get("/api/audit", headers=h).json()
    assert any(a["action"] == "topology_edge_accept" for a in (audit["rows"] if isinstance(audit, dict) else audit))
    assert c.post("/api/aiops/topology/learned/decision", headers=h, json={**body, "decision": "revoke"}).status_code == 200
    assert N["db-01"] not in app.state.aiops.graph("tenant-alpha").upstream(EXTRA)


def test_cycles_unknown_nodes_and_bad_decisions_are_refused(env):
    c, app, h, login = env
    post = lambda **b: c.post("/api/aiops/topology/learned/decision", headers=h, json=b)  # noqa: E731
    assert post(up=EXTRA, dep=N["db-01"], decision="accept").status_code == 409        # no such evidence
    assert post(up=N["db-01"], dep=EXTRA, decision="maybe").status_code == 409
    assert post(up="n-nonexistent", dep=EXTRA, decision="accept").status_code == 404
    assert post(up=N["db-01"], dep=EXTRA, decision="reject").status_code == 200
    assert learned(c, h)["applied"] == []                                              # rejected is recorded, not applied
    c.post("/api/aiops/topology/learned/decision", headers=h, json={"up": N["db-01"], "dep": EXTRA, "decision": "accept"})
    assert post(up=EXTRA, dep=N["db-01"], decision="accept").status_code == 409        # would close a cycle


def test_learned_edges_are_tenant_scoped(env):
    c, app, h, login = env
    c.post("/api/aiops/topology/learned/decision", headers=h, json={"up": N["db-01"], "dep": EXTRA, "decision": "accept"})
    hb = login("beta-admin", "beta-demo-pass")
    assert learned(c, hb)["edges"] == [] and learned(c, hb)["applied"] == []
    assert c.post("/api/aiops/topology/learned/decision", headers=hb, json={"up": N["db-01"], "dep": EXTRA, "decision": "accept"}).status_code == 404


def test_cascade_scenario_shape():
    from collector import scenarios
    ev = scenarios.build("cascade", ticks=2)
    assert len(ev) == 2 * 36 * 3 and "cascade" in scenarios.EVENT_SCENARIOS
    hot = {n: sorted({e["ts"] for e in ev if e["node"] == n and (e["latency_ms"] > 80 or e["cpu_percent"] > 80)}) for n in ("net-01", "db-01", "app-01")}
    assert hot["net-01"][0] < hot["db-01"][0] < hot["app-01"][0]
