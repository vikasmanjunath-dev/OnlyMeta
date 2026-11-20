"""P7 ask the platform: plain-English questions answered by rules from this tenant's own records (no model). Intent parsing, grounding
(every answer's facts and cites resolve against the API), refusal to guess, tenant isolation, privacy, and a remediation round trip."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from saas.aiops.ask import EXAMPLES, MAX_Q, dur, parse, window  # noqa: E402
from test_p3_aiops import N, env, spike_and_draft  # noqa: E402,F401

LABELS = ["app-01", "db-01", "net-01"]


def ask(c, h, q):
    r = c.post("/api/ask", headers=h, json={"question": q})
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------- parsing
@pytest.mark.parametrize("q,intent,extra", [
    ("What is wrong right now?", "open", {}), ("is anything broken", "open", {}), ("Why did db-01 fail?", "why", {"nodes": ["db-01"]}),
    ("what is the root cause of INC-3", "why", {"incident": 3}), ("What should I do about INC-12?", "fix", {"incident": 12}), ("how do i fix this", "fix", {}),
    ("Who approved the fix?", "who", {}), ("who acknowledged incident 4", "who", {"incident": 4}), ("How long did the last incident take?", "timeline", {}),
    ("when did it start", "timeline", {}), ("How is app-01?", "node", {"nodes": ["app-01"]}), ("is db 01 ok", "node", {"nodes": ["db-01"]}),
    ("What depends on db-01?", "blast", {"nodes": ["db-01"]}), ("what if net-01 goes down", "blast", {"nodes": ["net-01"]}),
    ("How many incidents in the last 24 hours?", "count", {"window_s": 86400}), ("What are the open anomalies?", "anomalies", {}),
    ("What is our MTTD and MTTR?", "slo", {}), ("alert noise reduction", "slo", {}), ("help", "help", {}), ("what is the weather in Paris", None, {}),
])
def test_intents_entities_and_windows(q, intent, extra):
    p = parse(q, LABELS)
    assert p["intent"] == intent and all(p[k] == v for k, v in extra.items())


def test_windows_and_durations():
    assert window("in the last 30 minutes") == (1800, True) and window("past hour") == (3600, True) and window("last 2 days") == (172800, True) and window("anything") == (3600, False)
    assert [dur(x) for x in (None, 42, 300, 86400, 7260)] == ["n/a", "42 s", "5 min", "24 h", "2 h 1 min"]


# ---------------------------------------------------------------- grounded answers
def test_answers_match_the_records_they_cite(env):
    c, app, ha, login = env
    (r,) = spike_and_draft(c, app, ha)
    inc = c.get("/api/incidents", headers=ha).json()[0]
    a = ask(c, ha, "What is wrong right now?")
    assert a["intent"] == "open" and inc["ref"] in a["answer"] and inc["root_label"] in a["answer"] and a["facts"]["open_incidents"] == 1
    assert {x["id"] for x in a["cites"] if x["type"] == "incident"} == {inc["id"]}
    w = ask(c, ha, f"Why did {inc['root_label']} fail?")
    assert w["intent"] == "why" and f"{round(inc['confidence'] * 100)}%" in w["answer"] and w["facts"]["root"] == inc["root_label"] and "coverage" in w["answer"]
    f = ask(c, ha, f"What should I do about {inc['ref']}?")
    assert f["intent"] == "fix" and "Scale out" in f["answer"] and "simulated" in f["answer"] and any(x["type"] == "remediation" and x["id"] == r["id"] for x in f["cites"])
    n = ask(c, ha, "How is app-01?")
    assert n["intent"] == "node" and "app-01 is" in n["answer"] and inc["ref"] in n["answer"]
    b = ask(c, ha, "What depends on db-01?")
    assert b["facts"]["dependents"] == ["app-01"] and b["facts"]["depends_on"] == ["net-01"]
    cnt = ask(c, ha, "How many incidents in the last 24 hours?")
    assert cnt["facts"]["open"] == 1 and cnt["parsed"]["window_s"] == 86400
    for x in (a, w, f, n, b, cnt, ask(c, ha, "What are the open anomalies?"), ask(c, ha, "What is our MTTD and MTTR?"), ask(c, ha, "How long did the last incident take?")):
        for cite in x["cites"]:                                                   # every citation resolves to a real record of this tenant
            if cite["type"] == "incident":
                assert c.get(f"/api/incidents/{cite['id']}", headers=ha).status_code == 200
            if cite["type"] == "remediation":
                assert c.get(f"/api/remediation/{cite['id']}", headers=ha).status_code == 200


def test_who_approved_after_a_real_approval(env):
    c, app, ha, login = env
    (r,) = spike_and_draft(c, app, ha)
    assert "not yet approved" in ask(c, ha, "Who approved the fix?")["answer"]
    assert c.post(f"/api/remediation/{r['id']}/approve", headers=ha, json={"note": "go"}).status_code == 200
    a = ask(c, ha, "Who approved the fix?")
    assert "approved by alpha-admin" in a["answer"] and any(x["type"] == "remediation" for x in a["cites"])
    assert "acknowledged" in a["answer"]


def test_a_viewer_can_ask_and_an_anonymous_caller_cannot(env):
    c, app, ha, login = env
    spike_and_draft(c, app, ha)
    assert ask(c, login("alpha-viewer", "alpha-viewer-pass"), "what is wrong")["intent"] == "open"
    assert c.post("/api/ask", json={"question": "what is wrong"}).status_code == 401
    assert c.get("/api/ask/examples", headers=ha).json() == EXAMPLES


# ---------------------------------------------------------------- it does not guess
def test_unanswerable_questions_get_no_facts_and_no_cites(env):
    c, app, ha, _ = env
    spike_and_draft(c, app, ha)
    for q in ("What is the weather in Paris?", "Who is the CEO?", "write me a poem"):
        a = ask(c, ha, q)
        assert a["intent"] == "unsupported" and a["cites"] == [] and a["facts"] == {} and a["followups"] == EXAMPLES[:5]
    a = ask(c, ha, "How is cache-07?")
    assert a["intent"] == "unknown_node" and "cache-07" in a["answer"] and a["cites"] == []
    assert "no incident INC-99" in ask(c, ha, "Why did INC-99 happen?")["answer"]
    assert ask(c, ha, "")["intent"] == "help"


def test_input_is_validated_and_bounded(env):
    c, app, ha, _ = env
    assert c.post("/api/ask", headers=ha, json={"question": 5}).status_code == 422
    assert c.post("/api/ask", headers=ha, json={}).status_code == 422
    assert len(ask(c, ha, "why " + "x" * 5000)["question"]) <= MAX_Q


# ---------------------------------------------------------------- isolation and privacy
def test_another_tenant_cannot_see_these_incidents_through_questions(env):
    c, app, ha, login = env
    spike_and_draft(c, app, ha)
    hb = login("beta-admin", "beta-demo-pass")
    for q in ("What is wrong right now?", "Why did INC-1 happen?", "Why did app-01 fail?", "What should I do about INC-1?", "Who approved the fix?", "What are the open anomalies?"):
        a = ask(c, hb, q)
        assert "CPU saturation" not in a["answer"] and "root cause db-01" not in a["answer"] and "Scale out" not in a["answer"]      # nothing of alpha's incident
        assert all(x["type"] != "incident" for x in a["cites"]) and "alpha-admin" not in a["answer"]
    assert ask(c, hb, "What is wrong right now?")["facts"]["open_incidents"] == 0
    assert ask(c, hb, "Why did app-01 fail?")["intent"] == "unknown_node"


def test_answers_never_contain_pseudonyms_or_credentials(env):
    c, app, ha, _ = env
    spike_and_draft(c, app, ha)
    for q in EXAMPLES + ["help"]:
        a = ask(c, ha, q)
        blob = repr(a)
        assert not any(p in blob for p in N.values()) and "Bearer" not in blob and "password" not in blob.lower()
