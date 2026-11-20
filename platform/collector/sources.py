"""Live input sources besides the sample file. Every source yields the SAME normalised event dict (adapter.normalise),
so nothing downstream knows where a line came from. Async: they never block the event loop.

  tail:/var/log/app.jsonl        follow a file (JSON lines or syslog text), survives rotation and truncation
  syslog:0.0.0.0:5514            UDP syslog, RFC 5424 and RFC 3164

Limits (stated, not hidden): a plain-text line carries no CPU/memory numbers, so a node that ONLY ever sends text has
nothing to aggregate and its events are counted in `unusable` instead of being invented. Text still contributes
failed-login and service-down signals for nodes that also report metrics (e.g. through the JSON feed)."""
import asyncio
import json
import os
import re
from datetime import datetime, timezone
from typing import AsyncIterator, Optional

from collector.adapter import normalise

_SYSLOG_5424 = re.compile(r"^<(?P<pri>\d{1,3})>1 (?P<ts>\S+) (?P<host>\S+) (?P<app>\S+) (?P<pid>\S+) (?P<mid>\S+) (?P<sd>-|\[.*?\])\s*(?P<msg>.*)$", re.S)
_SYSLOG_3164 = re.compile(r"^(?:<(?P<pri>\d{1,3})>)?(?P<ts>[A-Z][a-z]{2} +\d{1,2} \d\d:\d\d:\d\d) (?P<host>\S+) (?P<msg>.*)$", re.S)


def short_node(host: str) -> str:
    """'prod-db-01.corp.local' -> 'prod-db-01': the label that gets pseudonymised, never the FQDN."""
    return (host or "unknown").split(".")[0][:64] or "unknown"


def parse_syslog(raw: str, now: Optional[datetime] = None) -> Optional[dict]:
    """-> raw-event dict (feed to normalise) or None. RFC 3164 has no year or zone, so arrival time is used."""
    now = now or datetime.now(timezone.utc)
    raw = raw.strip("\x00\r\n ")
    m = _SYSLOG_5424.match(raw)
    if m:
        ts = m.group("ts")
        try:
            datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            ts = now.isoformat()
        return {"ts": ts, "node": short_node(m.group("host")), "host": m.group("host"), "raw_log": m.group("msg")}
    m = _SYSLOG_3164.match(raw)
    if m:
        return {"ts": now.isoformat(), "node": short_node(m.group("host")), "host": m.group("host"), "raw_log": m.group("msg")}
    return None


def parse_line(text: str, default_node: str = "local") -> Optional[dict]:
    """One line from a file: JSON object, syslog, or bare text. Returns a raw-event dict or None for blanks."""
    text = text.strip()
    if not text:
        return None
    if text.startswith("{"):
        return json.loads(text)                             # ValueError => counted as malformed by the caller
    d = parse_syslog(text)
    return d or {"ts": datetime.now(timezone.utc).isoformat(), "node": default_node, "raw_log": text}


class TailSource:
    def __init__(self, path: str, poll_s: float = 0.25, from_start: bool = False, default_node: str = "local"):
        self.path, self.poll_s, self.from_start, self.default_node = path, poll_s, from_start, default_node
        self.read = self.malformed = 0

    async def aevents(self, stop: asyncio.Event) -> AsyncIterator[dict]:
        f, inode, buf, first = None, None, "", True
        try:
            while not stop.is_set():
                try:
                    st = os.stat(self.path)
                except FileNotFoundError:
                    await asyncio.sleep(self.poll_s)
                    continue
                if f is None or st.st_ino != inode or st.st_size < f.tell():      # first open, rotated, or truncated
                    if f:
                        f.close()
                    f, inode, buf = open(self.path, "r", errors="replace"), st.st_ino, ""
                    if first and not self.from_start:
                        f.seek(0, os.SEEK_END)                                     # only a FIRST open skips history
                    first = False
                chunk = f.read(65536)
                if not chunk:
                    await asyncio.sleep(self.poll_s)
                    continue
                buf += chunk
                *lines, buf = buf.split("\n")                                      # keep a partial last line for next read
                for ln in lines:
                    try:
                        d = parse_line(ln, self.default_node)
                        if d is None:
                            continue
                        ev = normalise(d)
                        self.read += 1
                    except (ValueError, KeyError, TypeError):
                        self.malformed += 1
                        continue
                    yield ev
                await asyncio.sleep(0)
        finally:
            if f:
                f.close()


class _Proto(asyncio.DatagramProtocol):
    def __init__(self, q: asyncio.Queue, src):
        self.q, self.src = q, src

    def datagram_received(self, data, addr):
        if len(data) > 8192:                                  # oversize datagrams are noise or abuse
            self.src.malformed += 1
            return
        try:
            d = parse_syslog(data.decode("utf-8", "replace"))
            if d is None:
                raise ValueError("unparseable")
            ev = normalise(d)
        except (ValueError, KeyError, TypeError):
            self.src.malformed += 1
            return
        if self.q.full():                                     # shed oldest under flood: bounded memory
            self.q.get_nowait()
            self.src.shed += 1
        self.q.put_nowait(ev)
        self.src.read += 1


class SyslogSource:
    def __init__(self, host: str = "127.0.0.1", port: int = 5514, queue_max: int = 10000):
        self.host, self.port, self.queue_max = host, port, queue_max
        self.read = self.malformed = self.shed = 0

    async def aevents(self, stop: asyncio.Event) -> AsyncIterator[dict]:
        q: asyncio.Queue = asyncio.Queue(self.queue_max)
        transport, _ = await asyncio.get_running_loop().create_datagram_endpoint(lambda: _Proto(q, self), local_addr=(self.host, self.port))
        self.port = transport.get_extra_info("sockname")[1]                       # real port when 0 was requested
        try:
            while not stop.is_set():
                try:
                    yield await asyncio.wait_for(q.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    continue
        finally:
            transport.close()


class CalmSource:
    """Synthetic steady state for live demos: app-01, db-01, net-01 report healthy values every 5 s (virtual clock, so SPEED works).
    Nothing abnormal ever happens unless a scenario is injected, so every anomaly on screen has a visible cause. It is synthetic
    and labelled as such in /api/status (sources: ["calm"])."""
    def __init__(self, interval_s: float = 5.0, nodes=("app-01", "db-01", "net-01")):
        self.interval_s, self.nodes, self.malformed, self.read = interval_s, nodes, 0, 0
        self.drift: dict = {}                                         # node -> [ticks left, overrides]

    def inject(self, node: str, ticks: int, overrides: dict):
        """Make `node` report `overrides` for the next `ticks` ticks of THIS feed (in order, in the same window: no mixing with calm samples)."""
        self.drift[node] = [max(int(ticks), 1), dict(overrides)]

    async def aevents(self, stop: asyncio.Event) -> AsyncIterator[dict]:
        from datetime import timedelta
        from collector.scenarios import ev
        t0, k = datetime.now(timezone.utc), 0
        while not stop.is_set():
            ts = t0 + timedelta(seconds=5 * k)
            for n in self.nodes:
                self.read += 1
                d = self.drift.get(n)
                yield normalise(ev(n, ts=ts, **(d[1] if d and d[0] > 0 else {})))
            for d in self.drift.values():
                d[0] -= 1
            k += 1
            try:
                await asyncio.wait_for(stop.wait(), timeout=self.interval_s)
            except asyncio.TimeoutError:
                pass


def make_sources(specs: list[str], default_file_source, speed: float = 1.0):
    """'file' | 'tail:PATH' | 'syslog:HOST:PORT' -> list of sources. Unknown specs fail loudly at start-up."""
    out = []
    for sp in specs:
        sp = sp.strip()
        if sp == "file":
            out.append(default_file_source())
        elif sp == "calm":
            out.append(CalmSource(5.0 / max(speed, 0.1)))
        elif sp.startswith("tail:"):
            out.append(TailSource(sp[5:]))
        elif sp.startswith("syslog:"):
            host, _, port = sp[7:].rpartition(":")
            out.append(SyslogSource(host or "127.0.0.1", int(port)))
        else:
            raise ValueError(f"unknown source spec {sp!r} (use file | calm | tail:PATH | syslog:HOST:PORT)")
    return out
