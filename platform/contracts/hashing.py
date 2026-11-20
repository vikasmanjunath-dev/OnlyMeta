"""Shared by collector AND SaaS: one canonical hash so "what was sent == what was stored" is checkable.

Canonical JSON = sorted keys, no whitespace, event_time normalised to UTC milliseconds with a Z suffix,
EXCLUDING the transport fields sent_at and is_replay (they are stamped at send time and change on retries).
"""
import hashlib
import json
from datetime import datetime, timezone

TRANSPORT_FIELDS = ("sent_at", "is_replay")


def utc_z(value) -> str:
    """Normalise any ISO string / datetime to 'YYYY-MM-DDTHH:MM:SS.mmmZ' (UTC)."""
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def canonical_json(payload: dict) -> str:
    d = {k: v for k, v in payload.items() if k not in TRANSPORT_FIELDS}
    d["event_time"] = utc_z(d["event_time"])
    return json.dumps(d, sort_keys=True, separators=(",", ":"))


def canonical_hash(payload: dict) -> str:
    return hashlib.sha256(canonical_json(payload).encode()).hexdigest()
