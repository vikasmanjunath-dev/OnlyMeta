"""Collector settings from contracts/*.yaml plus environment overrides."""
import os
from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Settings:
    tenant_id: str
    region: str
    source_tz: str
    collector_id: str
    api_key: str
    pseudo_key: bytes
    saas_url: str
    stream_path: str
    db_path: str
    speed: float = 1.0
    rebase: bool = True          # shift the stream so its first event is "now" (live demo)
    loop: bool = True            # repeat the stream forever
    version: str = "0.1.0"
    window_s: int = 5
    batch_size: int = 50
    backoff_s: tuple = (1, 2, 4, 5)
    replay_cutoff_s: int = 10
    raw_retention_s: int = 3600
    login_window_s: int = 60
    burst_threshold: int = 10
    fair_logins: int = 5
    node_silent_s: float = 15        # node quiet this long => SERVICE_DOWN payload
    config_status: str = "ok"        # ok | pending | error  (reported in every payload)
    config_version: int = 0
    config_poll_s: float = 30
    sources: tuple = ("file",)       # file | tail:PATH | syslog:HOST:PORT  (comma separated in SOURCES)
    outbox_max_rows: int = 20000
    stable_every: int = 1            # adaptive sampling (1 = off)
    actuator: str = "off"             # off | calm (acts on the synthetic demo source) | runbook (runs allow-listed local scripts); the customer's switch
    runbooks: str = ""               # YAML: action -> {argv: [...], timeout_s: n}; only these can ever run
    command_poll_s: float = 3.0
    ca_bundle: str = ""              # PEM of the CA that must have signed the SaaS certificate (https); empty = the system trust store


def load_settings(**over) -> Settings:
    tenants = yaml.safe_load((ROOT / "contracts/tenants.yaml").read_text())["tenants"]
    th = yaml.safe_load((ROOT / "contracts/thresholds.yaml").read_text())["constants"]
    tid = over.pop("tenant_id", os.getenv("TENANT", "tenant-alpha"))
    t = tenants[tid]
    short = tid.split("-")[-1]
    s = Settings(
        tenant_id=tid, region=t["region"], source_tz=t["source_tz"], collector_id=t["collector_id"],
        api_key=os.getenv(t["key_env"], f"dev-key-{short}"),
        pseudo_key=os.getenv("PSEUDO_KEY", f"dev-pseudo-{tid}").encode(),
        saas_url=os.getenv("SAAS_URL", "http://localhost:8000/ingest"),   # dev default; P2 adds TLS
        stream_path=os.getenv("STREAM", str(ROOT / "contracts/sample_stream.jsonl")),
        db_path=os.getenv("COLLECTOR_DB", str(ROOT / f"data/collector_{short}.db")),
        speed=float(os.getenv("SPEED", "1")), rebase=os.getenv("REBASE", "1") == "1",
        loop=os.getenv("LOOP", "1") == "1",
        window_s=th["send_interval_s"], batch_size=th["outbox_batch_size"], backoff_s=tuple(th["outbox_backoff_s"]),
        replay_cutoff_s=th["replay_cutoff_s"], raw_retention_s=th["raw_retention_s"],
        login_window_s=th["failed_login_window_s"], burst_threshold=th["failed_logins_poor"],
        fair_logins=th["failed_logins_fair"], node_silent_s=th.get("node_silent_s", 15),
        outbox_max_rows=th.get("outbox_max_rows", 20000), stable_every=th.get("stable_every", 1),
        actuator=os.getenv("ACTUATOR", "off"), ca_bundle=os.getenv("CA_BUNDLE", ""), runbooks=os.getenv("RUNBOOKS", ""),
        sources=tuple(x.strip() for x in os.getenv("SOURCES", "file").split(",") if x.strip()),
    )
    for k, v in over.items():
        setattr(s, k, v)
    return s
