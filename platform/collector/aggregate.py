"""5-second aggregation per node + rolling 60 s failed-login window. All time is EVENT time, never wall
clock, so replays of the stream behave identically. Raw IPs/usernames never leave this module: only an
HMAC pseudonym and a count come out."""
import re
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

METRICS = ("cpu", "mem", "disk", "bandwidth_mbps", "latency_ms", "packet_loss")
# Free-text hints that a service died. Matched against the raw line LOCALLY; only a boolean ever leaves.
SERVICE_DOWN_RE = re.compile(
    r"(service|daemon|process|unit)\b.{0,40}\b(stopped|crashed|failed|down|not running|exited)"
    r"|connection refused|systemd.{0,40}failed|segfault|oom[- ]kill", re.I)


class LoginWindow:
    """Rolling failed-login counter keyed by source pseudonym. Memory is bounded by trimming on every call."""

    def __init__(self, window_s: int = 60):
        self.window_s = window_s
        self.by_src: dict[str, deque] = {}

    def add(self, ts: datetime, src_pseudonym: str, n: int = 1):
        self.by_src.setdefault(src_pseudonym, deque()).append((ts, n))
        self.expire(ts)

    def expire(self, now: datetime):
        for src in list(self.by_src):
            d = self.by_src[src]
            while d and (now - d[0][0]).total_seconds() >= self.window_s:
                d.popleft()
            if not d:
                del self.by_src[src]

    def snapshot(self, now: datetime) -> tuple[int, Optional[str]]:
        """(total failures in the last window, pseudonym of the top source)."""
        self.expire(now)
        totals = {s: sum(n for _, n in d) for s, d in self.by_src.items()}
        if not totals:
            return 0, None
        top = max(totals, key=totals.get)
        return sum(totals.values()), top


@dataclass
class Sample:
    node: str
    bucket: datetime            # window start (UTC)
    event_time: datetime        # latest event time in the window
    metrics: dict
    auth_failures_60s: int = 0
    auth_source: Optional[str] = None
    raw_id: Optional[int] = None
    late: bool = False
    service_down: bool = False


@dataclass
class _Bucket:
    vals: dict = field(default_factory=lambda: {m: [] for m in METRICS})
    last_ts: Optional[datetime] = None
    raw_id: Optional[int] = None
    down: bool = False


class Aggregator:
    def __init__(self, pseudo_fn: Callable[[str], str], window_s: int = 5, login_window_s: int = 60,
                 node_silent_s: float = 15):
        self.pseudo, self.window_s, self.login_window_s = pseudo_fn, window_s, login_window_s
        self.node_silent_s = node_silent_s          # a node quiet this long is declared SERVICE_DOWN
        self.last_seen: dict[str, datetime] = {}
        self.down: set[str] = set()
        self.open: dict[tuple[str, int], _Bucket] = {}
        self.flushed: set[tuple[str, int]] = set()
        self.logins: dict[str, LoginWindow] = {}
        self.last_known: dict[str, dict] = {}
        self.watermark: Optional[datetime] = None
        self.dropped_incomplete = 0

    def _bucket_of(self, ts: datetime) -> int:
        return int(ts.timestamp() // self.window_s * self.window_s)

    def add(self, ev: dict, raw_id: Optional[int] = None) -> list[Sample]:
        ts, node = ev["ts"], ev["node"]
        key = (node, self._bucket_of(ts))
        if ev.get("auth_failed") and ev.get("source_ip"):
            self.logins.setdefault(node, LoginWindow(self.login_window_s)).add(
                ts, self.pseudo(ev["source_ip"]), ev["auth_failed"])
        b = self.open.setdefault(key, _Bucket())
        if self.last_seen.get(node) is None or ts > self.last_seen[node]:
            self.last_seen[node] = ts
        if SERVICE_DOWN_RE.search(ev.get("raw_log") or ""):
            b.down = True
            self.down.add(node)
        elif node in self.down and ts >= self.last_seen[node]:
            self.down.discard(node)                  # fresh, healthy event: the node is back
        for m in METRICS:
            v = ev["metrics"].get(m)
            if v is not None:
                b.vals[m].append(v)
        if b.last_ts is None or ts >= b.last_ts:
            b.last_ts, b.raw_id = ts, raw_id
        out: list[Sample] = []
        if key in self.flushed:                       # late event for a closed window: emit on its own
            s = self._close(key, late=True)
            return [s] if s else []
        if self.watermark is None or ts > self.watermark:
            self.watermark = ts
            out += self.flush_due(ts)
        return out

    def _close(self, key, late=False) -> Optional[Sample]:
        b = self.open.pop(key)
        node, bstart = key
        self.flushed.add(key)
        m = {}
        for name in METRICS:
            if b.vals[name]:
                m[name] = round(sum(b.vals[name]) / len(b.vals[name]), 3)
            elif name in self.last_known.get(node, {}):
                m[name] = self.last_known[node][name]        # carry forward, never invent
            else:
                self.dropped_incomplete += 1
                return None
        self.last_known[node] = dict(m)
        total, top = self.logins.get(node, LoginWindow()).snapshot(b.last_ts)
        return Sample(node=node, bucket=datetime.fromtimestamp(bstart, tz=timezone.utc), event_time=b.last_ts,
                      metrics=m, auth_failures_60s=total, auth_source=top, raw_id=b.raw_id, late=late,
                      service_down=b.down)

    def flush_due(self, now: datetime, check_silence: bool = True) -> list[Sample]:
        """Close every window whose end is <= now (event-time domain; live mode passes wall clock)."""
        out = []
        for key in sorted(k for k in self.open if k[1] + self.window_s <= now.timestamp()):
            s = self._close(key)
            if s:
                out.append(s)
        if check_silence:
            out += self.silent_nodes(now)
        return out

    def silent_nodes(self, now: datetime) -> list[Sample]:
        """One SERVICE_DOWN sample per node that stopped reporting (once per outage; recovery clears it).
        Metrics are the last known values, labelled by the category: we never invent new readings."""
        out = []
        for node, seen in sorted(self.last_seen.items()):
            if node in self.down or (now - seen).total_seconds() <= self.node_silent_s or node not in self.last_known:
                continue
            self.down.add(node)
            out.append(Sample(node=node, bucket=datetime.fromtimestamp(self._bucket_of(now), tz=timezone.utc),
                              event_time=now, metrics=dict(self.last_known[node]), service_down=True))
        return out

    def flush_all(self) -> list[Sample]:
        return [s for s in (self._close(k) for k in sorted(self.open)) if s]
