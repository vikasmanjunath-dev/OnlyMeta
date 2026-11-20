"""Ask the platform: plain-English questions about incidents, nodes, fixes and SLOs, answered ONLY from this tenant's own records.

Deliberately not a language model. The question is parsed by rules (intent, node, incident reference, time window); every answer is
a template filled from the same data the Tracker shows, so it is deterministic, instant, offline, auditable, and cannot invent a
fact or leak another tenant's. Each answer carries `facts` (the values it used) and `cites` (the incident / remediation / anomaly
records behind it), which the UI links and the tests resolve. A question it cannot parse gets a list of what it can answer, never a guess.

Privacy: answers use node labels only (the SaaS never holds hostnames), and only this tenant's rows are ever read."""
import json
import re
import time
from typing import Optional

from saas.aiops.baseline import METRICS
from saas.aiops.correlate import COLLECTOR_PREFIX, SECURITY_PREFIX

EXAMPLES = ["What is wrong right now?", "Why did db-01 fail?", "What should I do about INC-1?", "Who approved the fix?", "How long did the last incident take?",
            "How is app-01?", "What depends on db-01?", "How many incidents in the last 24 hours?", "What are the open anomalies?", "What is our MTTD and MTTR?"]
MAX_Q = 300


def dur(s: Optional[float]) -> str:
    if s is None:
        return "n/a"
    s = max(float(s), 0.0)
    if s < 90:
        return f"{s:.0f} s"
    if s < 5400:
        return f"{s / 60:.0f} min"
    h, m = s // 3600, round((s % 3600) / 60)
    return f"{h:.0f} h" + (f" {m} min" if m else "")


def window(q: str):
    """(seconds, explicit?) from phrases like 'last 30 minutes', 'past hour', 'today', 'last 2 days'."""
    m = re.search(r"(?:last|past|previous)\s+(\d+)?\s*(min|minute|hour|hr|day|week)s?", q)
    if m:
        n = int(m.group(1) or 1)
        return n * {"min": 60, "minute": 60, "hour": 3600, "hr": 3600, "day": 86400, "week": 604800}[m.group(2)], True
    if "today" in q:
        return 86400, True
    return 3600, False


def norm(s: str) -> str:
    return re.sub(r"[\s_\-]+", "", s.lower())


def parse(q: str, labels: list) -> dict:
    ql = q.lower().strip()
    ref = re.search(r"\binc(?:ident)?[\s\-#]*(\d+)\b", ql)
    nq = norm(ql)
    nodes = sorted((nq.find(norm(l)), l) for l in labels if norm(l) and norm(l) in nq)
    win, explicit = window(ql)
    has = lambda *k: any(x in ql for x in k)  # noqa: E731
    intent = None
    if has("what can you", "help", "what do you know", "examples"):
        intent = "help"
    elif has("who approved", "who acknowledged", "who ack", "who rolled", "who executed", "approved by", "who fixed", "who did") or (has("who") and has("approv", "ack", "roll", "execut")):
        intent = "who"
    elif has("mttd", "mttr", "slo", "noise", "time to detect", "time to resolve", "detection time", "alert reduction"):
        intent = "slo"
    elif has("how many", "number of", "count"):
        intent = "count"
    elif has("depend", "affected by", "blast", "impact of", "downstream", "upstream", "what breaks", "if ") and nodes:
        intent = "blast"
    elif has("anomal", "z-score", "zscore", "deviation", "unusual"):
        intent = "anomalies"
    elif has("what should", "how do i", "how to fix", "how can i fix", "recommend", "remediat", "resolve", "fix", "mitigat", "what do i do", "next step", "action"):
        intent = "fix"
    elif has("when", "how long", "timeline", "duration", "took", "start", "sequence", "mttr"):
        intent = "timeline"
    elif has("why", "root cause", "cause", "reason", "what happened", "explain", "what caused", "because"):
        intent = "why"
    elif nodes and has("how is", "how's", "is ", "status", "health", "ok", "okay", "doing", "fine", "wrong with", "up", "down"):
        intent = "node"
    elif has("wrong", "open", "right now", "happening", "going on", "current", "ongoing", "active", "any problem", "any issue", "anything", "status", "broken", "alert", "incident"):
        intent = "open"
    return {"intent": intent, "incident": int(ref.group(1)) if ref else None, "nodes": [l for _, l in nodes], "window_s": win, "explicit_window": explicit}


class Ask:
    def __init__(self, ai):
        self.ai = ai

    # ---------------------------------------------------------------- helpers
    def _labels(self, tenant: str) -> list:
        g = self.ai.graph(tenant)
        seen = {r["node"] for r in self.ai.eng.store_of(tenant).q("SELECT node FROM node_state WHERE tenant_id=?", (tenant,))}
        return sorted({g.name(n) for n in seen | set(g.label)})

    def _node_of(self, tenant: str, label: str) -> Optional[str]:
        g = self.ai.graph(tenant)
        cand = [n for n in set(g.label) | {r["node"] for r in self.ai.eng.store_of(tenant).q("SELECT node FROM node_state WHERE tenant_id=?", (tenant,))} if g.name(n) == label]
        return cand[0] if cand else None

    def _incident(self, tenant: str, p: dict, prefer_open: bool = True) -> Optional[dict]:
        if p["incident"]:
            return self.ai.inc.get(tenant, p["incident"])
        lst = [i for i in self.ai.inc.list(tenant, None, 100) if i["status"] != "merged"]
        if p["nodes"]:
            lst = [i for i in lst if p["nodes"][0] in {m["label"] for m in i["members"]}]
        if not lst:
            return None
        pick = next((i for i in lst if i["status"] == "open"), lst[0]) if prefer_open else lst[0]
        return self.ai.inc.get(tenant, pick["id"])

    @staticmethod
    def _cite_inc(i: dict) -> dict:
        return {"type": "incident", "id": i["id"], "ref": i["ref"]}

    @staticmethod
    def _sig(s: dict) -> str:
        if s.get("kind") == "anomaly":
            if s["metric"] == "joint":
                return "unusual combination of metrics (jointly improbable)"
            sp = METRICS.get(s["metric"], {"label": s["metric"], "unit": ""})
            return f"{sp['label']} {s['value']:g}{sp['unit']} ({abs(s['z']):.1f}σ {'above' if s['z'] >= 0 else 'below'} its baseline of {s['baseline']:g})"
        return str(s.get("text") or s.get("metric"))

    @staticmethod
    def _none(text: str, intent: str, **facts) -> dict:
        return {"intent": intent, "answer": text, "facts": facts, "cites": []}

    # ---------------------------------------------------------------- answers
    def a_open(self, tenant, p, now):
        op = [i for i in self.ai.inc.list(tenant, "open", 50)]
        an = [a for a in self.ai.anomalies(tenant, "open", 100)]
        pend = [r for r in self.ai.rem.list(tenant, "pending_approval", None, 50)]
        if not op:
            rec = [i for i in self.ai.inc.list(tenant, "resolved", 5)]
            tail = f" The most recent resolved incident is {rec[0]['ref']} ({rec[0]['title']}, {dur(rec[0]['duration_s'])})." if rec else ""
            return {"intent": "open", "answer": f"No incident is open right now. {len(an)} anomal{'y is' if len(an) == 1 else 'ies are'} open.{tail}", "facts": {"open_incidents": 0, "open_anomalies": len(an)},
                    "cites": [self._cite_inc(rec[0])] if rec else []}
        lines = [f"{i['ref']} ({i['severity']}, {i['kind']}): {i['title']}; root cause {i['root_label']} at {round(i['confidence'] * 100)}% confidence, open for {dur(now - i['first_ts'])}."
                 for i in op]
        txt = f"{len(op)} incident{'s are' if len(op) != 1 else ' is'} open. " + " ".join(lines)
        if pend:
            txt += f" {len(pend)} proposed fix{'es are' if len(pend) != 1 else ' is'} waiting for approval."
        return {"intent": "open", "answer": txt, "facts": {"open_incidents": len(op), "open_anomalies": len(an), "pending_fixes": len(pend), "refs": [i["ref"] for i in op]},
                "cites": [self._cite_inc(i) for i in op] + [{"type": "remediation", "id": r["id"], "ref": r["ref"]} for r in pend[:3]]}

    def a_why(self, tenant, p, now):
        i = self._incident(tenant, p)
        if not i:
            return self._none(self._missing(p), "why")
        ex, root = i["explanation"], i["root_label"]
        m = next((x for x in i["members"] if x["label"] == root), None)
        ev = "; ".join(self._sig(s) for s in (m["signals"] if m else [])[:3])
        f = {x["name"]: x["contribution"] for x in ex.get("factors", [])}
        txt = f"{i['ref']} ({i['status']}): {i['summary']}"
        if f:
            txt += f" The ranking weighed coverage {f.get('coverage', 0):.2f}, timing {f.get('timing', 0):.2f} and signal strength {f.get('strength', 0):.2f} (confidence {round(i['confidence'] * 100)}%)."
        if ev:
            txt += f" Evidence on {root}: {ev}."
        if ex.get("multi_root"):
            txt += " Another node also shows a problem this failure does not explain: " + ", ".join(r["label"] for r in ex.get("independent_roots", [])) + "."
        if p["nodes"] and p["nodes"][0] != root and p["nodes"][0] in {x["label"] for x in i["members"]}:
            role = next(x["role"] for x in i["members"] if x["label"] == p["nodes"][0])
            txt = f"{p['nodes'][0]} was a {role} node in {i['ref']}, not its root cause. " + txt
        return {"intent": "why", "answer": txt, "facts": {"ref": i["ref"], "root": root, "confidence_pct": round(i["confidence"] * 100), "status": i["status"], "factors": f},
                "cites": [self._cite_inc(i)]}

    def a_fix(self, tenant, p, now):
        i = self._incident(tenant, p)
        if not i:
            return self._none(self._missing(p), "fix")
        rems = self.ai.rem.list(tenant, incident_id=i["id"])
        if i["status"] != "open":
            did = [r for r in rems if r["status"] in ("executed", "rolled_back", "verified")]
            txt = f"{i['ref']} is {i['status']}; no action is needed." + (f" {did[0]['ref']} ({did[0]['title']} on {did[0]['label']}) was {did[0]['status']}." if did else "")
            return {"intent": "fix", "answer": txt, "facts": {"ref": i["ref"], "status": i["status"]}, "cites": [self._cite_inc(i)]}
        recs = self.ai.recommendations(tenant, i["id"]) or []
        if not recs:
            return {"intent": "fix", "answer": f"{i['ref']} is open, but there is no safe automated action for {i['root_label']}'s problem; investigate it directly. {i['summary']}",
                    "facts": {"ref": i["ref"], "recommendations": 0}, "cites": [self._cite_inc(i)]}
        parts = []
        for r in recs[:2]:
            pred = (r.get("predicted") or {}).get("state")
            parts.append(f"{r['title']} on {r['label']} (risk {r['risk']}, confidence {round(r['confidence'] * 100)}%" + (f", the twin predicts {pred}" if pred else "") + ")")
        txt = f"For {i['ref']} ({i['root_label']}) the platform recommends: " + "; then ".join(parts) + ". Remediation is simulated here and needs an admin's approval."
        live = [r for r in rems if r["status"] in ("pending_approval", "approved", "executed", "advisory")]
        if live:
            txt += f" {live[0]['ref']} is already {live[0]['status'].replace('_', ' ')}."
        return {"intent": "fix", "answer": txt, "facts": {"ref": i["ref"], "recommendations": [r["title"] for r in recs[:2]]},
                "cites": [self._cite_inc(i)] + [{"type": "remediation", "id": r["id"], "ref": r["ref"]} for r in live[:2]]}

    def a_who(self, tenant, p, now):
        i = self._incident(tenant, p, prefer_open=False)
        if not i:
            return self._none(self._missing(p), "who")
        rems = self.ai.rem.list(tenant, incident_id=i["id"])
        bits = [f"{i['ref']} was acknowledged by {i['ack_by']}." if i.get("ack_by") else f"{i['ref']} has not been acknowledged."]
        cites = [self._cite_inc(i)]
        for r in rems[:3]:
            ap = ", ".join(a["user"] if isinstance(a, dict) else str(a) for a in (r.get("approvals") or []))
            bits.append(f"{r['ref']} ({r['title']} on {r['label']}) was proposed by {r['proposer']}, status {r['status'].replace('_', ' ')}" + (f", approved by {ap}" if ap else ", not yet approved") + ".")
            cites.append({"type": "remediation", "id": r["id"], "ref": r["ref"]})
        if not rems:
            bits.append("No fix was proposed.")
        return {"intent": "who", "answer": " ".join(bits), "facts": {"ref": i["ref"], "ack_by": i.get("ack_by"), "remediations": [r["ref"] for r in rems[:3]]}, "cites": cites}

    def a_timeline(self, tenant, p, now):
        i = self._incident(tenant, p, prefer_open=False)
        if not i:
            return self._none(self._missing(p), "timeline")
        mttd = (i["detected_ts"] - i["first_ts"]) if i.get("detected_ts") else None
        txt = f"{i['ref']} started {dur(now - i['first_ts'])} ago on {i['root_label']}" + (f" and was detected {dur(mttd)} after onset" if mttd is not None and mttd >= 0 else "")
        txt += f"; it was resolved after {dur(i['duration_s'])}." if i["resolved_ts"] else f"; it is still open ({dur(i['duration_s'])} so far)."
        ev = i.get("timeline", [])[:6]
        if ev:
            txt += " Sequence: " + "; ".join(f"+{dur(e['ts'] - i['first_ts'])} {e['kind'].replace('_', ' ')}" for e in ev) + "."
        return {"intent": "timeline", "answer": txt, "facts": {"ref": i["ref"], "duration_s": i["duration_s"], "status": i["status"]}, "cites": [self._cite_inc(i)]}

    def a_node(self, tenant, p, now):
        label = p["nodes"][0]
        node = self._node_of(tenant, label)
        st = self.ai.eng.store_of(tenant).one("SELECT * FROM node_state WHERE tenant_id=? AND node=?", (tenant, node)) if node else None
        if not st:
            return self._none(f"I have no data for a node called {label} in this tenant.", "node")
        m = json.loads(st["metrics"] or "{}")
        an = [a for a in self.ai.anomalies(tenant, "open", 100) if a["label"] == label]
        inc = [i for i in self.ai.inc.list(tenant, "open", 50) if label in {x["label"] for x in i["members"]}]
        txt = f"{label} is {st['state']} (last data {dur(now - st['last_seen_ts'])} ago; CPU {m.get('cpu', 0):.0f}%, memory {m.get('mem', 0):.0f}%, latency {m.get('latency_ms', 0):.0f} ms, packet loss {m.get('packet_loss', 0):.1f}%)."
        txt += (f" It has {len(an)} open anomal{'y' if len(an) == 1 else 'ies'}: " + ", ".join(f"{a['metric_label']} ({abs(a['z']):.1f}σ)" for a in an[:3]) + ".") if an else " No open anomalies."
        txt += (" It is part of " + ", ".join(i["ref"] for i in inc) + ".") if inc else ""
        fc = (self.ai.insights.get(tenant, {}).get(node) or {})
        for metric, f in list(fc.items())[:1]:
            txt += f" Forecast: {METRICS[metric]['label']} is trending towards its limit."
        return {"intent": "node", "answer": txt, "facts": {"node": label, "state": st["state"], "open_anomalies": len(an), "incidents": [i["ref"] for i in inc]},
                "cites": [{"type": "node", "label": label}] + [self._cite_inc(i) for i in inc]}

    def a_blast(self, tenant, p, now):
        label = p["nodes"][0]
        node = self._node_of(tenant, label)
        g = self.ai.graph(tenant)
        if not node or (node not in g.deps and not any(node in d for d in g.deps.values())):
            return self._none(f"{label} is not in this tenant's dependency map, so I cannot say what depends on it.", "blast")
        down, up = sorted(g.name(n) for n in g.dependents(node)), sorted(g.name(n) for n in g.upstream(node))
        txt = f"{label} " + (f"is depended on by {', '.join(down)}, which {'is' if len(down) == 1 else 'are'} hurt when it is" if down else "has no dependents") + (f"; it depends on {', '.join(up)}" if up else "; it depends on nothing else") + "."
        return {"intent": "blast", "answer": txt, "facts": {"node": label, "dependents": down, "depends_on": up}, "cites": [{"type": "node", "label": label}]}

    def a_count(self, tenant, p, now):
        s = self.ai.inc.summary(tenant, now, p["window_s"])
        k = ", ".join(f"{n} {k}" for k, n in s["by_kind"].items() if n) or "none"
        txt = (f"In the last {dur(p['window_s'])}: {s['open']} open, {s['resolved']} resolved, {s['merged']} merged incident(s) ({k})."
               + (f" {s['alerts_linked_to_incident']} of {s['alerts_in_window']} alerts were grouped into incidents." if s["alerts_in_window"] else ""))
        return {"intent": "count", "answer": txt, "facts": {k2: s[k2] for k2 in ("open", "resolved", "merged", "alerts_in_window", "alerts_linked_to_incident")}, "cites": []}

    def a_anomalies(self, tenant, p, now):
        an = self.ai.anomalies(tenant, "open", 100)
        if not an:
            sm = self.ai.summary(tenant, now, p["window_s"])
            return self._none(f"No anomaly is open. {sm['anomalies']} were raised in the last {dur(p['window_s'])}.", "anomalies", open=0, window_anomalies=sm["anomalies"])
        top = sorted(an, key=lambda a: -abs(a["z"]))[:5]
        txt = f"{len(an)} open: " + "; ".join(f"{a['label']} {a['metric_label']} {abs(a['z']):.1f}σ" for a in top) + "."
        return {"intent": "anomalies", "answer": txt, "facts": {"open": len(an)}, "cites": [{"type": "anomaly", "id": a["id"]} for a in top]}

    def a_slo(self, tenant, p, now):
        win = max(p["window_s"], 3600)
        s = self.ai.summary(tenant, now, win)
        sl, tg = s["slo"], s["slo"]["targets"]
        d, r, n = sl["mttd"], sl["mttr"], sl["noise"]
        parts = [f"detection p50 {dur(d['p50'])}, p95 {dur(d['p95'])} against a {tg['mttd_s']} s target ({d['n']} measured)" if d["n"] else "no detections measured yet",
                 f"resolution p50 {dur(r['p50'])} against a {tg['mttr_s']} s target ({r['n']} resolved)" if r["n"] else "no incident resolved yet",
                 f"{n['alerts']} alerts became {n['incidents']} incident(s)" + (f", a {n['reduction_pct']}% reduction" if n["reduction_pct"] is not None else "")]
        return {"intent": "slo", "answer": f"Over the last {dur(win)}: " + "; ".join(parts) + ".", "facts": {"mttd_p50": d["p50"], "mttr_p50": r["p50"], "alerts": n["alerts"], "incidents": n["incidents"]}, "cites": []}

    def a_help(self, tenant, p, now):
        return {"intent": "help", "answer": "I answer from this tenant's own incident, node and remediation records (no model, no guessing). Ask about: open incidents, why something failed, what to do, who approved, timelines, a node's health, what depends on a node, counts, anomalies, MTTD/MTTR.",
                "facts": {}, "cites": []}

    def _missing(self, p) -> str:
        if p["incident"]:
            return f"I have no incident INC-{p['incident']} in this tenant."
        if p["nodes"]:
            return f"I found no incident involving {p['nodes'][0]}."
        return "I found no incident in this tenant."

    # ---------------------------------------------------------------- entry
    def answer(self, tenant: str, question: str, now: Optional[float] = None) -> dict:
        now = now if now is not None else time.time()
        q = (question or "").strip()[:MAX_Q]
        labels = self._labels(tenant)
        p = parse(q, labels)
        known = re.findall(r"\b[a-z]+-\d{2}\b", q.lower())
        unknown = [k for k in known if k not in {norm_l.lower() for norm_l in labels} and not re.match(r"inc-\d+", k)]
        if not q:
            return {"question": q, "intent": "help", **self.a_help(tenant, p, now), "followups": EXAMPLES[:4], "parsed": p}
        if unknown and not p["nodes"]:
            out = self._none(f"I do not know a node called {unknown[0]} in this tenant. Known nodes: {', '.join(labels) or 'none yet'}.", "unknown_node")
        elif not p["intent"] and p["nodes"]:
            p["intent"] = "node"
            out = self.a_node(tenant, p, now)
        elif not p["intent"]:
            out = {"intent": "unsupported", "answer": "I can only answer questions about this platform's incidents, nodes, fixes and SLOs, and I do not guess. Try one of the examples.", "facts": {}, "cites": []}
        else:
            out = getattr(self, "a_" + p["intent"])(tenant, p, now)
        if not out["cites"] and out["intent"] in ("unsupported", "unknown_node"):
            out["followups"] = EXAMPLES[:5]
        out.setdefault("followups", self._followups(out))
        return {"question": q, "parsed": {k: p[k] for k in ("intent", "incident", "nodes", "window_s")}, **out}

    @staticmethod
    def _followups(out: dict) -> list:
        ref = next((c["ref"] for c in out["cites"] if c["type"] == "incident"), None)
        if ref:
            return [f"Why did {ref} happen?", f"What should I do about {ref}?", f"Who approved the fix for {ref}?", f"How long did {ref} take?"]
        return EXAMPLES[:3]
