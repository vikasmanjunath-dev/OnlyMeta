"""Stream adapter: the ONLY module that knows the source format.

Normalised RawEvent (dict):
  ts (aware UTC datetime), node, host, metrics{cpu, mem, disk, bandwidth_mbps, latency_ms, packet_loss}
  (each float or None), raw_log, auth_failed (int), source_ip, user, raw (original line dict, local only)

Missing fields become None (never a crash). Malformed lines are counted and skipped. Timestamps may be
ISO with Z / offset, naive (treated as UTC) or epoch seconds. Format: JSON Lines file (sample_stream.jsonl);
when the organizer's spec arrives, only `normalise()` needs to change.
"""
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator, Optional

METRIC_MAP = {  # normalised name -> accepted source keys
    "cpu": ("cpu_percent", "cpu"), "mem": ("mem_percent", "mem"), "disk": ("disk_percent", "disk"),
    "bandwidth_mbps": ("bandwidth_mbps",), "latency_ms": ("latency_ms",), "packet_loss": ("packet_loss_pct", "packet_loss"),
}


def parse_ts(v) -> datetime:
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(v, tz=timezone.utc)
    d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d.astimezone(timezone.utc)


def _num(v) -> Optional[float]:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


# Failed-login evidence in plain log text (sshd, PAM, generic). Used ONLY when the line carries no explicit
# auth_failed_count, so structured feeds are never double counted. The text itself never leaves the collector.
_IP = r"(?P<ip>\d{1,3}(?:\.\d{1,3}){3})"
FAILED_LOGIN_PATTERNS = [
    re.compile(rf"(?i)failed (?:password|publickey|login|authentication)\b.*?\bfrom {_IP}"),
    re.compile(rf"(?i)invalid user \S+ from {_IP}"),
    re.compile(rf"(?i)authentication failure.*?\brhost={_IP}"),
    re.compile(rf"(?i)\b(?:login|auth)\w* (?:failed|failure|denied)\b.*?\b(?:from|src|source)[= ]{_IP}"),
]


def failed_login_from_text(text):
    for p in FAILED_LOGIN_PATTERNS:
        m = p.search(text or "")
        if m:
            return m.group("ip")
    return None


def normalise(line: dict) -> dict:
    """Raises KeyError/ValueError if ts or node is missing/unparseable (=> malformed)."""
    ts = parse_ts(line["ts"])
    node = str(line["node"])
    metrics = {k: next((_num(line[s]) for s in srcs if s in line), None) for k, srcs in METRIC_MAP.items()}
    af = line.get("auth_failed_count", line.get("auth_failure"))
    ip = line.get("src_ip") or line.get("source_ip")
    if af is None:                                        # no structured count: derive it from the text, once
        text_ip = failed_login_from_text(line.get("raw_log"))
        af, ip = (1, ip or text_ip) if text_ip else (0, ip)
    return {"ts": ts, "node": node, "host": line.get("host"), "metrics": metrics, "raw_log": line.get("raw_log"),
            "auth_failed": int(af) if isinstance(af, (int, float)) else (1 if af else 0),
            "source_ip": ip, "user": line.get("user"), "raw": line}


class FileSource:
    def __init__(self, path: str, rebase: bool = False, loop: bool = False):
        self.path, self.rebase, self.loop = Path(path), rebase, loop
        self.read = self.malformed = 0

    def _lines(self) -> list[dict]:
        out = []
        for ln in self.path.read_text().splitlines():
            if not ln.strip():
                continue
            try:
                out.append(normalise(json.loads(ln)))
                self.read += 1
            except (ValueError, KeyError, TypeError):
                self.malformed += 1
        return out

    def events(self, now: Optional[datetime] = None) -> Iterator[dict]:
        evs = self._lines()
        if not evs:
            return
        first, last = min(e["ts"] for e in evs), max(e["ts"] for e in evs)
        offset = ((now or datetime.now(timezone.utc)) - first) if self.rebase else timedelta(0)
        span = (last - first) + timedelta(seconds=5)
        while True:
            for e in evs:
                yield {**e, "ts": e["ts"] + offset}
            if not self.loop:
                return
            offset += span
