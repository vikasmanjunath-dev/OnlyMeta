"""Identity for both kinds of caller.

People:      username + password (scrypt) -> opaque session token, stored as a hash in the tenant's regional DB so sessions
             survive restarts and can be revoked. Roles: viewer (read) and admin (read + change).
Collectors:  HMAC-signed requests (contracts/signing.py). Keys can be rotated with a grace window, or revoked at once.
Both throttled; every decision that matters goes to the audit log by the caller."""
import hashlib
import hmac
import os
import secrets
import time
from collections import OrderedDict
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from contracts import signing
from saas.settings import _hash


def load_kek(data_dir) -> Fernet:
    """Key-encryption key for secrets stored at rest. SAAS_KEK (a Fernet key) wins; otherwise a random key is created once
    in <data_dir>/saas.kek (chmod 600) so a copied database file alone does not reveal collector secrets.
    Production: supply SAAS_KEK from a secret manager / KMS and keep it off the data volume."""
    env = os.getenv("SAAS_KEK")
    if env:
        return Fernet(env.encode())
    path = data_dir / "saas.kek"
    if not path.exists():
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(Fernet.generate_key())
    return Fernet(path.read_bytes().strip())


class AuthError(Exception):
    def __init__(self, status: int, message: str, retry_after: Optional[float] = None):
        super().__init__(message)
        self.status, self.message, self.retry_after = status, message, retry_after


def _th(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class UserService:
    def __init__(self, settings, stores, now=time.time):
        self.s, self.stores, self.now = settings, stores, now
        self.fails: dict[str, list] = {}

    def _store(self, tenant):
        return self.stores.for_region(self.s.tenants[tenant]["region"])

    def seed(self):
        """First start: create the dev accounts from settings (admin + viewer per tenant). Never overwrites."""
        for name, (tid, role, salt, h) in self.s.users.items():
            st = self._store(tid)
            if not st.one("SELECT 1 x FROM users WHERE username=?", (name,)):
                with st.tx() as c:
                    c.execute("INSERT INTO users(username,tenant_id,role,salt,hash,created_ts) VALUES(?,?,?,?,?,?)", (name, tid, role, salt, h, self.now()))

    def find(self, username: str):
        for r in self.stores.by_region.values():
            u = r.one("SELECT * FROM users WHERE username=?", (username,))
            if u:
                return u
        return None

    def login(self, username: str, password: str, ttl: float):
        now = self.now()
        recent = [t for t in self.fails.get(username, []) if t > now - 60]
        if len(recent) >= 5:
            raise AuthError(429, "too many attempts, wait a minute", 60)
        u = self.find(username)
        salt = u["salt"] if u else b"x" * 16
        ok = hmac.compare_digest(_hash(password, salt), u["hash"] if u else b"\0" * 64)      # same work whether or not the user exists
        if not (u and ok) or u["disabled"]:
            self.fails[username] = recent + [now]
            raise AuthError(401, "bad credentials")
        self.fails.pop(username, None)
        region = self.s.tenants[u["tenant_id"]]["region"]
        token = f"{region}.{secrets.token_urlsafe(32)}"
        with self._store(u["tenant_id"]).tx() as c:
            c.execute("INSERT INTO sessions(token_hash,tenant_id,username,role,exp,created_ts) VALUES(?,?,?,?,?,?)",
                      (_th(token), u["tenant_id"], username, u["role"], now + ttl, now))
        return token, u

    def session(self, token: str) -> Optional[dict]:
        region = token.split(".", 1)[0] if "." in token else ""
        st = self.stores.by_region.get(region)
        if not st:
            return None
        r = st.one("SELECT s.*, u.disabled FROM sessions s LEFT JOIN users u ON u.username=s.username WHERE s.token_hash=?", (_th(token),))
        if not r or r["exp"] < self.now() or r["disabled"]:
            return None
        return {"tenant": r["tenant_id"], "role": r["role"], "user": r["username"], "exp": r["exp"]}

    def logout(self, token: str):
        region = token.split(".", 1)[0]
        if region in self.stores.by_region:
            with self.stores.by_region[region].tx() as c:
                c.execute("DELETE FROM sessions WHERE token_hash=?", (_th(token),))

    def revoke_user_sessions(self, username: str):
        for st in self.stores.by_region.values():
            with st.tx() as c:
                c.execute("DELETE FROM sessions WHERE username=?", (username,))

    def create(self, tenant: str, username: str, password: str, role: str):
        if role not in ("viewer", "admin"):
            raise AuthError(422, "role must be viewer or admin")
        if not (3 <= len(username) <= 40) or not all(c.isalnum() or c in "-_." for c in username):
            raise AuthError(422, "username: 3-40 chars, letters digits - _ .")
        if len(password) < self.s.min_password_len:
            raise AuthError(422, f"password must be at least {self.s.min_password_len} characters")
        if self.find(username):
            raise AuthError(409, "username taken")
        salt = secrets.token_bytes(16)
        with self._store(tenant).tx() as c:
            c.execute("INSERT INTO users(username,tenant_id,role,salt,hash,created_ts) VALUES(?,?,?,?,?,?)",
                      (username, tenant, role, salt, _hash(password, salt), self.now()))

    def disable(self, tenant: str, username: str):
        u = self.find(username)
        if not u or u["tenant_id"] != tenant:
            raise AuthError(404, "no such user in this tenant")
        st = self._store(tenant)
        if u["role"] == "admin" and (st.one("SELECT COUNT(*) n FROM users WHERE tenant_id=? AND role='admin' AND disabled=0", (tenant,))["n"] <= 1):
            raise AuthError(409, "cannot disable the last admin")
        with st.tx() as c:
            c.execute("UPDATE users SET disabled=1 WHERE username=?", (username,))
        self.revoke_user_sessions(username)

    def change_password(self, username: str, old: str, new: str):
        u = self.find(username)
        if not u or not hmac.compare_digest(_hash(old, u["salt"]), u["hash"]):
            raise AuthError(401, "bad credentials")
        if len(new) < self.s.min_password_len:
            raise AuthError(422, f"password must be at least {self.s.min_password_len} characters")
        salt = secrets.token_bytes(16)
        with self._store(u["tenant_id"]).tx() as c:
            c.execute("UPDATE users SET salt=?, hash=? WHERE username=?", (salt, _hash(new, salt), username))
        self.revoke_user_sessions(username)                    # a new password ends every other session

    def list(self, tenant: str) -> list:
        return [{"username": r["username"], "role": r["role"], "disabled": bool(r["disabled"])}
                for r in self._store(tenant).q("SELECT username, role, disabled FROM users WHERE tenant_id=? ORDER BY username", (tenant,))]


class KeyService:
    """Collector keys: environment keys (bootstrap, never stored) plus rotated keys (stored for HMAC verification)."""

    def __init__(self, settings, stores, now=time.time):
        self.s, self.stores, self.now = settings, stores, now
        self.kek = load_kek(settings.data_dir)

    def _store(self, tenant):
        return self.stores.for_region(self.s.tenants[tenant]["region"])

    def _seal(self, secret: str) -> str:
        return "enc:" + self.kek.encrypt(secret.encode()).decode()

    def _open(self, stored: str):
        if not stored.startswith("enc:"):
            return stored                                      # row written before encryption existed
        try:
            return self.kek.decrypt(stored[4:].encode()).decode()
        except InvalidToken:
            return None                                        # wrong KEK: the key is unusable, never a crash

    def resolve(self, kid: str):
        """-> (tenant, secret) when the key id is currently valid, else None."""
        now = self.now()
        if kid in self.s.env_keys:
            tenant, secret = self.s.env_keys[kid]
            r = self._store(tenant).one("SELECT expires_ts, revoked FROM key_retirements WHERE key_id=?", (kid,))
            if r and (r["revoked"] or (r["expires_ts"] is not None and r["expires_ts"] < now)):
                return None
            return tenant, secret
        for st in self.stores.by_region.values():
            r = st.one("SELECT * FROM api_keys WHERE key_id=?", (kid,))
            if r:
                if r["revoked"] or (r["expires_ts"] is not None and r["expires_ts"] < now):
                    return None
                secret = self._open(r["secret"])
                return (r["tenant_id"], secret) if secret else None
        return None

    def list(self, tenant: str) -> list:
        now, out = self.now(), []
        st = self._store(tenant)
        for kid, (t, _) in self.s.env_keys.items():
            if t == tenant:
                r = st.one("SELECT expires_ts, revoked FROM key_retirements WHERE key_id=?", (kid,)) or {"expires_ts": None, "revoked": 0}
                out.append(self._row(kid, "environment", None, r["expires_ts"], r["revoked"], now))
        for r in st.q("SELECT * FROM api_keys WHERE tenant_id=? ORDER BY created_ts", (tenant,)):
            out.append(self._row(r["key_id"], r["label"] or "rotated", r["created_ts"], r["expires_ts"], r["revoked"], now))
        return out

    @staticmethod
    def _row(kid, label, created, expires, revoked, now):
        status = "revoked" if revoked else ("expired" if expires is not None and expires < now else ("retiring" if expires is not None else "active"))
        return {"key_id": kid, "label": label, "created": created, "expires": expires, "status": status}

    def rotate(self, tenant: str, grace_s: float) -> dict:
        """Issue a new key; every other live key keeps working for `grace_s` so collectors can be switched without downtime.
        The new secret is returned ONCE and cannot be read back."""
        now, st = self.now(), self._store(tenant)
        new = "ck_" + secrets.token_urlsafe(32)
        kid, exp = signing.key_id(new), now + grace_s
        with st.tx() as c:
            c.execute("INSERT INTO api_keys(key_id,tenant_id,secret,created_ts,label) VALUES(?,?,?,?,?)", (kid, tenant, self._seal(new), now, "rotated"))
            c.execute("UPDATE api_keys SET expires_ts=? WHERE tenant_id=? AND key_id<>? AND revoked=0 AND (expires_ts IS NULL OR expires_ts>?)",
                      (exp, tenant, kid, exp))
            for ekid, (t, _) in self.s.env_keys.items():
                if t == tenant:
                    c.execute("INSERT INTO key_retirements(key_id,tenant_id,expires_ts) VALUES(?,?,?) "
                              "ON CONFLICT(key_id) DO UPDATE SET expires_ts=MIN(COALESCE(expires_ts, excluded.expires_ts), excluded.expires_ts) WHERE revoked=0",
                              (ekid, tenant, exp))
        return {"key": new, "key_id": kid, "old_keys_valid_until": exp, "grace_s": grace_s}

    def revoke(self, tenant: str, kid: str):
        st = self._store(tenant)
        live = [k for k in self.list(tenant) if k["status"] in ("active", "retiring") and k["key_id"] != kid]
        if not live:
            raise AuthError(409, "cannot revoke the only live key; rotate first")
        with st.tx() as c:
            n = c.execute("UPDATE api_keys SET revoked=1 WHERE key_id=? AND tenant_id=?", (kid, tenant)).rowcount
            if not n and kid in self.s.env_keys and self.s.env_keys[kid][0] == tenant:
                c.execute("INSERT INTO key_retirements(key_id,tenant_id,revoked) VALUES(?,?,1) ON CONFLICT(key_id) DO UPDATE SET revoked=1", (kid, tenant))
                n = 1
        if not n:
            raise AuthError(404, "no such key for this tenant")


class NonceCache:
    """Remembers (key id, nonce) for the signature window so a captured request cannot be replayed. Bounded."""

    def __init__(self, ttl: float, cap: int = 200_000, now=time.time):
        self.ttl, self.cap, self.now = ttl, cap, now
        self.seen: OrderedDict = OrderedDict()

    def check_and_add(self, kid: str, nonce: str) -> bool:
        t = self.now()
        while self.seen and (next(iter(self.seen.values())) < t or len(self.seen) >= self.cap):
            self.seen.popitem(last=False)                       # oldest first: expired, or evicted when over capacity
        k = (kid, nonce)
        if k in self.seen:
            return False
        self.seen[k] = t + self.ttl
        return True


class RateLimiter:
    """Token bucket per key id: `rps` sustained, burst 2x. Returns seconds to wait (0 = allowed)."""

    def __init__(self, rps: float, now=time.time):
        self.rps, self.now, self.b = rps, now, {}

    def take(self, kid: str) -> float:
        t, cap = self.now(), max(2.0, self.rps * 2)
        tokens, last = self.b.get(kid, (cap, t))
        tokens = min(cap, tokens + (t - last) * self.rps)
        if tokens >= 1:
            self.b[kid] = (tokens - 1, t)
            return 0.0
        self.b[kid] = (tokens, t)
        return round((1 - tokens) / self.rps, 2)


class CollectorAuth:
    def __init__(self, settings, keys: KeyService, now=time.time):
        self.s, self.keys, self.now = settings, keys, now
        self.nonces = NonceCache(settings.signature_skew_s * 2, now=now)
        self.limiter = RateLimiter(settings.rate_limit_rps, now=now)
        self.stats = {"auth_failed": 0, "rate_limited": 0, "replayed": 0}
        self.floor = now()           # the nonce cache is memory-only: refuse anything signed before this process started,
                                     # so a request captured before a restart cannot be replayed after it

    def authenticate(self, method: str, path: str, body: bytes, headers) -> tuple:
        """-> (tenant_id, key_id). Raises AuthError. Unknown key and bad signature look identical to the caller."""
        kid = headers.get(signing.H_KEY.lower())
        if not kid:
            legacy = headers.get("x-collector-key")
            if legacy and self.s.allow_legacy_key:
                t = self.s.check_key(legacy)
                if t:
                    return self._limit(t, signing.key_id(legacy))
            self.stats["auth_failed"] += 1
            raise AuthError(401, "signed request required (X-Key-Id, X-Timestamp, X-Nonce, X-Signature)")
        found = self.keys.resolve(kid)
        secret = found[1] if found else "x"
        ts, nonce, sig = headers.get(signing.H_TS.lower(), ""), headers.get(signing.H_NONCE.lower(), ""), headers.get(signing.H_SIG.lower(), "")
        good = signing.verify(secret, method, path, body, ts, nonce, sig)        # always computed: no timing oracle for key ids
        if not (found and good):
            self.stats["auth_failed"] += 1
            raise AuthError(401, "invalid credentials")
        try:
            skew = abs(self.now() - int(ts))
        except ValueError:
            skew = 1e9
        if skew <= self.s.signature_skew_s and int(ts) < int(self.floor):
            self.stats["auth_failed"] += 1
            raise AuthError(401, "signed before the server restarted; sign again")
        if skew > self.s.signature_skew_s:
            self.stats["auth_failed"] += 1
            raise AuthError(401, f"timestamp outside +/-{int(self.s.signature_skew_s)} s (check the collector clock / NTP)")
        if not nonce or len(nonce) > 64 or not self.nonces.check_and_add(kid, nonce):
            self.stats["replayed"] += 1
            raise AuthError(401, "replayed or malformed nonce")
        return self._limit(found[0], kid)

    def _limit(self, tenant: str, kid: str):
        wait = self.limiter.take(kid)
        if wait:
            self.stats["rate_limited"] += 1
            raise AuthError(429, "rate limit exceeded", wait)
        return tenant, kid
