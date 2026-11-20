"""Four health states, worst signal wins. Downgrade on one sample, upgrade only after N clean samples (anti-flap).
Thresholds are the contract in thresholds.yaml (health_states). P3 can add anomaly reasons via `extra`."""
from typing import Optional

STATES = ["EXCELLENT", "GOOD", "FAIR", "POOR"]
RANK = {s: i for i, s in enumerate(STATES)}


def classify(m: dict, auth: int, category: str, cpu_hi_streak: int, extra: Optional[list] = None):
    """-> (state, reasons). `extra` = [(state, reason)] contributed by AIOps (e.g. open anomaly => FAIR)."""
    sig = []                                                    # (rank, reason)

    def add(state, reason):
        sig.append((RANK[state], reason))

    if category == "SERVICE_DOWN":
        add("POOR", "service down")
    if m["packet_loss"] > 10:
        add("POOR", f"packet loss {m['packet_loss']:.1f}% > 10%")
    elif m["packet_loss"] > 2:
        add("FAIR", f"packet loss {m['packet_loss']:.1f}% > 2%")
    elif m["packet_loss"] > 1:
        add("GOOD", f"packet loss {m['packet_loss']:.1f}% > 1%")
    if auth >= 10:
        add("POOR", f"{auth} failed logins in 60 s (brute force)")
    elif auth >= 5:
        add("FAIR", f"{auth} failed logins in 60 s")
    elif auth >= 3:
        add("GOOD", f"{auth} failed logins in 60 s")
    if m["cpu"] > 95 and cpu_hi_streak >= 3:
        add("POOR", f"CPU {m['cpu']:.0f}% > 95% for {cpu_hi_streak} samples")
    elif m["cpu"] > 85:
        add("FAIR", f"CPU {m['cpu']:.0f}% > 85%")
    elif m["cpu"] > 70:
        add("GOOD", f"CPU {m['cpu']:.0f}% > 70%")
    if m["mem"] > 90:
        add("FAIR", f"memory {m['mem']:.0f}% > 90%")
    elif m["mem"] > 80:
        add("GOOD", f"memory {m['mem']:.0f}% > 80%")
    if m["latency_ms"] > 250:
        add("FAIR", f"latency {m['latency_ms']:.0f} ms > 250 ms")
    elif m["latency_ms"] > 100:
        add("GOOD", f"latency {m['latency_ms']:.0f} ms > 100 ms")
    for st, reason in extra or []:
        add(st, reason)
    if not sig:
        return "EXCELLENT", ["all signals normal"]
    worst = max(r for r, _ in sig)
    return STATES[worst], [t for r, t in sorted(sig, reverse=True) if r == worst] + [t for r, t in sorted(sig, reverse=True) if r < worst]


def next_state(current: Optional[str], candidate: str, recent: list, clean_needed: int = 3):
    """Hysteresis. `recent` = candidate states of the last samples including this one (newest last).
    Returns the new state."""
    if current is None or RANK[candidate] >= RANK[current]:
        return candidate                                        # first sample, same, or worse: immediate
    last = recent[-clean_needed:]
    if len(last) == clean_needed and all(RANK[c] < RANK[current] for c in last):
        return max(last, key=RANK.get)                          # upgrade to the worst of the clean run
    return current
