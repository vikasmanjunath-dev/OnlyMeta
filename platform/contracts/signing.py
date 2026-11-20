"""Request signing shared by collector and SaaS (HMAC-SHA256). The API key (the secret) never travels:
the collector sends only a key id and a signature over  METHOD \\n path?query \\n timestamp \\n nonce \\n sha256(body).

Why: with TLS this is defence in depth. Without TLS (plain-HTTP dev) an eavesdropper can read traffic but cannot forge
a new batch, change one, or replay one outside the time window / nonce cache. Secrets are compared in constant time."""
import hashlib
import hmac
import secrets
import time
from typing import Optional

H_KEY, H_TS, H_NONCE, H_SIG = "X-Key-Id", "X-Timestamp", "X-Nonce", "X-Signature"


def key_id(secret: str) -> str:
    return hashlib.sha256(b"key-id|" + secret.encode()).hexdigest()[:16]


def canonical(method: str, path: str, ts: str, nonce: str, body: bytes) -> bytes:
    return "\n".join([method.upper(), path, ts, nonce, hashlib.sha256(body).hexdigest()]).encode()


def sign(secret: str, method: str, path: str, body: bytes = b"", ts: Optional[int] = None, nonce: Optional[str] = None) -> dict:
    ts = str(int(time.time()) if ts is None else ts)
    nonce = nonce or secrets.token_hex(12)
    sig = hmac.new(secret.encode(), canonical(method, path, ts, nonce, body), hashlib.sha256).hexdigest()
    return {H_KEY: key_id(secret), H_TS: ts, H_NONCE: nonce, H_SIG: sig}


def verify(secret: str, method: str, path: str, body: bytes, ts: str, nonce: str, sig: str) -> bool:
    good = hmac.new(secret.encode(), canonical(method, path, ts, nonce, body), hashlib.sha256).hexdigest()
    return hmac.compare_digest(good, sig or "")
