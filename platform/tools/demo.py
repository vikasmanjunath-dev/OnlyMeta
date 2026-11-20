"""One-command demo runner for the three 'extras'. Nothing here is mocked: it starts the real SaaS and real collectors.

  python3 tools/demo.py up      SaaS :8000 + alpha collector :8001 + beta collector :8002 (Ctrl-C stops all)
  python3 tools/demo.py preflight [--fix]   demo-day readiness check against a running `up` (--fix primes cold detectors)
  python3 tools/demo.py boardcheck          drives the /demo Proof Board in headless Chrome on a throw-away stack (needs Playwright)
  python3 tools/demo.py drill   self-checking run in a throw-away data dir (ports 18000-18002), prints PASS/FAIL, exit 0 only if all pass
        1. two tenants      each tenant sees only its own data; IN and EU land in separate region files
        2. CLI scenarios    secret / dup / incident / outage via tools/inject.py (the same commands you run by hand)
        3. crash recovery   kill -9 the SaaS while events keep arriving, restart it, verify_delivery = 0 missing for BOTH tenants
"""
import argparse
import json
import os
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
FAKE_SECRETS = [b"Hunter2", b"ghp_FAKEFAKEFAKE1234", b"sk-proj-9988221100"]      # what tools/inject.py secret sends


def http(method, url, body=None, token=None, timeout=10, headers=None):
    h = {"Content-Type": "application/json", **(headers or {})}
    if token:
        h["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None, method=method, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b"null")


def wait(fn, what, timeout=40, every=0.4):
    end, last = time.time() + timeout, None
    while time.time() < end:
        try:
            r = fn()
            if r:
                return r
        except Exception as e:                      # not up yet
            last = e
        time.sleep(every)
    raise TimeoutError(f"timed out waiting for {what} ({last})")


class Stack:
    def __init__(self, data: Path, saas_port, ports: dict, speed="1", source="file"):
        self.data, self.saas_port, self.ports, self.speed, self.source = data, saas_port, ports, speed, source       # ports: {"alpha": 8001, "beta": 8002}
        self.procs = {}
        data.mkdir(parents=True, exist_ok=True)
        self.logs = {}

    def _spawn(self, name, args, env):
        log = open(self.data / f"{name}.log", "ab")
        self.logs[name] = log
        self.procs[name] = subprocess.Popen([PY, *args], cwd=ROOT, env={**os.environ, **env}, stdout=log, stderr=subprocess.STDOUT)

    def start_saas(self):
        self._spawn("saas", ["-m", "saas.main", "--port", str(self.saas_port)], {"SAAS_DATA": str(self.data)})
        wait(lambda: http("GET", f"http://127.0.0.1:{self.saas_port}/healthz"), "SaaS /healthz")

    def start_collector(self, short):
        port = self.ports[short]
        self._spawn(f"collector-{short}", ["-m", "collector.main", "--port", str(port)],
                    {"TENANT": f"tenant-{short}", "SAAS_URL": f"http://127.0.0.1:{self.saas_port}/ingest", "SPEED": self.speed, "SOURCES": self.source, "ACTUATOR": "calm" if (short == "alpha" and self.source == "calm") else "off",
                     "CHAOS_ORIGINS": f"http://127.0.0.1:{self.saas_port},http://localhost:{self.saas_port}",
                     "COLLECTOR_DB": str(self.data / f"collector_{short}.db")})
        wait(lambda: http("GET", f"http://127.0.0.1:{port}/api/status"), f"collector {short}")

    def kill9_saas(self):
        p = self.procs["saas"]
        os.kill(p.pid, signal.SIGKILL)
        p.wait()

    def stop(self):
        for p in self.procs.values():
            if p.poll() is None:
                p.terminate()
        for p in self.procs.values():
            try:
                p.wait(5)
            except subprocess.TimeoutExpired:
                p.kill()

    def status(self, short):
        return http("GET", f"http://127.0.0.1:{self.ports[short]}/api/status")

    def login(self, short, role="admin"):
        pw = f"{short}-demo-pass" if role == "admin" else f"{short}-viewer-pass"
        return http("POST", f"http://127.0.0.1:{self.saas_port}/api/login", {"username": f"{short}-{role}", "password": pw})["token"]

    def saas(self, token, path):
        return http("GET", f"http://127.0.0.1:{self.saas_port}{path}", token=token)

    def inject(self, short, *args):
        r = subprocess.run([PY, "-m", "tools.inject", *args, "--base", f"http://127.0.0.1:{self.ports[short]}"], cwd=ROOT,
                           capture_output=True, text=True, timeout=120)
        return r.returncode == 0, (r.stdout + r.stderr).strip()[-160:]

    def drained(self, short):
        return wait(lambda: self.status(short)["queue_depth"] == 0 and self.status(short)["outage_remaining_s"] == 0, f"{short} outbox to drain", 60)

    def verify(self, short):
        r = subprocess.run([PY, "-m", "tools.verify_delivery", "--collector-db", str(self.data / f"collector_{short}.db"),
                            "--saas-url", f"http://127.0.0.1:{self.saas_port}", "--tenant", f"tenant-{short}"],
                           cwd=ROOT, capture_output=True, text=True, timeout=60)
        return r.returncode == 0, [(r.stdout + r.stderr).strip()[-160:]]


def up():
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))    # `kill` stops the children too
    data = ROOT / "data"
    st = Stack(data, 8000, {"alpha": 8001, "beta": 8002}, source=os.getenv("DEMO_STREAM", "calm"))    # calm = healthy synthetic feed, faults only when injected
    try:
        st.start_saas()
        for t in ("alpha", "beta"):
            st.start_collector(t)
        print("""
 SaaS tracker      http://127.0.0.1:8000/tracker      alpha-admin / alpha-demo-pass     beta-admin / beta-demo-pass
 Alpha collector   http://127.0.0.1:8001              (tenant-alpha, region IN)
 Beta  collector   http://127.0.0.1:8002              (tenant-beta,  region EU)
 In the tracker's Chaos tab, signed in as beta-admin, change the collector URL to http://127.0.0.1:8002 and press Check.
 CLI:  python3 tools/inject.py secret [--base http://127.0.0.1:8002]
 Ctrl-C stops all three.""")
        while all(p.poll() is None for p in st.procs.values()):
            time.sleep(1)
        print("a process exited; see data/*.log")
    except KeyboardInterrupt:
        pass
    finally:
        st.stop()


def drill():
    res = []

    def check(name, ok, detail=""):
        res.append((name, bool(ok), str(detail)))
        print(f"  {'PASS' if ok else 'FAIL'}  {name}  {detail}", flush=True)

    tmp = Path(tempfile.mkdtemp(prefix="cicada-drill-"))
    st = Stack(tmp, 18000, {"alpha": 18001, "beta": 18002}, speed="20")
    try:
        print(f"[drill] data dir {tmp}")
        st.start_saas()
        for t in ("alpha", "beta"):
            st.start_collector(t)
        ta, tb = st.login("alpha"), st.login("beta")
        for t in ("alpha", "beta"):
            wait(lambda: st.status(t)["sent"] > 0, f"{t} first delivery")

        print("[1] second tenant")
        for t in ("alpha", "beta"):
            wait(lambda: st.saas({"alpha": ta, "beta": tb}[t], "/api/tracker/recent?limit=5"), f"{t} rows in tracker")
        ra, rb = st.saas(ta, "/api/tracker/recent?limit=50"), st.saas(tb, "/api/tracker/recent?limit=50")
        ia, ib = {r["payload_id"] for r in ra}, {r["payload_id"] for r in rb}
        check("alpha and beta see different payloads", ia and ib and not (ia & ib), f"{len(ia)} vs {len(ib)} recent, overlap {len(ia & ib)}")
        try:
            st.saas(ta, f"/api/tracker/payload/{next(iter(ib))}")
            leak = True
        except urllib.error.HTTPError as e:
            leak = e.code != 404
        check("alpha cannot open a beta payload (404)", not leak)
        me_a, me_b = st.saas(ta, "/api/me"), st.saas(tb, "/api/me")
        check("regions are IN and EU", (me_a.get("region"), me_b.get("region")) == ("in", "eu"), f"{me_a.get('region')}/{me_b.get('region')}")
        time.sleep(1)

        def tenants_in(db):
            c = sqlite3.connect(f"file:{tmp / db}?mode=ro", uri=True)
            return {r[0] for r in c.execute("SELECT DISTINCT tenant_id FROM events")}
        check("region files hold only their own tenant", (tenants_in("saas_in.db"), tenants_in("saas_eu.db")) == ({"tenant-alpha"}, {"tenant-beta"}),
              f"in={tenants_in('saas_in.db')} eu={tenants_in('saas_eu.db')}")

        print("[2] CLI scenarios")
        ok, out = st.inject("alpha", "secret")
        check("inject secret runs", ok, out[:60])
        ok, out = st.inject("alpha", "dup", "--n", "3")
        check("inject dup: SaaS reports 3 duplicates", ok and '"duplicates_reported_by_saas": 3' in out.replace("'", '"'), out[:70])
        ok, out = st.inject("alpha", "incident")
        check("inject incident runs", ok)
        st.drained("alpha")
        al = st.saas(ta, "/api/alerts?limit=100")
        check("incident produced alerts for alpha", len(al) > 0, f"{len(al)} alerts")
        ok, out = st.inject("beta", "outage", "--seconds", "6")
        check("inject outage runs", ok, out[:60])
        wait(lambda: st.status("beta")["outage_remaining_s"] > 0 or st.status("beta")["mode"] != "live", "beta outage to start", 5)
        time.sleep(7)
        check("beta recovered after the outage (outbox empty)", st.drained("beta"))
        blob = b"".join(p.read_bytes() for p in tmp.glob("saas_*.db*"))
        check("fake secrets never reached the SaaS files", not any(s in blob for s in FAKE_SECRETS))

        print("[2b] P3: anomaly -> incident -> root cause -> proposal -> approve -> rollback")
        bg = subprocess.Popen([PY, "-m", "tools.inject", "incident", "--ticks", "9", "--base", f"http://127.0.0.1:{st.ports['alpha']}"], cwd=ROOT,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            op = lambda: [i for i in st.saas(ta, "/api/incidents?limit=20") if i["status"] == "open" and not i["root_node"].startswith("collector:")]
            wait(op, "an open incident", 40)
            inc = st.saas(ta, f"/api/incidents/{op()[0]['id']}")
            check("incident opened with a named root cause and weighted explanation", inc["root_label"] and inc["explanation"]["factors"], f"{inc['ref']} root {inc['root_label']} ({inc['confidence']})")
            check("alerts are folded into the incident", any(a.get("incident_id") for a in st.saas(ta, "/api/alerts?limit=100")))
            check("anomalies carry z-score evidence", any(a.get("z") for a in st.saas(ta, "/api/aiops/anomalies?limit=50")))
            pend = lambda: [r for r in st.saas(ta, "/api/remediation?limit=20") if r["status"] == "pending_approval" and r["reversible"]]
            wait(pend, "a drafted fix proposal", 40)
            rid = pend()[0]["id"]
            tv = st.login("alpha", "viewer")
            try:
                http("POST", f"http://127.0.0.1:{st.saas_port}/api/remediation/{rid}/approve", {}, tv)
                viewer_ok = True
            except urllib.error.HTTPError as e:
                viewer_ok = e.code != 403
            check("a viewer cannot approve a fix (403)", not viewer_ok)
            r = http("POST", f"http://127.0.0.1:{st.saas_port}/api/remediation/{rid}/approve", {}, ta)
            check("admin approval executes it as a SIMULATION", r["status"] in ("executed", "verified", "approved") and "simulat" in json.dumps(r).lower(), r["status"])
            check("beta's incidents never name an alpha node", not ({i["root_node"] for i in st.saas(ta, "/api/incidents?limit=50")} & {i["root_node"] for i in st.saas(tb, "/api/incidents?limit=50")}))
            r = http("POST", f"http://127.0.0.1:{st.saas_port}/api/remediation/{rid}/rollback", {}, ta)
            check("rollback restores the previous state", r["status"] == "rolled_back", r["status"])
            ev = st.saas(ta, "/api/audit?limit=200")
            check("every step is in the audit chain", sum(1 for e in ev if "remediation" in json.dumps(e)) >= 3, f"{len(ev)} audit rows")
            sm = st.saas(ta, "/api/aiops/summary")
            md = sm["slo"]["mttd"]
            check("SLO card counts detections and never reports a negative time", md["n"] + md["skewed"] >= 1 and (md["p50"] is None or md["p50"] >= 0),
                  f"p50 {md['p50']} s over {md['n']}, {md['skewed']} skipped (drill clock runs 20x)")
            mw = http("POST", f"http://127.0.0.1:{st.saas_port}/api/maintenance", {"node": "net-01", "minutes": 5, "reason": "drill window"}, ta)
            check("maintenance window set, listed and cancelled", mw["status"] == "active" and any(w["id"] == mw["id"] for w in st.saas(ta, "/api/maintenance"))
                  and http("DELETE", f"http://127.0.0.1:{st.saas_port}/api/maintenance/{mw['id']}", None, ta)["ok"])
            pm = http("POST", f"http://127.0.0.1:{st.saas_port}/api/remediation/policy/simulate", {"policy": {"autonomy": "auto_low"}}, ta)
            check("policy what-if replays history and saves nothing", pm["n"] >= 1 and st.saas(ta, "/api/remediation/config")["autonomy"] != "auto_low", f"{pm['n']} proposals, {pm['changed']} would change")
        finally:
            bg.terminate()
            st.drained("alpha")

        print("[2c] P4: Proof Board evidence")
        sb, pa = f"http://127.0.0.1:{st.saas_port}", f"http://127.0.0.1:{st.ports['alpha']}"
        page = urllib.request.urlopen(f"{sb}/demo", timeout=10).read().decode()
        check("/demo serves the Proof Board (8 proofs, no data in the page)", all(k in page for k in ("A secret never leaves", "A network cut loses nothing", "AIOps names the root cause", "Tenants and regions are isolated", "Dependencies are learned", "Many small deviations", "Ask the platform", "only with two keys")) and "tenant-alpha" not in page)
        cx = {"X-Chaos": "1", "Origin": sb}
        ev = http("POST", f"{pa}/api/chaos/scenario/secret", None, headers=cx)
        check("secret scenario returns outbound evidence with 0 credentials", ev["evidence"] and all(e["secrets_in_outbound"] == 0 for e in ev["evidence"]) and not any(x.decode() in json.dumps(ev) for x in FAKE_SECRETS), f"{len(ev['evidence'])} payloads")
        st.drained("alpha")
        time.sleep(2)
        led = http("GET", f"{pa}/api/chaos/ledger", None, headers={"Origin": sb})
        rc = http("POST", f"{sb}/api/tracker/reconcile", {"sent": led}, ta)
        check("collector ledger reconciles exactly with the SaaS store", rc["ok"] and rc["missing_count"] == 0 and rc["hash_mismatch_count"] == 0, f"{rc['claimed']} sent, {rc['missing_count']} missing")
        try:
            http("POST", f"{sb}/api/aiops/baselines/rebuild", {}, st.login("alpha", "viewer"))
            vok = True
        except urllib.error.HTTPError as e:
            vok = e.code != 403
        check("only an admin can rebuild baselines (viewer 403)", not vok)
        check("baseline rebuild is audited", http("POST", f"{sb}/api/aiops/baselines/rebuild", {}, ta)["nodes"] >= 1 and any(e["action"] == "baselines_rebuilt" for e in st.saas(ta, "/api/audit?limit=50")))

        print("[2d] P5: learned topology")
        http("POST", f"{pa}/api/chaos/scenario/cascade?ticks=6", None, headers=cx)
        st.drained("alpha")
        lt = {}
        for _ in range(40):
            lt = http("GET", f"{sb}/api/aiops/topology/learned", None, ta)
            if lt["declared"] and all(d["seen"] for d in lt["declared"]) and sum(lt["episodes"].values()) >= 18:
                break
            time.sleep(1)
        check("declared dependencies rediscovered from telemetry alone, none contradicted", bool(lt["declared"]) and all(d["seen"] for d in lt["declared"]) and not any(e["status"] == "contradicts" for e in lt["edges"]),
              ", ".join(f"{e['up_label']}->{e['dep_label']} {e['forward']}/{e['support']} p={e['p']}" for e in lt["edges"]))
        try:
            http("POST", f"{sb}/api/aiops/topology/learned/decision", {"up": lt["edges"][0]["up"], "dep": lt["edges"][0]["dep"], "decision": "accept"}, st.login("alpha", "viewer"))
            vok = True
        except urllib.error.HTTPError as e:
            vok = e.code != 403
        check("only an admin can accept a learned edge (viewer 403)", not vok)
        lb = http("GET", f"{sb}/api/aiops/topology/learned", None, st.login("beta", "admin"))
        check("beta (EU) learns only from its own nodes", not ({n for e in lb["edges"] for n in (e["up"], e["dep"])} & {n for e in lt["edges"] for n in (e["up"], e["dep"])}), f"beta {len(lb['edges'])} edges, alpha {len(lt['edges'])}")

        print("[2e] P7: ask the platform")
        ask = lambda tok, q: http("POST", f"{sb}/api/ask", {"question": q}, tok)  # noqa: E731
        opn = http("GET", f"{sb}/api/incidents?limit=20", None, ta)
        a1, a2 = ask(ta, "What is wrong right now?"), ask(ta, "Who is the CEO of Google?")
        check("ask: answers cite real incidents of this tenant", a1["intent"] == "open" and all(any(i["id"] == c["id"] for i in opn) for c in a1["cites"] if c["type"] == "incident"), a1["answer"][:90])
        check("ask: an unanswerable question gets no facts and no citations", a2["intent"] == "unsupported" and not a2["cites"] and not a2["facts"])
        ab = ask(st.login("beta", "admin"), "Why did db-01 fail?")
        check("ask: beta cannot reach alpha's nodes or incidents through questions", ab["intent"] == "unknown_node" and not ab["cites"])

        print("[2f] P8: real actuation needs two keys")
        act = http("GET", f"{sb}/api/actuator", None, ta)
        check("actuator: default is the simulator, and this collector (actuator off) offers nothing", act["mode"] == "simulation" and act["capabilities"] == [] and act["commands"] == [], f"online={act['online']}")
        try:
            urllib.request.urlopen(f"{sb}/collector/commands", timeout=5)
            unsigned = 200
        except urllib.error.HTTPError as e:
            unsigned = e.code
        check("actuator: an unsigned request cannot fetch commands", unsigned == 401, str(unsigned))
        try:
            http("PUT", f"{sb}/api/remediation/config", {"actuator": "shell"}, ta)
            bad = 200
        except Exception as e:  # noqa: BLE001
            bad = 422 if "422" in str(e) else str(e)[:60]
        check("actuator: only 'simulation' or 'collector' are accepted values", bad == 422, str(bad))

        print("[3] crash recovery (kill -9)")
        before = st.status("alpha")["sent"]
        st.kill9_saas()
        check("SaaS killed with SIGKILL", st.procs["saas"].returncode == -9)
        st.inject("alpha", "bruteforce", "--n", "8")
        st.inject("beta", "bruteforce", "--n", "8")
        time.sleep(4)
        check("collectors keep buffering while the SaaS is down", st.status("alpha")["queue_depth"] > 0, f"queue {st.status('alpha')['queue_depth']}")
        st.start_saas()
        for t in ("alpha", "beta"):
            st.drained(t)
        time.sleep(2)
        for t in ("alpha", "beta"):
            ok, tail = st.verify(t)
            check(f"verify_delivery {t}: 0 missing / 0 duplicate / 0 mismatch", ok, tail[0][:90])
        check("alpha delivered more after restart", st.status("alpha")["sent"] > before)
    except Exception as e:
        check("drill ran to the end", False, repr(e))
    finally:
        st.stop()
    bad = [r for r in res if not r[1]]
    print(f"\n[drill] {len(res) - len(bad)}/{len(res)} passed" + ("" if not bad else "  FAILED: " + ", ".join(b[0] for b in bad)))
    print(f"[drill] logs in {tmp}")
    return 1 if bad else 0


def preflight(fix=False, saas="http://127.0.0.1:8000", alpha="http://127.0.0.1:8001", beta="http://127.0.0.1:8002"):
    """Demo-day readiness against a running `up` stack. FAIL = the demo will visibly break; WARN = it will work but look off."""
    rows = []

    def chk(name, level, detail=""):
        rows.append((name, level, detail))
        print(f"  {level:4}  {name}" + (f"  - {detail}" if detail else ""))
    try:
        http("GET", f"{saas}/healthz")
        chk("SaaS reachable", "PASS", saas)
    except Exception as e:
        chk("SaaS reachable", "FAIL", f"{saas}: {e}; run `python3 tools/demo.py up` first")
        return 1
    toks = {}
    for short, col in (("alpha", alpha), ("beta", beta)):
        try:
            sta = http("GET", f"{col}/api/status")
            toks[short] = http("POST", f"{saas}/api/login", {"username": f"{short}-admin", "password": f"{short}-demo-pass"})["token"]
            chk(f"{short}: collector online, admin login works", "PASS" if sta["mode"] == "ONLINE" else "FAIL", f"{sta['mode']}, sources {sta['sources']}, queue {sta['queue_depth']}")
            if sta["sources"] != ["calm"]:
                chk(f"{short}: healthy feed", "WARN", f"sources {sta['sources']}: the sample stream loops its own faults; start with DEMO_STREAM=calm")
        except Exception as e:
            chk(f"{short}: collector + login", "FAIL", str(e)[:90])
    if "alpha" not in toks:
        return 1
    ta = toks["alpha"]
    try:
        req = urllib.request.Request(f"{alpha}/api/chaos/status", headers={"Origin": saas, "X-Chaos": "1"})
        urllib.request.urlopen(req, timeout=5)
        pre = urllib.request.Request(f"{alpha}/api/chaos/scenario/secret", method="OPTIONS", headers={"Origin": saas, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "x-chaos"})
        chk("collector accepts the SaaS page's origin (CORS)", "PASS" if urllib.request.urlopen(pre, timeout=5).status == 204 else "FAIL")
    except Exception as e:
        chk("collector accepts the SaaS page's origin (CORS)", "FAIL", f"{e}; start the collector with CHAOS_ORIGINS={saas}")
    n0 = (http("GET", f"{saas}/api/fleet", None, ta)["nodes"] or [{}])[0].get("node")
    warm = False
    if n0:
        b = http("GET", f"{saas}/api/aiops/baselines/{n0}", None, ta)
        warm = b["cpu"]["warm"]
        if not warm and fix:
            http("POST", f"{alpha}/api/chaos/scenario/prime?ticks=40", None, headers={"X-Chaos": "1", "Origin": saas})
            time.sleep(5)
            http("POST", f"{saas}/api/aiops/baselines/rebuild", {}, ta)
            warm = bool(wait(lambda: http("GET", f"{saas}/api/aiops/baselines/{n0}", None, ta)["cpu"]["warm"], "baselines to warm", 20))
        chk("detectors warm", "PASS" if warm else "WARN", f"cpu baseline n={b['cpu']['n']}" + ("" if warm else "; run with --fix to prime, or wait ~150 s"))
    else:
        chk("detectors warm", "WARN", "no nodes yet")
    inc = [i for i in http("GET", f"{saas}/api/incidents?limit=20", None, ta) if i["status"] == "open"]
    chk("no open incident left over", "PASS" if not inc else "WARN", f"{len(inc)} open; they clear on their own once nodes are healthy for 3 samples")
    mw = [w for w in http("GET", f"{saas}/api/maintenance", None, ta) if w["status"] == "active"]
    chk("no active maintenance window (it would hide the incident)", "PASS" if not mw else "FAIL", f"{len(mw)} active")
    cfg = http("GET", f"{saas}/api/remediation/config", None, ta)
    chk("autonomy is 'assisted' and no change freeze", "PASS" if cfg["autonomy"] == "assisted" and not cfg.get("change_freeze") else "WARN", f"autonomy={cfg['autonomy']} freeze={cfg.get('change_freeze')}")
    tk = http("GET", f"{saas}/api/tracker?window_s=600", None, ta)
    p95 = tk["target"]["measured_p95_s"]
    chk("event-to-dashboard p95 within target", "PASS" if p95 is None or tk["target"]["met"] else "FAIL", f"{p95} s vs {tk['target']['p95_s']} s")
    chk("audit chain verifies", "PASS" if http("GET", f"{saas}/api/audit/verify", None, ta)["ok"] else "FAIL")
    wh = http("GET", f"{saas}/api/webhooks", None, ta)
    chk("no outbound webhook configured (nothing can leave by accident)", "PASS" if not wh.get("hooks") and not wh.get("webhooks") else "WARN", "configured hooks are listed in the tracker")
    bad = [r for r in rows if r[1] == "FAIL"]
    print(f"\n[preflight] {len([r for r in rows if r[1] == 'PASS'])} pass, {len([r for r in rows if r[1] == 'WARN'])} warn, {len(bad)} fail" + ("  - ready: open " + saas + "/demo" if not bad else ""))
    return 1 if bad else 0


def boardcheck():
    """Drives the real /demo page in headless Chrome (Playwright) on a throw-away stack: healthy feed, real clock, all eight proofs."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("boardcheck needs Playwright: pip install playwright && playwright install chromium")
        return 2
    tmp = Path(tempfile.mkdtemp(prefix="cicada-board-"))
    st = Stack(tmp, 18100, {"alpha": 18101, "beta": 18102}, speed="1", source="calm")
    ok, detail = False, ""
    try:
        st.start_saas()
        for t in ("alpha", "beta"):
            st.start_collector(t)
        time.sleep(6)
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page(viewport={"width": 1500, "height": 1100})
            pg.goto(f"http://127.0.0.1:{st.saas_port}/demo")
            pg.fill("#ac", f"http://127.0.0.1:{st.ports['alpha']}")
            pg.fill("#bc", f"http://127.0.0.1:{st.ports['beta']}")
            pg.click("#go")
            pg.wait_for_selector("#board:not([hidden])", timeout=10000)
            pg.click("#all")
            pg.wait_for_function("document.querySelector('#all').disabled===false", timeout=300000)
            pg.wait_for_timeout(500)
            verdicts = pg.evaluate("[1,2,3,4,5,6,7,8].map(n=>document.querySelector('#p'+n+' .v').textContent)")
            bad = pg.evaluate("[...document.querySelectorAll('.steps li.bad')].map(l=>l.textContent)")
            pg.screenshot(path=str(tmp / "board.png"), full_page=True)
            b.close()
        ok = all(v == "PROOF HOLDS" for v in verdicts)
        detail = f"{verdicts} {bad}"
    except Exception as e:
        detail = repr(e)
    finally:
        st.stop()
    print(f"[boardcheck] {'PASS' if ok else 'FAIL'}  {detail}\n[boardcheck] screenshot + logs in {tmp}")
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["up", "drill", "preflight", "boardcheck"])
    ap.add_argument("--fix", action="store_true", help="preflight: prime the detectors when they are cold")
    a = ap.parse_args()
    sys.exit({"drill": drill, "up": up, "boardcheck": boardcheck}.get(a.cmd, lambda: preflight(a.fix))())
