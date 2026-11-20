# CICADA 2026 · Secure Two-Tier AIOps Observability

Phase 1 scaffold: the shared contracts every teammate builds to, plus tests proving the allow-list and redaction.

```
contracts/   schema.py thresholds.yaml tenants.yaml dependency_map.yaml sample_stream.jsonl
collector/   redact.py (scrub, scan_outbound, pseudo)  payload.py (raw event -> Payload)
saas/        P2: app.py engine.py store.py health.py tracker.py topology.py ui/tracker.html   (P3: saas/aiops/ next)
tools/       gen_sample_stream.py (more: inject.py, verify_delivery.py, latency_report.py)
docs/        diagram.png  allowlist.md  feature_list.md  decisions.md  phase1_pack.pdf  demo_script.md
tests/       test_contracts.py
```

## Run
```
pip3 install -r requirements.txt
python3 -m pytest -q                              # 182 tests (contracts, collector, SaaS)
python3 -m saas.main                              # terminal 1: real SaaS :8000 + tracker http://127.0.0.1:8000/tracker
python3 -m collector.main                         # terminal 2: collector + Egress Proof Panel http://127.0.0.1:8001
TENANT=tenant-beta python3 -m collector.main --port 8002   # optional 2nd tenant (COLLECTOR_DB auto per tenant)
python3 tools/inject.py secret                    # also: outage --seconds 30 | bruteforce --n 15 | latency --ms 400
                                                  #       cpu --pct 95 | incident | dup --n 3 | ooo
python3 tools/verify_delivery.py --collector-db data/collector_alpha.db --saas-url http://localhost:8000
```
Env: `SAAS_URL` (default http://localhost:8000/ingest), `KEY_ALPHA`/`KEY_BETA`, `PSEUDO_KEY`, `STREAM`, `SPEED`, `REBASE`, `LOOP`.

## Demo extras (one command each)
```
python3 tools/demo.py up          # SaaS :8000 + alpha collector :8001 + beta collector :8002 (Ctrl-C stops all); healthy synthetic feed
python3 tools/demo.py preflight   # demo-day readiness check against a running `up` (--fix primes cold detectors)
python3 tools/demo.py boardcheck  # drives the /demo Proof Board in headless Chrome on a throw-away stack (needs Playwright)
python3 tools/demo.py drill       # self-checking: isolation, CLI scenarios, AIOps, Proof Board evidence, kill -9 recovery; 35 checks
```
Then open **http://127.0.0.1:8000/demo** (the Proof Board; `docs/demo_script.md` is the 5-minute script).
`drill` runs in a throw-away data dir on ports 18000-18002, so it never touches `data/`. With `up` running, sign in as `beta-admin`
and point the Chaos tab at `http://127.0.0.1:8002` to drive the EU collector.

## Phase 1 evidence for the judge
| Ask | Where |
|---|---|
| One-page data-flow sketch with trust boundary | `docs/diagram.png` (full pack: `docs/phase1_pack.pdf`) |
| Allow-list fields + redaction examples | `docs/allowlist.md`, `contracts/schema.py`, `tests/test_contracts.py` |
| Simulated-telemetry plan + roles | `docs/phase1_pack.pdf` p.10-11, `contracts/sample_stream.jsonl`, `tools/gen_sample_stream.py` |
| Prioritised features + MVP demo | `docs/feature_list.md` |
| 5-minute demo script (Proof Board) | `docs/demo_script.md` |

Read `docs/decisions.md` first: one design decision (pseudonyms vs dependency map) needs a team answer.

## P1 additions (SERVICE_DOWN, config polling, latency report)
- **SERVICE_DOWN** (`event_category`, severity critical): a node silent for `node_silent_s` (15 s) or a log line matching a
  service-failure pattern. Sent once per outage; the next healthy event clears it. Log text stays local; only the enum leaves.
- **Config polling** every 30 s: `GET /collector/config` (signed request; 404 = none). Whitelisted, bounded keys:
  `burst_threshold, fair_logins, node_silent_s, batch_size, raw_retention_s`. Bad config is rejected, old values stay, and
  `config_status` in each payload becomes `error`. P2: implement this endpoint; `tools/mock_saas.py` has a stand-in.
- **Latency report** (measured, event time to SaaS ACK; replayed payloads reported separately):

```
python3 tools/latency_report.py --collector-db data/collector_alpha.db
python3 tools/inject.py servicedown
python3 tools/inject.py config --burst 8
```

## P2 · SaaS backend + end-to-end tracker
Run `python3 -m saas.main`, then open **http://127.0.0.1:8000/tracker** (dev logins `alpha-admin / alpha-demo-pass`, `beta-admin / beta-demo-pass`; override with `USER_ALPHA_PASSWORD`, `KEY_ALPHA`, ...).
Every payload is stamped at six hops (collected, sent, received, stored, evaluated, published), so latency per hop and the p95 vs the 10 s target are measured.

| Route | Who | Purpose |
|---|---|---|
| `POST /ingest` | signed collector | validate, residency, dedup on (tenant_id, payload_id), conflict check, STORE then ACK; evaluation is queued; 413 over 500 items |
| `GET /collector/config`, `PUT /api/config` | signed collector / admin | remote config (bounded keys); version bumps on each PUT |
| `POST /api/login`, `/api/logout`, `GET /api/me`, `POST /api/password` | user | persistent session (8 h, hash stored, revocable), 5 tries/min throttle |
| `GET /api/fleet`, `/api/nodes/{n}/history`, `/api/state-history`, `/api/topology`, `/api/stream` (SSE) | user | for P4's dashboard; tenant comes from the token only |
| `GET /api/tracker`, `/recent`, `/payload/{id}`, `POST /reconcile` | user | funnel, hop latency, lineage, exact sent-vs-stored comparison |
| `GET /api/ids` | signed collector or user | ids + hashes for `tools/verify_delivery.py` |

Rules implemented: four health states (worst signal wins; downgrade at once, upgrade after 3 clean samples), stale rule (30 s silence = POOR, checked every 5 s), old replayed samples never move "now", per-region SQLite files (`data/saas_in.db`, `data/saas_eu.db`), schema errors never echo values.
**P3 hook:** `engine.analysers.append(fn)` where `fn(tenant, sample, store) -> [(state, reason)]`; reasons appear in the fleet view. **P4:** consume `/api/stream` (events `hello`, `sample`, `state`, `alert`, `collector`, `bye`). `fleet` keeps `collector` (the worst/offline one) and adds `collectors[]`.
TLS: `python3 -m saas.main --certfile c.pem --keyfile k.pem` (mkcert); plain HTTP on localhost otherwise, stated in the demo.

## P3 · AIOps: anomalies, incidents, root cause, safe remediation
Tabs **Incidents** and **Remediation** in the tracker. Everything below is measured or auditable; nothing touches a real system.
- **Anomalies**: rolling per-node baseline (15 min, 30-sample warm-up), z-score with sigma floor, 2-of-3 confirmation (fast path z>=6), 3 clean samples to clear, anomalous samples are not learned (no baseline poisoning), level shifts re-baseline after 3 min, baselines rebuild from stored events on restart. Linear-trend **forecast** for mem/disk/cpu (r2>=0.8, 30 min horizon).
- **Incidents**: alerts + anomalies on nodes <=2 hops apart within 30 s become ONE incident (merge/resolve lifecycle, timeline). **Root cause** = weighted score (coverage 0.5, timing 0.3, strength 0.2) over the dependency graph; a silent collector is its own root (`collector:<id>`).
- **Recommendations**: rule table per pattern, ranked by confidence x benefit / risk, each with a digital-twin prediction (labelled an estimate).
- **Remediation (simulation)**: allow-listed catalogue, `contracts/remediation_policy.yaml` (every rule reported), autonomy off / suggest / assisted / auto_low, two approvals for high risk, approver must differ from proposer, 15 min expiry, preconditions re-checked at execution, before/after verification ("does not prove causation"), auto-rollback if worse, kill switch, change freeze. Every step is in the hash-chained audit log.
- **API** (all tenant-scoped): `GET /api/aiops/{summary,anomalies,baselines/{node}}` · `GET /api/incidents[/{id}]`, `PUT /api/incidents/{id}/ack` · `GET /api/remediation[/{id}|/catalogue|/config]`, `PUT /api/remediation/config`, `POST /api/remediation/{simulate,propose}`, `POST /api/remediation/{id}/{approve,reject,cancel,rollback}`. Metrics: `cicada_incidents_open`, `cicada_anomalies_open`, `cicada_remediations{status}`.
- **Benchmark**: `python3 tools/aiops_bench.py --seeds 30` (labelled synthetic faults; AIOps vs static thresholds: recall, false anomalies per node-hour, time to detect, RCA top-1 vs "first alert" / "highest z"). It reports its own misses (e.g. a 12->17 ms latency shift is not detected).
- **P3+ (enhancements)**: hour-of-day **seasonal baselines** (`aiops.seasonal`; a nightly batch stops paging) · **SLO card** (measured MTTD/MTTR vs targets in `aiops.slo`, alert-noise reduction) · **signing-key abuse incidents** (a burst of rejected signed requests on one real key id opens a security incident on `sec:<key>`, with an advisory "rotate or revoke") · **flap damping** (same root failing again within 5 min reopens the incident) · **maintenance windows** (`/api/maintenance`; admin, reason required, max 24 h, audited, suppressed-count shown) · **learned ranking** (recommendations are re-weighted by this tenant's own verified outcomes, "improved 4 of 5 runs here") · **policy what-if** (`POST /api/remediation/policy/simulate` replays past proposals under a draft policy, saves nothing) · **signed webhooks** (`contracts/webhooks.yaml`: host allow-list, secrets from env, HMAC + timestamp, retries, delivery log, incident summaries only) · **post-mortem export** (`/api/incidents/{id}/report`).
- **Benchmark** now compares static thresholds, EWMA, rolling MAD and the AIOps z-score on the same labelled faults (recall, time-to-detect, false anomalies per node-hour) and reports where each loses.
- **Demo**: `python3 tools/demo.py up`, then `python3 tools/inject.py incident --ticks 12`; open Incidents, wait ~10 s for a proposal, approve it in Remediation, roll it back. `python3 tools/demo.py drill` checks all of it (35 checks).

## Advancements (P1 + P2)
**Request signing (collector -> SaaS).** Headers `X-Key-Id, X-Timestamp, X-Nonce, X-Signature`; signature = HMAC-SHA256 over
`METHOD \n path?query \n ts \n nonce \n sha256(body)`. The key is never sent. +/-300 s window, nonce cache (replays refused),
constant-time compare, unknown key and bad signature look identical, 429 + `Retry-After` per key (20 rps, burst 40).
Requests signed before a SaaS restart are refused after it (the nonce cache is memory-only), so a captured request cannot be replayed across a restart. Plain `X-Collector-Key` is refused unless `SAAS_ALLOW_LEGACY_KEY=1` (dev tools only). Signing proves integrity and origin; it is NOT encryption: use TLS outside localhost (verified: SaaS with `--certfile/--keyfile`, collector over `https://` with the cert trusted via `SSL_CERT_FILE`).
Rotated key secrets are encrypted at rest (Fernet; `SAAS_KEK` from your secret manager, else an auto-created `data/saas.kek`, chmod 600). Wrong KEK = key unusable, never a crash.

**Keys, sessions, audit.** `POST /api/keys/rotate` (old keys keep working for `key_grace_s`, new secret shown once), `DELETE /api/keys/{id}`,
`GET /api/keys` (admin). Roles `viewer` (read) and `admin`; `/api/users` (create, disable), password change revokes sessions.
`GET /api/audit` + `/api/audit/verify`: per-tenant hash chain; editing or deleting any row breaks verification at that row. Never purged.

**Alert-noise reduction.** `/api/alerts`, `/api/alerts/summary`, `PUT /api/alerts/{id}/ack`. One alert per problem (numbers stripped from the signature),
cool-down re-open, flap detection (4 changes / 5 min = one "flapping" alert), one alert per collector outage instead of one per node. `noise_reduction_pct` = 1 - alerts shown / alert-worthy transitions.

**Reliability.** Store-before-ACK, evaluate afterwards; `recover()` on start re-queues anything stored but unevaluated. Same `payload_id` with different content is refused
(`payload_id_conflict`, audited), never overwritten. Multi-collector per tenant (cap 50): per-collector offline detection and `GET /api/collectors` with self-health.
Retention purge (`SAAS_RETENTION_S`, default 24 h; derived history 7x). Clock-skew estimate in `/api/tracker` (`clock`). Schema v1 and v2 accepted.

**Collector.** Strong secret patterns + entropy detector (near-misses counted, never sent), text-derived failed-login detection, `tail:PATH` and `syslog:HOST:PORT` sources
(`SOURCES=file,tail:/var/log/auth.log`), outbox backpressure (sheds lowest severity first; always recorded as DROPPED), adaptive sampling (`stable_every`, 1-4, remote-config), self-health in every payload.
Chaos panel: the tracker's Chaos tab drives the local collector; every state-changing chaos call needs `X-Chaos: 1` and an origin in `CHAOS_ORIGINS`; raw-data endpoints get no CORS.

**Ops.** `GET /metrics` (Prometheus text; `METRICS_TOKEN` = everything, an admin session = own tenant only). `tools/loadtest.py` (in-process or `--url`).
`Dockerfile` + `docker-compose.yml` + `.env.example` (ports bound to 127.0.0.1).

Measured here (in-process, no network, one laptop-class core): 10,000 payloads across 5 collectors, 0 lost, 0 duplicated: ~2.6k payloads/s with inline evaluation,
~5.2k/s acknowledged with the async queue (evaluation drains right behind). Live over loopback HTTP: p95 event-to-dashboard 1.5 s at the demo stream.

**Known limits:** single process (rate limiter, login throttle and live-stream bus are in memory; several workers need a shared store); ingest runs on the event loop. The Docker files are untested (no daemon in the authoring sandbox).
**Roadmap only (not built):** Postgres/Timescale for scale-out, a real message queue between ingest and evaluation, a managed KMS, mTLS.

## P4 · Judge-first demo layer
- **Proof Board** (`/demo`, `saas/ui/demo.html`): five one-click live proofs, each a real run against the real system, with a verdict and the evidence on screen: (1) a secret never leaves (raw vs outbound, SHA-256 equal on the SaaS), (2) a 40 s network cut loses nothing (live timeline, exact ledger reconciliation), (3) AIOps root cause with weights, z-scores, twin prediction and approve/rollback (simulated), (4) tenant/region isolation and three refused forgeries, (5) dependencies learned from telemetry (P5). Trust strip: p95 vs target, delivered funnel, audit chain, fleet, alert noise, detector warm-up. Keys `1`-`5` run one proof, `R` runs all.
- **Trust boundary kept**: the page is static (no data); the browser calls the SaaS API with each tenant's session and the collector's `/api/chaos/*` endpoints, which are origin-allow-listed and return only evidence (clean outbound JSON, ids and hashes). Raw data stays unreadable cross-origin.
- **Healthy synthetic feed** (`SOURCES=calm`, default for `demo.py up`): app-01/db-01/net-01 report steady values on a virtual 5 s clock; faults appear only when injected. `scenario/prime` back-fills calm history and `POST /api/aiops/baselines/rebuild` (admin, audited) re-learns baselines from it, so detectors are warm in seconds.
- **Fixes found while building it**: incident evidence uses each anomaly's peak z (not the latest sample); the secret scenario uses `app-01` (a one-off node would go silent and hold an incident open).
- **Verification**: `tests/test_p4_board.py` (12), full suite, `demo.py drill` (35 checks), `demo.py boardcheck` (browser, 5/5).

## P5 · Learned topology
- **What it does**: infers "B depends on A" from which node deviates first, failure after failure (`saas/aiops/learn.py`, pure and deterministic). Per node: a robust baseline (median/MAD over a 6 h look-back) and deviation episodes. Per pair: episodes that co-occur within 20 s; the one that starts earlier, consistently, is upstream. An edge needs 3 ordered co-occurrences, a sign-test p <= 0.15, and a lift >= 2.5 over what unrelated nodes would produce by chance; skip-level edges a chain already explains are dropped.
- **Honest by construction**: nodes that start at the same moment are reported as *undirected* (no guessed order). Each edge is compared with the declared map: `confirmed`, `new`, `implied` or `contradicts` (a contradiction is flagged and can only be accepted if it creates no cycle).
- **A human decides**: `GET /api/aiops/topology/learned` returns suggestions with evidence (support, forward/reverse, p, lift, median lag). `POST /api/aiops/topology/learned/decision` (admin, audited as `topology_edge_accept|reject|revoke`) is the only way an edge reaches root-cause analysis and incident merging. Tenant-scoped; thresholds in `contracts/thresholds.yaml` (`aiops.learn`).
- **Demo**: Proof Board card 5 injects six back-dated cascades (`scenario/cascade`: net-01, then db-01 +5 s, then app-01 +10 s, placed 2 h back so they never mix with the live feed) and shows the declared map being rediscovered from telemetry alone, with the evidence for each edge.
- **Verification**: `tests/test_p5_topology.py` (14), full suite, `demo.py drill` (35 checks), `demo.py boardcheck` (browser, 5/5).
- **Limits**: needs repeated failures to learn (3+ per pair); correlation in onset order is evidence, not proof of causation (hence the admin gate); a node that fails more than half of the look-back has no usable baseline; the synthetic cascade is generated, the learner itself is generic.
