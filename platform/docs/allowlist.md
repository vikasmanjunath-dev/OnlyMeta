# Allow-list and block-list (Phase 1 evidence)

Source of truth: `contracts/schema.py` (`extra="forbid"` on `Payload` and `Metrics`). A field not listed here cannot be serialised by the collector or accepted by the SaaS.

## LEAVES Tier 1 (allow-listed)
| Field | Type | Notes |
|---|---|---|
| payload_id | UUID | idempotency key, created once at enqueue time |
| tenant_id, collector_id, region | str | bound to the collector API key |
| collector_version, config_status | str / ok\|pending\|error | fleet health |
| event_time, sent_at | UTC datetime | event time orders data; sent_at is transport |
| source_tz | str | display only |
| is_replay | bool | sent_at - event_time > 10 s; replay never drives live state |
| node_pseudonym | str | `n-` + HMAC-SHA256(tenant_key, node label)[:10] |
| event_category | METRICS \| SECURITY_BURST \| SERVICE_DOWN | |
| severity | info \| low \| medium \| high \| critical | |
| metrics.cpu / mem / disk / packet_loss | float % | |
| metrics.bandwidth_mbps / latency_ms | float | |
| auth_failures_60s | int | a count only |
| auth_source_pseudonym | str \| null | HMAC pseudonym, never a raw IP |
| schema_version | int | 1 = original contract, 2 = adds `collector_health`; the SaaS accepts both |
| collector_health | object \| null | counters only: queue_depth, oldest_pending_s, dropped_total, blocked_total, sampled_out_total, near_miss_total (no text, no identifiers; unknown keys rejected) |

## STAYS in Tier 1 (never serialised)
Raw log lines and payload bodies; passwords, API keys, tokens; usernames and emails; raw IP addresses and real hostnames (FQDNs); any free-text field; anything not in the schema. Raw store retention: 1 hour.

## Redacted / transformed
| Input | Becomes |
|---|---|
| `sk-…`, `password=…`, `token=…`, Bearer, JWT, AWS key id | `[REDACTED]` in any displayed/local text (`collector/redact.py: scrub`) |
| hostname / node label, source IP | HMAC pseudonym (`pseudo`) |
| failed-login events | `auth_failures_60s` count |
| payload still matching a secret pattern | BLOCKED, never sent, logged (`scan_outbound`) |

## Example
Raw (stays local): `{"host": "prod-db-01.corp.local", "api_key": "sk-proj-9988221100aa", "raw_log": "… password=Summer@2026", "cpu_percent": 94.2}`
Outbound: `{"payload_id": "…", "tenant_id": "tenant-alpha", "node_pseudonym": "n-…", "event_category": "SECURITY_BURST", "severity": "high", "metrics": {"cpu": 94.2, …}, "auth_failures_60s": 14, …}`

Proof: `tests/test_contracts.py::test_no_secret_hostname_or_ip_in_any_outbound_payload` builds all 60 sample events and asserts no secret, FQDN, IP, user or raw log appears in any outbound JSON.
