"""Tier 1 pipeline: raw event -> raw store (local) -> 5 s aggregate -> allow-listed payload -> secret scan ->
egress log + outbox (one atomic transaction) . Raw data never leaves this process except as schema fields."""
import asyncio
import json
import time
from collections import Counter
from datetime import datetime, timezone
from typing import Optional

from collector.adapter import FileSource
from collector.aggregate import Aggregator, Sample
from collector.egress import EgressLog
from collector.outbox import SEV_RANK, Outbox
from collector.payload import build_from_sample
from collector.redact import pseudo, scan_outbound, secret_summary
from collector.sources import make_sources
from collector.store import DB, RawStore
from contracts.schema import CollectorHealth


def severity_is_info(sample, s) -> bool:
    from collector.payload import severity_from_metrics
    return severity_from_metrics(sample.metrics, sample.auth_failures_60s, s.fair_logins, s.burst_threshold) == "info"


class Pipeline:
    def __init__(self, settings, db: Optional[DB] = None):
        self.s = settings
        self.db = db or DB(settings.db_path)
        self.raw = RawStore(self.db, settings.raw_retention_s)
        self.egress = EgressLog(self.db)
        self.outbox = Outbox(self.db)
        self.agg = Aggregator(lambda v: pseudo(v, settings.pseudo_key), settings.window_s, settings.login_window_s,
                              settings.node_silent_s)
        self.events_in = self.payloads_out = self.blocked = 0
        self.dropped = self.sampled_out = self.near_miss = 0
        self.near_miss_kinds: Counter = Counter()
        self.sources: list = []
        self._stable_seen: dict[str, int] = {}
        self._last_stable: dict[str, bool] = {}
        self._health_cache = (0.0, 0, 0.0)

    def health(self) -> CollectorHealth:
        """Vital signs stamped into each payload. Queue figures are cached for 1 s: cheap even at high rates."""
        t, depth, age = self._health_cache
        if time.monotonic() - t > 1.0:
            depth, age = self.outbox.depth(), self.outbox.oldest_pending_age()
            self._health_cache = (time.monotonic(), depth, age)
        return CollectorHealth(queue_depth=depth, oldest_pending_s=round(age, 1), dropped_total=self.dropped,
                               blocked_total=self.blocked, sampled_out_total=self.sampled_out, near_miss_total=self.near_miss)

    def _skip_for_sampling(self, node: str, stable: bool) -> bool:
        """Adaptive sampling: while a node is stable send every Nth sample; anomalies, the first sample and the first
        stable sample after an anomaly always go out. N is capped at 4 so the SaaS stale rule (30 s) is never at risk."""
        n = max(1, int(self.s.stable_every))
        if n == 1 or not stable:
            self._last_stable[node], self._stable_seen[node] = stable, 0
            return False
        first_or_recovery = node not in self._last_stable or not self._last_stable[node]
        self._last_stable[node] = True
        self._stable_seen[node] = self._stable_seen.get(node, 0) + 1
        if first_or_recovery or self._stable_seen[node] % n == 0:
            return False
        return True

    # ---- core, synchronous, deterministic ----
    def process_event(self, ev: dict) -> list[str]:
        raw_id = self.raw.insert(ev)
        self.events_in += 1
        found = secret_summary(json.dumps(ev["raw"]))             # secrets SEEN locally; the wire never gets them
        if found:
            self.near_miss += sum(found.values())
            self.near_miss_kinds.update(found)
        return [pid for s in self.agg.add(ev, raw_id) if (pid := self.emit(s))]

    def emit(self, sample: Sample) -> Optional[str]:
        stable = (not getattr(sample, "service_down", False) and sample.auth_failures_60s == 0
                  and severity_is_info(sample, self.s))
        if self._skip_for_sampling(sample.node, stable):
            self.sampled_out += 1
            return None
        payload = build_from_sample(sample, self.s, health=self.health())
        wire = payload.model_dump_json()
        pid = str(payload.payload_id)
        hits = scan_outbound(wire)                       # layer 3: block, never send
        with self.db.tx():
            if hits:
                self.egress.record(pid, "BLOCKED", wire, sample.raw_id, ",".join(hits))
                self.blocked += 1
                return None
            verdict, victim = self.outbox.make_room(self.s.outbox_max_rows, SEV_RANK.get(payload.severity, 0))
            if verdict == "refuse":                      # full of more important data: shed the newcomer, on the record
                self.egress.record(pid, "DROPPED", wire, sample.raw_id, "backpressure")
                self.dropped += 1
                return None
            if verdict == "shed":
                self.egress.mark_in_tx([victim], "DROPPED", "backpressure")
                self.dropped += 1
            self.egress.record(pid, "QUEUED", wire, sample.raw_id)
            self.outbox.enqueue(pid, payload.event_time.isoformat(), payload.severity)   # persist BEFORE send
        self.payloads_out += 1
        return pid

    def flush_due(self, now: Optional[datetime] = None) -> list[str]:
        """Wall-clock silence checks only when the stream is rebased to 'now' (live) or `now` is given explicitly;
        replaying an old file with the wall clock would wrongly mark every node silent."""
        check = now is not None or self.s.rebase
        return [pid for s in self.agg.flush_due(now or datetime.now(timezone.utc), check) if (pid := self.emit(s))]

    def flush_all(self) -> list[str]:
        return [pid for s in self.agg.flush_all() if (pid := self.emit(s))]

    # ---- live runner ----
    async def run_stream(self, stop: asyncio.Event):
        """Run every configured source concurrently (file replay, tail, syslog). One event loop thread, so
        process_event stays single-writer and deterministic."""
        specs = make_sources(list(self.s.sources), lambda: FileSource(self.s.stream_path, rebase=self.s.rebase, loop=self.s.loop), speed=self.s.speed)
        self.sources = specs
        self.source = specs[0] if specs else None

        async def one(src):
            if isinstance(src, FileSource):
                await self._run_file(src, stop)
            else:
                async for ev in src.aevents(stop):
                    self.process_event(ev)
        await asyncio.gather(*(one(x) for x in specs))

    async def _run_file(self, src, stop: asyncio.Event):
        last = None
        for ev in src.events():
            if stop.is_set():
                return
            if self.s.rebase and self.s.speed == 1.0:            # stay locked to the wall clock
                wait = (ev["ts"] - datetime.now(timezone.utc)).total_seconds()
            elif last is not None and ev["ts"] > last:
                wait = (ev["ts"] - last).total_seconds() / self.s.speed
            else:
                wait = 0.0
            if wait > 0:
                try:
                    await asyncio.wait_for(stop.wait(), timeout=wait)
                    return
                except asyncio.TimeoutError:
                    pass
            last = ev["ts"] if last is None else max(last, ev["ts"])
            self.process_event(ev)
        self.flush_all()

    async def run_flusher(self, stop: asyncio.Event, every_s: float = 1.0):
        """Live mode: close windows by wall clock so latency stays ~one window, and purge old raw rows."""
        n = 0
        while not stop.is_set():
            self.flush_due()
            n += 1
            if n % 60 == 0:
                self.raw.purge()
                self.outbox.purge_acked()
            try:
                await asyncio.wait_for(stop.wait(), timeout=every_s)
            except asyncio.TimeoutError:
                pass
