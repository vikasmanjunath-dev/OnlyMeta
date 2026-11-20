"""Minimal raw-event -> Payload builder (Phase 1 reference; P1 extends it with aggregation/outbox).

Everything that is not copied into the schema stays behind: raw_log, user, src_ip, host, api_key, ...
"""
import uuid
from datetime import datetime, timezone

from contracts.schema import SCHEMA_VERSION, CollectorHealth, Metrics, Payload
from collector.redact import pseudo


def _parse(ts: str) -> datetime:
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def severity_for(raw: dict, auth_failures_60s: int) -> str:
    if auth_failures_60s >= 10 or raw["packet_loss_pct"] > 10 or raw["cpu_percent"] > 95:
        return "critical"
    if auth_failures_60s >= 5 or raw["cpu_percent"] > 85 or raw["latency_ms"] > 250 or raw["packet_loss_pct"] > 2:
        return "high"
    if raw["cpu_percent"] > 70 or raw["latency_ms"] > 100:
        return "medium"
    return "info"


def build_payload(raw: dict, *, tenant_id: str, region: str, source_tz: str, collector_id: str,
                  tenant_key: bytes, auth_failures_60s: int = 0, now: datetime | None = None,
                  version: str = "0.1.0") -> Payload:
    now = now or _parse(raw["ts"])
    event_time = _parse(raw["ts"])
    burst = auth_failures_60s >= 5
    return Payload(
        payload_id=uuid.uuid4(),            # created once, at enqueue time
        tenant_id=tenant_id, collector_id=collector_id, region=region, collector_version=version,
        config_status="ok", event_time=event_time, source_tz=source_tz, sent_at=now,
        is_replay=(now - event_time).total_seconds() > 10,
        node_pseudonym=pseudo(raw["node"], tenant_key),
        event_category="SECURITY_BURST" if burst else "METRICS",
        severity=severity_for(raw, auth_failures_60s),
        metrics=Metrics(cpu=raw["cpu_percent"], mem=raw["mem_percent"], disk=raw["disk_percent"],
                        bandwidth_mbps=raw["bandwidth_mbps"], latency_ms=raw["latency_ms"],
                        packet_loss=raw["packet_loss_pct"]),
        auth_failures_60s=auth_failures_60s,
        auth_source_pseudonym=pseudo(raw["src_ip"], tenant_key) if auth_failures_60s else None,
    )


# ---------------- aggregated-sample path used by the live pipeline ----------------
def severity_from_metrics(m: dict, auth_failures_60s: int, fair_logins: int = 5, poor_logins: int = 10) -> str:
    if auth_failures_60s >= poor_logins or m["packet_loss"] > 10 or m["cpu"] > 95:
        return "critical"
    if auth_failures_60s >= fair_logins or m["cpu"] > 85 or m["latency_ms"] > 250 or m["packet_loss"] > 2 or m["mem"] > 90:
        return "high"
    if m["cpu"] > 70 or m["latency_ms"] > 100 or m["mem"] > 80 or m["packet_loss"] > 1 or auth_failures_60s >= 3:
        return "medium"
    return "info"


def build_from_sample(sample, s, now: datetime | None = None, health: CollectorHealth | None = None) -> Payload:
    """Build the allow-listed Payload from an aggregated Sample. Only numbers, enums and pseudonyms are
    copied; no free text can reach the payload (layer 1 of the redaction defence)."""
    now = now or datetime.now(timezone.utc)
    m = sample.metrics
    down = getattr(sample, "service_down", False)
    return Payload(
        schema_version=SCHEMA_VERSION if health is not None else 1,
        payload_id=uuid.uuid4(), tenant_id=s.tenant_id, collector_id=s.collector_id, region=s.region,
        collector_version=s.version, config_status=getattr(s, "config_status", "ok"), event_time=sample.event_time, source_tz=s.source_tz,
        sent_at=now, is_replay=False, node_pseudonym=pseudo(sample.node, s.pseudo_key),
        event_category="SERVICE_DOWN" if down else (
            "SECURITY_BURST" if sample.auth_failures_60s >= s.burst_threshold else "METRICS"),
        severity="critical" if down else severity_from_metrics(m, sample.auth_failures_60s, s.fair_logins, s.burst_threshold),
        metrics=Metrics(cpu=m["cpu"], mem=m["mem"], disk=m["disk"], bandwidth_mbps=m["bandwidth_mbps"],
                        latency_ms=m["latency_ms"], packet_loss=m["packet_loss"]),
        auth_failures_60s=sample.auth_failures_60s,
        auth_source_pseudonym=sample.auth_source, collector_health=health,
    )
