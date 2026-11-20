# Prioritised feature list and minimum viable demo (Phase 1 sign-off)

Sign-off: P1 ______  P2 ______  P3 ______  P4 ______  (all four, hour 1.5)

## P0 · MVP (must ship, never cut)
- [ ] Collector reading the organizer stream (only `adapter.py` knows its format) + schema allow-list + secret scrubbing
- [ ] Egress Proof Panel: raw line ⟷ exact outbound JSON, payload_id, SHA-256, status SENT/QUEUED/BLOCKED
- [ ] SQLite outbox: persist → send → ACK → delete; backoff 1, 2, 4, 5 s
- [ ] Authenticated ingest (TLS + per-collector API key), dedup on PRIMARY KEY (tenant_id, payload_id)
- [ ] Four health states + stale-data rule (30 s silence = POOR), live UTC dashboard

## P1 · Score boosters
- [ ] Rolling z-score anomalies (15-min baseline, warm-up fallback, sigma floor)
- [ ] Correlation: alerts within 30 s on dependent nodes merge into one incident with weighted explanation
- [ ] Local failed-login detection (5 in 60 s = Fair, 10 = Poor/brute force)
- [ ] Two tenants (alpha/in, beta/eu) with isolation test
- [ ] Latency clock and measured p95 (`tools/latency_report.py`)

## P2 · If time allows
- [ ] Safe remediation simulation: propose → policy → approve → audit → rollback
- [ ] Fleet page and state history; per-region stores + residency rejection; collector config polling

## Roadmap (stated, not built)
Autonomous Ops with approved reversible actions; seasonal baselines; learned topology; mTLS + key rotation; Kafka + TimescaleDB.

## Minimum viable demo (5 min, 4 proofs)
1. Inject a secret → visible raw side only; absent from outbound JSON and SaaS.
2. Kill SaaS 30 s → POOR within 35 s, queue rises, drains; sent IDs = received IDs, duplicates 0.
3. Inject CPU spike → z-score, baseline, signal weights, recommendation.
4. Beta token requests alpha data → zero rows.

## Cut order if behind
Hour 5: second tenant, fleet page → TLS to plain HTTP on localhost (say so). Hour 8: config polling, tenant login polish → remediation polish. Hour 11: history polish → recommendation table to 3 patterns. Hour 13: freeze.
