"""SaaS settings: tenants, regions, keys, users, thresholds. Secrets come from the environment, never git."""
import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from contracts.signing import key_id

ROOT = Path(__file__).resolve().parent.parent


def _hash(pw: str, salt: bytes) -> bytes:
    return hashlib.scrypt(pw.encode(), salt=salt, n=2 ** 14, r=8, p=1)


@dataclass
class Settings:
    data_dir: Path
    tenants: dict
    keys: dict                      # api key -> tenant_id
    users: dict                     # username -> (tenant_id, role, salt, hash)
    th: dict
    max_batch: int = 500
    max_body_bytes: int = 2_000_000
    token_ttl_s: int = 8 * 3600
    offline_s: float = 30
    stale_loop_s: float = 5
    sigma: dict = field(default_factory=dict)
    env_keys: dict = field(default_factory=dict)      # key_id -> (tenant_id, secret); secrets stay in the environment
    allow_legacy_key: bool = False                    # accept bare X-Collector-Key (dev tools only)
    rate_limit_rps: float = 20
    key_grace_s: float = 600
    signature_skew_s: float = 300
    retention_s: float = 86400
    cooldown_s: float = 60
    flap_transitions: int = 4
    flap_window_s: float = 300
    skew_warn_s: float = 2
    metrics_token: str = ""
    cors_origins: tuple = ()
    min_password_len: int = 10

    def check_key(self, presented: str):
        """Constant-time lookup; returns tenant_id or None."""
        found = None
        for k, t in self.keys.items():
            if hmac.compare_digest(k.encode(), presented.encode()):
                found = t
        return found

    def check_login(self, username: str, password: str):
        u = self.users.get(username)
        salt = u[2] if u else b"x" * 16
        ok = hmac.compare_digest(_hash(password, salt), u[3] if u else b"\0" * 64)
        return (u[0], u[1]) if (u and ok) else None


def load_settings(data_dir=None) -> Settings:
    tenants = yaml.safe_load((ROOT / "contracts/tenants.yaml").read_text())["tenants"]
    th = yaml.safe_load((ROOT / "contracts/thresholds.yaml").read_text())
    c = th["constants"]
    keys, users = {}, {}
    for tid, t in tenants.items():
        short = tid.split("-")[-1]
        keys[os.getenv(t["key_env"], f"dev-key-{short}")] = tid
        # Dev logins (override with USER_<SHORT>_PASSWORD). One admin per tenant for the demo.
        salt = secrets.token_bytes(16)
        users[f"{short}-admin"] = (tid, "admin", salt, _hash(os.getenv(f"USER_{short.upper()}_PASSWORD", f"{short}-demo-pass"), salt))
        vsalt = secrets.token_bytes(16)
        users[f"{short}-viewer"] = (tid, "viewer", vsalt, _hash(os.getenv(f"USER_{short.upper()}_VIEWER_PASSWORD", f"{short}-viewer-pass"), vsalt))
    return Settings(data_dir=Path(data_dir or os.getenv("SAAS_DATA", ROOT / "data")), tenants=tenants, keys=keys, users=users,
                    th=th, offline_s=c["offline_threshold_s"], stale_loop_s=c["stale_check_loop_s"], sigma=c,
                    env_keys={key_id(k): (t, k) for k, t in keys.items()},
                    allow_legacy_key=os.getenv("SAAS_ALLOW_LEGACY_KEY", "0") == "1",
                    rate_limit_rps=float(os.getenv("SAAS_RATE_LIMIT_RPS", c.get("rate_limit_rps", 20))),
                    key_grace_s=c.get("key_grace_s", 600), signature_skew_s=c.get("signature_skew_s", 300),
                    retention_s=float(os.getenv("SAAS_RETENTION_S", c.get("retention_s", 86400))),
                    cooldown_s=c.get("alert_cooldown_s", 60), flap_transitions=c.get("flap_transitions", 4),
                    flap_window_s=c.get("flap_window_s", 300), skew_warn_s=c.get("skew_warn_s", 2),
                    metrics_token=os.getenv("METRICS_TOKEN", ""),
                    cors_origins=tuple(x.strip() for x in os.getenv("CORS_ORIGINS", "http://127.0.0.1:8001,http://localhost:8001").split(",") if x.strip()))


def regions(s: Settings) -> set:
    return {t["region"] for t in s.tenants.values()}
