# CICADA 2026: end-to-end demo and build guide

One document for the whole presentation: **how to run the demo** (every feature, with timings measured on a real stack), **how to explain the build**, and **what to say when it goes wrong**.
Older, narrower scripts still apply: `docs/demo_script.md` (Proof Board only) and `docs/evaluation_map.md` (evaluation sheet to evidence).

---

## 0. The pitch in 20 seconds

> "Companies run monitoring in many places and usually ship raw logs, passwords and keys to one central tool to see everything. We built the opposite: a **collector inside the customer's network** that removes secrets locally and sends only an allow-listed, signed summary to a **multi-tenant SaaS**. The SaaS turns that into live health, one incident with a root cause instead of five alerts, a human-approved fix, and plain-English answers, and every claim on screen can be re-run as a check."

Two tiers, one trust boundary: **raw data never crosses it.**

---

## 1. Before you go on stage

### T-30 min: start a clean stack
```
cd /Users/vkm/Desktop/CICADA2026_Complete/platform
source .venv/bin/activate
python3 tools/demo.py up --fresh
```
`--fresh` wipes old demo databases so the Console opens healthy with no leftover incidents. Add `--tls` to serve https with a throw-away CA (then import `data/tls/ca.pem` into the browser once).
Leave that terminal running (Ctrl-C stops everything). Open a **second** terminal in the same folder, with the venv active, for commands.

### T-10 min: readiness check
```
python3 tools/demo.py preflight --fix
```
Expect `11 pass, 0 warn, 0 fail`. `--fix` primes cold detectors. If anything is amber, fix it now (section 6).

### T-5 min: browser tabs (this order)
| Tab | URL | Sign in | What it is |
|---|---|---|---|
| 1 | `http://127.0.0.1:8000/console` | `alpha-admin` / `alpha-demo-pass` | The customer's live Console (main stage) |
| 2 | `http://127.0.0.1:8000/demo` | prefilled, press **Connect** | Proof Board: one-key re-runnable proofs |
| 3 | `http://127.0.0.1:8001` | none | Collector **Egress Proof Panel** (customer side) |
| 4 | `http://127.0.0.1:8000/tracker` | `alpha-admin` | Engineering view: funnel, hop latency, audit |
| 5 | A **private window** | opened live | For the share link and the second tenant |

Second tenant for the isolation moment: `beta-admin` / `beta-demo-pass` (EU region), in the private window at `/console`.
Zoom the browser so the Console fits the projector. Press **Reset** on the Proof Board (clock 0:00).

### Optional rehearsal (3 minutes, any time)
```
python3 tools/livecheck.py --user alpha-admin --password alpha-demo-pass
python3 tools/consolecheck.py --user alpha-admin --password alpha-demo-pass
```
`livecheck` is the realtime proof (6 checks, it injects a fault, so run it **before** `--fresh` / not during the show). `consolecheck` walks every Console view (13 checks).

### Three commands you will use live (second terminal)
```
python3 tools/inject.py fault --node db-01     # sustained CPU saturation on one node
python3 tools/inject.py clear                  # end it: the platform recovers on screen
python3 tools/inject.py leak                   # fake secrets through the real pipeline
```
(`fault` needs the healthy synthetic feed that `demo.py up` starts by default; if you see `409`, the collector is not on `SOURCES=calm`.)

---

## 2. Choose your length

| Slot | Do |
|---|---|
| **5 min** | Acts 1, 2, 3, 4 (healthy, secret never leaves, fault to fix, isolation) |
| **10 min** | Acts 1 to 7 |
| **15 to 20 min** | Everything, including Act 8 (depth proofs) and Act 9 (operate it) |

Two people is best: one talks, one drives. One person works too.

---

## 3. The demo, act by act

Timings are measured on a real stack. "You say" is a suggestion; keep it short.

### Act 1. A healthy customer Console (about 1 min)
**Do:** Console tab. Point left to right: banner **Operational 3/3**, four KPIs, "Needs your attention" (empty), dependency map `net-01 -> db-01 -> app-01`, Live activity, Collectors.
Click **Fleet**: CPU, memory, disk, latency, loss, network, each with a live sparkline. Hover a sparkline for the crosshair and value.
**You say:** "This is what a customer sees. Everything here is live: the green dot top right is a server-sent event stream. Watch the numbers on Fleet: they tick without a reload."
**Point at:** "updated just now" in the header, the `live` dot, ticking values, the keyboard shortcuts (`Cmd+K` search, `g` then `o i f a p s` to jump).

### Act 2. A secret never leaves (about 1.5 min)
**Do:** Proof Board, press **1** (1 s). Then Collector tab (`:8001`).
**You see:** fake credentials highlighted on the RAW side; none in the OUTBOUND JSON; the SaaS stored hash equals the outbound hash.
Or from the terminal: `python3 tools/inject.py leak` prints `secrets in outbound: 0`.
**You say:** "Secrets are scrubbed on the customer's machine before anything is built for sending. The sent payload only has allow-listed fields (`docs/allowlist.md`), and an outbound scanner refuses anything that still looks like a secret."

### Act 3. Fault to explanation to fix (about 3 min)
**Do:** second terminal: `python3 tools/inject.py fault --node db-01`. Switch to the Console and talk while it unfolds.

| Seconds | What appears on the Console |
|---|---|
| 0 | nothing yet (the platform waits for evidence, on purpose) |
| about 7 | toasts: **db-01 is now Degraded** and **Incident: db-01: unusual combination of metrics** (the multivariate detector fires first); banner turns amber, header pill **FAIR** |
| about 17 | toast **db-01 is now Disrupted**; banner **Disrupted**, ring 2/3, pill **POOR** (the incident title sharpens to "CPU saturation") |
| about 20 | "Needs your attention" shows **Approve: scale out on db-01** (risk low, confidence about 90%) and the unacknowledged incident |

**You say (while waiting):** "It does not page on one reading. The joint detector flags an unusual combination within seconds and opens an incident; a node is only marked disrupted after six consecutive samples over the limit, so a blip never causes an outage banner. That took about 17 seconds here."
**Then:** click **Details** (or open the incident). Walk the page:
- **Why - root cause:** db-01 CPU saturation, with the **weighted score**: coverage 50, timing 30, strength 20 (z-score against db-01's own baseline).
- **Fixes:** ranked recommendations, each with a predicted outcome (labelled an estimate) and a policy line ("needs_approval (1 approval)").
- **Timeline:** opened, fix proposed, and later approved, executed.
**Do:** click **Approve**. The fix shows **executed**; the toast says Approved. Click **Roll back** to show it is reversible.
**You say:** "A human approves. By default execution is simulated and nothing real is touched. Real actions need two keys, shown in Act 8."
**Then:** open **Acknowledge** and **Download post-mortem** to show the incident workflow.
**Finish the act:** `python3 tools/inject.py clear` and watch the banner go back to **Operational**, and the incident resolve after a few clean samples. (Do this before Act 7, so the fleet is calm.)

### Act 4. Ask it in plain English (about 1 min)
**Do:** Console, **Ask**. Click the chips or type: `What is wrong right now?`, `Why did INC-1 happen?`, `What should I do about INC-1?`, `Who approved the fix for INC-1?`, `How long did INC-1 take?`. Then type `what is the weather in Paris`.
**You see:** answers that cite the incident and the audit record; the weather question is **declined** with the list of what it can answer.
**You say:** "This is deliberately not a language model. It is a rules parser over this tenant's own records, so it cannot invent a fact or leak another tenant's data, and it works offline."

### Act 5. Share a read-only link (about 1 min)
**Do:** on the incident page, **Share read-only link** (copies a link, valid 7 days). Paste it into the **private window**. Then Console **Settings -> Share links**: create a **status page** link, open it, then **Revoke** it and refresh the private window.
**You see:** a clean public page: status or incident, no usernames, no IPs, no node ids, no metrics. After revoke it answers 404, the same answer as for any unknown link.
**You say:** "Customers can show their own customers a status page without giving them an account. Only a hash of the token is stored; every create and revoke is audited."

### Act 6. Command palette, themes, roles (about 1 min)
**Do:** `Cmd+K`, type `fleet`, `INC-1`, a node name. Toggle **Theme** to light and back. Sign in as `alpha-viewer` / `alpha-viewer-pass` in the private window to show that a viewer sees the same data but has **no Approve, Acknowledge or Roll back** buttons.
**You say:** "Two roles, enforced on the server, not just hidden in the UI."

### Act 7. Isolation, integrity and resilience (about 2 min)
**Do:** Proof Board, press **4** (instant), then **2** (about 45 s; talk while it runs).
**You see (4):** the EU tenant (beta) gets 404 or 0 rows for alpha's payload, node and incident; three forged deliveries are refused with reasons.
**You see (2):** collector goes OFFLINE, the SaaS marks nodes stale at about 30 s, the link returns, the outbox drains, the ledger reconciles: **0 missing, 0 mismatched**.
**You say while 2 runs:** "The collector writes every payload to a local SQLite outbox before sending and deletes it only after the SaaS acknowledges. Each payload has one id minted once, so a retry after a crash is a duplicate the SaaS absorbs. A silent node is shown stale, never assumed healthy."
**Optional:** sign in as `beta-admin` in the private window: it sees only its own EU fleet and an empty incident list.

### Act 8. Depth proofs (optional, about 4 min)
Proof Board keys, each one a real run with its evidence on screen:

| Key | Proof | Time | The one-line point |
|---|---|---|---|
| **5** | Learned topology | 3 s | It rediscovers `net-01 -> db-01 -> app-01` from telemetry alone; an admin must accept an edge before it affects root cause |
| **6** | Joint anomaly | 16 s | Four metrics each drift 2.6 sigma, no threshold fires, the multivariate test still catches it |
| **8** | Real action, two keys | 2 min | Tenant admin chooses "real", the collector owner enables the actuator; signed 60 s command; verdict `improved` from real telemetry |
| **9** | Counterfactual | 80 s | The naive check says "improved"; the counterfactual says "coincident": the fix is not credited |
| **7** | Ask (board version) | instant | Same engine as Act 4, checked against the API |

Key **C** runs the four core proofs (1, 3, 2, 4) in about 65 s; **R** runs all nine in about 5 min. Proof 3 waits for a calm fleet, so run `python3 tools/inject.py clear` first.

### Act 9. Operate it (optional, about 3 min)
Show that this is a product someone can run, using a **throw-away** environment so the live demo is untouched:
```
export CICADA_ENV=/tmp/demo.env SAAS_DATA=/tmp/demo-data
python3 tools/ctl.py init                       # generates every secret, mode 600
python3 tools/ctl.py doctor                     # checks config, ports, permissions
python3 tools/ctl.py backup                     # consistent SQLite backup + sha256 manifest
python3 tools/ctl.py status
unset CICADA_ENV SAAS_DATA
```
In the Console: **Operations** (autonomy: off / suggest / assisted / auto for low risk; the kill switch; maintenance windows; notifications), **Settings** (People, **Collector keys** with rotation, **Audit trail**, which shows the hash chain as "chain verified" with the entry count), and **Connect a collector** (`Cmd+K`, "Connect"): the three-step onboarding that turns green when the first data arrives.
**You say:** "Onboarding a tenant is one command, secrets are generated not typed, backups are checksummed, and the audit trail is a hash chain: edit or delete any row and verification fails at that row."

### Close (20 s)
> "Raw data never leaves. Delivery is exactly-once in effect. Root cause is explained with weights. Fixes need a human, and a fix is only credited when it beats the node's own trend. Tenants and regions are isolated, the Console is live, and every claim here is a check you can re-run. Our limits, stated openly: remediation is simulated unless two keys are turned; the digital twin is an estimate; the feed is synthetic until we plug in the organiser's stream; TLS here uses a demo CA."

---

## 4. Explaining the build

### 4.1 The 3-minute architecture talk
Draw or show `docs/diagram.png`, then say it in this order.

```
 CUSTOMER NETWORK (trust boundary)                          |   SAAS (multi-tenant, per-region)
                                                            |
 sources ->  adapter  ->  scrub + allow-list  -> outbox ----|-> ingest: verify HMAC, dedup, residency
 (stream,    (the only   (secrets removed,       (SQLite,   |       |  store BEFORE ack
  tail,      module that  pseudonymised ids,     local)     |       v
  syslog,    knows the    outbound scanner)         |       |   engine: health states, stale rule
  calm)      input)                                 v       |       |        |
                                             signed sender  |       |        +-> bus -> SSE -> Console (live)
 actuator <-- signed command (2 keys) <-----------------<---|-------+
 (off / calm / runbook)                                     |   AIOps: anomalies, joint (Mahalanobis),
                                                            |   incidents + root cause, recommendations,
 Egress Proof Panel: raw ⟷ exactly what is sent             |   remediation policy, counterfactual,
                                                            |   learned topology, Ask
                                                            |   audit hash chain, shares, ops (ctl)
```

1. **Two tiers.** The collector runs on the customer's side and is the only thing that ever sees raw data. The SaaS only ever receives allow-listed, signed summaries.
2. **Scrub, then build.** `collector/redact.py` strips secrets with strong patterns plus an entropy detector; `payload.py` builds a payload from an explicit allow-list (`contracts/schema.py`); an outbound scanner is the last gate. Node names are **pseudonyms** (HMAC with a tenant key), so the SaaS never sees real hostnames.
3. **Delivery you can trust.** Outbox first, send second, delete on ACK. One `payload_id` per payload, so retries are idempotent. Requests are HMAC-signed (key id, timestamp, nonce, body hash) with replay protection and rate limits.
4. **Store before ACK.** The SaaS writes the payload, acknowledges, then evaluates asynchronously; on restart it re-queues anything stored but unevaluated. Six timestamps per payload (collected, sent, received, stored, evaluated, published) give measured latency per hop.
5. **Health, then intelligence.** Four health states with a reason for each (worst signal wins, downgrade at once, upgrade after three clean samples). On top: per-node rolling baselines and z-scores, a joint multivariate test, correlation into one incident, a weighted root-cause score over the dependency graph.
6. **Human in the loop.** Recommendations are ranked by confidence times benefit over risk; a policy file decides what needs approval; two keys are needed for real execution; every step lands in the hash-chained audit trail; verification credits a fix only if it beats the counterfactual trend.
7. **Live.** The bus publishes every sample and event; the Console subscribes over SSE and patches values in place, so metrics tick and timers count without reloads.

### 4.2 Design decisions and why (use when asked "why did you...")
| Decision | Reason |
|---|---|
| Collector on the customer side, allow-list not block-list | Safe by construction: a new field cannot leak because it is not on the list |
| Pseudonymised node ids | SaaS compromise reveals no hostnames or IPs |
| HMAC-signed requests, not just an API key | Integrity and replay protection; the key never travels |
| Store-before-ACK + idempotent ids | Crashes and retries lose and duplicate nothing |
| SQLite per region (`saas_in.db`, `saas_eu.db`) | Data residency is physical, not a filter; tenant always comes from the token |
| z-score and Mahalanobis, no black-box model | Deterministic, explainable, O(1) per sample; the benchmark shows where it wins and where it misses |
| Ask is rules, not an LLM | Instant, offline, cannot hallucinate or cross tenants; declines instead of guessing |
| Counterfactual verification | "Improved after the action" is not "because of it"; we do not flatter our own success rate |
| Two keys for real actions | The customer's collector owner must agree, independently of the SaaS admin |
| Single-file Console, no external URLs, strict CSP | Works offline, nothing to leak to a CDN, a small attack surface |
| Share links store only a hash, identical 404s | A leaked database cannot reveal links; no oracle for guessing |

### 4.3 How it was built (a timeline you can narrate)
| Phase | What it added |
|---|---|
| P1 | Collector, schema allow-list, scrubbing, Egress Proof Panel, outbox, scenarios |
| P2 | SaaS backend, signing, tenants and regions, tracker with six-hop latency, audit chain |
| P3 | AIOps: anomalies, incidents, root cause, recommendations, simulated remediation |
| P4 | Proof Board: nine one-click live proofs |
| P5 to P7 | Learned topology, joint (multivariate) anomalies, Ask |
| P8 to P9 | Real actuation with two keys, counterfactual verification |
| P10 | TLS end to end with a demo CA |
| P11 | Operator layer: `ctl` (init, onboard, up, down, backup, restore, doctor), env files |
| P12 | Customer Console, setup wizard, read-only share links |
| P13 to P16 | Restyle to the tracker look, professional polish, realtime (live metrics, ticking timers), refined depth |

### 4.4 Stack and map of the repo
Python 3.12, FastAPI, SQLite (WAL), server-sent events, vanilla JavaScript (one static file per page), Playwright for browser checks.
```
collector/  redact.py payload.py sources.py actuator.py main.py   (customer side)
saas/       app.py engine.py store.py health.py sharing.py aiops/ ui/   (server side)
contracts/  schema.py thresholds.yaml dependency_map.yaml remediation_policy.yaml
tools/      demo.py ctl.py inject.py livecheck.py consolecheck.py aiops_bench.py ...
tests/      377 tests
docs/       demo_runbook.md demo_script.md evaluation_map.md allowlist.md operations.md diagram.png
```

### 4.5 Numbers you can quote (all measured, all reproducible)
| Claim | Number | How to re-check |
|---|---|---|
| Automated tests | 377 passing | `python3 -m pytest -q` |
| Scripted end-to-end drill | 41 checks | `python3 tools/demo.py drill` |
| Proof Board in a real browser | 9/9 (core 4: about 65 s) | `python3 tools/demo.py boardcheck` |
| TLS | 8/8 | `python3 tools/demo.py tlscheck` |
| Console in a real browser | 13/13 | `python3 tools/consolecheck.py ...` |
| Realtime | 6/6: values tick in 1 to 4 s, incident in about 7 s, Disrupted in about 17 s | `python3 tools/livecheck.py ...` |
| Event to dashboard | p95 about 2.6 s on this stack (target 10 s) | Tracker tab, or `preflight` |
| Ingest | about 5.2k payloads/s acknowledged, 0 lost, 0 duplicated over 10,000 | `python3 tools/loadtest.py` |

---

## 5. Likely questions

**Where does data live?** Per-region SQLite files; every query carries the tenant from the session token, never from the request body.
**What if a collector is compromised?** It holds only its own key. Forged tenant ids, edited payloads and unknown fields are refused (Proof 4); keys can be rotated or revoked; abuse of a key raises a security incident.
**How do you know a fix worked?** Counterfactual: fit the node's own pre-action trend, predict what it would have done alone, credit the action only if reality beats that. Other nodes act as peers.
**Why six samples before "Disrupted"?** To avoid an outage banner on a blip. The multivariate detector and the incident still react within seconds (about 7 s here); the six-sample rule is configurable.
**Why not an LLM for Ask?** On purpose, see 4.2. A model could rephrase the already-grounded facts later.
**Why SSE and not websockets?** One-way server push is all the Console needs, it works through proxies, reconnects by itself, and needs no extra dependency.
**What about scale?** Measured about 5.2k payloads/s on one process. The stated path is a message queue and Postgres or Timescale; it is not built.
**Does it need a hand-written dependency map?** No. It learns edges from which node deviates first, repeatedly, with evidence; a person accepts them.
**Is remediation real?** Only when two people say so (tenant admin: actuator = collector; collector owner: `ACTUATOR=calm|runbook`, default off). Otherwise it is simulated and labelled.
**Is the data real?** Synthetic until the organiser's stream is used; the adapter is the only module that knows the input format.
**Honest limits:** single process (rate limiter and live bus are in memory); the Docker files are untested; the digital twin is an estimate; the counterfactual is a statistical attribution under stated assumptions; the demo certificate is a throw-away CA.

---

## 6. If something goes wrong

| Symptom | Likely cause | Fix |
|---|---|---|
| `ports in use` on `up` | An earlier demo is still running | `lsof -tiTCP:8000,8001,8002 -sTCP:LISTEN \| xargs kill`, wait 5 s, run `up --fresh` again |
| `409` from `inject.py fault` | Collector not on the calm source | Start with `demo.py up` (not a file stream); or `SOURCES=calm` |
| Console shows old incidents | Data from earlier runs | Restart with `--fresh` |
| Banner never turns Disrupted | Detectors cold, or fault on a different node | `preflight --fix`; confirm `--node db-01` |
| No Approve card | Policy cooldown after a recent approval on that node, or autonomy off | Wait 2 min, or Operations: set autonomy to Assisted |
| Proof 3 waits or fails | A fault is still active | `python3 tools/inject.py clear`, wait for green, retry |
| Proof says "UI cannot reach collector" | Collector origin allow-list | `CHAOS_ORIGINS=http://127.0.0.1:8000` (the default); `preflight` shows it |
| Console looks unstyled or old | Browser cache | Hard refresh (`Cmd+Shift+R`) |
| Sign-in fails | Passwords overridden by env | `USER_ALPHA_PASSWORD`, or use the values in `.env` |
| Browser warns about the certificate (`--tls`) | Demo CA not trusted | Import `data/tls/ca.pem` once, or accept for 127.0.0.1 and say so |
| Any proof is red | A real failure | Say so, show the failing step's detail, and run `python3 tools/demo.py drill` as the independent check |

## 7. After the demo
Press **Reset** on the Proof Board. `Ctrl-C` the `up` terminal. To re-verify everything on a throw-away stack: `python3 -m pytest -q`, `python3 tools/demo.py drill`, `python3 tools/demo.py boardcheck`.
