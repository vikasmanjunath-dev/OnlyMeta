"""Joint (multivariate) anomaly detection: several metrics each a little off, together very unlikely.

A per-metric z-score only fires when ONE metric crosses its own limit. A degradation that nudges CPU, memory, latency and loss by
2σ each trips nothing, yet is jointly improbable. Here the node's recent clean samples give a mean vector and a covariance matrix, and
every sample is scored by its Mahalanobis distance D² = (x-μ)ᵀ Σ⁻¹ (x-μ). Under normal operation D² follows a chi-square law with
k = number of metrics, so the alert limit is a probability (alpha), not a guess. Covariance also catches a broken relationship
(CPU up while latency stays flat) that no single metric shows.

Design points: the covariance diagonal is never below the same noise floor the univariate detector uses (so a flat metric cannot make
D² explode); only samples the univariate detector found clean are learned (a fault is not absorbed into "normal"); a joint anomaly
is only raised where no single-metric anomaly is already open (it adds information, it does not echo); the result is reported as a
verdict shaped like the univariate ones, with its distance expressed in univariate-equivalent sigmas, so incidents and root-cause
analysis consume it unchanged. Pure Python, O(k²) per sample, the inverse refreshed every few samples."""
import math
import statistics
from collections import deque
from typing import Callable, Optional

from saas.aiops.baseline import METRICS

KEYS = tuple(METRICS)
CHI2 = {0.001: {1: 10.83, 2: 13.82, 3: 16.27, 4: 18.47, 5: 20.52, 6: 22.46, 7: 24.32},
        0.01: {1: 6.63, 2: 9.21, 3: 11.34, 4: 13.28, 5: 15.09, 6: 16.81, 7: 18.48}}
DEFAULTS = {"enabled": True, "alpha": 0.001, "warmup": 40, "window": 180, "confirm_k": 3, "confirm_n": 4, "fast_mult": 2.0, "clear_clean_samples": 3,
            "level_shift_samples": 36, "reinvert_every": 10, "equiv_sigma": 3.0, "rebuild_trim_mads": 4.0}


def settings(cfg: Optional[dict]) -> dict:
    return {**DEFAULTS, **{k: v for k, v in (cfg or {}).items() if k in DEFAULTS}}


def critical(alpha: float, k: int) -> float:
    t = CHI2.get(alpha, CHI2[0.001])
    return t.get(k, t[max(t)] + 2.0 * (k - max(t)))


def invert(a: list) -> Optional[list]:
    """Gauss-Jordan with partial pivoting; None if singular."""
    n = len(a)
    m = [row[:] + [1.0 if i == j else 0.0 for j in range(n)] for i, row in enumerate(a)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(m[r][c]))
        if abs(m[p][c]) < 1e-12:
            return None
        m[c], m[p] = m[p], m[c]
        d = m[c][c]
        m[c] = [x / d for x in m[c]]
        for r in range(n):
            if r != c and m[r][c]:
                f = m[r][c]
                m[r] = [x - f * y for x, y in zip(m[r], m[c])]
    return [row[n:] for row in m]


class JointState:
    def __init__(self, size: int, confirm_n: int, k: int):
        self.k, self.size = k, size
        self.win: deque = deque()
        self.s = [0.0] * k
        self.ss = [[0.0] * k for _ in range(k)]
        self.inv: Optional[list] = None
        self.stale = 0
        self.flags: deque = deque(maxlen=confirm_n)
        self.open = False
        self.run_anom = self.run_ok = 0
        self.run_start_ts: Optional[float] = None
        self.onset_ts: Optional[float] = None
        self.peak = 0.0
        self.recent: deque = deque(maxlen=64)
        self.anomaly_id: Optional[int] = None
        self.shifts = 0

    def clear(self):
        self.win.clear()
        self.s = [0.0] * self.k
        self.ss = [[0.0] * self.k for _ in range(self.k)]
        self.inv, self.stale = None, 0

    def add(self, x: list):
        self.win.append(x)
        for i in range(self.k):
            self.s[i] += x[i]
            for j in range(self.k):
                self.ss[i][j] += x[i] * x[j]
        if len(self.win) > self.size:
            y = self.win.popleft()
            for i in range(self.k):
                self.s[i] -= y[i]
                for j in range(self.k):
                    self.ss[i][j] -= y[i] * y[j]
        self.stale += 1

    def mean(self) -> list:
        n = len(self.win)
        return [v / n for v in self.s] if n else [0.0] * self.k

    def cov(self) -> list:
        n = len(self.win)
        mu = self.mean()
        return [[(self.ss[i][j] - n * mu[i] * mu[j]) / max(n - 1, 1) for j in range(self.k)] for i in range(self.k)]


class JointDetector:
    def __init__(self, th: dict, sigma_eff: Callable):
        self.c = settings(th["aiops"].get("joint"))
        self.sigma_eff = sigma_eff
        self.k = len(KEYS)
        self.crit = critical(float(self.c["alpha"]), self.k)
        self.on = bool(self.c["enabled"])
        self.nodes: dict = {}
        self.seeded: set = set()

    def _st(self, tenant: str, node: str) -> JointState:
        k = (tenant, node)
        if k not in self.nodes:
            self.nodes[k] = JointState(int(self.c["window"]), int(self.c["confirm_n"]), self.k)
        return self.nodes[k]

    def forget(self, tenant: str, node: str):
        self.nodes.pop((tenant, node), None)
        self.seeded.discard((tenant, node))

    @staticmethod
    def vector(metrics: dict) -> Optional[list]:
        if any(metrics.get(m) is None for m in KEYS):
            return None
        return [float(metrics[m]) for m in KEYS]

    def seed(self, tenant: str, node: str, rows: list):
        """Rebuild from history (oldest first), dropping points far from the per-metric median (an old fault is not 'normal')."""
        st = self._st(tenant, node)
        st.clear()
        vecs = [v for v in (self.vector(r) for r in rows) if v][-int(self.c["window"]):]
        if len(vecs) >= 5:
            cols = list(zip(*vecs))
            keep = []
            lims = []
            for i, col in enumerate(cols):
                med = statistics.median(col)
                mad = 1.4826 * statistics.median(abs(x - med) for x in col)
                lims.append((med, float(self.c["rebuild_trim_mads"]) * max(mad, self.sigma_eff(KEYS[i], med, 0.0))))
            vecs = [v for v in vecs if all(abs(v[i] - lims[i][0]) <= lims[i][1] for i in range(self.k))]
        for v in vecs:
            st.add(v)
        self.seeded.add((tenant, node))

    # ---------------------------------------------------------------- scoring
    def _model(self, st: JointState):
        mu = st.mean()
        cov = st.cov()
        for i in range(self.k):                                                    # noise is never assumed below the univariate floor
            cov[i][i] = max(cov[i][i], self.sigma_eff(KEYS[i], mu[i], 0.0) ** 2)
        if st.inv is None or st.stale >= int(self.c["reinvert_every"]):
            st.inv, st.stale = invert(cov), 0
        return mu, cov

    def score(self, st: JointState, x: list):
        mu, cov = self._model(st)
        if st.inv is None:
            return None
        d = [x[i] - mu[i] for i in range(self.k)]
        d2 = sum(d[i] * st.inv[i][j] * d[j] for i in range(self.k) for j in range(self.k))
        parts = {KEYS[i]: round(d[i] / math.sqrt(cov[i][i]), 2) for i in range(self.k)}
        return max(d2, 0.0), parts, mu

    def baseline(self, tenant: str, node: str) -> dict:
        st = self._st(tenant, node)
        n = len(st.win)
        return {"n": n, "warm": n >= int(self.c["warmup"]), "metrics": list(KEYS), "alpha": self.c["alpha"], "threshold_d2": self.crit, "open": st.open,
                "level_shifts": st.shifts}

    def observe(self, tenant: str, node: str, metrics: dict, ts: float, uni_raw: bool, uni_open: bool, learn: bool = True) -> Optional[dict]:
        """One verdict (or None while warming up / disabled / metrics missing)."""
        if not self.on:
            return None
        x = self.vector(metrics)
        if x is None:
            return None
        st = self._st(tenant, node)
        if len(st.win) < int(self.c["warmup"]):
            if learn and not uni_raw:
                st.add(x)
            return None
        sc = self.score(st, x)
        if sc is None:
            return None
        d2, parts, mu = sc
        beyond = d2 > self.crit
        dist = math.sqrt(d2)
        z_eq = dist * float(self.c["equiv_sigma"]) / math.sqrt(self.crit)
        v = {"metric": "joint", "value": round(dist, 2), "warm": True, "z": round(z_eq, 3), "raw": beyond, "opened": False, "closed": False, "open": st.open,
             "level_shift": False, "onset_ts": st.onset_ts, "mean": round(math.sqrt(self.k), 2), "sigma": 1.0, "direction": "above", "d2": round(d2, 2),
             "threshold_d2": self.crit, "alpha": self.c["alpha"], "contrib": parts, "peak_z": round(st.peak, 2)}
        if not learn:
            return v
        if not st.open and (uni_open or uni_raw):                                   # a single-metric anomaly already says it: no echo, and do not learn it
            st.flags.clear()
            st.run_start_ts = None
            return v
        st.flags.append(beyond)
        confirmed = beyond and (d2 >= float(self.c["fast_mult"]) * self.crit or sum(st.flags) >= int(self.c["confirm_k"]))
        if beyond:
            if st.run_start_ts is None:
                st.run_start_ts = ts
            st.recent.append(x)
            if st.open or confirmed:
                st.peak = max(st.peak, z_eq)
        if not st.open:
            if confirmed:
                st.open, st.run_anom, st.run_ok = True, sum(st.flags), 0
                st.onset_ts = st.run_start_ts if st.run_start_ts is not None else ts
                v.update(opened=True, open=True, onset_ts=st.onset_ts)
            elif not beyond:
                st.add(x)
                st.run_start_ts = None
                st.recent.clear()
        else:
            if beyond:
                st.run_anom += 1
                st.run_ok = 0
                if st.run_anom >= int(self.c["level_shift_samples"]):                # sustained: this combination is the new normal
                    st.clear()
                    for y in st.recent:
                        st.add(y)
                    st.open, st.shifts = False, st.shifts + 1
                    st.run_anom = st.run_ok = 0
                    st.run_start_ts, st.onset_ts, st.peak = None, None, 0.0
                    st.flags.clear()
                    st.recent.clear()
                    v.update(closed=True, open=False, level_shift=True)
            else:
                st.run_ok += 1
                if st.run_ok >= int(self.c["clear_clean_samples"]):
                    st.open, st.run_anom, st.run_ok = False, 0, 0
                    st.run_start_ts, st.peak = None, 0.0
                    st.recent.clear()
                    st.flags.clear()
                    v.update(closed=True, open=False)
                if not st.open:
                    st.add(x)
        v["peak_z"] = round(st.peak, 2)
        return v


def describe_joint(v: dict) -> str:
    """One sentence, digits stable enough for alert de-duplication. Names the metrics that moved most; none needs to be out of range alone."""
    top = sorted(v["contrib"].items(), key=lambda kv: -abs(kv[1]))
    names = ", ".join(f"{METRICS[m]['label']} {z:+.1f}σ" for m, z in top[:4] if abs(z) >= 1.0) or "several metrics"
    return f"anomaly: unusual combination of metrics ({names}); jointly improbable (p<{v['alpha']})"
