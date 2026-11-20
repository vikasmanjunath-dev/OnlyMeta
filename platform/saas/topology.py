"""Dependency map in pseudonyms (decision A in docs/decisions.md): pseudonym = HMAC(tenant_key, logical label).
The SaaS holds the per-tenant key, so it can name nodes without ever receiving a hostname. For P3 correlation."""
import os
from pathlib import Path

import yaml

from collector.redact import pseudo

ROOT = Path(__file__).resolve().parent.parent


def topology(tenant_id: str) -> dict:
    dep = yaml.safe_load((ROOT / "contracts/dependency_map.yaml").read_text()).get(tenant_id, {})
    key = os.getenv("PSEUDO_KEY", f"dev-pseudo-{tenant_id}").encode()
    p = {label: pseudo(label, key) for label in dep}
    return {p[label]: {"label": label, "depends_on": [p[d] for d in deps if d in p]} for label, deps in dep.items()}
