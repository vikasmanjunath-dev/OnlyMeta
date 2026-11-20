import diagrams as D

TOTAL = 13
FOOT = "CICADA 2026 · Secure Two-Tier AIOps Observability · Phase 1: Problem Understanding & Ideation"


def page(n, acc, chip, title, sub, body, z=1.0):
    hdr = (f'<div class="hdr"><span class="chip">{chip}</span><div><h1>{title}</h1><div class="sub">{sub}</div></div></div>')
    return (f'<section class="page" style="--acc:{acc}"><div class="topbar"></div>{hdr}<div style="zoom:{z}">{body}</div>'
            f'<div class="ftr"><span>{FOOT}</span><span>Page {n} / {TOTAL}</span></div></section>')


pages = []

# ------------------------------------------------------------------ 1 COVER
cover = f'''
<section class="page" style="background:linear-gradient(135deg,#0B1F3A 0%,#1E1B4B 55%,#4C1D95 100%); padding:0;">
  <svg style="position:absolute;left:0;top:0" width="100%" height="100%" viewBox="0 0 1122 794" preserveAspectRatio="none">
    <circle cx="1020" cy="90" r="190" fill="#7C3AED" opacity=".22"/><circle cx="1090" cy="700" r="230" fill="#0D9488" opacity=".22"/>
    <circle cx="60" cy="760" r="150" fill="#E11D48" opacity=".16"/><circle cx="520" cy="-20" r="120" fill="#F59E0B" opacity=".14"/>
  </svg>
  <div class="topbar" style="height:10px"></div>
  <div style="position:absolute;left:60px;top:64px;right:60px;">
    <span class="chip" style="background:#F59E0B;color:#0B1F3A;font-size:11px">CICADA 2026 · 24-HOUR HACKATHON · TechForcz × Atria Institute of Technology</span>
    <h1 style="color:#fff;font-size:50px;line-height:1.05;margin-top:22px;font-weight:800">Secure Two-Tier<br>AIOps Observability</h1>
    <div style="color:#C4B5FD;font-size:20px;margin-top:14px;font-weight:600">Phase 1 · Problem Understanding &amp; Ideation</div>
    <div style="color:#CBD5E1;font-size:14px;margin-top:6px">Complete end-to-end submission pack · 10 marks</div>
  </div>
  <div style="position:absolute;left:60px;top:322px;width:660px">{D.cover_hero()}</div>
  <div style="position:absolute;left:60px;top:584px;right:60px;display:flex;gap:10px;flex-wrap:wrap">
    <span class="chip" style="background:#0D9488;font-size:12px;padding:6px 14px">Local-first data security</span>
    <span class="chip" style="background:#E11D48;font-size:12px;padding:6px 14px">Metadata-only SaaS</span>
    <span class="chip" style="background:#7C3AED;font-size:12px;padding:6px 14px">AIOps-driven operations</span>
    <span class="chip" style="background:#2563EB;font-size:12px;padding:6px 14px">Global-ready design</span>
    <span class="chip" style="background:#F59E0B;color:#0B1F3A;font-size:12px;padding:6px 14px">Autonomous-Ops roadmap</span>
  </div>
  <div style="position:absolute;left:60px;bottom:44px;color:#94A3B8;font-size:12px">Team: ______________________ &nbsp;·&nbsp; Team ID: ________ &nbsp;·&nbsp; Prepared Nov 20, 2026</div>
</section>'''
pages.append(cover)

# ------------------------------------------------------------------ 2 AT A GLANCE
rows = [
    ("1", "Why raw telemetry stays local; SaaS gets metadata only", "p.3", "#0D9488"),
    ("2", "Use cases: infra health, latency / packet loss, failed logins, fleet health", "p.6", "#2563EB"),
    ("3", "Prioritised features with a clear minimum viable demo", "p.9", "#F59E0B"),
    ("4", "What stays local / is redacted / is sent; tenant separation", "p.7 – 8", "#E11D48"),
    ("5", "Feasible 24-hour scope, roles, simulated-telemetry plan", "p.10 – 11", "#7C3AED"),
    ("Q1", "Before observability: the situation before monitoring was in place", "p.4", "#B91C1C"),
    ("Q2", "Observation: what the team now observes with the solution", "p.4 · p.12", "#047857"),
]
rhtml = "".join(
    f'<tr><td style="width:34px"><span class="tag" style="--c:{c};font-size:10px;padding:3px 8px">{k}</span></td>'
    f'<td style="font-size:11.5px;font-weight:600">☑ &nbsp;{t}</td><td style="width:70px;font-weight:800;color:{c};font-size:11.5px">{p}</td></tr>'
    for k, t, p, c in rows)
body = f'''
<div class="grid" style="grid-template-columns:1.05fr 1fr;gap:16px">
  <div style="display:flex;flex-direction:column;gap:12px">
    <div class="card" style="--c:#7C3AED;--bg:#F5F3FF"><div class="strip"></div>
      <h3>The solution in one sentence</h3>
      <p class="big">A <b style="color:#0D9488">local collector</b> keeps raw logs and secrets inside the customer environment and sends only
      <b style="color:#E11D48">allow-listed metadata</b> to a <b style="color:#7C3AED">multi-tenant SaaS</b>, which shows four health states,
      explainable anomalies and incidents, and <b>proves what left the building</b> with an Egress Proof Panel.</p></div>
    <div class="grid g3">
      <div class="card" style="--c:#E11D48;--bg:#FFF1F2"><div class="strip"></div><h3>Problem</h3><p>Raw logs shipped to a central platform expose secrets, create blind spots and drown operators in noisy alerts.</p></div>
      <div class="card" style="--c:#0D9488;--bg:#F0FDFA"><div class="strip"></div><h3>Solution</h3><p>Two tiers: collect, redact and analyse locally; transmit metadata; correlate and explain centrally.</p></div>
      <div class="card" style="--c:#2563EB;--bg:#EFF6FF"><div class="strip"></div><h3>Proof</h3><p>Egress panel, sent = received IDs, timestamps for every latency target, tenant isolation test.</p></div>
    </div>
    <div class="card" style="--c:#F59E0B;--bg:#FFFBEB"><div class="strip"></div>
      <h3>Evidence the Phase 1 judge will ask for</h3>
      <ul><li><b>One-page data-flow sketch</b> with the trust boundary between Tier 1 and Tier 2 → <b>page 5</b></li>
      <li><b>Allow-list fields</b> and examples of what is redacted or dropped → <b>page 7</b></li>
      <li><b>Simulated-telemetry plan</b> and who builds which component → <b>pages 10 – 11</b></li></ul></div>
  </div>
  <div>
    <div class="card" style="--c:#0B1F3A;padding:0"><table><tr><th colspan="3">Phase 1 scoring checklist · where each criterion is answered</th></tr>{rhtml}</table></div>
    <div class="grid g2" style="margin-top:12px">
      <div class="card" style="--c:#16A34A;--bg:#F0FDF4"><div class="strip"></div><h3>Strong (what we show)</h3>
        <ul><li>Precisely states what leaves</li><li>Small set of high-value use cases</li><li>Believable 24-hour plan</li></ul></div>
      <div class="card" style="--c:#E11D48;--bg:#FFF1F2"><div class="strip"></div><h3>Weak (what we avoid)</h3>
        <ul><li>Generic dashboard idea</li><li>Vague metadata-only boundary</li><li>Scope far too large to finish</li></ul></div>
    </div>
  </div>
</div>'''
pages.append(page(2, "#7C3AED", "PHASE 1 · 10 MARKS", "Phase 1 at a glance", "Every checkbox on the score sheet, mapped to the page that answers it", body, z=1.25))

# ------------------------------------------------------------------ 3 WHY LOCAL
body = f'''
<div class="grid g4">
  <div class="card" style="--c:#E11D48;--bg:#FFF1F2"><div class="strip"></div><h3>Data exposure risk</h3><p>Shipping raw logs, payloads and credentials to a central platform widens the attack surface and can breach compliance obligations.</p></div>
  <div class="card" style="--c:#2563EB;--bg:#EFF6FF"><div class="strip"></div><h3>Operational blind spots</h3><p>Teams running many sites, networks and apps need one consolidated view without losing local control of their data.</p></div>
  <div class="card" style="--c:#F59E0B;--bg:#FFFBEB"><div class="strip"></div><h3>Alert fatigue</h3><p>Static thresholds create noisy, duplicated alerts. Operators need correlated incidents with likely causes.</p></div>
  <div class="card" style="--c:#7C3AED;--bg:#F5F3FF"><div class="strip"></div><h3>Global operations</h3><p>Customers span regions, time zones and data-residency rules, so the platform must be designed for that from day one.</p></div>
</div>
<div style="margin-top:12px">
  <div class="note" style="margin-bottom:4px"><b>Representational model:</b> detail shrinks as data moves right; decisions are taken locally, so only a thin metadata layer crosses the boundary.</div>
  {D.funnel()}
</div>
<div class="grid" style="grid-template-columns:1.2fr 1fr;margin-top:8px">
  <div class="card" style="--c:#0D9488;--bg:#F0FDFA"><div class="strip"></div><h3>Why the SaaS still works with metadata only</h3>
    <ul><li><b>Anomaly detection</b> needs numbers over time (rolling baseline per metric), not log text.</li>
    <li><b>Correlation</b> needs which node, when and how severe: pseudonymous node IDs plus a dependency map are enough.</li>
    <li><b>Security signals</b> are summarised locally (failed logins per 60 s) so the SaaS sees a risk indicator, never the credentials.</li>
    <li><b>Recommendations</b> are explained from metric deviations, so no payload content is required.</li></ul></div>
  <div class="card" style="--c:#E11D48;--bg:#FFF1F2"><div class="strip"></div><h3>Three guarantees we can demonstrate</h3>
    <ul><li><b>Structural allow-list:</b> a field not in the schema cannot be serialised.</li>
    <li><b>Visible proof:</b> Egress Proof Panel shows the exact payload before it leaves.</li>
    <li><b>Safe delivery:</b> persist before send, delete only after ACK; unique <span class="mono">payload_id</span> means no duplicates.</li></ul></div>
</div>'''
pages.append(page(3, "#0D9488", "CRITERION 1", "Why raw telemetry stays local, and SaaS gets metadata only", "Problem understanding: the risk, the principle and why metadata is still enough", body, z=1.15))

# ------------------------------------------------------------------ 4 BEFORE / AFTER
body = f'''
<div class="grid g2" style="gap:14px">
  <div class="card" style="--c:#E11D48;--bg:#FFF5F5;padding-bottom:6px"><div class="strip" style="height:7px"></div>
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px"><span class="tag" style="--c:#E11D48;font-size:11px;padding:3px 10px">Q1</span><h3 style="font-size:15px;margin:0">BEFORE observability: what was the situation?</h3></div>
    {D.before_svg()}
    <ul style="margin-top:6px">
      <li><b>Blind spots:</b> sites, networks and apps watched through separate tools; failures were often noticed when users complained.</li>
      <li><b>Data exposure:</b> the usual fix shipped raw logs and payloads to a central platform, moving credentials outside the customer's control.</li>
      <li><b>Alert fatigue:</b> static thresholds gave duplicate, noisy alerts; one database bottleneck looked like many unrelated problems.</li>
      <li><b>Security signals buried:</b> repeated failed logins found only by reading raw logs after the fact.</li>
      <li><b>Silent failures:</b> a dead agent kept showing its last good value, so nobody knew it had stopped.</li>
      <li><b>No proof:</b> nobody could show exactly what data left the environment.</li></ul>
  </div>
  <div class="card" style="--c:#047857;--bg:#F0FDF9;padding-bottom:6px"><div class="strip" style="height:7px"></div>
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px"><span class="tag" style="--c:#047857;font-size:11px;padding:3px 10px">Q2</span><h3 style="font-size:15px;margin:0">OBSERVATION: what the team now observes</h3></div>
    {D.after_svg()}
    <div class="grid g2" style="gap:6px;margin-top:6px">
      <div style="background:#CCFBF1;border-radius:8px;padding:6px 8px"><div style="font-size:10px;font-weight:800;color:#115E59">FLEET</div><div style="font-size:10px;line-height:1.35">online / offline · last seen (UTC) · version · resource use · config status · region</div></div>
      <div style="background:#DBEAFE;border-radius:8px;padding:6px 8px"><div style="font-size:10px;font-weight:800;color:#1E40AF">INFRASTRUCTURE</div><div style="font-size:10px;line-height:1.35">CPU · memory · disk · service state → one of 4 health states with a reason</div></div>
      <div style="background:#FEF3C7;border-radius:8px;padding:6px 8px"><div style="font-size:10px;font-weight:800;color:#92400E">NETWORK</div><div style="font-size:10px;line-height:1.35">bandwidth · latency · packet loss · connectivity</div></div>
      <div style="background:#FFE4E6;border-radius:8px;padding:6px 8px"><div style="font-size:10px;font-weight:800;color:#9F1239">SECURITY</div><div style="font-size:10px;line-height:1.35">failed-login bursts as a count + pseudonymous source, never raw records</div></div>
      <div style="background:#EDE9FE;border-radius:8px;padding:6px 8px"><div style="font-size:10px;font-weight:800;color:#5B21B6">AIOPS</div><div style="font-size:10px;line-height:1.35">z-score anomalies · related alerts merged into one incident · weights + reasoning</div></div>
      <div style="background:#DCFCE7;border-radius:8px;padding:6px 8px"><div style="font-size:10px;font-weight:800;color:#166534">TRUST</div><div style="font-size:10px;line-height:1.35">egress log · delivery stats (received, duplicates, p95) · audit trail</div></div>
    </div>
    <div class="note" style="margin-top:6px">Phase 1 = design intent: these are the signals the solution is built to observe, not yet claims about a running system.</div>
  </div>
</div>'''
pages.append(page(4, "#B91C1C", "Q1 + Q2", "Before observability vs. what we now observe", "The situation before monitoring, and what the two-tier solution makes visible", body, z=1.25))

# ------------------------------------------------------------------ 5 DATA FLOW
legend = [
    ("1", "#0D9488", "Sources → adapter", "agents · SNMP · syslog · flow · APIs"),
    ("2", "#0D9488", "Raw copy kept local", "1 h retention, never serialised"),
    ("3", "#0D9488", "Local pipeline", "redact → aggregate → analyse → policy → scan → egress log"),
    ("4", "#E11D48", "Collector → SaaS", "POST /ingest batch over HTTPS/TLS + X-Collector-Key"),
    ("5", "#7C3AED", "SaaS → collector", "ACK (accepted + duplicates) → delete from outbox"),
    ("6", "#7C3AED", "Ingest → analytics", "auth, tenant check, dedup, store, health, AIOps"),
    ("7", "#2563EB", "SaaS → dashboard", "server-sent events, scoped per tenant"),
]
lg = "".join(f'<div style="display:flex;gap:6px;align-items:flex-start"><span style="flex:none;width:17px;height:17px;border-radius:9px;background:{c};color:#fff;font-size:10px;font-weight:800;text-align:center;line-height:17px">{n}</span><div style="font-size:9.5px;line-height:1.3"><b>{t}</b><br><span style="color:#64748B">{d}</span></div></div>' for n, c, t, d in legend)
body = f'''
{D.dataflow()}
<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:7px 14px;margin-top:6px">{lg}
  <div style="display:flex;gap:6px;align-items:flex-start"><span style="flex:none;width:17px;height:17px;border-radius:3px;background:#E11D48"></span><div style="font-size:9.5px;line-height:1.3"><b>Trust boundary</b><br><span style="color:#64748B">everything left of it is customer-controlled</span></div></div>
</div>'''
pages.append(page(5, "#0D9488", "THE ONE-PAGE DATA-FLOW SKETCH", "Data flow and trust boundary between Tier 1 and Tier 2", "Every hop is numbered; the red dashed line is the only place data leaves the customer environment", body))

# ------------------------------------------------------------------ 6 USE CASES
def uc(color, bg, title, spark, rows_):
    r = "".join(f'<tr><td style="width:84px;font-weight:800;color:{color};font-size:10px">{a}</td><td style="font-size:10.5px">{b}</td></tr>' for a, b in rows_)
    return f'''<div class="card" style="--c:{color};--bg:{bg}"><div class="strip" style="height:6px"></div><h3 style="font-size:14px">{title}</h3>
    <div style="background:#fff;border-radius:8px;margin:4px 0 6px 0;border:1px solid {color}33">{spark}</div><table style="background:#fff;border-radius:8px">{r}</table></div>'''
body = '<div class="grid g2" style="gap:12px">' + \
    uc("#0D9488", "#F0FDFA", "1 · Infrastructure health", D.sp_cpu(), [
        ("Signals", "CPU · memory · disk · service up / down"),
        ("Local step", "5 s aggregation per node, moving average, service check"),
        ("Leaves", "cpu / mem / disk %, severity, category"),
        ("SaaS shows", "Health state + reason, e.g. “CPU 91 over 85 limit”"),
        ("Question answered", "Which node needs attention, and why?")]) + \
    uc("#2563EB", "#EFF6FF", "2 · Network latency and packet loss", D.sp_lat(), [
        ("Signals", "bandwidth · latency · packet loss · connectivity"),
        ("Local step", "sampling and aggregation per node"),
        ("Leaves", "bandwidth_mbps, latency_ms, packet_loss (numbers only)"),
        ("SaaS shows", "z-score anomaly, severity, trend, dependent service impact"),
        ("Thresholds", "latency over 250 ms = Fair · loss over 10 % = Poor")]) + \
    uc("#E11D48", "#FFF1F2", "3 · Repeated failed logins", D.sp_login(), [
        ("Signals", "authentication failures from local auth logs"),
        ("Local step", "rolling 60 s counter; raw events never leave"),
        ("Leaves", "auth_failures_60s (a count) + pseudonymous source"),
        ("SaaS shows", "Security alert “Brute force attempt”, no usernames, no IPs"),
        ("Thresholds", "5 in 60 s = Fair · 10 in 60 s = Poor")]) + \
    uc("#7C3AED", "#F5F3FF", "4 · Collector fleet health", D.sp_fleet(), [
        ("Signals", "heartbeat (each payload), version, config status"),
        ("Local step", "collector stamps version, region, config status"),
        ("Leaves", "collector_version, config_status, region, UTC time"),
        ("SaaS shows", "online / offline, last seen, resource usage; 30 s silence = POOR"),
        ("Rule", "stale data downgrades; last good value is never shown")]) + '</div>'
pages.append(page(6, "#2563EB", "CRITERION 2", "Use cases: four high-value scenarios", "Each use case follows the same pattern: signal → local processing → minimal metadata → actionable view", body))

# ------------------------------------------------------------------ 7 WHAT STAYS / REDACTED / SENT
body = f'''
<div class="grid g3" style="gap:12px">
  <div class="card" style="--c:#E11D48;--bg:#FFF1F2"><div class="strip" style="height:6px"></div><h3 style="font-size:14px">STAYS LOCAL · never serialised</h3>
    <ul><li>Raw log lines and payload bodies</li><li>Passwords, API keys, tokens</li><li>Usernames and email addresses</li><li>Raw IP addresses and real hostnames</li><li>Any free-text field</li><li>Anything not defined in the schema</li></ul>
    <p class="note" style="margin-top:4px">Raw store retention: 1 hour, then deleted.</p></div>
  <div class="card" style="--c:#F59E0B;--bg:#FFFBEB"><div class="strip" style="height:6px"></div><h3 style="font-size:14px">REDACTED / TRANSFORMED</h3>
    <ul><li>Secret patterns (<span class="mono">sk-…</span>, <span class="mono">password=</span>, tokens) scrubbed</li><li>Hostnames and source IPs → <b>HMAC pseudonyms</b>: <span class="mono">n-</span> + HMAC-SHA256(tenant key, value)[:10]</li><li>Failed-login events → a <b>count</b> per 60 s</li><li>Free text → dropped</li><li>Payload still matching a secret pattern → <b>BLOCKED</b>, logged</li></ul></div>
  <div class="card" style="--c:#16A34A;--bg:#F0FDF4"><div class="strip" style="height:6px"></div><h3 style="font-size:14px">SENT · allow-listed fields only</h3>
    <ul><li><span class="mono">payload_id</span>, <span class="mono">tenant_id</span>, <span class="mono">collector_id</span>, <span class="mono">region</span></li><li><span class="mono">collector_version</span>, <span class="mono">config_status</span></li><li><span class="mono">event_time</span> (UTC), <span class="mono">source_tz</span>, <span class="mono">sent_at</span>, <span class="mono">is_replay</span></li><li><span class="mono">node_pseudonym</span>, <span class="mono">event_category</span>, <span class="mono">severity</span></li><li><span class="mono">metrics</span>: cpu, mem, disk, bandwidth_mbps, latency_ms, packet_loss</li><li><span class="mono">auth_failures_60s</span>, <span class="mono">auth_source_pseudonym</span></li></ul></div>
</div>
<div class="grid" style="grid-template-columns:1fr 38px 1fr;margin-top:12px;align-items:stretch;gap:6px">
  <div class="codebox" style="background:#FFF1F2;border:2px solid #E11D48">
    <div style="font-size:10px;font-weight:800;color:#9F1239;margin-bottom:3px">RAW EVENT · exists on the collector only</div>
<pre>{{ "ts": "2026-11-20T10:30:00Z",
  "host": "prod-db-01.corp.local",
  "src_ip": "192.168.1.50",
  "<span class="red">api_key</span>": "<span class="red">sk-proj-9988221100</span>",
  "raw_log": "Failed login for root from
    192.168.1.50 <span class="red">password=Summer@2026</span>",
  "cpu_percent": 94.2, "mem_percent": 81.0 }}</pre></div>
  <div style="display:flex;align-items:center;justify-content:center;flex-direction:column"><div style="font-size:26px;color:#E11D48;font-weight:800">➜</div><div style="font-size:7.5px;font-weight:800;color:#9F1239;text-align:center">POLICY<br>+ SCAN</div></div>
  <div class="codebox" style="background:#F0FDF4;border:2px solid #16A34A">
    <div style="font-size:10px;font-weight:800;color:#166534;margin-bottom:3px">OUTBOUND PAYLOAD · exactly what crosses the wire</div>
<pre>{{ "payload_id": "9a8b7c6d-…", "tenant_id": "tenant-alpha",
  "collector_id": "col-alpha-01", "region": "in",
  "event_time": "2026-11-20T10:30:00Z", "source_tz": "Asia/Kolkata",
  "node_pseudonym": "<span class="grn">n-8f3a1b9c2d</span>",
  "event_category": "SECURITY_BURST", "severity": "high",
  "metrics": {{ "cpu": 94.2, "mem": 81.0, … }},
  "auth_failures_60s": <span class="grn">14</span>,
  "auth_source_pseudonym": "<span class="grn">n-41c07de9aa</span>" }}</pre></div>
</div>
<div class="note" style="margin-top:3px">Illustrative values. Pseudonym values are examples only.</div>
<div class="grid" style="grid-template-columns:1fr 24px 1fr 24px 1fr;gap:4px;margin-top:8px;align-items:center">
  <div class="card" style="--c:#0D9488;--bg:#F0FDFA;padding:8px 10px"><h3 style="margin:0;font-size:11.5px">LAYER 1 · Schema allow-list</h3><p style="font-size:10px">pydantic model with <span class="mono">extra="forbid"</span>: unknown fields cannot be serialised. This is the real defence.</p></div>
  <div style="color:#94A3B8;font-size:18px;text-align:center">+</div>
  <div class="card" style="--c:#F59E0B;--bg:#FFFBEB;padding:8px 10px"><h3 style="margin:0;font-size:11.5px">LAYER 2 · Regex scrub</h3><p style="font-size:10px">Strips secret patterns from any text that is displayed or kept in local summaries.</p></div>
  <div style="color:#94A3B8;font-size:18px;text-align:center">+</div>
  <div class="card" style="--c:#E11D48;--bg:#FFF1F2;padding:8px 10px"><h3 style="margin:0;font-size:11.5px">LAYER 3 · Outbound scanner</h3><p style="font-size:10px">Last check before send: a payload matching a secret pattern is blocked and logged as BLOCKED.</p></div>
</div>'''
pages.append(page(7, "#E11D48", "CRITERION 4 · EVIDENCE", "What stays local, what is redacted, what is sent", "The allow-list, with a before-and-after example and the three-layer defence", body, z=1.25))

# ------------------------------------------------------------------ 8 TENANT SEPARATION
def mark(v):
    return {"y": '<span class="ok">✓</span>', "n": '<span class="no">✗</span>', "-": '<span class="na">–</span>'}[v]
mat = [
    ("Raw logs, secrets, usernames, IPs", "y", "n", "n", "n"),
    ("Own tenant metadata and dashboards", "-", "y", "n", "n"),
    ("Another tenant's metadata", "n", "n", "n", "n"),
    ("Own audit log and remediation approval", "-", "y", "n", "n"),
    ("Collector retention and policy settings", "y", "n", "n", "n"),
]
mt = "".join(f'<tr><td style="font-weight:600">{a}</td>' + "".join(f'<td style="text-align:center;font-size:14px">{mark(v)}</td>' for v in r) + "</tr>" for a, *r in mat)
body = f'''
<div style="background:#fff;border:1.5px solid #E2E8F0;border-radius:12px;padding:8px">{D.tenant_svg()}</div>
<div class="grid" style="grid-template-columns:1.15fr 1fr;margin-top:10px;gap:12px">
  <div class="card" style="--c:#0B1F3A;padding:0"><table>
    <tr><th>Who can see what (proposed access policy)</th><th style="text-align:center">Customer admin<br><span style="font-weight:400">Tier 1 UI</span></th><th style="text-align:center">Tenant operator<br><span style="font-weight:400">SaaS login</span></th><th style="text-align:center">Other tenant<br><span style="font-weight:400">operator</span></th><th style="text-align:center">SaaS platform<br><span style="font-weight:400">staff</span></th></tr>{mt}</table>
    <div class="note" style="padding:4px 8px">SaaS staff cannot see raw data because it is never received. ✓ allowed · ✗ denied · – not applicable.</div></div>
  <div class="card" style="--c:#7C3AED;--bg:#F5F3FF"><div class="strip"></div><h3>Metadata-only SaaS flow: how isolation is enforced</h3>
    <ul><li><b>Per-collector API key</b> bound to one tenant and one region; <span class="mono">tenant_id</span> is taken from the key, never from the request body.</li>
    <li><b>tenant_id on every row</b> and in every query; SSE streams are scoped per tenant.</li>
    <li><b>Region store per tenant:</b> one SQLite file per region; a payload whose region differs from the tenant's is rejected.</li>
    <li><b>Isolation test:</b> beta token sees zero alpha rows.</li>
    <li><b>Production path:</b> separate schemas or stores per tenant, mTLS, key rotation.</li></ul></div>
</div>'''
pages.append(page(8, "#7C3AED", "CRITERION 4", "Metadata-only SaaS flow and tenant separation", "Who can see what, and how the platform guarantees one customer never sees another's metadata", body))

# ------------------------------------------------------------------ 9 FEATURES + MVP
def tier(color, bg, tag, title, items):
    li = "".join(f"<li>{i}</li>" for i in items)
    return f'<div class="card" style="--c:{color};--bg:{bg}"><div class="strip" style="height:6px"></div><span class="tag" style="--c:{color}">{tag}</span><h3 style="font-size:13px;margin-top:4px">{title}</h3><ul>{li}</ul></div>'
body = f'''
<div class="grid g4" style="gap:10px">
  {tier("#E11D48", "#FFF1F2", "P0 · MVP", "Must ship, never cut", ["Collector on the organizer stream + schema allow-list + secret scrubbing", "Egress Proof Panel (raw ⟷ outbound)", "SQLite outbox: persist → send → ACK → delete", "Authenticated ingest (TLS + API key), dedup by payload_id", "4 health states + stale-data rule, live UTC dashboard"])}
  {tier("#F59E0B", "#FFFBEB", "P1 · Score boosters", "Built right after MVP", ["Rolling z-score anomalies, warm-up fallback", "Correlation: 5 alerts → 1 incident with explanation", "Local failed-login detection → security alert", "Two tenants (alpha / in, beta / eu) isolation test", "Latency clock + measured p95"])}
  {tier("#2563EB", "#EFF6FF", "P2 · If time allows", "Bonus and polish", ["Safe remediation simulation: propose → policy → approve → audit → rollback", "Fleet page and state history", "Per-region stores + residency rejection", "Collector config polling"])}
  {tier("#64748B", "#F1F5F9", "ROADMAP · not built", "Stated honestly", ["Autonomous Ops with approved, reversible actions", "Seasonal baselines; learned topology from flow data", "mTLS, key rotation, secret vault", "Kafka + TimescaleDB at scale"])}
</div>
<div style="margin-top:10px;display:flex;align-items:center;gap:10px"><span class="chip" style="--acc:#E11D48">MINIMUM VIABLE DEMO · 5 minutes, four proofs</span><span class="note">Everything below runs on the organizer stream, not on hard-coded screens.</span></div>
<div class="grid g4" style="margin-top:8px;gap:10px">
  <div><div style="background:#fff;border-radius:10px">{D.sb1()}</div><div style="font-size:10.5px;margin-top:4px"><b style="color:#E11D48">① Secret stays home.</b> Inject a secret: visible in the raw panel, absent from the outbound JSON and the SaaS.</div></div>
  <div><div style="background:#fff;border-radius:10px">{D.sb2()}</div><div style="font-size:10.5px;margin-top:4px"><b style="color:#D97706">② Survive an outage.</b> Kill SaaS 30 s: collector goes POOR, buffers, drains; sent IDs = received IDs.</div></div>
  <div><div style="background:#fff;border-radius:10px">{D.sb3()}</div><div style="font-size:10.5px;margin-top:4px"><b style="color:#0D9488">③ Explain the anomaly.</b> Inject a CPU spike: z-score, baseline, signal weights, recommendation.</div></div>
  <div><div style="background:#fff;border-radius:10px">{D.sb4()}</div><div style="font-size:10.5px;margin-top:4px"><b style="color:#2563EB">④ Tenants never mix.</b> Beta token requests alpha data and gets zero rows.</div></div>
</div>
<div class="card" style="--c:#0B1F3A;--bg:#F8FAFC;margin-top:10px;padding:8px 12px"><p><b>Cut order if behind schedule</b> (never cut the P0 items): second tenant and fleet page → TLS to plain HTTP on localhost (stated openly) → remediation polish → recommendation table reduced to 3 patterns.</p></div>'''
pages.append(page(9, "#F59E0B", "CRITERION 3", "Prioritised features and the minimum viable demo", "A realistic scope: P0 proves the privacy boundary; P1 adds the intelligence; P2 and roadmap are optional", body, z=1.2))

# ------------------------------------------------------------------ 10 PLAN + ROLES
def role(color, bg, title, port, owns, proof):
    return f'''<div class="card" style="--c:{color};--bg:{bg};padding:9px 11px"><div class="strip" style="height:6px"></div>
    <h3 style="font-size:12.5px;margin-bottom:2px">{title} <span style="font-size:9px;color:#64748B;font-weight:600">{port}</span></h3>
    <p style="font-size:10px"><b>Owns:</b> {owns}</p><p style="font-size:10px;margin-top:2px"><b style="color:{color}">Proof:</b> {proof}</p></div>'''
body = f'''
<div class="note" style="margin-bottom:3px"><b>Representational model:</b> hour-by-hour plan from the team playbook (15 build hours); hours 15–24 are buffer for judging slots and fixes. Hours are compressed to the left.</div>
<div style="background:#fff;border:1.5px solid #E2E8F0;border-radius:12px;padding:6px">{D.gantt()}</div>
<div class="grid g4" style="margin-top:9px;gap:9px">
  {role("#0D9488", "#F0FDFA", "P1 · Collector (Tier 1)", "port 8001", "stream adapter, 3-layer redaction, egress log, outbox + sender, failed-login detection, scenario injector", "Egress panel; sent = received")}
  {role("#7C3AED", "#F5F3FF", "P2 · SaaS backend", "port 8000", "ingest, auth, tenants, dedup, event-time store, health engine, SSE, latency metrics, audit", "Same payload 3× = 1 row; beta sees 0 alpha")}
  {role("#D97706", "#FFFBEB", "P3 · AIOps + remediation", "module in SaaS", "z-score baselines, correlation, explanations, recommendations, remediation flow", "Weights sum to 100; exactly one incident")}
  {role("#E11D48", "#FFF1F2", "P4 · Frontend + demo", "static pages", "dashboard, egress panel UI, incident widgets, trust-boundary diagram, slides, Q&amp;A", "Latency clock; rehearsed 8–10 min demo")}
</div>
<div class="grid g3" style="margin-top:9px;gap:9px">
  <div class="card" style="--c:#2563EB;--bg:#EFF6FF;padding:7px 11px"><p><b style="color:#2563EB">CHECKPOINT 1 · hour 5</b> One payload flows collector → SaaS → screen, live; latency clock under 10 s.</p></div>
  <div class="card" style="--c:#16A34A;--bg:#F0FDF4;padding:7px 11px"><p><b style="color:#16A34A">CHECKPOINT 2 · hour 8</b> Kill SaaS: POOR within 35 s, queue rises, drains; sent = received, duplicates = 0.</p></div>
  <div class="card" style="--c:#E11D48;--bg:#FFF1F2;padding:7px 11px"><p><b style="color:#E11D48">FEATURE FREEZE · hour 13</b> All 8 scenarios back-to-back without a restart; then bug fixes and rehearsal only.</p></div>
</div>'''
pages.append(page(10, "#16A34A", "CRITERION 5", "Feasible 24-hour scope, roles and plan", "Four owners, one shared contract, three hard checkpoints and a freeze", body, z=1.2))

# ------------------------------------------------------------------ 11 TELEMETRY + GLOBAL
body = f'''
<div class="grid g2" style="gap:14px">
  <div class="card" style="--c:#F59E0B;--bg:#FFFBEB"><div class="strip" style="height:6px"></div><h3 style="font-size:14px">Simulated-telemetry plan</h3>
    <div style="background:#fff;border-radius:10px;border:1px solid #FDE68A">{D.telemetry_svg()}</div>
    <ul style="margin-top:6px"><li>The <b>organizer stream is the source of truth</b>: the same stream for all teams, so bursts, latency spikes and outages are injected identically.</li>
    <li>If its format differs from our sample, only <span class="mono">adapter.py</span> changes.</li>
    <li>Until the spec arrives, <span class="mono">sample_stream.jsonl</span> (60 lines incl. fake secrets) unblocks P2–P4 by hour 1.5.</li></ul></div>
  <div class="card" style="--c:#2563EB;--bg:#EFF6FF"><div class="strip" style="height:6px"></div><h3 style="font-size:14px">Early global-readiness: regions, time zones, residency</h3>
    <div style="background:#fff;border-radius:10px;border:1px solid #BFDBFE">{D.global_svg()}</div>
    <ul style="margin-top:6px"><li><b>Regional ingest:</b> each tenant sends to its assigned region.</li>
    <li><b>Residency:</b> metadata stays in the tenant's region (simulated with one DB file per region).</li>
    <li><b>UTC + source timezone</b> on every event; ordering by event time, not arrival.</li></ul></div>
</div>
<div class="grid g4" style="margin-top:10px;gap:10px">
  <div class="card" style="--c:#0D9488;--bg:#F0FDFA;padding:8px 11px"><h3 style="font-size:11.5px;margin-bottom:2px">Regions</h3><p style="font-size:10px">alpha → IN, beta → EU, configured in <span class="mono">tenants.yaml</span>.</p></div>
  <div class="card" style="--c:#7C3AED;--bg:#F5F3FF;padding:8px 11px"><h3 style="font-size:11.5px;margin-bottom:2px">Time zones</h3><p style="font-size:10px">UTC for logic, source timezone for display; charts labelled UTC.</p></div>
  <div class="card" style="--c:#F59E0B;--bg:#FFFBEB;padding:8px 11px"><h3 style="font-size:11.5px;margin-bottom:2px">Out-of-order</h3><p style="font-size:10px">Late events slot into place by event time without corrupting trends.</p></div>
  <div class="card" style="--c:#E11D48;--bg:#FFF1F2;padding:8px 11px"><h3 style="font-size:11.5px;margin-bottom:2px">Idempotent retry</h3><p style="font-size:10px"><span class="mono">payload_id</span> is created once; retries after outages never duplicate.</p></div>
</div>'''
pages.append(page(11, "#F59E0B", "CRITERION 5 · TELEMETRY + GLOBAL", "Simulated-telemetry plan and early global awareness", "How we get comparable data without real devices, and how the design respects regions, time zones and residency", body, z=1.15))

# ------------------------------------------------------------------ 12 MODELS
body = f'''
<div class="note" style="margin-bottom:6px">Preview of the product models behind Q2 (what we observe). Numbers on this page are illustrative; thresholds come from the team's configurable constants.</div>
<div class="grid g3" style="gap:12px">
  <div class="card" style="--c:#16A34A;--bg:#fff"><div class="strip" style="height:6px"></div><h3 style="font-size:13.5px">A · Four health states (worst signal wins)</h3>
    <div style="display:flex;flex-direction:column;gap:5px;margin-top:4px">
      <div style="background:#16A34A;color:#fff;border-radius:8px;padding:6px 9px"><b style="font-size:11.5px">EXCELLENT · healthy</b><div style="font-size:9.5px">CPU &lt; 70 · mem &lt; 80 · latency &lt; 100 ms · loss &lt; 1 % · logins &lt; 3</div></div>
      <div style="background:#2563EB;color:#fff;border-radius:8px;padding:6px 9px"><b style="font-size:11.5px">GOOD · normal</b><div style="font-size:9.5px">CPU 70–85 · latency 100–250 ms · loss 1–2 % · logins 3–4</div></div>
      <div style="background:#D97706;color:#fff;border-radius:8px;padding:6px 9px"><b style="font-size:11.5px">FAIR · needs attention</b><div style="font-size:9.5px">CPU &gt; 85 · latency &gt; 250 ms · loss 2–10 % · logins 5–9 · open anomaly</div></div>
      <div style="background:#E11D48;color:#fff;border-radius:8px;padding:6px 9px"><b style="font-size:11.5px">POOR · critical</b><div style="font-size:9.5px">Collector silent 30 s · loss &gt; 10 % · service down · logins ≥ 10</div></div>
    </div>
    <ul style="margin-top:6px"><li>Downgrade on one sample; upgrade after 3 clean samples</li><li>Stale data = POOR, never the last good value</li><li>Every transition logged with UTC time and reason</li></ul></div>
  <div class="card" style="--c:#2563EB;--bg:#fff"><div class="strip" style="height:6px"></div><h3 style="font-size:13.5px">B · Anomaly beyond a static threshold</h3>
    {D.zscore_svg()}
    <ul><li>Rolling 15-minute baseline per metric</li><li>Warm-up fallback to static limits; sigma floor avoids false alarms on flat metrics</li></ul></div>
  <div class="card" style="--c:#7C3AED;--bg:#fff"><div class="strip" style="height:6px"></div><h3 style="font-size:13.5px">C · Correlation and explanation</h3>
    {D.incident_svg()}
    <ul style="margin-top:2px"><li>Alerts within 30 s on nodes linked in the dependency map merge into one incident</li></ul></div>
</div>
<div style="margin-top:10px"><div class="note" style="margin-bottom:4px"><b>Roadmap model:</b> how the observations grow from monitoring to Autonomous Ops. Stages 1–4 are prototype scope; stage 5 is simulated and kept human-approved.</div>
<div style="display:flex;gap:0">
<div style="flex:1;background:#0D9488;color:#fff;padding:9px 16px 9px 12px;margin-left:0px;clip-path:polygon(0 0,calc(100% - 14px) 0,100% 50%,calc(100% - 14px) 100%,0 100%,0px 50%);"><div style="font-size:11px;font-weight:800">1. OBSERVE</div><div style="font-size:9.5px;line-height:1.3;opacity:.95">collect and visualise health, metrics, events, collector status</div></div><div style="flex:1;background:#2563EB;color:#fff;padding:9px 16px 9px 22px;margin-left:-10px;clip-path:polygon(0 0,calc(100% - 14px) 0,100% 50%,calc(100% - 14px) 100%,0 100%,14px 50%);"><div style="font-size:11px;font-weight:800">2. DETECT</div><div style="font-size:9.5px;line-height:1.3;opacity:.95">anomalies and unusual patterns from metadata</div></div><div style="flex:1;background:#7C3AED;color:#fff;padding:9px 16px 9px 22px;margin-left:-10px;clip-path:polygon(0 0,calc(100% - 14px) 0,100% 50%,calc(100% - 14px) 100%,0 100%,14px 50%);"><div style="font-size:11px;font-weight:800">3. CORRELATE</div><div style="font-size:9.5px;line-height:1.3;opacity:.95">group related alerts, identify affected components</div></div><div style="flex:1;background:#D97706;color:#fff;padding:9px 16px 9px 22px;margin-left:-10px;clip-path:polygon(0 0,calc(100% - 14px) 0,100% 50%,calc(100% - 14px) 100%,0 100%,14px 50%);"><div style="font-size:11px;font-weight:800">4. RECOMMEND</div><div style="font-size:9.5px;line-height:1.3;opacity:.95">likely causes and remediation steps for operator review</div></div><div style="flex:1;background:#64748B;color:#fff;padding:9px 16px 9px 22px;margin-left:-10px;clip-path:polygon(0 0,calc(100% - 14px) 0,100% 50%,calc(100% - 14px) 100%,0 100%,14px 50%);"><div style="font-size:11px;font-weight:800">5. ACT (future)</div><div style="font-size:9.5px;line-height:1.3;opacity:.95">approved, policy-bounded, reversible actions with audit and rollback</div></div>
</div></div>'''
pages.append(page(12, "#2563EB", "Q2 · REPRESENTATIVE MODELS", "What the team observes: health, anomalies and incidents", "Three models that turn metadata into an explainable, actionable view", body, z=1.1))

# ------------------------------------------------------------------ 13 Q&A
qa = [
    ("#E11D48", "Exactly what leaves the environment?", "Only schema fields: numeric metrics, UTC time + source timezone, HMAC-pseudonymous node and source IDs, severity, category, counts (failed logins per 60 s), version, config status, payload_id. Raw logs, secrets, usernames, raw IPs, hostnames and free text stay in Tier 1."),
    ("#7C3AED", "Why is metadata enough for AIOps?", "Baselines and z-scores need numbers over time; correlation needs which node, when and how severe (pseudonyms plus a dependency map); recommendations are explained from metric deviations, not log text."),
    ("#0D9488", "How do you stop a secret slipping out?", "Three layers: schema allow-list (structural), regex scrub, and an outbound scanner that blocks a matching payload and logs it as BLOCKED. The Egress Proof Panel shows the result live."),
    ("#2563EB", "Who can see what?", "Raw data: the customer on the Tier 1 UI only. Metadata: that tenant's operators only, enforced by key-bound tenant_id on every query. Other tenants and SaaS staff get nothing raw, because it never arrives."),
    ("#F59E0B", "Is the scope realistic in 24 hours?", "P0 is small and proves the boundary. Checkpoints at hours 5 and 8, freeze at 13, a written cut list, and hours 15–24 as buffer."),
    ("#16A34A", "How do you test without real devices?", "The organizer stream plus our injector for the eight judge scenarios. Honest limit: no real SNMP or syslog at volume; scale path is stated."),
]
qh = "".join(f'<div class="card" style="--c:{c};padding:8px 11px"><h3 style="font-size:11.5px;margin-bottom:2px">{q}</h3><p style="font-size:10px">{a}</p></div>' for c, q, a in qa)
body = f'''
<div class="grid g2" style="gap:9px">{qh}</div>
<div class="grid" style="grid-template-columns:1fr 1fr 1fr;gap:10px;margin-top:10px">
  <div class="card" style="--c:#0B1F3A;--bg:#F8FAFC"><div class="strip" style="height:6px"></div><h3 style="font-size:12.5px">Evidence pack: hand to the judge</h3>
    <ul style="list-style:none;padding-left:0"><li>☐ &nbsp;One-page data-flow sketch with trust boundary <b>(p.5)</b></li><li>☐ &nbsp;Allow-list fields + redaction examples <b>(p.7)</b></li><li>☐ &nbsp;Telemetry plan + role split <b>(p.10 – 11)</b></li><li>☐ &nbsp;Feature list signed off by all four members <b>(p.9)</b></li></ul></div>
  <div class="card" style="--c:#16A34A;--bg:#F0FDF4"><div class="strip" style="height:6px"></div><h3 style="font-size:12.5px">Self-check against “Strong”</h3>
    <ul style="list-style:none;padding-left:0"><li><span class="ok">✓</span> States precisely what leaves (p.7)</li><li><span class="ok">✓</span> Four high-value use cases (p.6)</li><li><span class="ok">✓</span> Believable 24-hour plan (p.10)</li><li><span class="ok">✓</span> Tenant separation and “who sees what” (p.8)</li><li><span class="ok">✓</span> Early awareness of regions, time zones, residency (p.11)</li></ul></div>
  <div class="card" style="--c:#E11D48;--bg:#FFF1F2"><div class="strip" style="height:6px"></div><h3 style="font-size:12.5px">Honest Phase 1 limitations</h3>
    <ul><li>Telemetry is simulated from the organizer stream</li><li>SQLite and a single process; production uses Kafka + TimescaleDB</li><li>Residency simulated with separate DB files</li><li>Self-signed TLS in demo; production needs mTLS and key rotation</li></ul></div>
</div>'''
pages.append(page(13, "#0B1F3A", "JUDGE Q&amp;A · EVIDENCE", "Phase 1 judge questions, evidence pack and self-check", "Short, precise answers: say exactly what leaves, pick few use cases, show a believable plan", body, z=1.36))

html = ('<!DOCTYPE html><html><head><meta charset="utf-8"><title>CICADA 2026 · Phase 1 · Problem Understanding & Ideation</title>'
        '<style>' + open("style.css").read() + '</style></head><body>' + "".join(pages) + '</body></html>')
open("phase1.html", "w").write(html)
print("pages:", len(pages))
