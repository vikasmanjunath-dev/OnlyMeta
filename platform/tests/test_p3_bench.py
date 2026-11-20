"""The benchmark is deterministic: guard its headline claims so a detector change that regresses them fails CI."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import aiops_bench as b  # noqa: E402


def test_subtle_faults_caught_that_static_misses():
    for name in ("cpu_subtle (38→60%)", "latency_subtle (12→45 ms)", "memory_creep (+0.4%/sample)"):
        node, fn = b.FAULTS[name]
        assert all(b.run_fault(s, node, fn, b.Ours) is not None for s in range(10)), name
        assert all(b.run_fault(s, node, fn, b.Static) is None for s in range(10)), name
    node, fn = b.FAULTS["memory_creep (+0.4%/sample)"]
    assert all(b.run_fault(s, node, fn, b.Ewma) is None for s in range(10))     # a learn-everything EWMA follows the leak and never fires


def test_clean_running_has_no_false_anomalies():
    fa, n = b.run_clean(1, b.Ours)
    assert fa == 0 and n > 2000
    assert sum(b.run_clean(s, b.Mad)[0] for s in range(6)) > 0                  # the more sensitive MAD does raise false anomalies


def test_root_cause_beats_naive_heuristics():
    res = {r: [b.run_cascade(s, r) for s in range(10)] for r in b.DOWN}
    ok = {k: sum(x[k] for rs in res.values() for x in rs if x) for k in ("rca", "first_alert", "max_z")}
    assert ok["rca"] == 30 and ok["rca"] > ok["first_alert"] and ok["rca"] > ok["max_z"]
