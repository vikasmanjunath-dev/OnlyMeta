"""Remote config polling: GET <saas>/collector/config with the collector key, apply whitelisted, bounded keys.

Contract (P2 implements):  GET /collector/config   header X-Collector-Key
  -> 200 {"config_version": int, "burst_threshold": int, "fair_logins": int, "node_silent_s": number,
          "batch_size": int, "raw_retention_s": int}      (all keys optional)   | 404 = no remote config
config_status reported in every payload: ok = latest applied (or nothing to apply), pending = a newer version was
seen but not applied yet, error = last config was rejected (the previous values stay in force).
Unknown keys are ignored; out-of-range values reject the whole document, so a bad push can't break the collector."""
import asyncio
from typing import Optional

import httpx

from collector.transport import signed_headers

BOUNDS = {"burst_threshold": (2, 100), "fair_logins": (1, 50), "node_silent_s": (10, 300),
          "batch_size": (1, 500), "raw_retention_s": (60, 86400),
          "stable_every": (1, 4),                 # x 5 s must stay well under the 30 s stale rule
          "outbox_max_rows": (100, 1_000_000)}


def config_url(ingest_url: str) -> str:
    return ingest_url.rsplit("/ingest", 1)[0] + "/collector/config"


def validate(doc: dict) -> dict:
    """Return the applicable subset or raise ValueError."""
    out = {}
    for k, (lo, hi) in BOUNDS.items():
        if k in doc:
            v = doc[k]
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi:
                raise ValueError(f"{k}={v!r} outside [{lo}, {hi}]")
            out[k] = v
    if out.get("fair_logins", 0) and out.get("burst_threshold") and out["fair_logins"] >= out["burst_threshold"]:
        raise ValueError("fair_logins must be below burst_threshold")
    return out


class ConfigPoller:
    def __init__(self, pipe, client: Optional[httpx.AsyncClient] = None):
        self.pipe, self.s = pipe, pipe.s
        self.client = client or httpx.AsyncClient(timeout=5.0)
        self.last_error: Optional[str] = None
        self.applied = 0

    def apply(self, doc: dict) -> bool:
        ver = int(doc.get("config_version", 0))
        if ver and ver == self.s.config_version:
            return False                                           # nothing new
        self.s.config_status = "pending"
        try:
            ok = validate(doc)
            if ok.get("fair_logins", self.s.fair_logins) >= ok.get("burst_threshold", self.s.burst_threshold):
                raise ValueError("fair_logins must be below burst_threshold")
        except ValueError as e:
            self.s.config_status, self.last_error = "error", str(e)
            return False
        for k, v in ok.items():
            setattr(self.s, k, v)
        if "node_silent_s" in ok:
            self.pipe.agg.node_silent_s = ok["node_silent_s"]
        if "raw_retention_s" in ok:
            self.pipe.raw.retention_s = ok["raw_retention_s"]
        self.s.config_version, self.s.config_status, self.last_error = ver, "ok", None
        self.applied += 1
        return True

    async def poll_once(self) -> str:
        try:
            url = config_url(self.s.saas_url)
            r = await self.client.get(url, headers=signed_headers(self.s, "GET", url))
        except httpx.HTTPError:
            return "unreachable"                                   # keep last config; delivery path reports the outage
        if r.status_code == 404:
            return "none"
        if r.status_code != 200:
            return f"http {r.status_code}"
        try:
            doc = r.json()
        except ValueError:
            self.s.config_status, self.last_error = "error", "bad json"
            return "error"
        return "applied" if self.apply(doc) else ("error" if self.s.config_status == "error" else "unchanged")

    async def run(self, stop: asyncio.Event):
        while not stop.is_set():
            await self.poll_once()
            try:
                await asyncio.wait_for(stop.wait(), timeout=self.s.config_poll_s)
            except asyncio.TimeoutError:
                pass
