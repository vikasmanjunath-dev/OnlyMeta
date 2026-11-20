"""Tiny .env loader (no dependency). Real environment variables always win; the file only fills gaps."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def parse(text: str) -> dict:
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        out[k.strip().removeprefix("export ").strip()] = v
    return out


def load(path=None) -> dict:
    p = Path(path or os.getenv("CICADA_ENV", ROOT / ".env"))
    if not p.is_file():
        return {}
    vals = parse(p.read_text())
    for k, v in vals.items():
        os.environ.setdefault(k, v)
    return vals
