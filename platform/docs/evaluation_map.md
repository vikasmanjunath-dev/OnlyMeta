# Evaluation sheet → where it is shown (CICADA 2K26)

One row per box on the evaluation sheet. "Show" is what to do in the room (10 s each); "Backed by" is what the judge can check afterwards.
Proof Board = `/demo` (keys 1-9). Egress panel = the alpha collector, `http://127.0.0.1:8001`. Tracker = `/tracker`.

## Phase 1: Problem understanding and ideation
| Criterion | Show | Backed by |
|---|---|---|
| Why raw telemetry stays local; SaaS gets metadata only | Say the Q1 line (demo script), press **1** | `docs/allowlist.md`, Proof 1 |
| Use cases: infra health, latency/packet loss, failed logins, fleet health | Tracker: Tracker tab (fleet and node health), Alerts tab (failed-login bursts) | `docs/phase1_pack.pdf` p.4 |
| Prioritised features, clear minimum viable demo | The **Run core 4** button is the MVP | `docs/feature_list.md` |
| What stays local / is redacted / is sent; tenant separation | Egress panel, then Proof **4** | `docs/allowlist.md` |
| Feasible 24 h scope, roles, simulated-telemetry plan | One sentence | `docs/phase1_pack.pdf` p.10-11, `docs/feature_list.md`, `tools/gen_sample_stream.py` |
| Q1 before observability | Opening line 1 (demo script) | `docs/phase1_pack.pdf` p.4 |
| Q2 what the team now observes | Opening line 2, then the trust strip | `docs/phase1_pack.pdf` p.4 |

## Phase 2: Architecture and technical design
| Criterion | Show | Backed by |
|---|---|---|
| Two tiers, authenticated link | Trust strip **TRANSPORT** tile (TLS) | `python3 tools/demo.py tlscheck` (8 checks), signed requests, `docs/diagram.png` |
| Collect → filter/redact → aggregate → analyse → policy → send | Proof 1 (redact) and Proof 3 (analyse, policy) | `collector/pipeline.py`, `saas/aiops/` |
| Allow-listing, secret scrubbing, pseudonymous IDs, auth, TLS, audit | Proof 1; Tracker → Audit & keys; tlscheck | `contracts/schema.py`, `collector/redact.py`, hash-chained audit |
| Telemetry: CPU, memory, disk, bandwidth, latency, packet loss | Tracker tab (node cards) | `contracts/schema.py` |
| AIOps beyond static thresholds; scales to many collectors/tenants | Proof 3, Proof 6 (joint); Tracker → Collectors tab | per-node baselines, `fleet_collectors`, two regional stores |
| Global-ready: regional ingest, residency, UTC, out-of-order, idempotent | Proof 4 (alpha IN, beta EU) | per-region SQLite, `payload_id` dedup, event-time evaluation |

## Phase 3: Working prototype
| Criterion | Show | Backed by |
|---|---|---|
| Working collector on the organiser stream; raw/secrets stay local | Start with `STREAM=<organiser file> DEMO_STREAM=file`, then Proof 1 | `collector/adapter.py` is the only module that knows the format; see "Organiser stream" below |
| SaaS shows only allow-listed metadata per tenant | Tracker as alpha-admin vs beta-admin | Proof 4 |
| Dashboard: 4 health states, thresholds, stale-data handling | Tracker tab (node cards, state history); Proof 2 shows the stale state | `saas/health.py` |
| Contextual alerts, outage detection, buffering, retry | Proof 2 | SQLite outbox, backoff, 30 s silence rule |
| Egress proof panel shows the exact payload before it leaves | Open `:8001` during Proof 1 | `collector/egress.py` |
| Real-time: dashboard ≤ 10 s, alert ≤ 15 s, offline ≤ 60 s, zero loss/duplicates | Trust strip p95 tile; Proof 2 reconcile line | `/api/tracker`, `tools/verify_delivery.py`, `tools/latency_report.py` |

## Phase 4: Final demo, validation and presentation
| Criterion | Show | Backed by |
|---|---|---|
| End to end: raw source → actionable recommendation | Proof 3 | recommendation plus digital twin |
| Correct response to live injected scenarios; few false alarms | Proofs 1, 2, 3; the calm feed stays quiet between them | `tools/inject.py`, noise-reduction tile |
| Explainable AIOps (weighted higher) | Proof 3: root cause, weights (coverage 0.5, timing 0.3, strength 0.2), z-scores, why this action; Proof 9 (did the fix work) | `saas/aiops/correlate.py`, `counterfactual.py` |
| Honest limitations; privacy/correlation innovation | The close (demo script) | README "Limits" per section; pseudonymous IDs, learned topology |
| Clear presentation; confident answers | `docs/demo_script.md` Q&A | |

## Mandatory and bonus
| Item | Where |
|---|---|
| Real-time measured from timestamps | Trust strip p95 tile, Tracker hop timings |
| Shared organiser telemetry stream | see below |
| Egress proof panel present | `:8001` |
| Bonus: privacy pipeline · local buffering · explainable AIOps · alert-noise reduction · safe remediation · global-ready | Proofs 1 · 2 · 3 · noise tile · 3 (approve/rollback), 8, 9 · 4 |

## Organiser stream (to do on the day, 5 min)
`contracts/sample_stream.jsonl` is our assumed raw format. When the organiser's file arrives: put it anywhere, run
`STREAM=/path/to/file DEMO_STREAM=file python3 tools/demo.py up`, open the egress panel and check the Proof 1 line. If a field
name differs, edit `METRIC_MAP` in `collector/adapter.py` (only that module changes) and re-run `python3 -m pytest -q tests/test_collector.py`.
Missing fields become empty, never a crash; malformed lines are counted and skipped.

## What is simulated or limited (say it before they ask)
Remediation is simulated unless a tenant admin and the collector owner both switch real actuation on (P8). The feed is synthetic
unless the organiser's stream is used. Localhost uses a throw-away CA for TLS (`--tls`); production would use a real certificate.
