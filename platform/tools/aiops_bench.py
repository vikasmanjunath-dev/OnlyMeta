"""P3 benchmark: synthetic LABELLED faults -> measured recall / false alerts / time-to-detect / root-cause accuracy, AIOps vs static thresholds.
  python3 tools/aiops_bench.py [--seeds 30] [--json out.json]
Everything is generated from a seeded RNG, so the numbers are reproducible; they describe THIS synthetic workload, not production."""
import argparse
import json
import random
import statistics as st
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from saas.aiops.baseline import Detector  # noqa: E402
from saas.aiops.correlate import Graph, rca  # noqa: E402
from saas.health import classify  # noqa: E402
from saas.topology import topology  # noqa: E402

TH = yaml.safe_load((ROOT / "contracts/thresholds.yaml").read_text())
TOPO = topology("tenant-alpha")
LAB = {v["label"]: p for p, v in TOPO.items()}
G = Graph(TOPO)
STEP, WARM, FAULT_AT, N_FAULT = 5, 120, 0, 60                    # 5 s samples, 10 min warm-up, 5 min fault window
NORMAL = {"app-01": dict(cpu=38, mem=55, latency_ms=40, packet_loss=0.1, bandwidth_mbps=100, disk=60),
          "db-01": dict(cpu=45, mem=62, latency_ms=12, packet_loss=0.05, bandwidth_mbps=140, disk=70),
          "net-01": dict(cpu=22, mem=40, latency_ms=8, packet_loss=0.05, bandwidth_mbps=300, disk=30)}
NOISE = dict(cpu=0.04, mem=0.012, latency_ms=0.12, packet_loss=0.25, bandwidth_mbps=0.06, disk=0.002)
DOWN = {"net-01": ["db-01", "app-01"], "db-01": ["app-01"], "app-01": []}   # who suffers when X is the root cause


def sample(rnd, node, over=None):
    m = {k: max(0.0, v * (1 + rnd.gauss(0, NOISE[k]))) for k, v in NORMAL[node].items()}
    for k, v in (over or {}).items():
        m[k] = max(0.0, v * (1 + rnd.gauss(0, NOISE[k])))
    m["cpu"], m["mem"] = min(m["cpu"], 100), min(m["mem"], 100)
    return m


def static_alert(m):
    return classify(m, 0, "METRICS", 3)[0] in ("FAIR", "POOR")


class Ours:
    name = "AIOps z-score"

    def __init__(self):
        self.d = Detector(TH)

    def step(self, node, m, ts):                                    # True on the sample where an anomaly OPENS
        return any(v["opened"] for v in self.d.observe("t", LAB[node], m, ts))


class _Roll:                                                         # shared: 2-of-3 confirmation like ours, so only the SCORE differs
    def __init__(self):
        self.h, self.flags, self.open = {}, {}, {}

    def step(self, node, m, ts):
        fire = False
        for k in ("cpu", "mem", "latency_ms", "packet_loss"):
            hist = self.h.setdefault((node, k), [])
            x = m[k]
            if len(hist) >= 30:
                beyond = self.score(hist, x, k) > 3.0
                f = self.flags.setdefault((node, k), [])
                f.append(beyond); del f[:-3]
                if beyond and not self.open.get((node, k)) and (sum(f) >= 2 or self.score(hist, x, k) >= 6):
                    self.open[(node, k)], fire = True, True
                elif not beyond and self.open.get((node, k)) and not any(f):
                    self.open[(node, k)] = False
            self.learn(hist, x)
        return fire


class Ewma(_Roll):
    name = "EWMA"

    def score(self, hist, x, k):
        mean, var = hist[-1]
        return abs(x - mean) / max(var ** 0.5, 0.05 * abs(mean), 0.01)

    def learn(self, hist, x):
        if not hist:
            hist.append((x, 0.0)); return
        mean, var = hist[-1]; d = x - mean
        hist.append((mean + 0.05 * d, 0.95 * (var + 0.05 * d * d)))
        del hist[:-40]
        if len(hist) < 30:
            hist.extend([hist[-1]] * (30 - len(hist)))


class Mad(_Roll):
    name = "rolling MAD"

    def score(self, hist, x, k):
        w = hist[-180:]
        med = st.median(w)
        mad = 1.4826 * st.median([abs(v - med) for v in w])
        return abs(x - med) / max(mad, 0.05 * abs(med), 0.01)

    def learn(self, hist, x):
        hist.append(x)
        del hist[:-180]


class Static:
    name = "static thresholds"

    def step(self, node, m, ts):
        a = static_alert(m)
        r = a and not getattr(self, "on", {}).get(node)
        self.__dict__.setdefault("on", {})[node] = a
        return r


DETECTORS = [Static, Ewma, Mad, Ours]


FAULTS = {                                                          # name -> (node, k -> overrides)
    "cpu_saturation (95%)": ("app-01", lambda k: dict(cpu=95)),
    "cpu_subtle (38→60%)": ("app-01", lambda k: dict(cpu=60)),
    "latency_subtle (12→45 ms)": ("db-01", lambda k: dict(latency_ms=45)),
    "cpu_slight (38→46%)": ("app-01", lambda k: dict(cpu=46)),
    "latency_slight (12→17 ms)": ("db-01", lambda k: dict(latency_ms=17)),
    "latency_hard (400 ms)": ("net-01", lambda k: dict(latency_ms=400)),
    "memory_creep (+0.4%/sample)": ("db-01", lambda k: dict(mem=62 + 0.4 * k)),
    "loss_small (0.05→1.5%)": ("net-01", lambda k: dict(packet_loss=1.5)),
}


def run_fault(seed, node, fn, cls=Ours):
    rnd, d = random.Random(seed), cls()
    ts = 0.0
    for _ in range(WARM):
        d.step(node, sample(rnd, node), ts); ts += STEP
    t0, hit = ts, None
    for k in range(N_FAULT):
        if d.step(node, sample(rnd, node, fn(k)), ts) and hit is None:
            hit = ts - t0
        ts += STEP
    return hit


def run_clean(seed, cls=Ours):
    """One clean hour on all three nodes -> (false opens, samples)."""
    rnd, d = random.Random(seed), cls()
    ts, fa, n = 0.0, 0, 0
    for i in range(WARM + 720):
        for node in NORMAL:
            o = d.step(node, sample(rnd, node), ts)
            if i >= WARM:
                fa += bool(o); n += 1
        ts += STEP
    return fa, n


def run_cascade(seed, root):
    rnd = random.Random(seed)
    det = {n: Detector(TH) for n in NORMAL}
    ts = 0.0
    for _ in range(WARM):
        for n in NORMAL:
            det[n].observe("t", LAB[n], sample(rnd, n), ts)
        ts += STEP
    lag = {root: 0.0, **{n: 4 + 5 * i + rnd.uniform(0, 3) for i, n in enumerate(DOWN[root])}}   # propagation delay, topology order
    mem, onset, first_alert = {}, {}, {}
    for k in range(N_FAULT):
        t = ts + k * STEP
        for n in NORMAL:
            over = None
            if n in lag and t - ts >= lag[n]:
                over = dict(latency_ms=NORMAL[n]["latency_ms"] * (14 if n == root else 6))
            m = sample(rnd, n, over)
            for v in det[n].observe("t", LAB[n], m, t):
                if v["opened"] and n not in mem:
                    mem[n] = {"onset_ts": v["onset_ts"], "state": "FAIR", "signals": [{"kind": "anomaly", "metric": v["metric"], "z": v["z"]}]}
            if n not in first_alert and static_alert(m):
                first_alert[n] = t
    if not mem:
        return None
    ex = rca({LAB[n]: x for n, x in mem.items()}, G, TH["aiops"])
    naive = min(first_alert, key=first_alert.get) if first_alert else None
    zmax = max(mem, key=lambda n: abs(mem[n]["signals"][0]["z"]))
    return {"rca": ex["root_label"] == root, "first_alert": naive == root, "max_z": zmax == root, "multi": len(mem) > 1}


def pct(a, b):
    return round(100 * a / b, 1) if b else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=30)
    ap.add_argument("--json")
    a = ap.parse_args()
    out = {"seeds": a.seeds, "faults": {}, "synthetic": True}
    names = [c.name for c in DETECTORS]
    print(f"\nAIOps benchmark - {a.seeds} seeded trials per cell - 5 s samples - 10 min warm-up - synthetic data")
    print("\nrecall % (median time-to-detect, s) per fault\n" + f"{'fault':30}" + "".join(f"{n[:22]:>24}" for n in names))
    for name, (node, fn) in FAULTS.items():
        row, cells = {}, ""
        for c in DETECTORS:
            r = [run_fault(sd, node, fn, c) for sd in range(a.seeds)]
            hit = [x for x in r if x is not None]
            row[c.name] = {"recall": pct(len(hit), a.seeds), "mttd_s": round(st.median(hit), 1) if hit else None}
            cells += f"{str(row[c.name]['recall']) + '%  (' + (str(row[c.name]['mttd_s']) if hit else '-') + ')':>24}"
        out["faults"][name] = row
        print(f"{name:30}{cells}")
    print("\nfalse anomalies per node-hour on clean running")
    out["clean"] = {}
    for c in DETECTORS:
        r = [run_clean(sd, c) for sd in range(max(5, a.seeds // 3))]
        fa, n = sum(x[0] for x in r), sum(x[1] for x in r)
        out["clean"][c.name] = {"node_hours": round(n * STEP / 3600, 1), "false": fa, "per_node_hour": round(fa / (n * STEP / 3600), 3)}
        print(f"  {c.name:28}{fa:4d} in {n * STEP / 3600:.0f} node-hours = {fa / (n * STEP / 3600):.2f}/node-hour")
    res = {r: [run_cascade(s, r) for s in range(a.seeds)] for r in DOWN}
    print(f"\nroot cause (cascade: fault propagates down the dependency chain, {a.seeds} trials each)")
    print(f"{'true root':12}{'RCA top-1':>12}{'first-alert':>14}{'highest-z':>12}")
    tot = {"rca": 0, "first_alert": 0, "max_z": 0, "n": 0}
    for root, rs in res.items():
        rs = [x for x in rs if x]
        row = {k: pct(sum(x[k] for x in rs), len(rs)) for k in ("rca", "first_alert", "max_z")}
        for k in ("rca", "first_alert", "max_z"):
            tot[k] += sum(x[k] for x in rs)
        tot["n"] += len(rs)
        print(f"{root:12}{str(row['rca']) + '%':>12}{str(row['first_alert']) + '%':>14}{str(row['max_z']) + '%':>12}")
        out.setdefault("rca", {})[root] = row
    out["rca"]["overall"] = {k: pct(tot[k], tot["n"]) for k in ("rca", "first_alert", "max_z")}
    print(f"{'overall':12}{str(out['rca']['overall']['rca']) + '%':>12}{str(out['rca']['overall']['first_alert']) + '%':>14}{str(out['rca']['overall']['max_z']) + '%':>12}\n")
    if a.json:
        Path(a.json).write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
