"""Signed outbound webhooks for incident events (Slack / ticket / pager style).
Safety by construction: URLs come from contracts/webhooks.yaml only and must match its host allow-list (https; plain http only to loopback for demos);
secrets live in environment variables; every body is HMAC-signed with a timestamp; a bounded queue with retries and a delivery log; a slow or dead
endpoint can never block the engine (delivery is on its own thread). Payloads carry incident summaries only."""
import fnmatch
import hashlib
import hmac
import json
import os
import queue
import threading
import time
import uuid
from urllib.parse import urlparse

import httpx
import yaml

EVENTS = {"incident_opened", "incident_resolved", "incident_reopened", "test"}
LOOPBACK = {"127.0.0.1", "localhost", "::1"}
BACKOFF = (1.0, 5.0, 20.0)


def sign(secret: str, ts: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), ts.encode() + b"." + body, hashlib.sha256).hexdigest()


class Webhooks:
    def __init__(self, path, store_of, audit, threaded: bool = True):
        self.store_of, self.audit, self.threaded = store_of, audit, threaded
        doc = yaml.safe_load(open(path)) if path and os.path.exists(path) else {}
        self.allow = [str(h) for h in (doc.get("allow_hosts") or [])]
        self.hooks: dict = {}                                      # tenant -> [hook]
        self.problems: list = []
        for tenant, lst in (doc.get("tenants") or {}).items():
            for h in lst or []:
                why = self._check(h)
                if why:
                    self.problems.append(f"{tenant}/{h.get('name')}: {why}")
                    continue
                self.hooks.setdefault(tenant, []).append({"name": h["name"], "url": h["url"], "secret_env": h["secret_env"],
                                                          "events": set(h.get("events") or ["incident_opened", "incident_resolved"]) & EVENTS})
        self.q: queue.Queue = queue.Queue(maxsize=500)
        self.dropped = 0
        self._t = None

    def _check(self, h: dict):
        try:
            u = urlparse(h["url"])
            if not h.get("name") or not h.get("secret_env"):
                return "name and secret_env are required"
            if u.scheme != "https" and not (u.scheme == "http" and u.hostname in LOOPBACK):
                return "url must be https (http only to loopback)"
            if u.hostname not in LOOPBACK and not any(fnmatch.fnmatch(u.hostname or "", p) for p in self.allow):
                return f"host {u.hostname} is not in allow_hosts"
        except Exception as e:                                    # noqa: BLE001
            return f"bad url ({type(e).__name__})"
        return None

    # ---------------------------------------------------------------- public
    def listing(self, tenant: str) -> list:
        return [{"name": h["name"], "host": urlparse(h["url"]).netloc, "events": sorted(h["events"]), "secret_set": bool(os.environ.get(h["secret_env"]))}
                for h in self.hooks.get(tenant, [])]

    def emit(self, tenant: str, event: str, payload: dict, only: str = None):
        n = 0
        for h in self.hooks.get(tenant, []):
            if (only and h["name"] != only) or (event not in h["events"] and event != "test"):
                continue
            item = {"tenant": tenant, "hook": h, "event": event, "id": str(uuid.uuid4()), "ts": time.time(), "payload": payload, "attempt": 0}
            n += 1
            if self.threaded:
                self._start()
                try:
                    self.q.put_nowait(item)
                except queue.Full:
                    self.dropped += 1
            else:
                self._deliver(item, retries=False)
        return n

    def log(self, tenant: str, limit: int = 50) -> list:
        return self.store_of(tenant).q("SELECT * FROM webhook_log WHERE tenant_id=? ORDER BY id DESC LIMIT ?", (tenant, limit))

    # ---------------------------------------------------------------- delivery
    def _start(self):
        if self._t is None:
            self._t = threading.Thread(target=self._run, daemon=True, name="webhooks")
            self._t.start()

    def _run(self):
        while True:
            item = self.q.get()
            self._deliver(item, retries=True)

    def _deliver(self, item: dict, retries: bool):
        h, secret = item["hook"], os.environ.get(item["hook"]["secret_env"], "")
        body = json.dumps({"id": item["id"], "event": item["event"], "tenant": item["tenant"], "ts": item["ts"], **item["payload"]}, separators=(",", ":")).encode()
        status, err = None, None
        for attempt in range(len(BACKOFF) + 1 if retries else 1):
            ts = str(int(time.time()))
            try:
                r = httpx.post(h["url"], content=body, timeout=5.0, follow_redirects=False,
                               headers={"Content-Type": "application/json", "X-Cicada-Event": item["event"], "X-Cicada-Delivery": item["id"], "X-Cicada-Timestamp": ts,
                                        "X-Cicada-Signature": sign(secret, ts, body) if secret else "unsigned"})
                status, err = r.status_code, None
                if 200 <= r.status_code < 300:
                    break
                err = f"http {r.status_code}"
            except Exception as e:                                # noqa: BLE001
                status, err = None, type(e).__name__
            if attempt < len(BACKOFF) and retries:
                time.sleep(BACKOFF[attempt])
        ok = status is not None and 200 <= status < 300
        try:
            with self.store_of(item["tenant"]).tx() as c:
                c.execute("INSERT INTO webhook_log(tenant_id,hook,event,delivery_id,ts,ok,http_status,attempts,error) VALUES(?,?,?,?,?,?,?,?,?)",
                          (item["tenant"], h["name"], item["event"], item["id"], time.time(), int(ok), status, attempt + 1, err))
        except Exception as e:                                    # noqa: BLE001
            print("webhook log error:", type(e).__name__, e)
        return ok
