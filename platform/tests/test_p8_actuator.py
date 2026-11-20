"""P8 real actuation: a signed command queue the customer's collector re-verifies and executes only if its owner switched it on.
Signature, allow-list, replay/expiry, at-most-once delivery, the two-key rule, runbook safety, and the full approve -> execute -> verify loop."""
import asyncio
import json
import stat
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from collector.actuator import CALM_EFFECT, CommandRunner, load_runbooks  # noqa: E402
from collector.scenarios import CALM, FAULT  # noqa: E402
from collector.sources import CalmSource  # noqa: E402
from contracts.signing import command_sign, command_verify, key_id  # noqa: E402
from test_p3_aiops import env, feed, spike_and_draft  # noqa: E402,F401
from test_saas import A, B  # noqa: E402

SECRET = "dev-key-alpha"


def runner(mode="calm", runbooks="", src=None):
    s = SimpleNamespace(actuator=mode, runbooks=runbooks, api_key=SECRET, tenant_id="tenant-alpha", saas_url="http://x/ingest", command_poll_s=1)
    return CommandRunner(SimpleNamespace(s=s, sources=[src] if src else []), None)


def cmd(cid=1, action="scale_out", target="app-01", exp=None, secret=SECRET, tenant="tenant-alpha", kid=None, params=None):
    kid, params, exp = kid or key_id(SECRET), params or {}, int(exp or time.time() + 60)
    return {"id": cid, "tenant": tenant, "kid": kid, "action": action, "target": target, "params": params, "exp": exp,
            "sig": command_sign(secret, cid, tenant, kid, action, target, params, exp)}


# ---------------------------------------------------------------- signature
def test_signature_binds_every_field():
    c = cmd()
    assert command_verify(SECRET, c)
    for k, v in {"id": 2, "tenant": "tenant-beta", "kid": "x", "action": "restart_service", "target": "db-01", "params": {"a": 1}, "exp": c["exp"] + 1}.items():
        assert not command_verify(SECRET, {**c, k: v}), k
    assert not command_verify("other-secret", c) and not command_verify(SECRET, {"id": 1})


# ---------------------------------------------------------------- the collector never trusts the wire
def test_collector_refuses_everything_it_should():
    r, now = runner("calm", src=CalmSource()), time.time()
    assert r.check(cmd(), now) is None
    assert "off" in runner("off").check(cmd(), now)
    assert r.check({**cmd(), "sig": "00" * 32}, now) == "bad signature"
    assert "different tenant" in r.check(cmd(tenant="tenant-beta"), now)
    assert "different tenant" in r.check(cmd(kid="kid-other"), now)
    assert r.check(cmd(exp=now - 5), now) == "command expired"
    assert "allow-list" in r.check(cmd(action="isolate_node"), now) and "allow-list" in r.check(cmd(action="rm -rf"), now)
    assert r.check(cmd(target="a;touch x"), now) == "malformed target" and r.check(cmd(target="../etc"), now) == "malformed target"
    r.seen[1] = now
    assert "replay" in r.check(cmd(cid=1), now)


def test_off_by_default_has_no_capabilities():
    assert runner("off").caps() == [] and runner("bogus").mode == "off"


# ---------------------------------------------------------------- calm backend changes the managed system for real
def test_calm_fault_is_sustained_until_acted_on_and_rollback_restores_it():
    src = CalmSource()
    src.fault("app-01", FAULT, ticks=3)
    assert src._fault_values("app-01") == {"cpu_percent": 96.0, "latency_ms": 160.0}
    assert src.mitigate("app-01", CALM_EFFECT["scale_out"]) and src._fault_values("app-01")["cpu_percent"] < CALM["cpu_percent"] + 4
    assert src.mitigate("app-01", CALM_EFFECT["scale_in"]) and src._fault_values("app-01")["cpu_percent"] == 96.0
    assert not src.mitigate("db-01", 1.0)
    src.faults["app-01"]["left"] = 0
    assert src._fault_values("app-01") is None                                                       # fail-safe: a fault cannot last forever


def test_calm_execute_applies_or_refuses_with_reason():
    src = CalmSource()
    r = runner("calm", src=src)
    assert r.execute(cmd())[0] == "refused"                                                          # nothing to act on
    src.fault("app-01", FAULT)
    assert r.execute(cmd())[0] == "applied" and src.faults["app-01"]["cut"] == 0.95
    assert r.execute(cmd(target="nope-99"))[0] == "refused"


# ---------------------------------------------------------------- runbook backend: fixed argv, no shell
def runbook(tmp_path, body):
    sh = tmp_path / "rb.sh"
    sh.write_text("#!/bin/sh\n" + body)
    sh.chmod(sh.stat().st_mode | stat.S_IEXEC)
    y = tmp_path / "runbooks.yaml"
    y.write_text(f"scale_out: {{argv: ['{sh}', '{{target}}'], timeout_s: 5}}\nrestart_service: {{argv: ['{sh}', 'x'], timeout_s: 1}}\n")
    return str(y), sh


def test_runbook_runs_only_named_argv_with_target_substituted(tmp_path):
    y, _ = runbook(tmp_path, f'echo "$1" > {tmp_path}/marker\n')
    r = runner("runbook", y)
    assert r.caps() == ["restart_service", "scale_out"]
    st, d = r.execute(cmd(target="app-01"))
    assert st == "applied" and d["exit"] == 0 and (tmp_path / "marker").read_text().strip() == "app-01"
    assert r.check(cmd(action="throttle_traffic"), time.time()) and "allow-list" in r.check(cmd(action="throttle_traffic"), time.time())


def test_runbook_failure_and_timeout_are_reported_not_hidden(tmp_path):
    y, _ = runbook(tmp_path, "echo boom >&2\nexit 3\n")
    st, d = runner("runbook", y).execute(cmd())
    assert st == "failed" and d["exit"] == 3 and "boom" in d["stderr"]
    y2, _ = runbook(tmp_path, "sleep 5\n")
    assert runner("runbook", y2).execute(cmd(action="restart_service"))[0] == "failed"                # timeout_s 1


def test_runbook_rejects_relative_or_malformed_argv(tmp_path):
    y = tmp_path / "bad.yaml"
    y.write_text("scale_out: {argv: [reboot]}\n")
    with pytest.raises(ValueError):
        load_runbooks(str(y))
    y.write_text("scale_out: {argv: 'rm -rf /'}\n")
    with pytest.raises(ValueError):
        load_runbooks(str(y))


# ---------------------------------------------------------------- SaaS side
def poll(c, col=A, caps="scale_out,scale_in,throttle_traffic"):
    r = col.get(c, f"/collector/commands?caps={caps}")
    assert r.status_code == 200, r.text
    return r.json()["commands"]


def real(c, ha):
    assert c.put("/api/remediation/config", headers=ha, json={"actuator": "collector"}).status_code == 200


def test_default_is_simulation_and_only_admins_can_change_it(env):
    c, app, ha, login = env
    st = c.get("/api/actuator", headers=ha).json()
    assert st["mode"] == "simulation" and st["online"] is False and st["commands"] == []
    assert c.put("/api/remediation/config", headers=login("alpha-viewer", "alpha-viewer-pass"), json={"actuator": "collector"}).status_code == 403
    assert c.put("/api/remediation/config", headers=ha, json={"actuator": "shell"}).status_code == 422


def test_real_mode_queues_nothing_when_the_collector_is_absent_and_the_action_stays_approved(env):
    c, app, ha, _ = env
    (r,) = spike_and_draft(c, app, ha)
    real(c, ha)
    resp = c.post("/api/remediation/%d/approve" % r["id"], headers=ha, json={})
    assert resp.status_code == 409 and "not connected" in resp.json()["detail"]
    assert c.get("/api/remediation/%d" % r["id"], headers=ha).json()["status"] == "approved"          # nothing ran, nothing queued
    assert c.get("/api/actuator", headers=ha).json()["commands"] == []


def test_action_outside_the_collectors_declared_capabilities_is_refused(env):
    c, app, ha, _ = env
    (r,) = spike_and_draft(c, app, ha)
    real(c, ha)
    poll(c, caps="throttle_traffic")                                                                  # collector offers everything but scale_out
    resp = c.post("/api/remediation/%d/approve" % r["id"], headers=ha, json={})
    assert resp.status_code == 409 and "does not offer" in resp.json()["detail"]


def test_full_loop_signed_command_executes_reports_back_and_telemetry_verifies(env):
    c, app, ha, _ = env
    (r,) = spike_and_draft(c, app, ha)
    app.state.aiops.rem.doc["defaults"]["verify_after_s"] = 1
    real(c, ha)
    poll(c)
    ex = c.post("/api/remediation/%d/approve" % r["id"], headers=ha, json={}).json()
    assert ex["status"] == "executed" and ex["verdict"]["actuator"]["actuator"] == "collector" and ex["verdict"]["actuator"]["ref"].startswith("cmd-")
    (cm,) = poll(c)
    assert cm["action"] == "scale_out" and cm["target"] == "app-01" and cm["tenant"] == "tenant-alpha" and poll(c) == []   # delivered once
    rn = runner("calm", src=CalmSource())
    rn.pipe.sources[0].fault("app-01", FAULT)
    assert rn.check(cm, time.time()) is None                                                          # the collector accepts the SaaS's signature
    assert A.post(c, f"/collector/commands/{cm['id']}/result", {"status": "applied", "detail": {"applied": "scale_out on app-01"}}).status_code == 200
    feed(c, "app-01", [185, 180, 175, 170, 165, 160], cpu=40.0)                                       # what the collector's fix does to real telemetry
    app.state.engine.check_stale(now=time.time() + 3)
    v = c.get("/api/remediation/%d" % r["id"], headers=ha).json()
    assert v["status"] == "verified" and v["verdict"]["verdict"] == "improved"
    assert [e["event"] for e in v["timeline"]][:4] == ["proposed", "approved", "executed", "actuated"]
    assert any(e["actor"] == "collector" for e in v["timeline"])
    rb = c.post("/api/remediation/%d/rollback" % r["id"], headers=ha, json={"reason": "t"}).json()
    assert rb["status"] == "rolled_back" and poll(c)[0]["action"] == "scale_in"                       # rollback is a command too
    kinds = [x.get("action") or x.get("type") for x in c.get("/api/audit", headers=ha, params={"limit": 80}).json()]
    assert "command_applied" in kinds


def test_a_refused_command_aborts_the_action_instead_of_claiming_success(env):
    c, app, ha, _ = env
    (r,) = spike_and_draft(c, app, ha)
    real(c, ha)
    poll(c)
    c.post("/api/remediation/%d/approve" % r["id"], headers=ha, json={})
    (cm,) = poll(c)
    A.post(c, f"/collector/commands/{cm['id']}/result", {"status": "refused", "detail": {"reason": "actuator is switched off on this collector"}})
    v = c.get("/api/remediation/%d" % r["id"], headers=ha).json()
    assert v["status"] == "aborted" and "did not execute" in json.dumps(v["timeline"])


def test_verify_never_claims_improvement_for_a_command_the_collector_did_not_confirm(env):
    c, app, ha, _ = env
    (r,) = spike_and_draft(c, app, ha)
    app.state.aiops.rem.doc["defaults"]["verify_after_s"] = 1
    real(c, ha)
    poll(c)
    c.post("/api/remediation/%d/approve" % r["id"], headers=ha, json={})
    poll(c)                                                                                           # delivered, never answered
    feed(c, "app-01", [185, 180, 175, 170, 165, 160], cpu=40.0)                                       # the node even looks better
    app.state.engine.check_stale(now=time.time() + 3)
    v = c.get("/api/remediation/%d" % r["id"], headers=ha).json()
    assert v["verdict"]["verdict"] == "no_effect" and "never confirmed" in v["verdict"]["note"]


def test_results_are_tenant_scoped_once_only_and_validated(env):
    c, app, ha, _ = env
    (r,) = spike_and_draft(c, app, ha)
    real(c, ha)
    poll(c)
    c.post("/api/remediation/%d/approve" % r["id"], headers=ha, json={})
    (cm,) = poll(c)
    assert B.post(c, f"/collector/commands/{cm['id']}/result", {"status": "applied"}).status_code == 404       # another tenant's collector
    assert A.post(c, f"/collector/commands/{cm['id']}/result", {"status": "totally-fine"}).status_code == 422
    assert A.post(c, f"/collector/commands/{cm['id']}/result", {"nope": 1}).status_code == 400
    assert A.post(c, f"/collector/commands/{cm['id']}/result", {"status": "applied"}).status_code == 200
    assert A.post(c, f"/collector/commands/{cm['id']}/result", {"status": "applied"}).status_code == 409    # no second answer


def test_commands_expire_and_an_unanswered_one_is_never_redelivered(env):
    c, app, ha, _ = env
    cmdr, now = app.state.aiops.cmd, time.time()
    poll(c)
    cmdr.apply("tenant-alpha", "app-01", "scale_out", {}, now)                                          # queued, then the collector stays silent
    cmdr.apply("tenant-alpha", "app-01", "throttle_traffic", {}, now)
    st = app.state.engine.store_of("tenant-alpha")
    got = cmdr.deliver("tenant-alpha", key_id(SECRET), SECRET, now + 1)
    assert len(got) == 2 and cmdr.deliver("tenant-alpha", key_id(SECRET), SECRET, now + 2) == []
    cmdr.deliver("tenant-alpha", key_id(SECRET), SECRET, now + 200)
    assert {r["status"] for r in st.q("SELECT status FROM commands")} == {"unknown"}
    from saas.aiops.remediate import RemediationError
    with pytest.raises(RemediationError):
        cmdr.apply("tenant-alpha", "app-01", "scale_out", {}, now + 200)                                # the collector has been silent: nothing is queued


def test_real_actuation_always_needs_a_human_even_in_auto_mode(env):
    from saas.aiops.remediate import decide, effective_policy
    c, app, ha, _ = env
    rem = app.state.aiops.rem
    pol = {**rem.config("tenant-alpha"), "autonomy": "auto_low"}
    req = dict(action="scale_out", label="app-01", blast=0, confidence=0.95, severity="high", risk="low", reversible=True, advisory=False, telemetry_age_s=1,
               actions_last_hour=0, cooldown_hit=False, duplicate=False, offline_s=30)
    assert decide(pol, req)["decision"] == "allow_auto"
    d = decide(pol, {**req, "real": True})
    assert d["decision"] == "needs_approval" and "real_actuator" in [x["rule"] for x in d["rules"]]


def test_tenants_do_not_see_each_others_commands(env):
    c, app, ha, login = env
    (r,) = spike_and_draft(c, app, ha)
    real(c, ha)
    poll(c)
    c.post("/api/remediation/%d/approve" % r["id"], headers=ha, json={})
    hb = login("beta-admin", "beta-demo-pass")
    st = c.get("/api/actuator", headers=hb).json()
    assert st["commands"] == [] and st["mode"] == "simulation" and st["online"] is False
