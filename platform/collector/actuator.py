"""Collector-side actuator (P8). The customer's switch: ACTUATOR=off (default) | calm | runbook.

Never trusts the wire: every command is re-verified here (signature with THIS collector's key, its own tenant and key id, expiry,
not seen before, action in the local allow-list, target well-formed and known) and refused with a reason otherwise.
  calm    : acts on the synthetic demo source (a real state change in the managed system, which then shows up in real telemetry)
  runbook : runs ONLY the argv lists named in the RUNBOOKS yaml; no shell, fixed argv, `{target}` is the only substitution, timeout, output capped."""
import asyncio
import json
import re
import subprocess
import time
from collections import deque
from pathlib import Path

import yaml

from contracts.signing import command_verify, key_id
from collector.transport import signed_headers

CALM_EFFECT = {"scale_out": 0.95, "throttle_traffic": 0.5, "restart_service": 1.0, "scale_in": 0.0, "unthrottle_traffic": 0.0}
TARGET = re.compile(r"^[A-Za-z0-9._-]{1,40}$")


def load_runbooks(path: str) -> dict:
    out = {}
    if not path:
        return out
    for action, spec in (yaml.safe_load(Path(path).read_text()) or {}).items():
        argv = spec.get("argv")
        if not (isinstance(argv, list) and argv and all(isinstance(x, str) for x in argv) and Path(argv[0]).is_absolute()):
            raise ValueError(f"runbook {action!r}: argv must be a list of strings whose first item is an absolute path")
        out[action] = {"argv": argv, "timeout_s": min(max(float(spec.get("timeout_s", 20)), 1.0), 60.0)}
    return out


def commands_url(ingest_url: str) -> str:
    return ingest_url.rsplit("/ingest", 1)[0] + "/collector/commands"


class CommandRunner:
    def __init__(self, pipe, client):
        self.pipe, self.s, self.client = pipe, pipe.s, client
        self.mode = self.s.actuator if self.s.actuator in ("calm", "runbook") else "off"
        self.runbooks = load_runbooks(self.s.runbooks) if self.mode == "runbook" else {}
        self.seen: dict = {}
        self.log: deque = deque(maxlen=30)
        self.last_poll = None

    def caps(self) -> list:
        return sorted(CALM_EFFECT) if self.mode == "calm" else sorted(self.runbooks) if self.mode == "runbook" else []

    def _live(self):
        return next((x for x in self.pipe.sources if hasattr(x, "mitigate")), None)

    def check(self, cmd: dict, now: float):
        """-> None if the command may run, else the reason it is refused."""
        if self.mode == "off":
            return "actuator is switched off on this collector"
        if not command_verify(self.s.api_key, cmd):
            return "bad signature"
        if cmd.get("tenant") != self.s.tenant_id or cmd.get("kid") != key_id(self.s.api_key):
            return "command was issued for a different tenant or key"
        if int(cmd["exp"]) < now:
            return "command expired"
        if cmd["id"] in self.seen:
            return "replay: this command id was already handled"
        if cmd["action"] not in self.caps():
            return f"'{cmd['action']}' is not in this collector's allow-list"
        if not isinstance(cmd.get("target"), str) or not TARGET.match(cmd["target"]):
            return "malformed target"
        return None

    def execute(self, cmd: dict) -> tuple:
        if self.mode == "calm":
            live = self._live()
            if not live or cmd["target"] not in live.nodes:
                return "refused", {"reason": f"unknown target '{cmd['target']}'"}
            ok = live.mitigate(cmd["target"], CALM_EFFECT[cmd["action"]])
            return ("applied", {"applied": f"{cmd['action']} on {cmd['target']}", "backend": "calm-source"}) if ok else ("refused", {"reason": "nothing to act on: no fault is active on that target"})
        rb = self.runbooks[cmd["action"]]
        argv = [a.replace("{target}", cmd["target"]) for a in rb["argv"]]
        try:
            p = subprocess.run(argv, shell=False, capture_output=True, text=True, timeout=rb["timeout_s"], stdin=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired) as e:
            return "failed", {"reason": f"{type(e).__name__}: {str(e)[:120]}"}
        return ("applied" if p.returncode == 0 else "failed"), {"exit": p.returncode, "stdout": p.stdout[-300:], "stderr": p.stderr[-300:], "backend": "runbook"}

    async def handle(self, cmd: dict, now: float) -> tuple:
        why = self.check(cmd, now)
        if why:
            status, detail = "refused", {"reason": why}
        else:
            self.seen[cmd["id"]] = now
            while len(self.seen) > 500:
                self.seen.pop(next(iter(self.seen)))
            status, detail = await asyncio.to_thread(self.execute, cmd)
        self.log.appendleft({"ts": now, "id": cmd.get("id"), "action": cmd.get("action"), "target": cmd.get("target"), "status": status, **{k: v for k, v in detail.items() if k in ("reason", "applied", "exit")}})
        return status, detail

    async def poll_once(self) -> str:
        import httpx
        url = commands_url(self.s.saas_url)
        full = url + "?caps=" + ",".join(self.caps())
        try:
            r = await self.client.get(full, headers=signed_headers(self.s, "GET", full))
            if r.status_code != 200:
                return f"http {r.status_code}"
            cmds = r.json().get("commands", [])
            self.last_poll = time.time()
            for cmd in cmds:
                status, detail = await self.handle(cmd, time.time())
                body = json.dumps({"status": status, "detail": detail}).encode()
                rurl = f"{url}/{int(cmd['id'])}/result"
                await self.client.post(rurl, content=body, headers={**signed_headers(self.s, "POST", rurl, body), "content-type": "application/json"})
            return f"{len(cmds)} command(s)"
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            return "unreachable"

    async def run(self, stop: asyncio.Event):
        while not stop.is_set():
            await self.poll_once()
            try:
                await asyncio.wait_for(stop.wait(), timeout=self.s.command_poll_s)
            except asyncio.TimeoutError:
                pass

    def state(self) -> dict:
        return {"mode": self.mode, "capabilities": self.caps(), "last_poll_s_ago": round(time.time() - self.last_poll, 1) if self.last_poll else None, "recent": list(self.log)}
