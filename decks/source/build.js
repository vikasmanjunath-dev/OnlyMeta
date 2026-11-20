const pptxgen = require("pptxgenjs");
const React = require("react"), RDS = require("react-dom/server"), sharp = require("sharp");
const fa = require("react-icons/fa");
const SK = "/root/.claude/skills/synced/b13cfb69-ef4e-491b-acce-aff69d020884_2e1c70c3-b6cd-4c0e-9843-7b9aeec52338/pptx";
const { applyTheme } = require(SK + "/scripts/apply_theme.js");

const THEME = { name: "Secure Observability", headFontFace: "Cambria", bodyFontFace: "Calibri",
  colors: { dk1: "0F172A", lt1: "FFFFFF", dk2: "0B1F3A", lt2: "EEF3F8", accent1: "0D9488", accent2: "E11D48",
    accent3: "16A34A", accent4: "D97706", accent5: "2563EB", accent6: "7C3AED", hlink: "0D9488", folHlink: "7C3AED" } };

const pres = new pptxgen();
pres.layout = "LAYOUT_16x9";
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
pres.title = "CICADA 2026 · Phase 1 · Secure AIOps Observability";
const C = pres.SchemeColor, S = pres.ShapeType;

pres.defineSlideMaster({ title: "DARK", background: { color: C.text2 },
  objects: [{ placeholder: { options: { name: "title", type: "title", x: 0.5, y: 0.3, w: 9, h: 0.8, fontSize: 30, bold: true, color: C.background1, margin: 0, valign: "middle" }, text: "" } }] });
pres.defineSlideMaster({ title: "CONTENT", background: { color: C.background1 },
  objects: [{ placeholder: { options: { name: "title", type: "title", x: 0.5, y: 0.3, w: 9, h: 0.8, fontSize: 30, bold: true, color: C.text2, margin: 0, valign: "middle" }, text: "" } }],
  slideNumber: { x: 9.1, y: 5.2, w: 0.5, h: 0.3, fontSize: 10, color: C.text1 } });

let n = 0;
const nm = (p) => `${p}-${++n}`;
async function icon(Comp, hex) {
  const svg = RDS.renderToStaticMarkup(React.createElement(Comp, { color: "#" + hex, size: 256 }));
  const buf = await sharp(Buffer.from(svg)).png().toBuffer();
  return "image/png;base64," + buf.toString("base64");
}
const card = (s, x, y, w, h, o = {}) => s.addShape(S.roundRect, { x, y, w, h, rectRadius: 0.1, fill: o.fill || { color: C.background2 }, line: o.line || { type: "none" }, objectName: nm("card") });
const txt = (s, t, o) => s.addText(t, Object.assign({ isTextBox: true, margin: 0, objectName: nm("text") }, o));
const box = (s, t, o) => s.addText(t, Object.assign({ isTextBox: true, shape: S.roundRect, rectRadius: 0.1, align: "center", valign: "middle", margin: 0.08, objectName: nm("box") }, o));
const arrow = (s, x, y, w, h, color) => s.addShape(S.line, { x, y, w, h, line: { color: color || C.text2, width: 2, endArrowType: "triangle" }, objectName: nm("arrow") });
async function circleIcon(s, Comp, x, y, d, fillColor, hexIcon = "FFFFFF") {
  s.addShape(S.ellipse, { x, y, w: d, h: d, fill: { color: fillColor }, line: { type: "none" }, objectName: nm("iconbg") });
  const k = d * 0.5;
  s.addImage({ data: await icon(Comp, hexIcon), x: x + (d - k) / 2, y: y + (d - k) / 2, w: k, h: k, altText: "icon" });
}

(async () => {
  // 1 ── Title
  pres.addSection({ title: "Context" });
  let s = pres.addSlide({ masterName: "DARK", sectionTitle: "Context" });
  txt(s, "CICADA 2026 · PHASE 1", { x: 0.7, y: 1.2, w: 5, h: 0.4, fontSize: 14, bold: true, color: C.accent1, charSpacing: 3 });
  txt(s, "Secure AIOps\nObservability", { x: 0.7, y: 1.7, w: 5.2, h: 1.7, fontSize: 40, bold: true, color: C.background1, fontFace: "Cambria", valign: "top" });
  txt(s, "Cloud intelligence. Secrets stay home.", { x: 0.7, y: 3.55, w: 5.2, h: 0.5, fontSize: 20, italic: true, color: C.background2 });
  txt(s, "Problem Understanding & Ideation", { x: 0.7, y: 4.6, w: 5.2, h: 0.35, fontSize: 14, color: C.background2 });
  // motif: local | boundary | cloud
  card(s, 6.2, 1.5, 1.4, 1.4, { fill: { color: C.accent1 } });
  txt(s, "Local\ncollector", { x: 6.2, y: 1.5, w: 1.4, h: 1.4, fontSize: 14, bold: true, color: C.background1, align: "center", valign: "middle" });
  card(s, 8.2, 1.5, 1.4, 1.4, { fill: { color: C.accent5 } });
  txt(s, "SaaS\nAIOps", { x: 8.2, y: 1.5, w: 1.4, h: 1.4, fontSize: 14, bold: true, color: C.background1, align: "center", valign: "middle" });
  arrow(s, 7.62, 2.2, 0.56, 0, C.background1);
  s.addShape(S.line, { x: 7.9, y: 1.2, w: 0, h: 3.2, line: { color: C.accent2, width: 2, dashType: "dash" }, objectName: nm("boundary") });
  txt(s, "trust boundary", { x: 6.9, y: 4.45, w: 2, h: 0.3, fontSize: 12, color: C.accent2, align: "center", bold: true });
  await circleIcon(s, fa.FaLock, 6.55, 3.2, 0.7, C.accent2);
  txt(s, "raw data", { x: 6.2, y: 3.95, w: 1.4, h: 0.3, fontSize: 12, color: C.background2, align: "center" });

  // 2 ── Problem
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Context" });
  s.addText("Monitoring needs data we can't share", { placeholder: "title" });
  const probs = [[fa.FaKey, C.accent2, "Logs carry secrets", "Passwords, API keys, tokens and IPs sit inside everyday logs."],
    [fa.FaCloud, C.accent5, "SaaS needs data", "Cloud AIOps spots anomalies only if metrics keep flowing."],
    [fa.FaBalanceScale, C.accent4, "A trust gap", "Shipping raw logs to a vendor breaks security and residency rules."]];
  for (let i = 0; i < 3; i++) {
    const x = 0.5 + i * 3.05, [Ic, col, h, b] = probs[i];
    card(s, x, 1.4, 2.9, 2.8);
    await circleIcon(s, Ic, x + 0.25, 1.65, 0.7, col);
    txt(s, h, { x: x + 0.25, y: 2.55, w: 2.4, h: 0.4, fontSize: 18, bold: true, color: C.text2 });
    txt(s, b, { x: x + 0.25, y: 3.0, w: 2.4, h: 1.05, fontSize: 14, color: C.text1, valign: "top" });
  }
  box(s, "Goal: full AIOps insight, with zero raw data leaving the customer.", { x: 0.5, y: 4.45, w: 9, h: 0.65, fontSize: 16, bold: true, color: C.background1, fill: { color: C.text2 } });

  // 3 ── Architecture
  pres.addSection({ title: "Design" });
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Design" });
  s.addText("Two tiers, one trust boundary", { placeholder: "title" });
  card(s, 0.4, 1.3, 4.3, 3.35, { fill: { color: C.accent1, transparency: 88 } });
  txt(s, "TIER 1 · Customer network", { x: 0.6, y: 1.4, w: 3.9, h: 0.35, fontSize: 14, bold: true, color: C.text2 });
  box(s, "Servers · DB ·\nnetwork devices", { x: 0.6, y: 1.95, w: 1.5, h: 1.0, fontSize: 14, color: C.text1, fill: { color: C.background1 }, line: { color: C.text2, width: 1 } });
  arrow(s, 2.12, 2.45, 0.5, 0);
  box(s, [{ text: "Collector", options: { bold: true, breakLine: true } }, { text: "raw stays here", options: { fontSize: 14 } }], { x: 2.65, y: 1.95, w: 1.85, h: 1.0, fontSize: 16, color: C.background1, fill: { color: C.accent1 } });
  box(s, "Local raw store + egress log", { x: 0.6, y: 3.5, w: 3.9, h: 0.75, fontSize: 14, color: C.text1, fill: { color: C.background1 }, line: { color: C.text2, width: 1 } });
  s.addShape(S.line, { x: 5.05, y: 1.2, w: 0, h: 3.55, line: { color: C.accent2, width: 2.5, dashType: "dash" }, objectName: nm("boundary") });
  card(s, 5.4, 1.3, 4.2, 3.35, { fill: { color: C.accent5, transparency: 88 } });
  txt(s, "TIER 2 · Multi-tenant SaaS", { x: 5.6, y: 1.4, w: 3.8, h: 0.35, fontSize: 14, bold: true, color: C.text2 });
  const saas = ["Ingest + dedup", "AIOps engine", "Dashboard"];
  saas.forEach((t, i) => {
    const y = 1.95 + i * 0.85;
    box(s, t, { x: 5.65, y, w: 3.7, h: 0.6, fontSize: 16, bold: true, color: C.background1, fill: { color: C.accent5 } });
    if (i < 2) arrow(s, 7.5, y + 0.6, 0, 0.25);
  });
  arrow(s, 4.52, 2.45, 1.1, -0.2, C.accent2);
  box(s, "Trust boundary: HTTPS + per-collector API key · allow-listed metadata only", { x: 1.4, y: 4.85, w: 7.2, h: 0.4, fontSize: 14, bold: true, color: C.accent2, fill: { color: C.background2 } });

  // 4 ── Redaction
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Design" });
  s.addText("Numbers cross the wire, never secrets", { placeholder: "title" });
  card(s, 0.5, 1.3, 3.9, 2.5, { fill: { color: C.accent2, transparency: 88 } });
  txt(s, "RAW · stays on customer side", { x: 0.7, y: 1.4, w: 3.5, h: 0.35, fontSize: 14, bold: true, color: C.accent2 });
  txt(s, [{ text: "deploy ", options: {} }, { text: "password=Summer@2026", options: { color: C.accent2, bold: true, breakLine: true } },
    { text: "token=", options: {} }, { text: "ghp_FAKE1234", options: { color: C.accent2, bold: true } }, { text: " user=root", options: { breakLine: true } },
    { text: "from ", options: {} }, { text: "192.168.1.50", options: { color: C.accent2, bold: true, breakLine: true } },
    { text: "host ", options: {} }, { text: "prod-db-01.corp.local", options: { color: C.accent2, bold: true } }],
    { x: 0.7, y: 1.85, w: 3.55, h: 1.8, fontSize: 12, fontFace: "Courier New", color: C.text1, valign: "top", paraSpaceAfter: 4 });
  arrow(s, 4.5, 2.55, 1.0, 0, C.accent1);
  txt(s, "filter", { x: 4.5, y: 2.2, w: 1.0, h: 0.3, fontSize: 12, bold: true, color: C.accent1, align: "center" });
  card(s, 5.6, 1.3, 3.9, 2.5, { fill: { color: C.accent3, transparency: 85 } });
  txt(s, "OUTBOUND · exactly what is sent", { x: 5.8, y: 1.4, w: 3.5, h: 0.35, fontSize: 14, bold: true, color: C.accent3 });
  txt(s, ['{"node": "n-b7cd652869",', ' "cpu": 40.0,', ' "latency_ms": 20.0,', ' "auth_failures_60s": 12,', ' "severity": "critical"}'].map((t, i, a) => ({ text: t, options: { breakLine: i < a.length - 1 } })),
    { x: 5.8, y: 1.85, w: 3.55, h: 1.8, fontSize: 12, fontFace: "Courier New", color: C.text1, valign: "top", paraSpaceAfter: 4 });
  const layers = [["1", "Schema allow-list"], ["2", "Regex scrub"], ["3", "Outbound scanner: BLOCK"]];
  layers.forEach(([k, t], i) => {
    const x = 0.5 + i * 3.05;
    box(s, [{ text: k + "  ", options: { bold: true } }, { text: t, options: {} }], { x, y: 4.1, w: 2.9, h: 0.7, fontSize: 14, color: C.background1, fill: { color: C.text2 } });
  });
  txt(s, "Three layers of redaction. Any hit means the payload is blocked, never sent.", { x: 0.5, y: 4.9, w: 8, h: 0.3, fontSize: 12, color: C.text1 });

  // 5 ── Reliability
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Design" });
  s.addText("Save first, send second", { placeholder: "title" });
  const steps = [["1 · Persist", "local outbox first"], ["2 · Send", "HTTPS batch"], ["3 · Dedup", "SaaS dedups by ID"], ["4 · ACK", "only then mark delivered"]];
  steps.forEach(([a, b], i) => {
    const x = 0.5 + i * 2.333;
    box(s, [{ text: a, options: { bold: true, fontSize: 18, breakLine: true } }, { text: b, options: { fontSize: 14 } }], { x, y: 1.4, w: 2.0, h: 1.3, color: C.background1, fill: { color: i === 3 ? C.accent3 : C.accent1 } });
    if (i < 3) arrow(s, x + 2.02, 2.05, 0.3, 0);
  });
  const rel = [[fa.FaWifi, C.accent4, "Offline?", "Buffer locally, then retry at 1, 2, 4, 5\u00A0s intervals."], [fa.FaPowerOff, C.accent5, "Crash?", "Same payload_id is re-sent, never duplicated."], [fa.FaCopy, C.accent6, "Lost ACK?", "Duplicate is acknowledged, stored once."]];
  for (let i = 0; i < 3; i++) {
    const x = 0.5 + i * 3.05, [Ic, col, h, b] = rel[i];
    card(s, x, 3.1, 2.9, 1.85);
    await circleIcon(s, Ic, x + 0.2, 3.3, 0.55, col);
    txt(s, h, { x: x + 0.9, y: 3.3, w: 1.9, h: 0.55, fontSize: 18, bold: true, color: C.text2, valign: "middle" });
    txt(s, b, { x: x + 0.2, y: 4.0, w: 2.5, h: 0.85, fontSize: 14, color: C.text1, valign: "top" });
  }

  // 6 ── Tenants
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Design" });
  s.addText("Tenants stay separate by design", { placeholder: "title" });
  [["Tenant Alpha", "Region IN", "col-alpha-01", "India data store", C.accent1], ["Tenant Beta", "Region EU", "col-beta-01", "EU data store", C.accent5]].forEach(([t, r, c, d, col], i) => {
    const x = 0.5 + i * 4.7;
    card(s, x, 1.3, 4.3, 2.55);
    txt(s, [{ text: t, options: { bold: true } }, { text: "  ·  " + r, options: {} }], { x: x + 0.25, y: 1.4, w: 3.8, h: 0.45, fontSize: 18, color: C.text2 });
    box(s, c, { x: x + 0.75, y: 2.0, w: 2.8, h: 0.55, fontSize: 14, bold: true, color: C.background1, fill: { color: col } });
    arrow(s, x + 2.15, 2.57, 0, 0.35);
    box(s, d, { x: x + 0.75, y: 2.95, w: 2.8, h: 0.55, fontSize: 14, bold: true, color: C.text2, fill: { color: C.background1 }, line: { color: col, width: 2 } });
  });
  [["API key", "binds to one tenant"], ["Wrong region", "payload rejected"], ["Pseudonym key", "unique per tenant"]].forEach(([a, b], i) => {
    box(s, [{ text: a, options: { bold: true, breakLine: true } }, { text: b, options: {} }], { x: 0.5 + i * 3.05, y: 4.15, w: 2.9, h: 0.85, fontSize: 14, color: C.background1, fill: { color: C.text2 } });
  });

  // 7 ── AIOps
  pres.addSection({ title: "AIOps and plan" });
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "AIOps and plan" });
  s.addText("Health, anomalies and incidents", { placeholder: "title" });
  [["Excellent", "all normal", C.accent3], ["Good", "minor drift", C.accent5], ["Fair", "5 failed logins / 60 s", C.accent4], ["Poor", "10+ failed logins / 60 s", C.accent2]].forEach(([a, b, col], i) => {
    box(s, [{ text: a, options: { bold: true, fontSize: 18, breakLine: true } }, { text: b, options: { fontSize: 14 } }], { x: 0.5 + i * 2.3, y: 1.3, w: 2.15, h: 1.05, color: C.background1, fill: { color: col } });
  });
  card(s, 0.5, 2.7, 4.3, 2.3);
  await circleIcon(s, fa.FaChartLine, 0.75, 2.9, 0.6, C.accent5);
  txt(s, "Anomaly detection", { x: 1.5, y: 2.9, w: 3.2, h: 0.6, fontSize: 18, bold: true, color: C.text2, valign: "middle" });
  txt(s, "A reading with z-score above 3 against a rolling 15-minute baseline is flagged.", { x: 0.75, y: 3.7, w: 3.8, h: 1.1, fontSize: 14, color: C.text1, valign: "top" });
  card(s, 5.2, 2.7, 4.3, 2.3);
  await circleIcon(s, fa.FaProjectDiagram, 5.45, 2.9, 0.6, C.accent6);
  txt(s, "Incident correlation", { x: 6.2, y: 2.9, w: 3.2, h: 0.6, fontSize: 18, bold: true, color: C.text2, valign: "middle" });
  ["app-01", "db-01", "net-01"].forEach((t, i) => {
    box(s, t, { x: 5.45 + i * 1.3, y: 3.7, w: 0.95, h: 0.45, fontSize: 14, bold: true, color: C.background1, fill: { color: C.text2 } });
    if (i < 2) arrow(s, 6.42 + i * 1.3, 3.925, 0.3, 0);
  });
  txt(s, "Alerts within 30 s follow the dependency map into one incident.", { x: 5.45, y: 4.3, w: 3.8, h: 0.6, fontSize: 14, color: C.text1, valign: "top" });

  // 8 ── Team & plan
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "AIOps and plan" });
  s.addText("Team and 24-hour plan", { placeholder: "title" });
  [["P1", "Collector", "Tier 1, redaction, outbox", C.accent1], ["P2", "SaaS backend", "Ingest, dedup, tenants", C.accent5], ["P3", "AIOps", "Health, anomalies, fixes", C.accent6], ["P4", "Frontend + demo", "Dashboard, story", C.accent4]].forEach(([p, r, d, col], i) => {
    const x = 0.5 + i * 2.3;
    card(s, x, 1.3, 2.15, 2.0);
    s.addShape(S.ellipse, { x: x + 0.15, y: 1.45, w: 0.65, h: 0.65, fill: { color: col }, line: { type: "none" }, objectName: nm("iconbg") });
    txt(s, p, { x: x + 0.15, y: 1.45, w: 0.65, h: 0.65, fontSize: 16, bold: true, color: C.background1, align: "center", valign: "middle" });
    txt(s, r, { x: x + 0.15, y: 2.2, w: 1.9, h: 0.35, fontSize: 16, bold: true, color: C.text2 });
    txt(s, d, { x: x + 0.15, y: 2.58, w: 1.9, h: 0.6, fontSize: 14, color: C.text1, valign: "top" });
  });
  txt(s, "Timeline", { x: 0.5, y: 3.6, w: 3, h: 0.3, fontSize: 14, bold: true, color: C.text2 });
  [["0–4 h", "Contracts, scaffold", 1.8, C.accent1], ["4–12 h", "Core build", 3.0, C.accent5], ["12–20 h", "Integrate, demo runs", 3.0, C.accent6], ["20–24 h", "Polish", 1.2, C.accent3]].reduce((x, [h, t, w, col]) => {
    box(s, [{ text: h, options: { bold: true, breakLine: true } }, { text: t, options: {} }], { x, y: 3.95, w: w - 0.06, h: 0.95, fontSize: 14, color: C.background1, fill: { color: col } });
    return x + w;
  }, 0.5);

  // 9 ── Proof (dark)
  s = pres.addSlide({ masterName: "DARK", sectionTitle: "AIOps and plan" });
  s.addText("What we will prove live", { placeholder: "title" });
  const proofs = [[fa.FaEyeSlash, C.accent2, "Secret in raw, absent on the wire", "Side-by-side egress panel"], [fa.FaPlug, C.accent4, "Cut the network", "Buffered locally, delivered after"],
    [fa.FaCopy, C.accent6, "Send a duplicate", "Stored once, acknowledged"], [fa.FaCheckDouble, C.accent3, "Delivery check", "0 missing, 0 duplicates, hashes match"]];
  for (let i = 0; i < 4; i++) {
    const x = 0.5 + (i % 2) * 4.6, y = 1.35 + Math.floor(i / 2) * 1.5, [Ic, col, h, b] = proofs[i];
    card(s, x, y, 4.4, 1.3, { fill: { color: C.background1, transparency: 90 } });
    await circleIcon(s, Ic, x + 0.2, y + 0.3, 0.7, col);
    txt(s, h, { x: x + 1.1, y: y + 0.2, w: 3.2, h: 0.45, fontSize: 16, bold: true, color: C.background1, valign: "middle" });
    txt(s, b, { x: x + 1.1, y: y + 0.7, w: 3.2, h: 0.4, fontSize: 14, color: C.background2, valign: "top" });
  }
  txt(s, "Cloud intelligence. Zero raw data leaving the customer.", { x: 0.5, y: 4.55, w: 9, h: 0.5, fontSize: 20, italic: true, color: C.accent1, align: "center" });

  await pres.writeFile({ fileName: "CICADA2026_Phase1.pptx" });
  await applyTheme("CICADA2026_Phase1.pptx", THEME);
  console.log("ok");
})();
