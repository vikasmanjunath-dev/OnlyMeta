"""P12: the customer Console page and the read-only share-link service (status page + incident link)."""
import re
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_p3_aiops import env, feed, incs, warm  # noqa: E402,F401


def incident(c, h):
    warm(c)
    feed(c, "db-01", [30, 25, 20, 15, 10, 5, 0], cpu=96.0, latency_ms=160.0)
    L = incs(c, h)
    assert L, "no incident opened"
    return L[0]["id"]


def mkshare(c, h, **b):
    r = c.post("/api/shares", headers=h, json=b)
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------- console page
def test_console_page_is_static_hardened_and_self_contained(env):
    c, *_ = env
    r = c.get("/console")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    assert "default-src 'none'" in r.headers["content-security-policy"] and "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["cache-control"] == "no-store" and r.headers["referrer-policy"] == "no-referrer"
    assert "tenant-alpha" not in r.text and "alpha-admin" not in r.text           # no data baked into the page
    urls = set(re.findall(r"https?://[^\s\"'<>)]+", r.text)) - {"http://www.w3.org/2000/svg"}
    assert not urls, urls                                                          # offline-safe: no CDN, no fonts, no trackers
    for marker in ("Needs your attention", "Dependency map", "Share read-only link", "Connect a collector", "Search or jump to"):
        assert marker in r.text


def test_console_api_calls_need_a_session(env):
    c, *_ = env
    assert c.get("/api/shares").status_code == 401 and c.post("/api/shares", json={"kind": "status"}).status_code == 401


# ---------------------------------------------------------------- status links
def test_status_link_works_without_login_and_leaks_nothing(env):
    c, app, ha, _ = env
    incident(c, ha)
    s = mkshare(c, ha, kind="status", label="Customer page", ttl_h=24)
    assert s["token"].startswith("in.") and s["path"] == "/s/" + s["token"]
    c.headers.pop("Authorization", None)
    r = c.get(s["path"] + "/data")
    assert r.status_code == 200
    d = r.json()
    assert d["kind"] == "status" and d["overall"] in ("EXCELLENT", "GOOD", "FAIR", "POOR") and {n["name"] for n in d["nodes"]} == {"app-01", "db-01", "net-01"}
    assert d["incidents"] and set(d["incidents"][0]) == {"ref", "title", "severity", "kind", "started_ts"}
    raw = r.text
    for secret in ("tenant-alpha", "alpha-admin", "n-", "col-alpha", "ack_by", "region", s["token"]):
        assert secret not in raw.replace("on-", ""), secret
    assert r.headers["x-robots-tag"].startswith("noindex") and r.headers["cache-control"] == "no-store"
    page = c.get(s["path"])
    assert page.status_code == 200 and "text/html" in page.headers["content-type"] and "tenant" not in page.text.lower().replace("tenants", "")


def test_the_token_is_stored_only_as_a_hash(env):
    c, app, ha, _ = env
    s = mkshare(c, ha, kind="status")
    rows = app.state.stores.for_region("in").q("SELECT * FROM share_links")
    assert len(rows) == 1 and s["token"] not in str(rows) and len(rows[0]["token_hash"]) == 64
    assert s["token"] not in str(c.get("/api/shares", headers=ha).json())


def test_view_counter_and_audit_trail(env):
    c, app, ha, _ = env
    s = mkshare(c, ha, kind="status")
    for _ in range(3):
        c.get(s["path"] + "/data")
    L = c.get("/api/shares", headers=ha).json()
    assert L[0]["views"] == 3 and L[0]["status"] == "active" and L[0]["created_by"] == "alpha-admin"
    assert c.delete(f"/api/shares/{s['id']}", headers=ha).status_code == 200
    acts = [a["action"] for a in c.get("/api/audit", headers=ha).json()]
    assert "share_created" in acts and "share_revoked" in acts
    assert c.get("/api/audit/verify", headers=ha).json()["ok"] is True


def test_revoked_and_expired_links_answer_exactly_like_unknown_ones(env):
    c, app, ha, _ = env
    a, b = mkshare(c, ha, kind="status"), mkshare(c, ha, kind="status")
    c.delete(f"/api/shares/{a['id']}", headers=ha)
    app.state.shares.create("tenant-alpha", "in", "alpha-admin", "status", None, "old", 1, now=time.time() - 7200)   # expired an hour ago
    old = app.state.stores.for_region("in").q("SELECT token_hash FROM share_links ORDER BY id DESC LIMIT 1")
    assert old
    unknown = c.get("/s/in.doesnotexist/data")
    revoked = c.get(a["path"] + "/data")
    assert revoked.status_code == unknown.status_code == 404 and revoked.json() == unknown.json()
    assert c.get(b["path"] + "/data").status_code == 200
    assert c.delete(f"/api/shares/{a['id']}", headers=ha).status_code == 404       # already revoked


def test_ttl_is_clamped(env):
    c, _, ha, _ = env
    assert mkshare(c, ha, kind="status", ttl_h=10 ** 9)["expires_ts"] - time.time() <= 24 * 90 * 3600 + 5
    assert mkshare(c, ha, kind="status", ttl_h=0)["expires_ts"] - time.time() > 0


@pytest.mark.parametrize("tok", ["", "nodot", "xx.abc", "in.", "in." + "a" * 300, "in.' OR 1=1 --", "../../etc/passwd", "eu.sameshape", "in.%00"])
def test_garbage_tokens_are_404_never_500(env, tok):
    c, *_ = env
    r = c.get(f"/s/{tok}/data") if tok else c.get("/s//data")
    assert r.status_code in (404, 405) and r.status_code != 500


def test_a_session_token_is_not_a_share_token(env):
    c, app, ha, _ = env
    tok = ha["Authorization"].split()[1]
    assert c.get(f"/s/{tok}/data").status_code == 404


def test_public_endpoint_is_rate_limited(env):
    c, *_ = env
    codes = [c.get("/s/in.x/data").status_code for _ in range(70)]
    assert 429 in codes and codes[0] == 404


# ---------------------------------------------------------------- permissions and isolation
def test_viewers_cannot_manage_links(env):
    c, app, ha, login = env
    hv = login("alpha-viewer", "alpha-viewer-pass")
    assert c.get("/api/shares", headers=hv).status_code == 403
    assert c.post("/api/shares", headers=hv, json={"kind": "status"}).status_code == 403


def test_another_tenant_cannot_see_or_revoke_my_links(env):
    c, app, ha, login = env
    s = mkshare(c, ha, kind="status")
    hb = login("beta-admin", "beta-demo-pass")
    assert c.get("/api/shares", headers=hb).json() == []
    assert c.delete(f"/api/shares/{s['id']}", headers=hb).status_code == 404
    assert c.get(s["path"] + "/data").status_code == 200                              # still alive


def test_bad_requests_are_422(env):
    c, _, ha, _ = env
    assert c.post("/api/shares", headers=ha, json={"kind": "nope"}).status_code == 422
    assert c.post("/api/shares", headers=ha, json={"kind": "incident", "incident": 99999}).status_code == 422
    assert c.post("/api/shares", headers=ha, json={"kind": "incident"}).status_code == 422
    assert c.post("/api/shares", headers=ha, json={"kind": "status", "ttl_h": "abc"}).status_code == 422


# ---------------------------------------------------------------- incident links
def test_incident_link_tells_the_story_without_identities(env):
    c, app, ha, _ = env
    iid = incident(c, ha)
    c.put(f"/api/incidents/{iid}/ack", headers=ha)
    rec = c.get(f"/api/incidents/{iid}", headers=ha).json()["recommendations"][0]
    rid = c.post("/api/remediation/propose", headers=ha, json={"node": rec["node"], "action": rec["action"], "incident_id": iid}).json()["id"]
    c.post(f"/api/remediation/{rid}/approve", headers=ha, json={"note": "approved by alice@example.com"})
    s = mkshare(c, ha, kind="incident", incident=iid, label="INC")
    c.headers.pop("Authorization", None)
    r = c.get(s["path"] + "/data")
    assert r.status_code == 200
    i = r.json()["incident"]
    assert i["root_cause"] == "db-01" and i["status"] == "open" and i["actions"] and i["timeline"] and "db-01" in i["affected"]
    for secret in ("alpha-admin", "alice@example.com", "n-", "tenant-alpha", "ack_by", "approver", "ip"):
        assert secret not in r.text.replace("on-", "").replace("description", ""), secret


def test_incident_link_is_pinned_to_its_incident(env):
    c, app, ha, _ = env
    iid = incident(c, ha)
    s = mkshare(c, ha, kind="incident", incident=iid)
    assert c.get(s["path"] + "/data").json()["incident"]["ref"] == f"INC-{iid}"
