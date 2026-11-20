"""Shared payload contract (Tier 1 -> Tier 2). Everyone builds to this file.

The allow-list is STRUCTURAL: both models forbid unknown fields, so anything not
declared here cannot be serialised by the collector or accepted by the SaaS.
Changes need a group-chat announcement.
"""
from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class Metrics(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cpu: float            # percent
    mem: float            # percent
    disk: float           # percent
    bandwidth_mbps: float
    latency_ms: float
    packet_loss: float    # percent


SCHEMA_VERSION = 2                      # emitted by this collector
SUPPORTED_SCHEMA_VERSIONS = (1, 2)      # accepted by the SaaS (rolling upgrades: old collectors keep working)


class CollectorHealth(BaseModel):
    """The collector's own vital signs. Counters and a queue age only: no text, no identifiers."""
    model_config = ConfigDict(extra="forbid")
    queue_depth: int = 0              # payloads waiting in the outbox
    oldest_pending_s: float = 0.0     # age of the oldest unsent payload
    dropped_total: int = 0            # shed under backpressure (lowest severity first); never silent
    blocked_total: int = 0            # stopped by the outbound secret scanner
    sampled_out_total: int = 0        # stable samples skipped by adaptive sampling
    near_miss_total: int = 0          # secret-like strings scrubbed from local text


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")   # unknown field => rejected

    schema_version: int = 1             # 1 = original contract, 2 = adds collector_health
    payload_id: UUID                    # idempotency key, created ONCE at enqueue time
    tenant_id: str
    collector_id: str
    region: str
    collector_version: str
    config_status: Literal["ok", "pending", "error"]
    event_time: datetime                # UTC, when the sample was taken
    source_tz: str                      # e.g. "Asia/Kolkata", display only
    sent_at: datetime                   # UTC, set at send time (transport field)
    is_replay: bool = False             # True if sent_at - event_time > replay cutoff
    node_pseudonym: str                 # "n-" + HMAC-SHA256(tenant_key, hostname)[:10]
    event_category: Literal["METRICS", "SECURITY_BURST", "SERVICE_DOWN"]
    severity: Literal["info", "low", "medium", "high", "critical"]
    metrics: Metrics
    auth_failures_60s: int = 0          # a count only; never usernames, never raw IPs
    auth_source_pseudonym: Optional[str] = None
    collector_health: Optional[CollectorHealth] = None     # schema_version >= 2


# Field names that may leave Tier 1. Used by tests and the docs generator.
ALLOWED_TOP_LEVEL = set(Payload.model_fields)
ALLOWED_METRICS = set(Metrics.model_fields)
ALLOWED_COLLECTOR_HEALTH = set(CollectorHealth.model_fields)
