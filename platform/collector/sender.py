"""Async sender: drains the outbox to POST /ingest. Never blocks the event loop (httpx.AsyncClient).

Guarantees (tested in tests/test_sender.py):
  * zero loss: rows leave PENDING only after the SaaS lists the id in accepted or duplicates
  * zero duplicates: payload_id is stable, so retries after a crash or a lost ACK are deduped by the SaaS
  * sent_at / is_replay are stamped at send time (is_replay = sent_at - event_time > cutoff)
  * exponential backoff 1, 2, 4, 5 s while the SaaS is unreachable; mode flips ONLINE <-> OFFLINE
"""
import asyncio
import json
import time
from datetime import datetime, timezone
from typing import Optional

import httpx

from collector.egress import EgressLog
from collector.outbox import Outbox
from collector.transport import signed_headers
from contracts.hashing import utc_z


class Sender:
    def __init__(self, outbox: Outbox, egress: EgressLog, settings, client: Optional[httpx.AsyncClient] = None):
        self.outbox, self.egress, self.s = outbox, egress, settings
        self.client = client or httpx.AsyncClient(timeout=5.0, verify=(getattr(settings, "ca_bundle", "") or True))
        self.mode = "ONLINE"
        self.chaos_until = 0.0              # simulated network cut (monotonic seconds)
        self.last_error: Optional[str] = None
        self.sent_total = self.failed_batches = self.rejected_total = self.duplicates_total = 0
        self._fail_streak = 0
        self.retry_after = 0.0

    # ---- chaos ----
    def start_outage(self, seconds: float):
        self.chaos_until = time.monotonic() + seconds

    def clear_outage(self):
        self.chaos_until = 0.0

    @property
    def outage_remaining(self) -> float:
        return max(0.0, self.chaos_until - time.monotonic())

    # ---- one send attempt ----
    def _stamp(self, row, now: datetime) -> str:
        d = json.loads(row["json"])
        ev = datetime.fromisoformat(d["event_time"].replace("Z", "+00:00"))
        d["sent_at"] = utc_z(now)
        d["is_replay"] = (now - ev).total_seconds() > self.s.replay_cutoff_s
        return json.dumps(d, separators=(",", ":"))

    async def send_once(self) -> bool:
        """True = nothing to do or batch delivered; False = failure (caller backs off)."""
        rows = self.outbox.claim_batch(self.s.batch_size)
        if not rows:
            self._online()
            return True
        ids = [r["payload_id"] for r in rows]
        if self.outage_remaining > 0:
            return self._fail(ids, "simulated outage (chaos)")
        now = datetime.now(timezone.utc)
        wires = []
        for r in rows:
            w = self._stamp(r, now)
            self.egress.update_wire(r["payload_id"], w)      # egress log shows the exact bytes sent
            wires.append(w)
        body = '{"batch":[' + ",".join(wires) + "]}"
        try:
            raw = body.encode()
            resp = await self.client.post(self.s.saas_url, content=raw,
                                          headers=signed_headers(self.s, "POST", self.s.saas_url, raw, {"Content-Type": "application/json"}))
        except httpx.HTTPError as e:
            return self._fail(ids, f"{type(e).__name__}: {e}")
        if resp.status_code == 429:                           # SaaS asked us to slow down: honour Retry-After, no loss
            self.retry_after = min(30.0, float(resp.headers.get("Retry-After", "1") or 1))
            return self._fail(ids, "HTTP 429 rate limited")
        if resp.status_code != 200:
            return self._fail(ids, f"HTTP {resp.status_code}")
        try:
            data = resp.json()
            accepted, dups, rejected = data.get("accepted", []), data.get("duplicates", []), data.get("rejected", [])
        except ValueError:
            return self._fail(ids, "bad response body")
        done = set(accepted) | set(dups)
        self.outbox.mark_acked(done)
        self.egress.mark(done, "SENT", ack=True)
        for rj in rejected:                                   # parked, never retried forever
            self.outbox.mark_rejected(rj["id"], str(rj.get("reason", ""))[:200])
            self.egress.mark([rj["id"]], "REJECTED")
        self.sent_total += len(accepted)
        self.duplicates_total += len(dups)
        self.rejected_total += len(rejected)
        self._online()
        return True

    def _online(self):
        self.mode, self._fail_streak, self.last_error = "ONLINE", 0, None

    def _fail(self, ids, err) -> bool:
        self.mode, self.last_error = "OFFLINE", err
        self.failed_batches += 1
        self._fail_streak += 1
        self.outbox.note_failure(ids, err)
        return False

    def backoff(self) -> float:
        b = self.s.backoff_s
        base = b[min(self._fail_streak - 1, len(b) - 1)] if self._fail_streak else b[0]
        ra, self.retry_after = self.retry_after, 0.0
        return max(base, ra)

    async def run(self, stop: asyncio.Event, idle_s: float = 0.5):
        while not stop.is_set():
            ok = await self.send_once()
            if ok:
                delay = 0.05 if self.outbox.depth() else idle_s
            else:
                delay = self.backoff()
            try:
                await asyncio.wait_for(stop.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass

    async def resend_last(self, n: int) -> int:
        """Chaos: replay the most recent SENT payload n times with the same payload_id (duplicate scenario)."""
        rows = self.egress.list(1, status="SENT")
        if not rows:
            return 0
        wire = rows[0]["json"]
        body = ('{"batch":[' + ",".join([wire] * n) + "]}").encode()
        resp = await self.client.post(self.s.saas_url, content=body,
                                      headers=signed_headers(self.s, "POST", self.s.saas_url, body, {"Content-Type": "application/json"}))
        return len(resp.json().get("duplicates", []))

    async def send_corrupt(self, kind: str) -> dict:
        """Chaos: deliver a deliberately damaged copy of the last SENT payload and report what the SaaS did.
          tamper  -> same payload_id, one metric changed  => SaaS must reject (payload_id_conflict), never overwrite
          extra   -> unknown field added                    => SaaS must reject (schema allow-list)
          tenant  -> claims another tenant                  => SaaS must reject (tenant_mismatch)"""
        rows = self.egress.list(1, status="SENT")
        if not rows:
            return {"error": "nothing sent yet"}
        d = json.loads(rows[0]["json"])
        if kind == "tamper":
            d["metrics"]["cpu"] = round(d["metrics"]["cpu"] + 7.7, 3)
        elif kind == "extra":
            d["raw_log"] = "[chaos] unexpected field"
        elif kind == "tenant":
            d["tenant_id"] = "tenant-other"
        else:
            return {"error": f"unknown corruption {kind!r}"}
        body = json.dumps({"batch": [d]}, separators=(",", ":")).encode()
        resp = await self.client.post(self.s.saas_url, content=body,
                                      headers=signed_headers(self.s, "POST", self.s.saas_url, body, {"Content-Type": "application/json"}))
        return {"status": resp.status_code, **(resp.json() if resp.status_code == 200 else {"detail": resp.text[:200]})}
