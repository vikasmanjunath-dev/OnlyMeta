# Demo script: 5 minutes, 4 live proofs

Everything below runs on the **Proof Board**: `http://127.0.0.1:8000/demo` (sign-in is prefilled; press **Connect**).
Two people is best: **presenter** talks, **operator** presses keys. One person works too: every proof is one keypress.

## Before the room (T-30 min)
| When | Do | Expect |
|---|---|---|
| T-30 | `python3 tools/demo.py up` (healthy synthetic feed by default; `DEMO_STREAM=file` restores the looping sample storyline) | three processes, URLs printed |
| T-10 | `python3 tools/demo.py preflight --fix` | `11 pass, 0 warn, 0 fail`; `--fix` primes cold detectors |
| T-5 | Open 3 tabs: **/demo** (signed in), **:8001** (collector Egress Proof Panel), **/tracker** (alpha-admin) | Board tiles all green, `detectors warm` |
| T-1 | Press **Reset** on the board; browser zoom so 5 cards fit the projector | clock reads 0:00 |

If anything is amber at T-5, fix it then; do not discover it live. Re-run `preflight` after any restart.

## The five minutes
| Time | Say | Do | The judge sees |
|---|---|---|---|
| 0:00 | "Two tiers. Raw data stays in the customer's network; the SaaS only ever sees a schema allow-list. We will prove six claims live, on the real system." | Point at the **trust strip**: p95 vs the 10 s target, delivered counts, audit chain, fleet, noise, detectors | Live numbers, not slides |
| 0:25 | "Claim 1: a secret never leaves." | Press **1** | Fake credentials highlighted on the RAW side; none in OUTBOUND; SaaS hash identical to the collector's |
| 1:10 | "Claim 2: a network cut loses nothing." | Press **2**. Talk while it runs (below) | Timeline: collector OFFLINE, SaaS marks nodes stale at about +30 s, link back, outbox drained, ledger reconciled: 0 missing, 0 mismatched |
| 2:20 | "Claim 3: it explains, not just alerts." | Press **3** | Incident with a named root (db-01), weighted explanation, z-scores against each node's own baseline, a fix with the twin's prediction |
| 3:10 | "A human approves. Execution is simulated, nothing real is touched." | Click **Approve (simulated)**, then **Roll back** | `executed`, then `rolled_back`; both are in the audit chain |
| 3:40 | "Claim 4: isolation and integrity." | Press **4** | Beta (EU) gets 404 / 0 rows for alpha's payload, node and incident; three forged deliveries refused with reasons |
| 4:15 | "Claim 5: nobody wrote the dependency map for us, and it still finds it." | Press **5** (about 15 s) | Edges net-01 → db-01 → app-01 with ordered counts, p-values and lag; both declared dependencies confirmed; "start together" pairs listed with no guessed direction |
| 4:35 | "Claim 6: it catches what no single threshold can." | Press **6**; talk through the next 30 s (below) | One anomaly, "metric pattern (joint)" on db-01; every metric's bar is green (inside its own ±3σ band); distance² above a chi-square limit |
| 5:10 | "Every proof is a re-runnable check, not a recording." | Point at **6/6** and the clock | `6/6` |
| 5:20 | Close (below) | Open **/tracker** → Audit if asked | Hash-chained audit, SLO card |

**While proof 2 runs (about 45 s), say:** "The collector writes every payload to a local SQLite outbox before sending and only deletes it
after the SaaS acknowledges. Each payload has one id minted once, so a retry after a crash is a duplicate the SaaS absorbs. The SaaS marks
a node stale after 30 s of silence rather than pretending it is healthy."

**While proof 6 runs (about 30 s), say:** "Memory, latency, loss and bandwidth each drift by about about 2.6 standard deviations. Every threshold alert stays silent. We score the whole vector against this node's own mean and covariance; the limit is a probability, one false alarm in a thousand samples, not a tuned number."

**Close (20 s):** "Raw data never leaves, delivery is exactly-once in effect, root cause is explained with weights, tenants and regions are
isolated, and every action is audited. Limits we state openly: remediation is a simulation, the digital twin is an estimate, the feed is
synthetic, and benchmark numbers come from seeded synthetic faults."

## If something goes wrong
| Symptom | Cause | Fix |
|---|---|---|
| Sign-in fails | Passwords overridden | `USER_ALPHA_PASSWORD` / `USER_BETA_PASSWORD`; edit the fields |
| Proof says "UI cannot reach collector" | Collector not started with the SaaS origin | `CHAOS_ORIGINS=http://127.0.0.1:8000` (default); `preflight` shows it |
| Proof 3: no incident | Detectors cold | Click **prime** in the DETECTORS tile, run again |
| Proof 3: "none drafted" | Policy cooldown after an approval in the last 2 minutes | Wait 2 min, or narrate it: "policy refuses a second action on the same node" |
| Proof 3 waits | An earlier incident still open | It waits up to 45 s for a calm fleet; keep talking |
| Proof 2 slow | Outage is real time (40 s) | Narrate the timeline; it recovers on its own |
| Any proof red | Real failure | Say so, show the failing step's detail, run `python3 tools/verify_delivery.py` or `python3 tools/demo.py drill` as the independent check |

## Likely judge questions
- **"Is the remediation real?"** No: allow-listed actions against a simulator, by design. What is real is the policy engine (two-person rule, separation of duties, protected nodes, blast radius, freeze, kill switch), verification, auto-rollback and the audit trail.
- **"Why is p95 about 6 s, not 1 s?"** The measure is event time to dashboard and includes the collector's 5 s aggregation window; the target is 10 s. Hops are measured per payload (Tracker tab).
- **"Why a z-score and not a model?"** Deterministic, explainable, runs per node in O(1). The benchmark shows where it wins and where it misses (small latency shifts); `tools/aiops_bench.py` prints both.
- **"What if the collector is compromised?"** It holds only its own key. A forged tenant, an edited copy or an unknown field is refused (proof 4). A key can be rotated or revoked; abuse of a key opens a security incident.
- **"Where does data live?"** Per-region files (`saas_in.db`, `saas_eu.db`); every query carries the tenant from the token, never from the request.
- **"What happens at scale?"** Ingest was measured at about 5.2k payloads/s acknowledged on one process; the design path (Kafka + TimescaleDB) is stated, not built.
- **"Does it need a hand-written dependency map?"** No. It learns edges from which node deviates first, repeatedly, and shows the evidence (ordered count, sign-test p, lift over chance, lag). The declared map is only the reference it is compared against (confirmed / new / contradicts).
- **"Order of failures is not causation."** Agreed, so a learned edge is a suggestion: nothing changes root-cause analysis until an admin accepts it (audited), edges that would create a cycle are refused, and nodes that start together get no direction at all.
- **"Why not just lower the thresholds?"** Lower per-metric limits raise false alarms on every metric. The joint test keeps one probability (0.1 % per sample) across all five metrics, and it also catches a broken relationship between metrics (CPU up, latency flat) that no threshold sees.
- **"Why synthetic data?"** The healthy feed and faults are generated locally so every anomaly on screen has a visible cause. The adapter is the only module that knows the input format.

## After the demo
Press **Reset**. `python3 tools/demo.py boardcheck` re-runs all six proofs in headless Chrome on a throw-away stack (about 4 min); `python3 tools/demo.py drill` runs the 35 independent checks.
