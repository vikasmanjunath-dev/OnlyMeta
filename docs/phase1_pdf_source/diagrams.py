from svgh import *

TEAL, VIO, ROSE, BLUE, GRN, AMB, SLT, NAVY = "#0D9488", "#7C3AED", "#E11D48", "#2563EB", "#16A34A", "#F59E0B", "#64748B", "#0B1F3A"


# ---------------- Cover hero ----------------
def cover_hero():
    b = ""
    b += R(0, 20, 300, 190, "#0F2A4A", TEAL, 18, 2.5)
    b += T(150, 46, "TIER 1 · CUSTOMER ENVIRONMENT", 11, "#5EEAD4", 800, "middle")
    for i, (t, c) in enumerate([("Apps", "#14B8A6"), ("Servers", "#14B8A6"), ("Network", "#14B8A6"), ("Auth logs", "#F43F5E")]):
        b += R(16, 62 + i * 34, 76, 26, c, "none", 7)
        b += T(54, 79 + i * 34, t, 11, "#fff", 700, "middle")
    b += line([(92, 75), (118, 120)], "#5EEAD4"); b += line([(92, 109), (118, 124)], "#5EEAD4")
    b += line([(92, 143), (118, 128)], "#5EEAD4"); b += line([(92, 177), (118, 132)], "#5EEAD4")
    b += R(118, 92, 166, 78, "#134E4A", "#5EEAD4", 12)
    b += T(201, 118, "LOCAL COLLECTOR", 12, "#fff", 800, "middle")
    b += T(201, 135, "redact · aggregate · analyse", 10, "#99F6E4", 500, "middle")
    b += T(201, 151, "allow-list · egress log", 10, "#99F6E4", 500, "middle")
    # boundary
    b += '<line x1="330" y1="10" x2="330" y2="220" stroke="#FB7185" stroke-width="3" stroke-dasharray="8 6"/>'
    b += R(300, 90, 60, 26, "#E11D48", "none", 13)
    b += T(330, 107, "TLS + key", 10, "#fff", 800, "middle")
    b += line([(284, 132), (390, 132)], "#FDA4AF", sw=3.5)
    b += T(337, 152, "metadata only", 10.5, "#FDA4AF", 700, "middle")
    b += R(390, 20, 260, 190, "#2E1065", "#A78BFA", 18, 2.5)
    b += T(520, 46, "TIER 2 · MULTI-TENANT SaaS", 11, "#C4B5FD", 800, "middle")
    for i, (t, c) in enumerate([("Excellent", "#16A34A"), ("Good", "#2563EB"), ("Fair", "#F59E0B"), ("Poor", "#E11D48")]):
        b += R(406 + i * 60, 62, 54, 24, c, "none", 7)
        b += T(433 + i * 60, 78, t, 10, "#fff", 700, "middle")
    b += R(406, 98, 228, 46, "#4C1D95", "#A78BFA", 10)
    b += T(520, 117, "1 INCIDENT ← 5 ALERTS", 11, "#fff", 800, "middle")
    b += T(520, 133, "explainable · z-score · correlated", 10, "#DDD6FE", 500, "middle")
    sp = spark([40, 42, 41, 43, 42, 44, 41, 43, 70, 78, 76, 55, 44], 228, 50, "#C4B5FD", hl=[8, 9, 10], fill=False)
    b += '<g transform="translate(406,150)">' + sp + "</g>"
    return svg(660, 230, b)


# ---------------- Page 3: funnel ----------------
def funnel():
    b = ""
    b += R(8, 14, 270, 204, "#FEE2E2", ROSE, 14, 2)
    b += T(143, 38, "RAW TELEMETRY", 13, "#9F1239", 800, "middle")
    for i, t in enumerate(["Full log lines & payload bodies", "Passwords · API keys · tokens", "Usernames · emails",
                           "Raw IPs · real hostnames", "Free-text messages"]):
        b += R(22, 50 + i * 30, 242, 24, "#fff", "#FDA4AF", 6, 1)
        b += T(32, 66 + i * 30, t, 11, "#7F1D1D", 600)
    b += T(143, 212, "STAYS IN TIER 1 · full detail", 10, "#9F1239", 800, "middle")
    b += line([(282, 116), (330, 116)], SLT, sw=3)
    b += R(334, 34, 300, 164, "#CCFBF1", TEAL, 14, 2)
    b += T(484, 56, "LOCAL PROCESSING (Tier 1)", 13, "#115E59", 800, "middle")
    steps = ["1  Filter & redact secrets", "2  Aggregate · 5 s window per node", "3  Analyse locally (login bursts, averages)",
             "4  Apply data policy · schema allow-list", "5  Scan outbound · write egress log"]
    for i, t in enumerate(steps):
        b += R(348, 66 + i * 25, 272, 21, "#fff", "#5EEAD4", 6, 1)
        b += T(358, 81 + i * 25, t, 10.5, "#134E4A", 600)
    b += T(484, 214, "DETAIL REDUCED · decisions made locally", 10, "#115E59", 800, "middle")
    # boundary
    b += '<line x1="665" y1="6" x2="665" y2="228" stroke="#E11D48" stroke-width="3" stroke-dasharray="8 5"/>'
    b += R(627, 100, 76, 32, "#E11D48", "none", 16)
    b += T(665, 114, "TRUST", 9, "#fff", 800, "middle")
    b += T(665, 126, "BOUNDARY", 9, "#fff", 800, "middle")
    b += line([(640, 160), (730, 160)], ROSE, sw=3.5)
    b += T(690, 178, "TLS + API key", 9.5, "#9F1239", 700, "middle")
    b += R(734, 54, 296, 128, "#EDE9FE", VIO, 14, 2)
    b += T(882, 76, "METADATA ONLY → SaaS (Tier 2)", 13, "#5B21B6", 800, "middle")
    for i, t in enumerate(["Numeric metrics · health state", "Severity · event category", "Counts (failed logins / 60 s)",
                           "HMAC pseudonyms · UTC time", "payload_id (idempotency key)"]):
        b += R(748, 86 + i * 19, 268, 16, "#fff", "#C4B5FD", 5, 1)
        b += T(758, 98 + i * 19, t, 10, "#4C1D95", 600)
    b += T(882, 202, "LEAVES · minimal, allow-listed", 10, "#5B21B6", 800, "middle")
    return svg(1040, 232, b)


# ---------------- Page 4: before / after ----------------
def before_svg():
    b = ""
    sites = [("Site A", 10), ("Site B", 10), ("Site C", 10)]
    for i, (t, x) in enumerate(sites):
        y = 14 + i * 62
        b += R(x, y, 150, 50, "#FFF1F2", ROSE, 9, 1.5)
        b += T(x + 10, y + 21, t + " · own tool", 11, "#9F1239", 800)
        b += T(x + 10, y + 38, "no shared view", 9.5, "#BE123C", 500)
        b += R(x + 112, y + 8, 30, 18, "#F43F5E", "none", 9)
        b += T(x + 127, y + 21, "×12", 10, "#fff", 800, "middle")
    b += line([(166, 40), (260, 100)], ROSE, sw=3)
    b += line([(166, 102), (260, 108)], ROSE, sw=3)
    b += line([(166, 164), (260, 116)], ROSE, sw=3)
    b += R(262, 70, 188, 74, "#FEE2E2", ROSE, 12, 2)
    b += T(356, 94, "CENTRAL PLATFORM", 11, "#9F1239", 800, "middle")
    b += T(356, 110, "raw logs + passwords + keys", 10, "#B91C1C", 700, "middle")
    b += T(356, 125, "arrive outside customer control", 9.5, "#BE123C", 500, "middle")
    b += T(356, 138, "attack surface ↑ · compliance risk", 9.5, "#BE123C", 500, "middle")
    b += R(262, 156, 188, 30, "#FFE4E6", ROSE, 8, 1, 'stroke-dasharray="4 3"')
    b += T(356, 175, "static thresholds → noisy alerts", 9.5, "#9F1239", 700, "middle")
    b += T(356, 56, "?", 30, "#F43F5E", 800, "middle")
    return svg(460, 196, b)


def after_svg():
    b = ""
    for i, (t, c) in enumerate([("Apps", TEAL), ("Servers", TEAL), ("Network", TEAL), ("Auth", TEAL)]):
        b += R(8, 10 + i * 46, 80, 36, "#CCFBF1", TEAL, 8, 1.5)
        b += T(48, 33 + i * 46, t, 11, "#115E59", 800, "middle")
        b += line([(88, 28 + i * 46), (112, 88)], TEAL, sw=1.8)
    b += R(112, 56, 112, 64, "#99F6E4", TEAL, 12, 2)
    b += T(168, 80, "LOCAL", 11, "#115E59", 800, "middle")
    b += T(168, 94, "COLLECTOR", 11, "#115E59", 800, "middle")
    b += T(168, 109, "raw stays here", 9, "#0F766E", 600, "middle")
    b += '<line x1="240" y1="4" x2="240" y2="190" stroke="#E11D48" stroke-width="2.5" stroke-dasharray="7 5"/>'
    b += line([(224, 88), (276, 88)], ROSE, sw=3)
    b += T(250, 78, "metadata", 8.5, "#9F1239", 700, "middle")
    b += R(280, 6, 176, 182, "#EDE9FE", VIO, 12, 2)
    b += T(368, 24, "ONE CONSOLIDATED VIEW", 10, "#5B21B6", 800, "middle")
    for i, (t, c) in enumerate([("Excellent", GRN), ("Good", BLUE), ("Fair", AMB), ("Poor", ROSE)]):
        b += R(290 + (i % 2) * 82, 32 + (i // 2) * 24, 76, 19, c, "none", 6)
        b += T(328 + (i % 2) * 82, 45 + (i // 2) * 24, t, 10, "#fff", 700, "middle")
    b += R(290, 86, 158, 44, "#fff", VIO, 8, 1.2)
    b += T(369, 103, "1 INCIDENT ← 5 ALERTS", 10, "#5B21B6", 800, "middle")
    b += T(369, 119, "root cause · signals · action", 9, "#6D28D9", 500, "middle")
    b += R(290, 138, 158, 40, "#fff", TEAL, 8, 1.2)
    b += T(369, 155, "EGRESS PROOF", 10, "#115E59", 800, "middle")
    b += T(369, 169, "exactly what left, per payload", 9, "#0F766E", 500, "middle")
    return svg(464, 196, b)


# ---------------- Page 5: main data-flow ----------------
def dataflow():
    b = ""
    # Tier 1
    b += R(0, 34, 628, 452, "#ECFDF5", "#10B981", 16, 2.5)
    b += R(0, 34, 628, 30, "#10B981", "none", 16)
    b += R(0, 50, 628, 14, "#10B981", "none", 0)
    b += T(314, 55, "TIER 1 · CUSTOMER ENVIRONMENT · LOCAL COLLECTOR  (port 8001)", 12.5, "#fff", 800, "middle")
    srcs = [("Applications", None), ("Servers", None), ("Network devices", "SNMP · syslog · flow"), ("Security sources", "auth logs")]
    for i, (t, s) in enumerate(srcs):
        y = 94 + i * 58
        b += box(14, y, 128, 48, "#fff", "#10B981", t, s, ts=11, ss=9)
        b += line([(142, y + 24), (166, 124)], "#10B981", sw=1.8)
    b += T(84, 84, "Telemetry sources", 10, "#047857", 800, "middle")
    b += box(166, 90, 94, 66, "#D1FAE5", "#047857", "Stream adapter", "organizer stream", ts=11, ss=9)
    # raw store
    b += box(166, 206, 94, 92, "#FEE2E2", ROSE, "Raw store", "LOCAL ONLY", tc="#9F1239", sc="#BE123C", ts=11.5)
    b += T(213, 280, "retention 1 h", 9, "#BE123C", 600, "middle")
    b += T(213, 292, "secrets visible here", 8.5, "#BE123C", 600, "middle")
    b += line([(213, 156), (213, 206)], ROSE, sw=2.2)
    b += T(228, 186, "local copy", 9, "#BE123C", 600)
    b += badge(213, 181, 2, "#E11D48", 9)
    steps = [("Redact & normalise", "regex scrub · drop free text"), ("Aggregate", "5 s window per node"),
             ("Analyse locally", "login window · moving average"), ("Apply data policy", "schema allow-list · HMAC IDs"),
             ("Outbound secret scanner", "match → payload BLOCKED"), ("Egress log", "exact JSON + SHA-256")]
    for i, (t, s) in enumerate(steps):
        y = 90 + i * 52
        fill = "#fff"
        b += box(282, y, 178, 42, fill, TEAL, t, s, ts=11, ss=9)
        if i:
            b += line([(371, y - 10), (371, y)], TEAL, sw=2)
    b += line([(260, 123), (282, 111)], TEAL, sw=2.2)
    # right column
    b += R(474, 90, 140, 102, "#FEE2E2", ROSE, 9, 1.4, 'stroke-dasharray="5 3"')
    b += T(544, 107, "NEVER LEAVES", 10, "#9F1239", 800, "middle")
    for i, t in enumerate(["passwords · API keys", "tokens · usernames", "raw IPs · hostnames", "log bodies · free text"]):
        b += T(544, 125 + i * 15, t, 9.5, "#7F1D1D", 600, "middle")
    b += R(474, 204, 140, 100, "#DCFCE7", GRN, 9, 1.4, 'stroke-dasharray="5 3"')
    b += T(544, 221, "ALLOW-LISTED ONLY", 10, "#166534", 800, "middle")
    for i, t in enumerate(["numeric metrics", "health · severity", "counts · pseudonyms", "UTC time · payload_id"]):
        b += T(544, 239 + i * 15, t, 9.5, "#14532D", 600, "middle")
    b += box(474, 330, 140, 56, "#FEF3C7", AMB, "SQLite outbox", "persist → send → ACK → delete", tc="#92400E", sc="#92400E", ts=11.5, ss=8.5)
    b += line([(460, 352), (474, 358)], AMB, sw=2.2)
    b += R(166, 408, 448, 62, "#CCFBF1", TEAL, 10, 1.6)
    b += T(390, 428, "COLLECTOR UI (local only) · EGRESS PROOF PANEL", 11, "#115E59", 800, "middle")
    b += T(390, 445, "raw line with secret in red  ⟷  exact outbound JSON in green · same payload_id + SHA-256", 9.5, "#134E4A", 600, "middle")
    b += T(390, 460, "queue depth · ONLINE / OFFLINE · BLOCKED rows in red", 9.5, "#134E4A", 600, "middle")
    b += line([(371, 384), (371, 408)], TEAL, dashed=True, sw=1.8)
    # boundary
    b += '<line x1="650" y1="10" x2="650" y2="496" stroke="#E11D48" stroke-width="3.5" stroke-dasharray="9 6"/>'
    b += R(632, 196, 36, 142, "#E11D48", "none", 12)
    b += '<text transform="translate(655,267) rotate(-90)" font-size="11" font-weight="800" fill="#fff" text-anchor="middle">TRUST BOUNDARY</text>'
    # transport
    b += line([(614, 358), (670, 358), (670, 112), (714, 112)], ROSE, sw=3.2)
    b += badge(670, 358, 4, "#E11D48", 10)
    b += line([(714, 212), (684, 212), (684, 378), (614, 378)], VIO, dashed=True, sw=2.2)
    b += badge(684, 296, 5, "#7C3AED", 10)
    # Tier 2
    b += R(704, 34, 336, 452, "#F5F3FF", VIO, 16, 2.5)
    b += R(704, 34, 336, 30, VIO, "none", 16)
    b += R(704, 50, 336, 14, VIO, "none", 0)
    b += T(872, 55, "TIER 2 · CENTRAL SaaS · MULTI-TENANT  (port 8000)", 12.5, "#fff", 800, "middle")
    t2 = [("Authenticate", "API key → tenant + region"), ("Validate & tenant check", "schema extra=forbid · tenant from key"),
          ("De-duplicate", "PRIMARY KEY (tenant, payload_id)"), ("Region store", "UTC · ordered by event_time"),
          ("Health engine", "4 states · stale-data rule (30 s)"), ("AIOps", "z-score · correlation · explanation"),
          ("Dashboard · SSE per tenant", "incidents · remediation · audit")]
    for i, (t, s) in enumerate(t2):
        y = 90 + i * 52
        b += box(714, y, 316, 42, "#fff", VIO, t, s, ts=11.5, ss=9.5)
        if i:
            b += line([(872, y - 10), (872, y)], VIO, sw=2)
    b += T(872, 82, "metadata only · tenant-scoped throughout", 9.5, "#6D28D9", 700, "middle")
    b += badge(714, 90, 6, "#7C3AED", 9)
    b += badge(1030, 436, 7, "#2563EB", 9)
    b += badge(22, 80, 1, "#0D9488", 9)
    b += badge(282, 90, 3, "#0D9488", 9)
    # zone labels
    b += T(314, 18, "Customer-controlled zone", 11, "#047857", 800, "middle")
    b += T(872, 18, "Vendor-hosted zone (never holds raw data)", 11, "#6D28D9", 800, "middle")
    return svg(1040, 496, b)


# ---------------- Page 6: sparkline icons ----------------
def sp_cpu():
    v = [40, 42, 41, 43, 42, 41, 44, 43, 78, 88, 91, 86, 60, 45]
    return svg(230, 56, spark(v, 230, 56, TEAL, hl=[9, 10], ymin=30, ymax=100))


def sp_lat():
    v = [38, 40, 39, 41, 40, 42, 40, 41, 120, 260, 310, 280, 150, 60]
    return svg(230, 56, spark(v, 230, 56, BLUE, hl=[9, 10, 11], ymin=0, ymax=330))


def sp_login():
    vals = [0, 1, 0, 0, 1, 0, 2, 1, 4, 7, 11, 14, 15, 9]
    b = ""
    for i, v in enumerate(vals):
        h = 4 + v * 2.9
        c = ROSE if v >= 10 else (AMB if v >= 5 else "#CBD5E1")
        b += R(6 + i * 16, 52 - h, 11, h, c, "none", 2)
    return svg(230, 56, b)


def sp_fleet():
    b = ""
    for i in range(20):
        off = 11 <= i <= 16
        c = ROSE if off else TEAL
        b += f'<circle cx="{10 + i * 11}" cy="22" r="{3.8 if not off else 4.6}" fill="{c}"/>'
    b += T(10, 46, "heartbeat every 5 s", 9, "#64748B", 600)
    b += T(222, 46, "30 s silence → POOR", 9, "#E11D48", 800, "end")
    return svg(230, 56, b)


# ---------------- Page 8: tenant isolation ----------------
def tenant_svg():
    b = ""
    # collectors
    b += box(6, 14, 170, 60, "#CCFBF1", TEAL, "Collector · tenant-alpha", "region IN · Asia/Kolkata", ts=11, ss=9.5)
    b += box(6, 170, 170, 60, "#DBEAFE", BLUE, "Collector · tenant-beta", "region EU · own timezone", ts=11, ss=9.5)
    b += T(91, 94, "key = KEY_ALPHA", 9.5, "#115E59", 700, "middle")
    b += T(91, 250, "key = KEY_BETA", 9.5, "#1E40AF", 700, "middle")
    # boundary
    b += '<line x1="206" y1="4" x2="206" y2="268" stroke="#E11D48" stroke-width="3" stroke-dasharray="8 5"/>'
    b += T(206, 280, "trust boundary", 9.5, "#9F1239", 800, "middle")
    # ingest
    b += R(236, 82, 150, 106, "#EDE9FE", VIO, 12, 2)
    b += T(311, 104, "INGEST GATE", 11.5, "#5B21B6", 800, "middle")
    for i, t in enumerate(["API key → tenant + region", "tenant_id from KEY, not body", "region must match tenant", "schema extra=forbid"]):
        b += T(311, 124 + i * 15, t, 9.5, "#4C1D95", 600, "middle")
    b += line([(176, 44), (236, 116)], TEAL, sw=2.6)
    b += line([(176, 200), (236, 156)], BLUE, sw=2.6)
    # stores
    b += R(430, 8, 214, 108, "#CCFBF1", TEAL, 12, 2)
    b += T(537, 28, "saas_in.db  (region IN)", 11, "#115E59", 800, "middle")
    b += R(442, 38, 190, 34, "#fff", TEAL, 7, 1.2)
    b += T(537, 59, "tenant_id = tenant-alpha · rows", 10, "#134E4A", 600, "middle")
    b += T(537, 98, "never copied to another region", 9, "#0F766E", 700, "middle")
    b += R(430, 150, 214, 108, "#DBEAFE", BLUE, 12, 2)
    b += T(537, 170, "saas_eu.db  (region EU)", 11, "#1E40AF", 800, "middle")
    b += R(442, 180, 190, 34, "#fff", BLUE, 7, 1.2)
    b += T(537, 201, "tenant_id = tenant-beta · rows", 10, "#1E3A8A", 600, "middle")
    b += T(537, 240, "every query: WHERE tenant_id = ?", 9, "#1E40AF", 700, "middle")
    b += line([(386, 112), (430, 60)], TEAL, sw=2.6)
    b += line([(386, 158), (430, 200)], BLUE, sw=2.6)
    # dashboards
    b += box(680, 30, 150, 54, "#fff", TEAL, "Alpha dashboard", "sees alpha only", ts=11, ss=9.5)
    b += box(680, 174, 150, 54, "#fff", BLUE, "Beta dashboard", "sees beta only", ts=11, ss=9.5)
    b += line([(644, 58), (680, 58)], TEAL, sw=2.4)
    b += line([(644, 200), (680, 200)], BLUE, sw=2.4)
    # forbidden path
    b += line([(755, 174), (755, 90)], ROSE, dashed=True, sw=2.6)
    b += R(716, 116, 78, 34, "#FFE4E6", ROSE, 8, 1.2)
    b += T(755, 131, "beta token →", 9, "#9F1239", 800, "middle")
    b += T(755, 143, "alpha data: 0 rows", 8.5, "#9F1239", 800, "middle")
    b += f'<circle cx="755" cy="104" r="9" fill="{ROSE}"/>' + T(755, 108, "×", 13, "#fff", 800, "middle")
    return svg(850, 292, b)


# ---------------- Page 9: MVP storyboard frames ----------------
def sb1():
    b = R(0, 0, 230, 108, "#F8FAFC", "#E2E8F0", 10, 1)
    b += R(8, 10, 100, 70, "#FEE2E2", ROSE, 7, 1.2)
    b += T(58, 24, "RAW (local)", 8.5, "#9F1239", 800, "middle")
    b += R(14, 32, 88, 14, "#F43F5E", "none", 3)
    b += T(58, 42, "sk-proj-9988…", 8.5, "#fff", 800, "middle")
    b += T(14, 62, "Failed login root", 8, "#7F1D1D", 500)
    b += T(14, 73, "password=********", 8, "#7F1D1D", 500)
    b += line([(110, 46), (122, 46)], SLT, sw=2)
    b += R(124, 10, 98, 70, "#DCFCE7", GRN, 7, 1.2)
    b += T(173, 24, "OUTBOUND", 8.5, "#166534", 800, "middle")
    b += T(130, 40, '"cpu": 94.2', 8.5, "#14532D", 600)
    b += T(130, 52, '"auth_fail_60s": 14', 8.5, "#14532D", 600)
    b += T(130, 64, '"severity": "high"', 8.5, "#14532D", 600)
    b += T(115, 98, "secret never crosses the wire", 9, "#0B1F3A", 700, "middle")
    return svg(230, 108, b)


def sb2():
    b = R(0, 0, 230, 108, "#F8FAFC", "#E2E8F0", 10, 1)
    b += R(10, 22, 70, 20, TEAL, "none", 6); b += T(45, 36, "ONLINE", 9, "#fff", 800, "middle")
    b += R(80, 22, 70, 20, ROSE, "none", 0); b += T(115, 36, "OFFLINE→POOR", 8.5, "#fff", 800, "middle")
    b += R(150, 22, 70, 20, AMB, "none", 6); b += T(185, 36, "DRAIN", 9, "#fff", 800, "middle")
    b += T(115, 14, "SaaS killed for 30 s", 9, "#64748B", 600, "middle")
    for i in range(9):
        b += R(12 + i * 8, 52, 6, 10, AMB if 3 <= i else "#CBD5E1", "none", 1)
    b += T(115, 78, "queue depth ↑ then drains to 0", 9, "#92400E", 700, "middle")
    b += T(115, 98, "sent = received · duplicates = 0", 9.5, "#0B1F3A", 800, "middle")
    return svg(230, 108, b)


def sb3():
    b = R(0, 0, 230, 108, "#F8FAFC", "#E2E8F0", 10, 1)
    v = [40, 42, 41, 43, 42, 41, 44, 43, 72, 80, 78, 52, 44]
    b += '<g transform="translate(6,6)">' + spark(v, 218, 64, TEAL, hl=[8, 9, 10], ymin=30, ymax=95) + "</g>"
    b += R(60, 12, 112, 18, "#FEE2E2", ROSE, 5, 1)
    b += T(116, 25, "z-score 7.2 > 3 → anomaly", 8.5, "#9F1239", 800, "middle")
    b += T(115, 90, "weights · baseline · reasoning shown", 9, "#0B1F3A", 700, "middle")
    b += T(115, 102, "(static >90% rule would never fire)", 8.5, "#64748B", 500, "middle")
    return svg(230, 108, b)


def sb4():
    b = R(0, 0, 230, 108, "#F8FAFC", "#E2E8F0", 10, 1)
    b += R(10, 14, 90, 46, "#CCFBF1", TEAL, 7, 1.4); b += T(55, 41, "alpha data", 10, "#115E59", 800, "middle")
    b += R(130, 14, 90, 46, "#DBEAFE", BLUE, 7, 1.4); b += T(175, 41, "beta data", 10, "#1E40AF", 800, "middle")
    b += '<line x1="115" y1="8" x2="115" y2="68" stroke="#E11D48" stroke-width="2.5" stroke-dasharray="5 3"/>'
    b += f'<circle cx="115" cy="38" r="9" fill="{ROSE}"/>' + T(115, 42, "×", 13, "#fff", 800, "middle")
    b += T(115, 86, "beta token sees alpha: 0 rows", 9.5, "#0B1F3A", 800, "middle")
    b += T(115, 99, "tenant_id enforced in every query", 8.5, "#64748B", 500, "middle")
    return svg(230, 108, b)


# ---------------- Page 10: Gantt ----------------
def gantt():
    X0, PH = 112, 58

    def x(h):
        return X0 + h * PH

    b = ""
    cols = {"P1": TEAL, "P2": VIO, "P3": "#D97706", "P4": ROSE}
    rows = {
        "P1": ("P1 · Collector", [(0, 1.5, "Contracts"), (1.5, 5, "Adapter · redact · egress log"), (5, 8, "Outbox · ACK · replay"), (8, 10, "Login window"),
                                  (10, 12, "inject.py · verify"), (12, 13, "2nd tenant"), (13, 15, "Dry runs")]),
        "P2": ("P2 · SaaS backend", [(0, 1.5, "Contracts"), (1.5, 5, "Ingest · auth · dedup · SSE"), (5, 8, "Health · stale · history"), (8, 10, "AIOps hook"),
                                     (10, 12, "Remediation · audit"), (12, 13, "Isolation"), (13, 15, "Dry runs")]),
        "P3": ("P3 · AIOps", [(0, 1.5, "Contracts"), (1.5, 5, "Z-score baselines"), (5, 8, "Alerts · correlation"), (8, 10, "Explanations"),
                              (10, 12, "Remed. policy"), (12, 13, "Tuning"), (13, 15, "Dry runs")]),
        "P4": ("P4 · Frontend", [(0, 1.5, "Diagram"), (1.5, 5, "Mock · dashboard · egress UI"), (5, 8, "Health cards · UTC charts"), (8, 10, "Incident UI"),
                                        (10, 12, "Remed. modal · fleet"), (12, 13, "Polish"), (13, 15, "Rehearsals")]),
    }
    # axis
    b += R(X0, 34, 15 * PH, 18, "#F1F5F9", "none", 4)
    for h in range(0, 16, 3):
        b += T(x(h) if h < 15 else x(h) - 8, 47, f"h{h}", 10, "#475569", 700, "middle")
        b += f'<line x1="{x(h)}" y1="52" x2="{x(h)}" y2="268" stroke="#E2E8F0" stroke-width="1"/>'
    for i, (k, (name, bars)) in enumerate(rows.items()):
        y = 62 + i * 52
        b += T(6, y + 24, name, 11.5, cols[k], 800)
        for j, (s, e, lab) in enumerate(bars):
            op = 1 if j % 2 == 0 else 0.82
            b += R(x(s) + 1, y, (e - s) * PH - 2, 40, cols[k], "none", 7, 1, f'opacity="{op}"')
            sz = 9.5 if (e - s) > 1.2 else 8.5
            b += T(x((s + e) / 2), y + 24, lab, sz, "#fff", 700, "middle")
    # buffer block
    bx = x(15) + 6
    b += R(bx, 62, 1040 - bx, 196, "#F1F5F9", "#94A3B8", 8, 1.2, 'stroke-dasharray="5 3"')
    b += f'<text transform="translate({bx + 30},160) rotate(-90)" font-size="11" font-weight="800" fill="#475569" text-anchor="middle">BUFFER · JUDGING · FIXES (h15–24)</text>'
    # milestones
    for h, lab, c in [(5, "CP1 · h5", BLUE), (8, "CP2 · h8", GRN), (13, "FEATURE FREEZE · h13", ROSE)]:
        b += f'<line x1="{x(h)}" y1="30" x2="{x(h)}" y2="262" stroke="{c}" stroke-width="2.4" stroke-dasharray="6 4"/>'
        b += R(x(h) - 70, 6, 140, 18, c, "none", 9)
        b += T(x(h), 19, lab, 9.5, "#fff", 800, "middle")
    return svg(1040, 272, b)


# ---------------- Page 11: telemetry plan & global ----------------
def telemetry_svg():
    b = ""
    b += box(6, 18, 150, 74, "#FEF3C7", AMB, "Organizer stream", "same for every team", tc="#92400E", sc="#92400E", ts=12, ss=9.5)
    b += T(81, 80, "bursts · spikes · outages", 9, "#92400E", 600, "middle")
    b += line([(156, 55), (190, 55)], SLT, sw=2.6)
    b += box(192, 18, 140, 74, "#CCFBF1", TEAL, "adapter.py", "only file that knows", ts=12, ss=9.5)
    b += T(262, 80, "the stream format", 9.5, "#475569", 500, "middle")
    b += line([(332, 55), (366, 55)], TEAL, sw=2.6)
    b += box(368, 18, 136, 74, "#115E59", "#0D9488", "Collector", "redact · aggregate", tc="#fff", sc="#99F6E4", ts=12, ss=9.5)
    b += T(436, 80, "egress · outbox", 9.5, "#99F6E4", 500, "middle")
    b += box(6, 128, 170, 62, "#F1F5F9", SLT, "sample_stream.jsonl", "60 lines · fake secrets · h1.5", ts=11, ss=9, dash=True)
    b += line([(176, 158), (262, 158), (262, 92)], SLT, dashed=True, sw=2)
    b += T(180, 178, "fallback until spec arrives", 8.5, "#64748B", 600)
    b += R(196, 206, 308, 86, "#FFE4E6", ROSE, 10, 1.6)
    b += T(350, 226, "tools/inject.py · rehearsal injector", 11.5, "#9F1239", 800, "middle")
    for i, t in enumerate(["secret", "outage", "bruteforce", "latency", "cpu", "incident", "dup", "ooo"]):
        cx, cy = 218 + (i % 4) * 72, 238 + (i // 4) * 26
        b += R(cx, cy, 64, 20, "#fff", "#FDA4AF", 10, 1)
        b += T(cx + 32, cy + 14, t, 9.5, "#9F1239", 700, "middle")
    b += line([(436, 206), (436, 92)], ROSE, dashed=True, sw=2)
    b += T(500, 150, "mimics the 8 live", 8.5, "#9F1239", 700, "end")
    b += T(500, 161, "judge scenarios", 8.5, "#9F1239", 700, "end")
    b += R(6, 206, 170, 86, "#DCFCE7", GRN, 8, 1.6)
    b += T(91, 226, "Measured, not claimed", 11.5, "#166534", 800, "middle")
    b += T(91, 244, "verify_delivery.py", 9.5, "#14532D", 700, "middle")
    b += T(91, 258, "latency_report.py", 9.5, "#14532D", 700, "middle")
    b += T(91, 274, "sent IDs vs received IDs", 8.5, "#166534", 600, "middle")
    return svg(510, 300, b)


def global_svg():
    b = ""
    b += R(4, 6, 242, 118, "#ECFDF5", "#10B981", 12, 1.8)
    b += T(125, 24, "REGION IN · tenant-alpha", 10.5, "#047857", 800, "middle")
    b += box(14, 34, 70, 44, "#fff", "#10B981", "Collector", "Asia/Kolkata", ts=9.5, ss=8)
    b += line([(84, 56), (100, 56)], "#10B981", sw=2)
    b += box(100, 34, 62, 44, "#fff", "#10B981", "Regional", "ingest", ts=9.5, ss=8.5)
    b += line([(162, 56), (176, 56)], "#10B981", sw=2)
    b += box(176, 34, 62, 44, "#fff", "#10B981", "saas_in", ".db", ts=9.5, ss=8.5)
    b += T(125, 98, "UTC + source timezone on every event", 8.5, "#047857", 700, "middle")
    b += T(125, 112, "stored in-region, never replicated", 8.5, "#047857", 700, "middle")
    b += R(262, 6, 242, 118, "#EFF6FF", BLUE, 12, 1.8)
    b += T(383, 24, "REGION EU · tenant-beta", 10.5, "#1E40AF", 800, "middle")
    b += box(272, 34, 70, 44, "#fff", BLUE, "Collector", "own tz", ts=9.5, ss=8)
    b += line([(342, 56), (358, 56)], BLUE, sw=2)
    b += box(358, 34, 62, 44, "#fff", BLUE, "Regional", "ingest", ts=9.5, ss=8.5)
    b += line([(420, 56), (434, 56)], BLUE, sw=2)
    b += box(434, 34, 62, 44, "#fff", BLUE, "saas_eu", ".db", ts=9.5, ss=8.5)
    b += T(383, 98, "payload region must equal tenant region", 8.5, "#1E40AF", 700, "middle")
    b += T(383, 112, "otherwise rejected at ingest", 8.5, "#1E40AF", 700, "middle")
    # out of order
    b += T(4, 148, "Arrival order (network)", 10, "#475569", 800)
    for i, (n, t) in enumerate([("e3", "10:00:10"), ("e1", "10:00:00"), ("e2", "10:00:05"), ("e2", "duplicate")]):
        c = "#FEE2E2" if t == "duplicate" else "#FEF3C7"
        s = ROSE if t == "duplicate" else AMB
        b += R(4 + i * 90, 156, 82, 34, c, s, 7, 1.4)
        b += T(45 + i * 90, 170, n, 10.5, "#0B1F3A", 800, "middle")
        b += T(45 + i * 90, 183, t, 8.5, "#475569", 600, "middle")
    b += line([(130, 194), (130, 222)], VIO, sw=2.6)
    b += T(142, 212, "sort by event_time (UTC) · de-duplicate by payload_id", 9.5, "#5B21B6", 800)
    b += T(4, 244, "Stored order", 10, "#475569", 800)
    for i, (n, t) in enumerate([("e1", "10:00:00"), ("e2", "10:00:05"), ("e3", "10:00:10")]):
        b += R(4 + i * 90, 252, 82, 34, "#EDE9FE", VIO, 7, 1.4)
        b += T(45 + i * 90, 266, n, 10.5, "#0B1F3A", 800, "middle")
        b += T(45 + i * 90, 279, t, 8.5, "#475569", 600, "middle")
    b += R(274, 252, 230, 34, "#DCFCE7", GRN, 7, 1.4)
    b += T(389, 266, "trend line stays smooth", 10, "#166534", 800, "middle")
    b += T(389, 279, "e2 counted once · no erratic history", 8.5, "#166534", 600, "middle")
    return svg(510, 296, b)


# ---------------- Page 12: models ----------------
def zscore_svg():
    import math
    base = [42, 44, 41, 43, 45, 40, 42, 44, 43, 41, 42, 45, 43, 40, 42, 44, 41, 43, 42, 44, 43, 41]
    spike = [60, 72, 78, 79, 76, 58, 47, 43]
    v = base + spike
    W, H = 340, 250
    px0, py0, pw, ph = 34, 14, 296, 186

    def X(i): return px0 + i * pw / (len(v) - 1)
    def Y(val): return py0 + ph - val / 100 * ph

    b = ""
    b += R(px0, Y(57), pw, Y(27) - Y(57), "#CCFBF1", "none", 0, 0, 'opacity="0.7"')
    for yv in (0, 25, 50, 75, 100):
        b += f'<line x1="{px0}" y1="{Y(yv)}" x2="{px0 + pw}" y2="{Y(yv)}" stroke="#E2E8F0"/>'
        b += T(px0 - 5, Y(yv) + 3, str(yv), 8.5, "#94A3B8", 600, "end")
    b += f'<line x1="{px0}" y1="{Y(42)}" x2="{px0 + pw}" y2="{Y(42)}" stroke="{TEAL}" stroke-width="1.6" stroke-dasharray="5 3"/>'
    b += T(px0 + pw, Y(42) + 11, "μ = 42", 9, "#115E59", 800, "end")
    b += f'<line x1="{px0}" y1="{Y(57)}" x2="{px0 + pw}" y2="{Y(57)}" stroke="{AMB}" stroke-width="1.6" stroke-dasharray="5 3"/>'
    b += T(px0 + 3, Y(57) - 4, "μ + 3σ = 57", 9, "#B45309", 800)
    b += f'<line x1="{px0}" y1="{Y(90)}" x2="{px0 + pw}" y2="{Y(90)}" stroke="#94A3B8" stroke-width="1.4" stroke-dasharray="2 3"/>'
    b += T(px0 + 3, Y(90) - 4, "static rule: CPU > 90 (never fires)", 8.5, "#64748B", 700)
    b += line([(round(X(i), 1), round(Y(val), 1)) for i, val in enumerate(v)], BLUE, sw=2.4, arrow=False)
    for i in range(22, 27):
        b += f'<circle cx="{X(i):.1f}" cy="{Y(v[i]):.1f}" r="4" fill="{ROSE}"/>'
    b += R(X(24) - 72, Y(79) - 40, 118, 28, "#FFE4E6", ROSE, 7, 1.3)
    b += T(X(24) - 13, Y(79) - 28, "z = |78 − 42| / 5 = 7.2", 9, "#9F1239", 800, "middle")
    b += T(X(24) - 13, Y(79) - 17, "> 3.0 → ANOMALY", 9, "#9F1239", 800, "middle")
    b += T(px0 + pw / 2, H - 22, "time (UTC) → rolling 15-min baseline (180 samples)", 9, "#64748B", 600, "middle")
    b += T(px0 + pw / 2, H - 9, "illustrative values", 8.5, "#94A3B8", 500, "middle")
    return svg(W, H, b)


def incident_svg():
    b = ""
    alerts = ["db-01 CPU · z 7.5", "db-01 memory · z 5.0", "app-01 latency · z 5.0", "app-01 pkt loss · z 4.0", "app-01 CPU · z 3.5"]
    for i, t in enumerate(alerts):
        y = 8 + i * 32
        b += R(0, y, 142, 25, "#FFE4E6", ROSE, 12, 1.3)
        b += T(71, y + 16.5, t, 9.5, "#9F1239", 700, "middle")
        b += line([(142, y + 12), (176, 82)], SLT, sw=1.4)
    b += R(178, 6, 162, 146, "#EDE9FE", VIO, 11, 2)
    b += T(259, 24, "INCIDENT", 10, "#5B21B6", 800, "middle")
    b += T(259, 39, "DB bottleneck → app latency", 8.8, "#4C1D95", 800, "middle")
    b += R(190, 48, 138, 20, VIO, "none", 10)
    b += T(259, 62, "5 alerts grouped into 1", 9.5, "#fff", 800, "middle")
    b += T(190, 86, "root cause:", 9, "#6D28D9", 600); b += T(246, 86, "db-01", 9.5, "#0B1F3A", 800)
    b += T(190, 101, "impacted:", 9, "#6D28D9", 600); b += T(246, 101, "app-01", 9.5, "#0B1F3A", 800)
    b += T(190, 116, "window:", 9, "#6D28D9", 600); b += T(246, 116, "30 s · dep. map", 9, "#0B1F3A", 700)
    b += T(190, 131, "confidence:", 9, "#6D28D9", 600); b += T(246, 131, "0.95 (heuristic)", 9, "#0B1F3A", 700)
    b += T(190, 146, "action:", 9, "#6D28D9", 600); b += T(246, 146, "investigate DB load", 9, "#0B1F3A", 700)
    b += T(0, 184, "Signal weight = |z| ÷ Σ|z|  (sums to 100)", 9.5, "#475569", 800)
    for i, (t, p, c) in enumerate([("db CPU", 30, ROSE), ("db mem", 20, AMB), ("app lat", 20, BLUE), ("app loss", 16, TEAL), ("app CPU", 14, VIO)]):
        y = 194 + i * 16
        b += T(0, y + 10, t, 9, "#334155", 700)
        b += R(52, y, p * 5.6, 12, c, "none", 4)
        b += T(52 + p * 5.6 + 5, y + 10, f"{p}%", 9, "#334155", 800)
    return svg(340, 280, b)
