# Demo script: core 5 minutes (4 proofs), full ~10 minutes (9 proofs)

Everything runs on the **Proof Board**: `http://127.0.0.1:8000/demo` (sign-in is prefilled; press **Connect**; with `--tls` it is `https://`).
Two people is best: **presenter** talks, **operator** presses keys. One person works too. Every proof is one keypress.
What each evaluation-sheet box maps to: `docs/evaluation_map.md`.

**Measured on a cold stack** (headless Chrome, `boardcheck`): **Run core 4** (key **C**: proofs 1, 3, 2, 4) takes **about 65 s** of machine time (Plan A presses them one by one instead).
**Run all** (key **R**) takes **about 5 min** (proof 8: 2 min, proof 9: 80 s, the rest under 45 s each). Each card shows its own duration.

## Before the room (T-30 min)
| When | Do | Expect |
|---|---|---|
| T-30 | `python3 tools/demo.py up --tls` (or without `--tls` for plain http; healthy synthetic feed by default; `DEMO_STREAM=file` plus `STREAM=<organiser file>` uses the organiser's stream) | three processes, URLs and the CA path printed |
| T-25 | `python3 tools/demo.py tlscheck` (30 s, separate stack) | `8/8 passed`: https works, untrusting and plain-http clients are refused, a wrong CA gets no data |
| T-10 | `python3 tools/demo.py preflight --fix` (with `--tls`: `SAAS_BASE=https://127.0.0.1:8000 SSL_CERT_FILE=data/tls/ca.pem python3 tools/demo.py preflight --fix`) | all pass; `--fix` primes cold detectors |
| T-5 | Open 3 tabs: **/demo** (signed in), **:8001** (collector Egress Proof Panel), **/tracker** (alpha-admin). With `--tls` import `data/tls/ca.pem` once, or use mkcert (`TLS_CA`, `TLS_CERT`, `TLS_KEY`) | Board tiles green, **TRANSPORT: TLS**, `detectors warm` |
| T-1 | Press **Reset**; zoom so the cards fit the projector | clock 0:00 |

If anything is amber at T-5, fix it then; do not discover it live. Re-run `preflight` after any restart.

## Opening (45 s): the two Phase 1 questions
Say: **"Q1, before observability: three sites, each with its own tool and no shared view. The usual fix ships raw logs, passwords and keys to a central platform, which moves the credentials out of the customer's control. Thresholds fire five alerts for one database bottleneck, a dead agent keeps showing its last good value, and nobody can prove what data left."**
Say: **"Q2, what we now observe: fleet, infrastructure, network, security and AIOps in one view, with four health states and a reason for each, one incident instead of five alerts with the root cause, signals and action, and a trust strip that proves delivery, audit and exactly what left the building."**
Point at the **trust strip**: p95 against the 10 s target, delivered counts, audit chain, fleet, noise, **TRANSPORT**.

## Plan A: core, 5 minutes (keys **1**, **3**, **4**, **2**)
Key **C** runs the same four back to back in about 65 s: use it to rehearse, or as the fallback if time is cut short. Press the keys one by one
live, because the approval step has to happen between proofs 3 and 2 (an outage in proof 2 makes the node data stale, and policy then refuses a late approval).
| Time | Say | Do | The judge sees |
|---|---|---|---|
| 0:45 | "Four claims, live, on the real system. Claim 1: a secret never leaves." | Press **1** (1 s). Then open **:8001** | Fake credentials highlighted on the RAW side; none in OUTBOUND (the egress panel shows the same bytes); the SaaS hash is identical to the collector's |
| 1:15 | "Claim 2: it explains, not just alerts." | Press **3** (about 20 s). Read the weighted explanation | Incident with a named root (db-01), weights (coverage 0.5, timing 0.3, strength 0.2), z-scores against each node's own baseline, a fix with the digital twin's prediction |
| 1:50 | "A human approves. Execution is simulated, nothing real is touched." | Click **Approve (simulated)**, then **Roll back** on the card | `executed`, then `rolled_back`; both in the audit chain |
| 2:20 | "Claim 3: isolation and integrity." | Press **4** (instant) | Beta (EU) gets 404 / 0 rows for alpha's payload, node and incident; three forged deliveries refused with reasons |
| 2:40 | "Claim 4: a network cut loses nothing." | Press **2** (about 45 s). Talk while it runs (below) | Collector OFFLINE, SaaS marks nodes stale at about +30 s, link back, outbox drained, ledger reconciled: 0 missing, 0 mismatched |
| 3:35 | "Every proof is a re-runnable check, not a recording." | Point at **4/9** and the clock; mention `tlscheck` | `4/9` (the other five are bonus depth) |
| 3:50 | Close (below) | Q&A below; keep `docs/evaluation_map.md` open | |

## Plan B: full, about 10 minutes (press **R**; 5 min of machine time)
Run Plan A first, then press the rest (or press **R** once for everything; it takes about 5 min of machine time), talking over each:
| Proof | Machine time | Say | The judge sees |
|---|---|---|---|
| 7 Ask | instant | "Ask it in plain English; no model, so no invention." Then type one question live in the Tracker's Incidents tab | Answers name the incident, root cause and confidence, each cited; "weather in Paris" is declined; beta gets "unknown node" |
| 5 Learned topology | 3 s | "Nobody wrote the dependency map for us, and it still finds it." | Edges net-01 → db-01 → app-01 with ordered counts, p-values and lag; both declared dependencies confirmed |
| 6 Joint anomaly | 16 s | "It catches what no single threshold can." Talk through the 16 s (below) | One anomaly "metric pattern (joint)" on db-01; every metric's bar is green; distance² above a chi-square limit |
| 8 Real action | 2 min | "A real action, two keys, verified by telemetry." Use the Q&A below while it runs | `improved`: CPU before → after; counterfactual `caused`; beta offers nothing |
| 9 Counterfactual | 80 s | "A fix is only credited when it beats the node's own trend." | Naive: improved. Counterfactual: coincident, not credited |
| End | | Point at **9/9** | `9/9` |

**While proof 2 runs (about 45 s), say:** "The collector writes every payload to a local SQLite outbox before sending and only deletes it
after the SaaS acknowledges. Each payload has one id minted once, so a retry after a crash is a duplicate the SaaS absorbs. The SaaS marks
a node stale after 30 s of silence rather than pretending it is healthy."

**While proof 6 runs (about 16 s), say:** "Memory, latency, loss and bandwidth each drift by about about 2.6 standard deviations. Every threshold alert stays silent. We score the whole vector against this node's own mean and covariance; the limit is a probability, one false alarm in a thousand samples, not a tuned number."

**Close (20 s):** "Raw data never leaves, delivery is exactly-once in effect, root cause is explained with weights, tenants and regions are
isolated, and every action is audited. Limits we state openly: remediation is simulated unless two keys are turned, the digital twin is an estimate, the feed is
synthetic until the organiser's stream is used, TLS here uses a throw-away CA, and benchmark numbers come from seeded synthetic faults."

## If something goes wrong
| Symptom | Cause | Fix |
|---|---|---|
| Sign-in fails | Passwords overridden | `USER_ALPHA_PASSWORD` / `USER_BETA_PASSWORD`; edit the fields |
| Proof says "UI cannot reach collector" | Collector not started with the SaaS origin | `CHAOS_ORIGINS=http://127.0.0.1:8000` (default); `preflight` shows it |
| Proof 3: no incident | Detectors cold | Click **prime** in the DETECTORS tile, run again |
| Proof 3: "none drafted" | Policy cooldown after an approval in the last 2 minutes | Wait 2 min, or narrate it: "policy refuses a second action on the same node" |
| Proof 3 waits | An earlier incident still open | It waits up to 45 s for a calm fleet; keep talking |
| Proof 2 slow | Outage is real time (40 s) | Narrate the timeline; it recovers on its own |
| Browser warns about the certificate (`--tls`) | The demo CA is not trusted by the browser yet | Import `data/tls/ca.pem` once, or use mkcert; or accept the warning for 127.0.0.1 and say so |
| Collector cannot deliver after switching to `--tls` | Collector started without the CA | `up --tls` sets `CA_BUNDLE` for you; by hand: `CA_BUNDLE=data/tls/ca.pem` |
| Any proof red | Real failure | Say so, show the failing step's detail, run `python3 tools/verify_delivery.py` or `python3 tools/demo.py drill` as the independent check |

## Likely judge questions
- **"How do you know the fix worked?"** We do not stop at before/after: we fit the node's own pre-action trend, predict what it would have done alone, and credit the action only if reality beats that by a stated margin, with other nodes as a control. A node that was already healing is reported as coincident; too little history is reported as inconclusive. It is a statistical attribution under stated assumptions, not a proof.
- **"Why is p95 about 6 s, not 1 s?"** The measure is event time to dashboard and includes the collector's 5 s aggregation window; the target is 10 s. Hops are measured per payload (Tracker tab).
- **"Why a z-score and not a model?"** Deterministic, explainable, runs per node in O(1). The benchmark shows where it wins and where it misses (small latency shifts); `tools/aiops_bench.py` prints both.
- **"What if the collector is compromised?"** It holds only its own key. A forged tenant, an edited copy or an unknown field is refused (proof 4). A key can be rotated or revoked; abuse of a key opens a security incident.
- **"Where does data live?"** Per-region files (`saas_in.db`, `saas_eu.db`); every query carries the tenant from the token, never from the request.
- **"What happens at scale?"** Ingest was measured at about 5.2k payloads/s acknowledged on one process; the design path (Kafka + TimescaleDB) is stated, not built.
- **"Does it need a hand-written dependency map?"** No. It learns edges from which node deviates first, repeatedly, and shows the evidence (ordered count, sign-test p, lift over chance, lag). The declared map is only the reference it is compared against (confirmed / new / contradicts).
- **"Order of failures is not causation."** Agreed, so a learned edge is a suggestion: nothing changes root-cause analysis until an admin accepts it (audited), edges that would create a cycle are refused, and nodes that start together get no direction at all.
- **"Why not just lower the thresholds?"** Lower per-metric limits raise false alarms on every metric. The joint test keeps one probability (0.1 % per sample) across all five metrics, and it also catches a broken relationship between metrics (CPU up, latency flat) that no threshold sees.
- **"Is the remediation real?"** Only when two people say so: the tenant admin sets the actuator to collector, and the customer's collector owner runs it with the actuator on (default off). The SaaS sends a signed, 60-second command; the collector re-verifies it, runs only what its own allow-list names, and reports back. Success is judged from the node's own telemetry afterwards, and a refused command aborts the action instead of pretending.
- **"Why is the Q&A not an LLM?"** On purpose: it is a rules parser over the tenant's own records, so it is instant, offline, deterministic and cannot hallucinate or leak another tenant's data; every answer lists its citations. The trade-off is a fixed vocabulary, and it says so when it cannot parse a question.
- **"Why synthetic data?"** The healthy feed and faults are generated locally so every anomaly on screen has a visible cause. The adapter is the only module that knows the input format.

## After the demo
Press **Reset**. `python3 tools/demo.py boardcheck` re-runs all nine proofs in headless Chrome on a throw-away stack (about 5 min; `--core` for the four core proofs, about 1 min; `--tls` over https); `python3 tools/demo.py drill` runs the 41 independent checks.
