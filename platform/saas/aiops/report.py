"""Blameless post-mortem draft from an incident record: facts only (what, when, why, what was done, how it was verified)."""
from datetime import datetime, timezone


def _t(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%H:%M:%S") if ts else "-"


def _sig(s):
    return f"{s['metric']} {s['value']} ({s['z']:+}σ vs {s['baseline']})" if s.get("kind") == "anomaly" else str(s.get("text") or s.get("metric"))


def postmortem(v: dict) -> str:
    ex, end = v.get("explanation") or {}, v.get("resolved_ts")
    o = [f"# {v['ref']} · {v['title']}", "",
         f"- Status **{v['status']}** · severity **{v['severity']}** · kind {v['kind']} · detected {_t(v['first_ts'])} UTC"
         + (f" · resolved {_t(end)} UTC (duration {round(end - v['first_ts'])} s)" if end else ""),
         f"- Root cause: **{v.get('root_label') or 'undetermined'}** (confidence {round((v.get('confidence') or 0) * 100)}%)", "",
         "## Summary", v.get("summary") or "-", ""]
    if ex.get("factors"):
        o += ["## Why this root cause (weighted)", *[f"- {f['name']} (weight {f['weight']}): {f['note']} → {f['contribution']}" for f in ex["factors"]], ""]
    o += ["## Impact", *[f"- **{m['label']}** {m['state']}{' (recovered)' if m.get('recovered') else ''}: " + "; ".join(_sig(s) for s in m.get("signals", [])) for m in v.get("members", [])], ""]
    o += ["## Timeline (UTC)", *[f"- {_t(e['ts'])} {e['kind']}" for e in v.get("timeline", [])], ""]
    rs = v.get("remediations") or []
    o += ["## Actions (simulated, audited)"]
    o += [f"- {r['ref']} {r['title']} on {r['label']}: {r['status']}"
          + (f", verification {r['verdict']['verdict']} ({r['verdict'].get('note', '')})" if (r.get("verdict") or {}).get("verdict") else "")
          + (f", approved by {', '.join(a['user'] if isinstance(a, dict) else str(a) for a in r.get('approvals', []))}" if r.get("approvals") else "") for r in rs] or ["- none taken"]
    o += ["", "## Follow-ups", "- [ ] Confirm the root cause against the host's own logs (this draft is derived from telemetry only)",
          "- [ ] Decide whether the recommended fix should become an alert threshold or runbook step", ""]
    return "\n".join(o)
