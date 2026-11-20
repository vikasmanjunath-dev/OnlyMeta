"""Rolling per-node baselines and anomaly detection (P3).

What it does, in the order a sample meets it:
  1. A node's baseline per metric is the last `baseline_window_samples` (180 = 15 min) CLEAN samples. Running sums, O(1) per sample.
  2. z = (x - mean) / sigma_eff,  sigma_eff = max(sigma, 5 % of mean, absolute floor)   (the floor stops a flat line from flagging
     noise: at sigma 0 every wobble would be infinite sigmas).
  3. Warm-up: fewer than `baseline_warmup_samples` clean samples => no judgement here; the static limits in health.py still apply.
  4. Open rule: z beyond the threshold in K of the last N samples (a moderate anomaly must repeat), or z >= fast_path_z (extreme: at once).
     Close rule: `clear_clean_samples` normal samples in a row. Same hysteresis idea as the health states.
  5. Baseline poisoning guard: samples that look anomalous are NOT learned, so a sustained spike cannot teach the baseline that the
     spike is normal. If the deviation lasts `level_shift_samples`, it is declared a LEVEL SHIFT (new normal, e.g. a deploy):
     the anomaly closes, the baseline re-learns from the new level, and the shift is recorded, never hidden.
  6. Restart safety: nothing here is stored separately. When a node is first seen, its baseline is rebuilt from the events table
     (median/MAD-trimmed so old anomalies do not poison it).
Also: a linear-trend forecast (memory leak, disk fill) that says when a limit will be hit, with the fit quality (r^2).
Pure python, deterministic: time is always the sample's own event time."""
import math
import time
import statistics
from collections import deque
from typing import Callable, Optional

# direction: "up" = only a rise is a problem (CPU dropping is not); "both" = a collapse matters too (bandwidth).
# health: does an open anomaly on this metric move the node's health state (FAIR)?  Bandwidth is context only.
METRICS = {
    "cpu":            {"label": "CPU",         "unit": "%",    "dir": "up",   "health": True},
    "mem":            {"label": "memory",      "unit": "%",    "dir": "up",   "health": True},
    "latency_ms":     {"label": "latency",     "unit": " ms",  "dir": "up",   "health": True},
    "packet_loss":    {"label": "packet loss", "unit": "%",    "dir": "up",   "health": True},
    "bandwidth_mbps": {"label": "bandwidth",   "unit": " Mbps", "dir": "both", "health": False},
}
DEFAULT_ABS_FLOOR = {"bandwidth_mbps": 10.0}
Z_CAP = 12.0                                         # one metric cannot dominate a weighted explanation just by being extreme


class Series:
    """Fixed-size window with running sums (O(1) add). Recomputed exactly every few thousand adds so float drift cannot build up."""

    def __init__(self, size: int):
        self.size, self.buf, self.s1, self.s2, self.k = size, deque(), 0.0, 0.0, 0

    def add(self, x: float):
        if len(self.buf) >= self.size:
            old = self.buf.popleft()
            self.s1 -= old
            self.s2 -= old * old
        self.buf.append(x)
        self.s1 += x
        self.s2 += x * x
        self.k += 1
        if self.k % 2048 == 0:
            self.s1, self.s2 = sum(self.buf), sum(v * v for v in self.buf)

    def clear(self):
        self.buf.clear()
        self.s1 = self.s2 = 0.0

    def __len__(self):
        return len(self.buf)

    @property
    def mean(self) -> float:
        return self.s1 / len(self.buf) if self.buf else 0.0

    @property
    def std(self) -> float:
        n = len(self.buf)
        if n < 2:
            return 0.0
        return math.sqrt(max(0.0, self.s2 / n - (self.s1 / n) ** 2))


class MetricState:
    def __init__(self, size: int, confirm_n: int):
        self.series = Series(size)
        self.flags = deque(maxlen=confirm_n)         # last N raw verdicts (True = beyond threshold)
        self.open = False
        self.run_anom = 0                            # consecutive anomalous samples (while open)
        self.run_ok = 0                              # consecutive normal samples (while open)
        self.run_start_ts: Optional[float] = None
        self.onset_ts: Optional[float] = None
        self.peak_z = 0.0
        self.recent_vals = deque(maxlen=64)          # values seen during the current deviation (for level-shift re-baselining)
        self.held_out = 0                            # anomalous samples NOT learned
        self.anomaly_id: Optional[int] = None
        self.shifts = 0
        self.season: dict = {}                       # seasonal bucket -> Series (same metric, same hour-of-day class)


class Detector:
    def __init__(self, th: dict):
        c, a = th["constants"], th["aiops"]
        self.thr = float(c["zscore_threshold"])
        self.window = int(c["baseline_window_samples"])
        self.warmup = int(c["baseline_warmup_samples"])
        self.rel_floor = float(c["sigma_floor_pct_of_mean"]) / 100.0
        self.abs_floor = {**DEFAULT_ABS_FLOOR, **{k: float(v) for k, v in c["sigma_floor_abs"].items()}}
        self.K, self.N = int(a["confirm_k"]), int(a["confirm_n"])
        self.fast = float(a["fast_path_z"])
        self.clear_n = int(a["clear_clean_samples"])
        self.shift_n = int(a["level_shift_samples"])
        self.trim = float(a["rebuild_trim_mads"])
        se = a.get("seasonal") or {}
        self.season_on = bool(se.get("enabled", False))
        self.season_min = int(se.get("min_samples", 40))
        self.season_size = int(se.get("size", 360))
        self.season_s = int(se.get("bucket_s", 3600))
        self.nodes: dict = {}                        # (tenant, node) -> {metric: MetricState}
        self.seeded: set = set()

    # ---------------------------------------------------------------- state
    def _ms(self, tenant: str, node: str) -> dict:
        k = (tenant, node)
        if k not in self.nodes:
            self.nodes[k] = {m: MetricState(self.window, self.N) for m in METRICS}
        return self.nodes[k]

    def forget(self, tenant: str, node: str):
        self.nodes.pop((tenant, node), None)
        self.seeded.discard((tenant, node))

    def seed(self, tenant: str, node: str, rows: list):
        """Rebuild a baseline from history (oldest first). Median/MAD trim: a point further than `trim` robust sigmas from the
        median is dropped, so an old incident in the window does not become part of "normal"."""
        ms = self._ms(tenant, node)
        for m in METRICS:
            vals = [float(r[m]) for r in rows if r.get(m) is not None][-self.window:]
            if len(vals) >= 5:
                med = statistics.median(vals)
                mad = statistics.median([abs(v - med) for v in vals]) * 1.4826
                lim = self.trim * max(mad, self.rel_floor * abs(med), self.abs_floor.get(m, 0.0))
                vals = [v for v in vals if abs(v - med) <= lim]
            ms[m].series.clear()
            for v in vals:
                ms[m].series.add(v)
            if self.season_on:
                for r in rows[-self.window:]:
                    if r.get(m) is not None and r.get("ts") and float(r[m]) in vals:
                        ms[m].season.setdefault(self.bucket(r["ts"]), Series(self.season_size)).add(float(r[m]))
        self.seeded.add((tenant, node))

    def ensure_seeded(self, tenant: str, node: str, loader: Optional[Callable]):
        if (tenant, node) in self.seeded:
            return
        self.seeded.add((tenant, node))
        if loader:
            rows = loader()
            if rows:
                self.seed(tenant, node, rows)

    # ---------------------------------------------------------------- seasonality
    def bucket(self, ts: float) -> tuple:
        """(weekend?, hour-of-day) from the sample's own UTC event time: 'Tuesday 02:00' is judged against past Tuesday-class 02:00 samples."""
        t = time.gmtime(ts)
        return (t.tm_wday >= 5, int(ts % 86400 // self.season_s))

    def _stats(self, st: "MetricState", ts: float):
        """(mean, sd, seasonal?) — the hour-of-day bucket once it has enough clean samples, else the rolling window."""
        if self.season_on:
            b = st.season.get(self.bucket(ts))
            if b is not None and len(b) >= self.season_min:
                return b.mean, b.std, True
        return st.series.mean, st.series.std, False

    def _learn(self, st: "MetricState", x: float, ts: float):
        st.series.add(x)
        if self.season_on:
            st.season.setdefault(self.bucket(ts), Series(self.season_size)).add(x)

    # ---------------------------------------------------------------- scoring
    def sigma_eff(self, metric: str, mean: float, sd: float) -> float:
        return max(sd, self.rel_floor * abs(mean), self.abs_floor.get(metric, 0.0))

    def baseline(self, tenant: str, node: str) -> dict:
        """What the dashboard shows: per metric, the learned normal and whether it is warm."""
        out = {}
        for m, st in self._ms(tenant, node).items():
            n = len(st.series)
            mean, sd = st.series.mean, st.series.std
            sig = self.sigma_eff(m, mean, sd)
            out[m] = {"n": n, "warm": n >= self.warmup, "mean": round(mean, 3), "sigma": round(sd, 3), "sigma_eff": round(sig, 3),
                      "band_low": round(mean - self.thr * sig, 3), "band_high": round(mean + self.thr * sig, 3),
                      "open": st.open, "held_out": st.held_out, "level_shifts": st.shifts, "seasonal_buckets": len(st.season)}
        return out

    def observe(self, tenant: str, node: str, metrics: dict, ts: float, learn: bool = True) -> list:
        """Judge one sample. Returns one verdict per metric:
        {metric, value, mean, sigma, z, warm, raw, opened, closed, open, level_shift, onset_ts, direction}.
        learn=False scores without updating anything (what-if / replayed history)."""
        ms = self._ms(tenant, node)
        out = []
        for m, spec in METRICS.items():
            x = metrics.get(m)
            if x is None:
                continue
            x = float(x)
            st = ms[m]
            n = len(st.series)
            v = {"metric": m, "value": x, "warm": n >= self.warmup, "z": None, "raw": False, "opened": False, "closed": False,
                 "open": st.open, "level_shift": False, "onset_ts": st.onset_ts, "mean": None, "sigma": None, "direction": None}
            if n < self.warmup:
                if learn:
                    self._learn(st, x, ts)
                out.append(v)
                continue
            mean, sd, seas = self._stats(st, ts)
            sig = self.sigma_eff(m, mean, sd)
            z = (x - mean) / sig
            beyond = z > self.thr if spec["dir"] == "up" else abs(z) > self.thr
            v.update(z=round(z, 3), mean=mean, sigma=sig, raw=beyond, direction="above" if z >= 0 else "below", seasonal=seas)
            if not learn:
                out.append(v)
                continue
            st.flags.append(beyond)
            confirmed = beyond and (abs(z) >= self.fast or sum(st.flags) >= self.K)
            if beyond:
                if st.run_start_ts is None:
                    st.run_start_ts = ts
                st.recent_vals.append(x)
                if st.open or confirmed:
                    st.peak_z = max(st.peak_z, abs(z))
            if not st.open:
                if confirmed:                                        # opens: onset = first sample of this run
                    st.open, st.run_anom, st.run_ok = True, sum(st.flags), 0
                    st.onset_ts = st.run_start_ts if st.run_start_ts is not None else ts
                    v.update(opened=True, open=True, onset_ts=st.onset_ts)
                elif beyond:
                    st.held_out += 1                                 # suspicious but unconfirmed: do not learn it
                else:
                    self._learn(st, x, ts)                           # clean: learn
                    st.run_start_ts = None
                    st.recent_vals.clear()
            else:
                if beyond:
                    st.run_anom += 1
                    st.run_ok = 0
                    st.held_out += 1
                    if st.run_anom >= self.shift_n:                  # sustained: this is the new normal
                        st.series.clear()
                        st.season.clear()
                        for y in st.recent_vals:
                            st.series.add(y)
                        st.open, st.shifts = False, st.shifts + 1
                        st.run_anom = st.run_ok = 0
                        st.run_start_ts, st.onset_ts = None, None
                        st.flags.clear()
                        st.recent_vals.clear()
                        v.update(closed=True, open=False, level_shift=True)
                else:
                    st.run_ok += 1
                    if st.run_ok >= self.clear_n:
                        st.open, st.run_anom, st.run_ok = False, 0, 0
                        st.run_start_ts, st.peak_z = None, 0.0
                        st.recent_vals.clear()
                        st.flags.clear()
                        v.update(closed=True, open=False)
                    if not st.open:
                        self._learn(st, x, ts)
            v["peak_z"] = round(st.peak_z, 2)
            out.append(v)
        return out

    def open_metrics(self, tenant: str, node: str) -> list:
        return [m for m, st in self._ms(tenant, node).items() if st.open]


def signal_weights(verdicts: list) -> dict:
    """Normalised share of each open-anomaly metric in the evidence (z capped so one extreme metric cannot drown the rest)."""
    zs = {v["metric"]: min(abs(v["z"]), Z_CAP) for v in verdicts if v.get("open") and v.get("z") is not None}
    tot = sum(zs.values())
    return {m: round(z / tot, 3) for m, z in sorted(zs.items(), key=lambda kv: -kv[1])} if tot else {}


def describe(v: dict) -> str:
    """One human sentence. Numbers are stable enough that alerts.signature() (which strips digits) folds repeats."""
    spec = METRICS[v["metric"]]
    return (f"anomaly: {spec['label']} {v['value']:.0f}{spec['unit']} is {abs(v['z']):.1f}σ {v['direction']} its baseline "
            f"({v['mean']:.0f}{spec['unit']} ± {v['sigma']:.0f}{', for this hour of day' if v.get('seasonal') else ''})")


# ------------------------------------------------------------------------------------------------ forecast
class Trend:
    """Linear-trend forecast per (tenant, node, metric). Answers "when will this hit its limit?" only when the line really fits
    (r^2 >= min). Evaluated every few samples: the fit is O(window) and a forecast does not change in 5 s."""

    def __init__(self, th: dict):
        a = th["aiops"]
        self.W, self.min_r2, self.horizon = int(a["trend_window_samples"]), float(a["trend_min_r2"]), float(a["trend_horizon_s"])
        self.limits = {k: float(v) for k, v in a["trend_limits"].items()}
        self.series: dict = {}
        self.k: dict = {}

    def add(self, tenant: str, node: str, metric: str, ts: float, x: float) -> Optional[dict]:
        key = (tenant, node, metric)
        d = self.series.setdefault(key, deque(maxlen=self.W))
        d.append((ts, float(x)))
        self.k[key] = self.k.get(key, 0) + 1
        if metric not in self.limits or len(d) < max(12, self.W // 4) or self.k[key] % 4:
            return None
        return fit(list(d), self.limits[metric], self.min_r2, self.horizon, metric)


def fit(points: list, limit: float, min_r2: float, horizon_s: float, metric: str = "") -> Optional[dict]:
    t0 = points[0][0]
    xs, ys = [p[0] - t0 for p in points], [p[1] for p in points]
    n = len(xs)
    if xs[-1] - xs[0] < 60:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return None
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    slope = sxy / sxx
    syy = sum((y - my) ** 2 for y in ys)
    r2 = (sxy * sxy) / (sxx * syy) if syy > 0 else 0.0
    cur = slope * xs[-1] + (my - slope * mx)                 # fitted current value (less noisy than the last raw sample)
    if slope <= 0 or r2 < min_r2 or cur >= limit:
        return None
    eta = (limit - cur) / slope
    if eta > horizon_s:
        return None
    return {"metric": metric, "slope_per_min": round(slope * 60, 3), "r2": round(r2, 3), "eta_s": round(eta, 0), "limit": limit,
            "current": round(cur, 2)}
