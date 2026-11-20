"""Signed requests to the SaaS. The API key is the HMAC secret and is never sent; see contracts/signing.py."""
from urllib.parse import urlsplit

from contracts.signing import sign


def signed_headers(settings, method: str, url: str, body: bytes = b"", extra: dict | None = None) -> dict:
    u = urlsplit(url)
    path = u.path + (("?" + u.query) if u.query else "")
    return {**sign(settings.api_key, method, path, body), **(extra or {})}
