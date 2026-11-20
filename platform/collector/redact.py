"""Tier 1 redaction helpers.

Three layers protect the boundary; this module holds layers 2 and 3 and the pseudonym helper:
  1. schema allow-list  -> contracts/schema.py (structural, extra="forbid")
  2. regex scrub        -> scrub(): secrets in any text kept for display
  3. outbound scanner   -> scan_outbound(): any hit means the payload is BLOCKED, never sent
"""
import hashlib
import hmac
import math
import re
from collections import Counter

REDACTED = "[REDACTED]"

# Secret patterns: used by scrub() and find_secrets(). Raw IPs in text are PII but not secrets, so
# the local UI may still show them; the outbound scanner (layer 3) additionally rejects IPs and emails.
SECRET_PATTERNS = {
    "api_key": re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}"),
    "aws_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "jwt": re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}"),
    "bearer": re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{8,}", re.I),
    "github_token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{8,}"),
    "github_pat": re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),
    "slack_token": re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}"),
    "stripe_key": re.compile(r"\b[sr]k_(?:live|test)_[A-Za-z0-9]{8,}"),
    "google_api_key": re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}"),
    "private_key_block": re.compile(r"-----BEGIN (?:[A-Z]+ )*PRIVATE KEY-----"),
    "cloud_account_key": re.compile(r"(?i)\b(?:AccountKey|SharedAccessKey|client_secret)\s*=\s*[A-Za-z0-9+/=_\-]{16,}"),
    "url_credentials": re.compile(r"\b[a-z][a-z0-9+.\-]*://[^\s:/@]+:[^\s@/]+@"),
    "credential_assignment": re.compile(
        r"""(?ix)["']?\b(password|passwd|pwd|secret|token|api[_-]?key)\b["']?\s*[=:]\s*["']?[^\s"',;}]+"""),
}
PII_PATTERNS = {
    "ipv4": re.compile(r"\b(?:25[0-5]|2[0-4]\d|1?\d?\d)(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3}\b"),
    "email": re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b"),
}


# Entropy detector: long random-looking tokens that no pattern knows. Pure hex (hashes, UUIDs) is excluded on
# purpose: a git SHA is not a secret and blocking it would drop legitimate payloads.
_TOKEN = re.compile(r"[A-Za-z0-9+/_=\-]{24,}")
ENTROPY_BITS = 4.2


def shannon(s: str) -> float:
    n = len(s)
    return -sum(c / n * math.log2(c / n) for c in Counter(s).values()) if n else 0.0


def _is_random_token(tok: str) -> bool:
    core = tok.replace("-", "")
    if re.fullmatch(r"[0-9a-fA-F]+", core):
        return False
    return any(c.isdigit() for c in tok) and any(c.isalpha() for c in tok) and shannon(tok) >= ENTROPY_BITS


def high_entropy_tokens(text: str) -> list[str]:
    return [m.group(0) for m in _TOKEN.finditer(text) if _is_random_token(m.group(0))]


def scrub(text: str) -> str:
    """Replace every secret-looking span with [REDACTED]."""
    for p in SECRET_PATTERNS.values():
        text = p.sub(REDACTED, text)
    for tok in high_entropy_tokens(text):
        text = text.replace(tok, REDACTED)
    return text


def find_secrets(text: str) -> list[str]:
    return [m.group(0) for p in SECRET_PATTERNS.values() for m in p.finditer(text)]


def secret_summary(text: str) -> dict:
    """{kind: count} with overlapping matches merged, so 'token=ghp_x' counts once. Used for the near-miss counter
    (secrets that were SEEN locally and kept off the wire)."""
    spans = []
    for kind, p in SECRET_PATTERNS.items():
        spans += [(m.start(), m.end(), kind) for m in p.finditer(text)]
    spans += [(m.start(), m.end(), "high_entropy") for m in _TOKEN.finditer(text) if _is_random_token(m.group(0))]
    out, end = Counter(), -1
    for a, b, kind in sorted(spans, key=lambda x: (x[0], -x[1])):
        if a >= end:
            out[kind] += 1
            end = b
        else:
            end = max(end, b)
    return dict(out)


def scan_outbound(payload_json: str) -> list[str]:
    """Last check before send. Returns names of matching patterns; non-empty => BLOCKED, never sent."""
    hits = [n for n, p in {**SECRET_PATTERNS, **PII_PATTERNS}.items() if p.search(payload_json)]
    if high_entropy_tokens(payload_json):
        hits.append("high_entropy")
    return hits


def pseudo(value: str, tenant_key: bytes) -> str:
    """Pseudonymous ID. HMAC (not a plain hash): the IPv4 space is tiny and a bare hash is reversible."""
    return "n-" + hmac.new(tenant_key, value.encode(), hashlib.sha256).hexdigest()[:10]
