const pptxgen = require("pptxgenjs");
const React = require("react"), RDS = require("react-dom/server"), sharp = require("sharp");
const fa = require("react-icons/fa");
const SK = "/root/.claude/skills/synced/b13cfb69-ef4e-491b-acce-aff69d020884_2e1c70c3-b6cd-4c0e-9843-7b9aeec52338/pptx";
const { applyTheme } = require(SK + "/scripts/apply_theme.js");
const { inject } = require("./lib_anim");

// ── Design tokens (Apple dark) ──
const BLUE = "0A84FF", GREEN = "30D158", ORANGE = "FF9F0A", RED = "FF453A", PURPLE = "BF5AF2", PINK = "FF375F", TEAL = "64D2FF", INDIGO = "5E5CE6", YELLOW = "FFD60A";
const BLACK = "000000", CARD = "1C1C1E", LINE = "2C2C2E", G1 = "A1A1A6", G2 = "6E6E73", WHITE = "FFFFFF";
const GR1 = "010203", GR2 = "010204", GR3 = "010205", GR4 = "010206";   // gradient-text markers
const THEME = { name: "Keynote Dark", headFontFace: "Arial", bodyFontFace: "Arial",
  colors: { dk1: BLACK, lt1: WHITE, dk2: CARD, lt2: "F5F5F7", accent1: BLUE, accent2: RED, accent3: GREEN, accent4: ORANGE, accent5: PURPLE, accent6: TEAL, hlink: TEAL, folHlink: PURPLE } };
const pres = new pptxgen();
pres.layout = "LAYOUT_16x9";
pres.theme = { headFontFace: "Arial", bodyFontFace: "Arial" };
pres.title = "CICADA 2026 · Secure AIOps Observability";
const S = pres.ShapeType;
pres.defineSlideMaster({ title: "KEYNOTE", background: { color: BLACK },
  objects: [{ placeholder: { options: { name: "title", type: "title", x: 0.6, y: 0.52, w: 8.8, h: 0.72, fontSize: 38, bold: true, color: WHITE, charSpacing: -1, margin: 0, valign: "middle", align: "left" }, text: "" } }] });
pres.defineSlideMaster({ title: "HERO", background: { color: BLACK }, objects: [] });

// ── registry ──
let SL = 0, cur = { t: 0, fx: "rise", click: 0 }, cnt = 0;
const entries = {}, links = {}, transitions = {};
const pen = (t, fx = "rise", click = 0) => { cur = { t, fx, click }; };
function NM(prefix, o = {}) {
  const name = o.id || `${prefix}-${++cnt}`;
  const fx = o.fx === undefined ? cur.fx : o.fx;
  if (!o.stat && fx) entries[SL].push({ name, fx, t: o.t === undefined ? cur.t : o.t, click: o.click === undefined ? cur.click : o.click, dur: o.dur });
  return name;
}
const loop = (name, kind, o = {}) => entries[SL].push(Object.assign({ name, kind, t: 0.6, click: 0 }, o));
const link = (name, to, tip) => (links[SL] = links[SL] || []).push({ name, to, tip });
const strip = (o) => { const { id, fx, t, click, stat, dur, ...rest } = o; return rest; };

// ── drawing helpers ──
async function iconPng(Comp, hex, px = 256) { return sharp(Buffer.from(RDS.renderToStaticMarkup(React.createElement(Comp, { color: "#" + hex, size: px })))).png().toBuffer(); }
const b64 = (buf) => "image/png;base64," + buf.toString("base64");
async function orbPng(hex) {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="400" height="400"><defs><radialGradient id="g"><stop offset="0" stop-color="#${hex}" stop-opacity="0.9"/><stop offset="0.5" stop-color="#${hex}" stop-opacity="0.3"/><stop offset="1" stop-color="#${hex}" stop-opacity="0"/></radialGradient></defs><circle cx="200" cy="200" r="200" fill="url(#g)"/></svg>`;
  return b64(await sharp(Buffer.from(svg)).png().toBuffer());
}
const txt = (s, t, o = {}) => { const name = NM("t", o); s.addText(t, Object.assign({ isTextBox: true, margin: 0, color: WHITE, fontSize: 14, valign: "middle", objectName: name }, strip(o))); return name; };
const pill = (s, t, o = {}) => { const name = NM("p", o); s.addText(t, Object.assign({ isTextBox: true, shape: S.roundRect, rectRadius: 0.12, align: "center", valign: "middle", margin: 0.05, color: WHITE, fontSize: 13, bold: true, objectName: name }, strip(o))); return name; };
const rect = (s, x, y, w, h, o = {}) => {
  const name = NM("r", o);
  s.addShape(o.oval ? S.ellipse : S.roundRect, { x, y, w, h, rectRadius: o.r === undefined ? 0.16 : o.r, fill: { color: o.fill || CARD, transparency: o.tr || 0 }, line: o.line ? { color: o.line, width: o.lw || 0.75 } : { type: "none" }, objectName: name });
  return name;
};
const hair = (s, x, y, w, o = {}) => { const name = NM("hair", Object.assign({ fx: "wipe" }, o)); s.addShape(S.line, { x, y, w, h: 0, line: { color: o.color || LINE, width: 0.75 }, objectName: name }); return name; };
const arrow = (s, x, y, w, h, o = {}) => { const name = NM("arrow", Object.assign({ fx: "wipe" }, o)); s.addShape(S.line, { x, y, w, h, line: { color: o.color || G2, width: 1.5, endArrowType: "triangle" }, objectName: name }); return name; };
async function sq(s, Comp, x, y, d, color, o = {}) {
  const bg = NM("sq", Object.assign({ fx: "pop" }, o));
  s.addShape(S.roundRect, { x, y, w: d, h: d, rectRadius: d * 0.26, fill: { color }, line: { type: "none" }, objectName: bg });
  const k = d * 0.5, im = NM("gl", Object.assign({ fx: "pop" }, o, { id: undefined }));
  s.addImage({ data: b64(await iconPng(Comp, "FFFFFF")), x: x + (d - k) / 2, y: y + (d - k) / 2, w: k, h: k, altText: "icon", objectName: im });
  return [bg, im];
}

// ── ambient glow (morph targets) ──
let ORB;
const ORBPOS = new Proxy({}, { get: (t, k) => { const i = +k; return [[-2.5 + 7 * Math.sin(i * 1.3), -2.8 + 2.5 * Math.cos(i * 0.9), 6 + 0.6 * Math.sin(i)], [5.5 + 3.5 * Math.cos(i * 1.1), 0.5 + 3 * Math.sin(i * 1.7), 6], [1 + 5 * Math.sin(i * 2.1), 3.2 + 1.2 * Math.cos(i * 1.3), 4.6]]; } });
function glow(s) { const p = ORBPOS[SL]; ["!!orbA", "!!orbB", "!!orbC"].forEach((n, i) => s.addImage({ data: ORB[i], x: p[i][0], y: p[i][1], w: p[i][2], h: p[i][2], transparency: i === 2 ? 72 : 62, altText: "", objectName: n })); }

// ── navigation: iOS-style segmented control ──
const SECTIONS = [["Why", 1], ["Design", 3], ["Platform", 7], ["Intelligence", 9], ["Build", 12], ["Proof", 15]];
const secOf = (n) => (n <= 2 ? 0 : n <= 6 ? 1 : n <= 8 ? 2 : n <= 11 ? 3 : n <= 14 ? 4 : 5);
function nav(s) {
  const ws = SECTIONS.map(([l]) => l.length * 0.085 + 0.4), tot = ws.reduce((a, b) => a + b, 0) + 0.12, x0 = (10 - tot) / 2, y0 = 5.1;
  s.addShape(S.roundRect, { x: x0, y: y0, w: tot, h: 0.34, rectRadius: 0.17, fill: { color: WHITE, transparency: 90 }, line: { type: "none" }, objectName: "nav-bg" });
  let x = x0 + 0.06;
  SECTIONS.forEach(([l, to], i) => {
    const on = secOf(SL) === i, nm = `nav-${i + 1}`;
    s.addText(l, { isTextBox: true, shape: S.roundRect, rectRadius: 0.14, x, y: y0 + 0.04, w: ws[i], h: 0.26, margin: 0, align: "center", valign: "middle", fontSize: 11, bold: true, color: on ? BLACK : G1, fill: { color: WHITE, transparency: on ? 0 : 100 }, objectName: nm });
    link(nm, to, l); x += ws[i];
  });
  s.addText("CICADA 2026", { isTextBox: true, x: 0.6, y: 5.17, w: 1.4, h: 0.2, margin: 0, fontSize: 10, color: G2, charSpacing: 1, objectName: "foot-l" });
  s.addText(`${String(SL).padStart(2, "0")} / 17`, { isTextBox: true, x: 8.4, y: 5.17, w: 1.0, h: 0.2, margin: 0, fontSize: 10, color: G2, align: "right", objectName: "foot-r" });
}
function hdr(s, eyebrow, ecolor, title, sub, hintText) {
  txt(s, eyebrow, { x: 0.6, y: 0.3, w: 6, h: 0.22, fontSize: 11, bold: true, charSpacing: 3, color: ecolor, fx: "fade", t: 0 });
  s.addText(title, { placeholder: "title" });
  txt(s, sub, { x: 0.6, y: 1.2, w: 8.8, h: 0.35, fontSize: 18, color: G1, fx: "fade", t: 0.2 });
  if (hintText) txt(s, hintText, { x: 6.0, y: 0.3, w: 3.4, h: 0.22, fontSize: 11, color: G2, align: "right", fx: "fade", t: 1 });
}

const NOTES = {
  1: "Open with the tension: monitoring wants your data, security says no. This platform resolves it. Tap Explore to begin.",
  2: "Logs carry secrets, SaaS AIOps needs data, and raw logs at a vendor break policy. That is the trust gap.",
  3: "Tier 1 stays in the customer network and keeps raw logs. Tier 2 sees only allow-listed metadata over HTTPS with a per-collector API key.",
  4: "Walk the redaction: secrets are covered, only numbers and pseudonyms leave. Three layers: schema allow-list, regex scrub, outbound scanner that blocks.",
  5: "Persist first, send second. Click through offline buffering with backoff, crash recovery with the same payload id, and lost-ACK dedup.",
  6: "Every API key binds to one tenant, the region must match, and pseudonym keys are per tenant.",
  7: "Bento overview: AIOps brain, collector, privacy pipeline, telemetry, dashboard and safe remediation. Tap a tile to jump to detail.",
  8: "Six stages. The first three run in the customer network, the last three in the SaaS. Everything is persisted and idempotent.",
  9: "Four health states, z-score anomaly detection against a 15 minute baseline, and incident correlation along the dependency map within 30 seconds.",
  10: "Explainability is weighted higher. Show why it was flagged, which signals contributed, and why the action. Scores here are illustrative. Narration is template-based; an optional LLM would only ever see allow-listed metadata.",
  11: "Targets: dashboard within 10 s, alert within 15 s, offline within 60 s, zero loss or duplicates. Global-ready: regional ingest, UTC, out-of-order safe, idempotent.",
  12: "A deliberately lean, proposed stack: Python and FastAPI end to end, SQLite for delivery speed, NumPy for statistics, React for the dashboard.",
  13: "Contract-first so four people build in parallel, vertical slices so something works end to end early, tests gate merges, and the demo is scripted.",
  14: "Four builders: collector, SaaS backend, AIOps, frontend and demo. 24 hours across four stages.",
  15: "Each phase of the evaluation sheet maps to features. The counts show criteria covered by design and proven in the live demo.",
  16: "Honest limitations are scored in Phase 4. Name them, then show the roadmap.",
  17: "Click through the four live proofs: secret in raw but absent on the wire, network cut, duplicate send, delivery check with zero missing and zero duplicates.",
};

(async () => {
  ORB = [await orbPng(BLUE), await orbPng(PURPLE), await orbPng(PINK)];
  const next = (master) => { SL++; entries[SL] = []; cnt = 0; const s = pres.addSlide({ masterName: master }); glow(s); s.addNotes(NOTES[SL]); return s; };
  const MORPH = { kind: "morph" };
  let s;

  // ═══ 1 · HERO ═══
  s = next("HERO"); transitions[SL] = { kind: "fade", xml: "<p:fade/>", dur: 1400 };
  loop("!!orbA", "pulse", { t: 1, dur: 5200, by: 106000 });
  pen(0.2, "fade"); txt(s, "CICADA 2026  ·  PHASE 1", { x: 0.5, y: 0.95, w: 9, h: 0.3, fontSize: 12, bold: true, charSpacing: 5, color: G1, align: "center" });
  pen(0.5, "rise");
  txt(s, [{ text: "Observability.", options: { breakLine: true } }, { text: "Without exposure.", options: { color: GR1 } }], { x: 0.5, y: 1.3, w: 9, h: 1.95, fontSize: 54, bold: true, charSpacing: -2, align: "center" });
  pen(1.0, "rise"); txt(s, "A privacy-first AIOps platform. Intelligence goes to the cloud. Secrets stay home.", { x: 1.6, y: 3.3, w: 6.8, h: 0.7, fontSize: 18, color: G1, align: "center", valign: "top" });
  pen(1.4, "rise");
  const cta = pill(s, "Explore the platform", { x: 2.85, y: 4.3, w: 2.1, h: 0.46, fontSize: 14, color: BLACK, fill: { color: WHITE }, rectRadius: 0.23 }); link(cta, 3, "Explore");
  const cta2 = txt(s, "Watch it live  ›", { x: 5.2, y: 4.3, w: 1.8, h: 0.46, fontSize: 15, color: BLUE, bold: true, align: "center" }); link(cta2, 17, "Live demo");
  nav(s);

  // ═══ 2 · PROBLEM ═══
  s = next("KEYNOTE"); transitions[SL] = MORPH;
  hdr(s, "THE PROBLEM", PINK, "The trust gap.", "Monitoring wants your data. Security says no.");
  const probs = [[fa.FaKey, RED, "Logs spill secrets", "Passwords, API keys, tokens and IPs hide in everyday logs.", 4], [fa.FaCloud, BLUE, "SaaS needs data", "Cloud AIOps only spots anomalies if metrics keep flowing.", 3], [fa.FaBalanceScale, ORANGE, "A policy wall", "Raw logs at a vendor break security and residency rules.", 6]];
  for (let i = 0; i < 3; i++) {
    const x = 0.6 + i * 2.98, [Ic, col, h, b, to] = probs[i], t0 = 0.4 + i * 0.3;
    pen(t0, "rise"); const g = rect(s, x, 1.85, 2.84, 2.15); link(g, to, h);
    await sq(s, Ic, x + 0.25, 2.07, 0.5, col, { t: t0 + 0.15 });
    txt(s, "›", { x: x + 2.4, y: 2.07, w: 0.3, h: 0.5, fontSize: 22, color: G2, align: "right" });
    txt(s, h, { x: x + 0.25, y: 2.75, w: 2.4, h: 0.35, fontSize: 18, bold: true });
    txt(s, b, { x: x + 0.25, y: 3.12, w: 2.35, h: 0.75, fontSize: 14, color: G1, valign: "top" });
  }
  pen(1.6, "rise"); txt(s, [{ text: "So raw data stays home. We ship " }, { text: "only what's safe.", options: { color: GR1 } }], { x: 0.6, y: 4.2, w: 8.8, h: 0.55, fontSize: 22, bold: true, align: "center" });
  nav(s);

  // ═══ 3 · IDEA ═══
  s = next("KEYNOTE"); transitions[SL] = MORPH;
  hdr(s, "THE IDEA", BLUE, "Two tiers. One boundary.", "Intelligence goes to the cloud. Secrets stay home.");
  pen(0.3, "fade"); rect(s, 0.6, 1.85, 3.55, 2.4, { r: 0.2 }); rect(s, 4.95, 1.85, 4.45, 2.4, { r: 0.2 });
  txt(s, "YOUR NETWORK", { x: 0.85, y: 1.98, w: 2.5, h: 0.22, fontSize: 10, bold: true, charSpacing: 2, color: TEAL });
  txt(s, "OUR SAAS", { x: 5.2, y: 1.98, w: 2.5, h: 0.22, fontSize: 10, bold: true, charSpacing: 2, color: BLUE });
  const nodes = [[1.3, fa.FaServer, G2, "Servers", "raw logs", 2], [3.2, fa.FaFilter, TEAL, "Collector", "redacts, buffers", 4], [5.7, fa.FaInbox, BLUE, "Ingest", "dedups per tenant", 5], [7.2, fa.FaBrain, PURPLE, "AIOps", "detects, explains", 9], [8.7, fa.FaDesktop, INDIGO, "Dashboard", "live health", 17]];
  const conns = [[1.7, 2.8], [3.6, 5.3], [6.1, 6.8], [7.6, 8.3]];
  conns.forEach(([a, b], i) => arrow(s, a, 2.8, b - a, 0, { t: 0.8 + i * 0.25, color: i === 1 ? G1 : G2 }));
  for (let i = 0; i < nodes.length; i++) {
    const [cx, Ic, col, l, sub, to] = nodes[i], t0 = 0.6 + i * 0.25;
    pen(t0, "pop"); const [bg] = await sq(s, Ic, cx - 0.35, 2.45, 0.7, col, { t: t0 }); link(bg, to, l);
    pen(t0, "fade"); txt(s, l, { x: cx - 0.7, y: 3.28, w: 1.4, h: 0.28, fontSize: 14, bold: true, align: "center" });
    txt(s, sub, { x: cx - 0.7, y: 3.56, w: 1.4, h: 0.4, fontSize: 11, color: G1, align: "center", valign: "top" });
  }
  const bd = NM("boundary", { fx: "wipeup", t: 1.0, dur: 900 });
  s.addShape(S.line, { x: 4.55, y: 1.75, w: 0, h: 2.6, line: { color: G2, width: 1.5, dashType: "dash" }, objectName: bd });
  pen(1.4, "pop"); const [l1, l2] = await sq(s, fa.FaLock, 4.38, 2.0, 0.34, RED); loop(l1, "pulse", { t: 2.4, dur: 900, by: 108000 }); loop(l2, "pulse", { t: 2.4, dur: 900, by: 108000 });
  for (let i = 0; i < 3; i++) { const pk = NM("packet", { stat: true }); s.addShape(S.ellipse, { x: 3.62, y: 2.72, w: 0.16, h: 0.16, fill: { color: GREEN }, line: { type: "none" }, objectName: pk }); loop(pk, "packet", { t: 2.2 + i * 0.6, dx: 0.17, dur: 1800 }); }
  pen(2.0, "fade"); txt(s, "HTTPS  ·  per-collector API key  ·  allow-listed metadata only", { x: 1.2, y: 4.45, w: 7.6, h: 0.3, fontSize: 12, color: G1, align: "center" });
  nav(s);

  // ═══ 4 · PRIVACY ═══
  s = next("KEYNOTE"); transitions[SL] = MORPH;
  hdr(s, "PRIVACY", GREEN, "Three layers. Zero leaks.", "Only numbers and pseudonyms ever leave.");
  pen(0.3, "left"); rect(s, 0.6, 1.85, 3.9, 2.1, { r: 0.2 });
  pen(0.3, "fade"); txt(s, "RAW  ·  STAYS LOCAL", { x: 0.85, y: 1.97, w: 3, h: 0.22, fontSize: 10, bold: true, charSpacing: 2, color: RED });
  const MONO = { fontFace: "Courier New", fontSize: 12, align: "left" };
  ["deploy password=Summer@2026", "token=ghp_FAKE1234 user=root", "from 192.168.1.50", "host prod-db-01.corp.local"].forEach((l, i) => { pen(0.7 + i * 0.25, "wipe"); txt(s, l, Object.assign({ x: 0.85, y: 2.4 + i * 0.3, w: 3.5, h: 0.25 }, MONO)); });
  [[7, 20], [6, 12], [5, 12], [5, 21]].forEach(([c0, len], i) => { pen(2.3 + i * 0.35, "wipe"); rect(s, 0.85 + c0 * 0.1 - 0.03, 2.395 + i * 0.3, len * 0.1 + 0.06, 0.26, { fill: RED, r: 0.06, dur: 350 }); });
  pen(2.2, "pop"); await sq(s, fa.FaShieldAlt, 4.7, 2.5, 0.6, GREEN);
  pen(2.0, "wipe"); arrow(s, 4.52, 2.8, 0.16, 0, { color: GREEN }); arrow(s, 5.32, 2.8, 0.16, 0, { color: GREEN, t: 3.6 });
  pen(3.7, "right"); rect(s, 5.5, 1.85, 3.9, 2.1, { r: 0.2 });
  pen(3.7, "fade"); txt(s, "OUTBOUND  ·  WHAT IS SENT", { x: 5.75, y: 1.97, w: 3.2, h: 0.22, fontSize: 10, bold: true, charSpacing: 2, color: GREEN });
  ['{"node": "n-b7cd652869",', ' "cpu": 40.0,', ' "latency_ms": 20.0,', ' "auth_failures_60s": 12,', ' "severity": "critical"}'].forEach((l, i) => { pen(4.0 + i * 0.25, "wipe"); txt(s, l, Object.assign({ x: 5.75, y: 2.4 + i * 0.3, w: 3.5, h: 0.25 }, MONO)); });
  [["1", "Schema allow-list", BLUE], ["2", "Regex scrub", PURPLE], ["3", "Scan and block", PINK]].forEach(([k, t, col], i) => {
    const x = 0.6 + i * 2.98; pen(5.0 + i * 0.25, "rise");
    rect(s, x, 4.2, 0.34, 0.34, { fill: col, oval: true }); txt(s, k, { x, y: 4.2, w: 0.34, h: 0.34, fontSize: 13, bold: true, align: "center" });
    txt(s, t, { x: x + 0.48, y: 4.2, w: 2.3, h: 0.34, fontSize: 16, bold: true });
  });
  nav(s);

  // ═══ 5 · RELIABILITY ═══
  s = next("KEYNOTE"); transitions[SL] = MORPH;
  hdr(s, "RELIABILITY", ORANGE, "It never loses a beat.", "Save first. Send second. Deliver exactly once.");
  pen(0.3, "wipe"); hair(s, 1.15, 2.15, 7.7, { color: G2, t: 0.3 });
  const pk5 = NM("packet", { stat: true }); s.addShape(S.ellipse, { x: 1.05, y: 2.05, w: 0.2, h: 0.2, fill: { color: YELLOW }, line: { type: "none" }, objectName: pk5 }); loop(pk5, "packet", { t: 1.8, dx: 0.77, dur: 3800 });
  [[fa.FaDatabase, BLUE, "Persist", "Local outbox first"], [fa.FaPaperPlane, INDIGO, "Send", "HTTPS batches"], [fa.FaClone, PURPLE, "Dedup", "SaaS keys on payload_id"], [fa.FaCheck, GREEN, "ACK", "Then mark delivered"]].forEach(async () => {});
  const st5 = [[fa.FaDatabase, BLUE, "Persist", "Local outbox first"], [fa.FaPaperPlane, INDIGO, "Send", "HTTPS batches"], [fa.FaClone, PURPLE, "Dedup", "SaaS keys on payload_id"], [fa.FaCheck, GREEN, "ACK", "Then mark delivered"]];
  for (let i = 0; i < 4; i++) {
    const [Ic, col, l, sub] = st5[i], cx = 1.15 + i * 2.57, t0 = 0.4 + i * 0.3;
    await sq(s, Ic, cx - 0.25, 1.9, 0.5, col, { t: t0 });
    pen(t0 + 0.1, "rise"); txt(s, l, { x: cx - 1.0, y: 2.5, w: 2.0, h: 0.3, fontSize: 18, bold: true, align: "center" }); txt(s, sub, { x: cx - 1.0, y: 2.82, w: 2.0, h: 0.3, fontSize: 12, color: G1, align: "center" });
  }
  const rel = [[fa.FaWifi, ORANGE, "Offline?", "Buffer locally, retry at 1, 2, 4, 5 s."], [fa.FaPowerOff, BLUE, "Crash?", "Same payload_id re-sent, never duplicated."], [fa.FaCopy, PURPLE, "Lost ACK?", "Duplicate acknowledged, stored once."]];
  for (let i = 0; i < 3; i++) {
    const x = 0.6 + i * 2.98, [Ic, col, h, b] = rel[i]; pen(0, "rise", i + 1);
    rect(s, x, 3.4, 2.84, 1.4); await sq(s, Ic, x + 0.2, 3.58, 0.42, col, { fx: "pop" });
    txt(s, h, { x: x + 0.72, y: 3.58, w: 1.9, h: 0.42, fontSize: 16, bold: true }); txt(s, b, { x: x + 0.2, y: 4.1, w: 2.45, h: 0.6, fontSize: 13, color: G1, valign: "top" });
  }
  pen(1.2, "fade"); txt(s, "Click to reveal each case", { x: 6.0, y: 0.3, w: 3.4, h: 0.22, fontSize: 11, color: G2, align: "right" });
  nav(s);

  // ═══ 6 · TENANTS ═══
  s = next("KEYNOTE"); transitions[SL] = MORPH;
  hdr(s, "MULTI-TENANT", TEAL, "Every tenant. Its own lane.", "Keys, regions and pseudonyms never cross.");
  [["Tenant Alpha", "IN", "col-alpha-01", "India data store", TEAL, "left", 0.6], ["Tenant Beta", "EU", "col-beta-01", "EU data store", INDIGO, "right", 5.3]].forEach(([t, r, c, d, col, side, x]) => {
    pen(0.3, side); rect(s, x, 1.85, 4.1, 1.95, { r: 0.2 });
    pen(0.7, "fade"); txt(s, t, { x: x + 0.25, y: 2.0, w: 2.5, h: 0.4, fontSize: 18, bold: true });
    pill(s, "Region " + r, { x: x + 2.75, y: 2.05, w: 1.15, h: 0.3, fontSize: 11, fill: { color: col, transparency: 15 }, color: col === TEAL ? BLACK : WHITE });
    pen(1.0, "rise"); pill(s, c, { x: x + 0.25, y: 2.85, w: 1.65, h: 0.5, fontSize: 12, fill: { color: LINE } });
    arrow(s, x + 1.95, 3.1, 0.3, 0, { t: 1.3, color: G1 });
    pill(s, d, { x: x + 2.3, y: 2.85, w: 1.6, h: 0.5, fontSize: 12, fill: { color: col, transparency: 82 }, line: { color: col, width: 1 } });
  });
  const wall = NM("wall", { fx: "wipeup", t: 0.6, dur: 800 }); s.addShape(S.line, { x: 5.0, y: 1.75, w: 0, h: 2.15, line: { color: G2, width: 1.5, dashType: "dash" }, objectName: wall });
  pen(1.6, "pop"); const [w1, w2] = await sq(s, fa.FaLock, 4.83, 2.65, 0.34, RED); loop(w1, "pulse", { t: 2.4, dur: 900, by: 108000 }); loop(w2, "pulse", { t: 2.4, dur: 900, by: 108000 });
  [["API key", "binds to one tenant", BLUE], ["Wrong region", "payload rejected", ORANGE], ["Pseudonym key", "unique per tenant", PURPLE]].forEach(([a, b, col], i) => {
    const x = 0.6 + i * 2.98; pen(2.0 + i * 0.3, "rise");
    rect(s, x, 4.12, 0.14, 0.14, { fill: col, oval: true, r: 0 }); txt(s, [{ text: a, options: { bold: true, breakLine: true } }, { text: b, options: { color: G1, fontSize: 13 } }], { x: x + 0.3, y: 4.0, w: 2.5, h: 0.65, fontSize: 16, valign: "top" });
  });
  nav(s);

  // ═══ 7 · PLATFORM (bento) ═══
  s = next("KEYNOTE"); transitions[SL] = MORPH;
  hdr(s, "THE PLATFORM", PURPLE, "Everything, built in.", "Six capabilities. One privacy-first pipeline.", "Tap a tile to jump");
  pen(0.3, "rise"); const big = rect(s, 0.6, 1.85, 3.7, 2.95, { fill: PURPLE, tr: 78, r: 0.22, line: PURPLE }); link(big, 9, "AIOps brain");
  await sq(s, fa.FaBrain, 0.9, 2.15, 0.6, PURPLE, { t: 0.5 });
  pen(0.6, "rise"); txt(s, "AIOps brain", { x: 0.9, y: 2.95, w: 3.1, h: 0.5, fontSize: 28, bold: true, color: GR1, charSpacing: -1 });
  txt(s, "Learns what normal looks like. Flags what isn't. Explains why.", { x: 0.9, y: 3.5, w: 3.1, h: 0.8, fontSize: 15, color: G1, valign: "top" });
  txt(s, "z-score  ·  EWMA  ·  dependency graph", { x: 0.9, y: 4.4, w: 3.2, h: 0.25, fontSize: 11, color: G1 });
  const tiles = [[fa.FaServer, TEAL, "Local collector", "Redact, buffer", 3, 4.45, 1.85, 2.35], [fa.FaShieldAlt, GREEN, "Privacy pipeline", "Scrub and scan", 4, 6.95, 1.85, 2.45],
    [fa.FaTachometerAlt, BLUE, "Rich telemetry", "CPU, memory, disk", 5, 4.45, 2.9, 2.35], [fa.FaDesktop, INDIGO, "Live dashboard", "Four live states", 17, 6.95, 2.9, 2.45], [fa.FaWrench, ORANGE, "Safe remediation", "Policy, approval gate and audit trail", 10, 4.45, 3.95, 4.95]];
  for (let i = 0; i < tiles.length; i++) {
    const [Ic, col, h, b, to, x, y, w] = tiles[i], t0 = 0.5 + i * 0.2;
    pen(t0, "rise"); const g = rect(s, x, y, w, i === 4 ? 0.85 : 0.9, { r: 0.18 }); link(g, to, h);
    await sq(s, Ic, x + 0.2, y + (i === 4 ? 0.22 : 0.25), 0.4, col, { t: t0 + 0.1 });
    txt(s, h, { x: x + 0.75, y: y + 0.15, w: w - 0.9, h: 0.3, fontSize: 14, bold: true }); txt(s, b, { x: x + 0.75, y: y + 0.45, w: w - 0.9, h: 0.35, fontSize: 12, color: G1, valign: "top" });
  }
  nav(s);

  // ═══ 8 · APPROACH ═══
  s = next("KEYNOTE"); transitions[SL] = { kind: "fade", xml: "<p:fade/>", dur: 900 };
  hdr(s, "THE APPROACH", TEAL, "From stream to action.", "Six stages. Persisted and idempotent at every hop.");
  hair(s, 1.25, 2.45, 7.5, { color: G2, t: 0.3 });
  const pk8 = NM("packet", { stat: true }); s.addShape(S.ellipse, { x: 1.15, y: 2.35, w: 0.2, h: 0.2, fill: { color: YELLOW }, line: { type: "none" }, objectName: pk8 }); loop(pk8, "packet", { t: 3.2, dx: 0.76, dur: 4800 });
  const st8 = [[fa.FaFileAlt, TEAL, "Collect", "Read the stream"], [fa.FaFilter, GREEN, "Redact", "Allow-list, scrub, scan"], [fa.FaClock, BLUE, "Aggregate", "5 s windows per node"], [fa.FaBrain, PURPLE, "Analyse", "Baselines, z-score, graph"], [fa.FaBalanceScale, ORANGE, "Decide", "Severity, rules, explain"], [fa.FaWrench, PINK, "Act", "Recommend, approve, audit"]];
  for (let i = 0; i < 6; i++) {
    const [Ic, col, l, sub] = st8[i], x = 0.6 + i * 1.5, cx = x + 0.65, t0 = 0.5 + i * 0.3;
    pen(t0, "fade"); txt(s, "0" + (i + 1), { x, y: 1.85, w: 1.3, h: 0.22, fontSize: 11, bold: true, color: G2, align: "center", charSpacing: 2 });
    await sq(s, Ic, cx - 0.27, 2.18, 0.54, col, { t: t0 });
    pen(t0 + 0.1, "rise"); txt(s, l, { x, y: 2.85, w: 1.3, h: 0.3, fontSize: 15, bold: true, align: "center" }); txt(s, sub, { x: x + 0.05, y: 3.17, w: 1.2, h: 0.5, fontSize: 11, color: G1, align: "center", valign: "top" });
  }
  pen(2.4, "wipe"); [["RUNS IN YOUR NETWORK", TEAL, 0.6, 4.35], ["RUNS IN THE SAAS", BLUE, 5.1, 4.3]].forEach(([l, col, x, w]) => { s.addShape(S.line, { x, y: 3.95, w, h: 0, line: { color: col, width: 2 }, objectName: NM("brk") }); txt(s, l, { x, y: 4.02, w, h: 0.22, fontSize: 10, bold: true, charSpacing: 2, color: col, align: "center", fx: "fade" }); });
  pen(2.8, "rise"); txt(s, "Same payload_id, same result: replay-safe by design.", { x: 0.6, y: 4.45, w: 8.8, h: 0.35, fontSize: 15, color: G1, align: "center" });
  nav(s);

  // ═══ 9 · AI BRAIN ═══
  s = next("KEYNOTE"); transitions[SL] = MORPH;
  hdr(s, "INTELLIGENCE", PURPLE, "Spot it. Link it. Explain it.", "Health, anomalies and incidents, in real time.");
  [["Excellent", "all normal", GREEN], ["Good", "minor drift", BLUE], ["Fair", "5+ failed logins / 60 s", ORANGE], ["Poor", "10+ failed logins / 60 s", RED]].forEach(([a, b, col], i) => {
    const x = 0.6 + i * 2.3; pen(0.3 + i * 0.2, "rise"); rect(s, x, 1.93, 0.16, 0.16, { fill: col, oval: true, r: 0 });
    txt(s, [{ text: a, options: { bold: true, fontSize: 16, breakLine: true } }, { text: b, options: { fontSize: 12, color: G1 } }], { x: x + 0.28, y: 1.8, w: 1.95, h: 0.5, valign: "top" });
  });
  hair(s, 0.6, 2.5, 8.8, { t: 0.9 });
  pen(1.0, "left"); rect(s, 0.6, 2.7, 4.3, 2.1, { r: 0.2 });
  pen(1.2, "fade"); txt(s, "Anomaly detection", { x: 0.85, y: 2.82, w: 3.5, h: 0.3, fontSize: 16, bold: true });
  const sig = [41, 43, 40, 42, 44, 41, 43, 42, 45, 43, 44, 88, 92, 46, 43, 42];
  pen(1.5, "wipe"); const chn = NM("chart-spark", {});
  s.addChart(pres.charts.LINE, [{ name: "signal", labels: sig.map((_, i) => String(i)), values: sig }, { name: "3σ", labels: sig.map((_, i) => String(i)), values: sig.map(() => 66) }],
    { x: 0.75, y: 3.15, w: 4.0, h: 1.2, chartColors: [BLUE, ORANGE], lineSize: 3, lineDataSymbol: "none", catAxisHidden: true, valAxisHidden: true, valGridLine: { style: "none" }, catGridLine: { style: "none" }, showLegend: false, valAxisMinVal: 20, valAxisMaxVal: 100, objectName: chn });
  pen(2.1, "pop"); pill(s, "z = 4.2", { x: 3.4, y: 3.1, w: 0.75, h: 0.26, fontSize: 11, fill: { color: RED } });
  pen(2.2, "fade"); txt(s, "z > 3 vs a 15-minute baseline is flagged", { x: 0.85, y: 4.4, w: 3.9, h: 0.28, fontSize: 12, color: G1 });
  pen(1.2, "right"); rect(s, 5.1, 2.7, 4.3, 2.1, { r: 0.2 });
  pen(1.4, "fade"); txt(s, "Incident correlation", { x: 5.35, y: 2.82, w: 3.5, h: 0.3, fontSize: 16, bold: true });
  ["app-01", "db-01", "net-01"].forEach((t, i) => {
    pen(1.8 + i * 0.35, "pop"); const rc = i === 2;
    const nmv = pill(s, t, { x: 5.4 + i * 1.3, y: 3.4, w: 0.95, h: 0.42, fontSize: 13, fill: { color: rc ? RED : LINE } });
    if (rc) loop(nmv, "pulse", { t: 3.2, dur: 800, by: 108000 });
    if (i < 2) arrow(s, 6.37 + i * 1.3, 3.61, 0.3, 0, { t: 2.0 + i * 0.35, color: G1 });
  });
  pen(2.8, "fade"); txt(s, "root cause", { x: 7.9, y: 3.86, w: 1.0, h: 0.22, fontSize: 11, bold: true, color: RED, align: "center" });
  txt(s, "Alerts within 30 s follow the dependency map into one incident.", { x: 5.35, y: 4.15, w: 3.8, h: 0.55, fontSize: 13, color: G1, valign: "top" });
  nav(s);

  // ═══ 10 · EXPLAINABLE ═══
  s = next("KEYNOTE"); transitions[SL] = MORPH;
  hdr(s, "EXPLAINABLE AI", PINK, "Explain every alert.", "Why flagged. Which signals. Why this action.", "Weighted higher by the judges");
  pen(0.3, "left"); rect(s, 0.6, 1.85, 4.5, 2.95, { r: 0.2 });
  pen(0.5, "fade"); txt(s, "Incident A-102  ·  db-01", { x: 0.85, y: 1.97, w: 2.9, h: 0.35, fontSize: 16, bold: true });
  pill(s, "POOR", { x: 4.1, y: 2.0, w: 0.8, h: 0.28, fontSize: 11, fill: { color: RED } });
  txt(s, "Weighted risk 0.82 (illustrative)", { x: 0.85, y: 2.33, w: 3.5, h: 0.25, fontSize: 11, color: G1 });
  [["db-01 CPU   z = 4.2", "35%", 0.35, RED], ["net-01 latency   z = 3.6", "25%", 0.25, ORANGE], ["Failed logins   12 / 60 s", "25%", 0.25, PURPLE], ["Packet loss   3.1%", "15%", 0.15, BLUE]].forEach(([l, p, wgt, col], i) => {
    const y = 2.72 + i * 0.5; pen(0.9 + i * 0.3, "fade");
    txt(s, l, { x: 0.85, y, w: 3.0, h: 0.24, fontSize: 13 }); txt(s, p, { x: 4.1, y, w: 0.8, h: 0.24, fontSize: 13, bold: true, align: "right" });
    s.addShape(S.roundRect, { x: 0.85, y: y + 0.27, w: 4.05, h: 0.1, rectRadius: 0.05, fill: { color: LINE }, line: { type: "none" }, objectName: NM("trk", { stat: true }) });
    pen(1.1 + i * 0.3, "wipe"); rect(s, 0.85, y + 0.27, (4.05 * wgt) / 0.4, 0.1, { fill: col, r: 0.05, dur: 700 });
  });
  const ex = [[fa.FaQuestion, BLUE, "Why flagged", "Two signals crossed z > 3 inside one 30 s window."], [fa.FaSignal, PURPLE, "Which signals", "db-01 CPU, net-01 latency and 12 failed logins."], [fa.FaBolt, ORANGE, "Why this action", "The map points at net-01 first: throttle the source, then page on-call."]];
  const pend = [];
  ex.forEach(([Ic, col, h, b], i) => {
    const y = 1.85 + i * 1.02; pen(1.6 + i * 0.5, "right"); rect(s, 5.3, y, 4.1, 0.92, { r: 0.18 });
    pend.push(sq(s, Ic, 5.5, y + 0.24, 0.44, col, { t: 1.8 + i * 0.5 }));
    txt(s, h, { x: 6.1, y: y + 0.1, w: 3.2, h: 0.28, fontSize: 14, bold: true }); txt(s, b, { x: 6.1, y: y + 0.4, w: 3.2, h: 0.48, fontSize: 12, color: G1, valign: "top" });
  });
  await Promise.all(pend);
  nav(s);

  // ═══ 11 · REAL-TIME ═══
  s = next("KEYNOTE"); transitions[SL] = MORPH;
  hdr(s, "PERFORMANCE", ORANGE, "Fast. Correct. Worldwide.", "Targets we measure, not just claim.");
  pen(0.4, "rise"); txt(s, "≤ 10 s", { x: 0.6, y: 1.65, w: 5.4, h: 1.5, fontSize: 88, bold: true, color: GR1, charSpacing: -3 });
  pen(0.8, "fade"); txt(s, "from event to dashboard", { x: 0.6, y: 3.15, w: 5.4, h: 0.35, fontSize: 18, color: G1 });
  [["≤ 15 s", "event to alert", ORANGE], ["≤ 60 s", "offline detected (we alert at 30 s)", PURPLE], ["0", "payloads lost or duplicated", GREEN]].forEach(([n, l, col], i) => {
    const y = 1.8 + i * 0.52; pen(0.9 + i * 0.3, "right");
    txt(s, n, { x: 6.3, y, w: 1.3, h: 0.45, fontSize: 26, bold: true, color: col }); txt(s, l, { x: 7.65, y, w: 1.8, h: 0.45, fontSize: 12, color: G1 });
    if (i < 2) hair(s, 6.3, y + 0.5, 3.1, { t: 1.0 + i * 0.3 });
  });
  hair(s, 0.6, 3.85, 8.8, { t: 1.6 });
  [["Regional ingest", "IN and EU stores"], ["UTC everywhere", "local time for display"], ["Out-of-order safe", "event-time windows"], ["Idempotent", "payload_id dedup"]].forEach(([h, b], i) => {
    const x = 0.6 + i * 2.3; pen(1.8 + i * 0.2, "rise");
    rect(s, x, 4.12, 0.14, 0.14, { fill: GREEN, oval: true, r: 0 }); txt(s, [{ text: h, options: { bold: true, breakLine: true } }, { text: b, options: { color: G1, fontSize: 12 } }], { x: x + 0.26, y: 4.0, w: 1.95, h: 0.6, fontSize: 14, valign: "top" });
  });
  nav(s);

  // ═══ 12 · TECH STACK ═══
  s = next("KEYNOTE"); transitions[SL] = MORPH;
  hdr(s, "TECH STACK", BLUE, "Built on proven tools.", "Lean, fast to ship, strong guarantees.", "Proposed stack");
  const stack = [["Collector", TEAL, "Python 3.12  ·  FastAPI  ·  SQLite WAL  ·  httpx  ·  pydantic v2"], ["Privacy", GREEN, "HMAC-SHA256 pseudonyms  ·  regex scanners  ·  allow-list schema"], ["SaaS", BLUE, "FastAPI  ·  SQLite per region  ·  API-key auth  ·  TLS"],
    ["AIOps", PURPLE, "NumPy  ·  z-score + EWMA  ·  dependency graph  ·  explainer"], ["Frontend", INDIGO, "React  ·  Recharts  ·  live updates over SSE"], ["Quality", ORANGE, "pytest  ·  Docker Compose  ·  mkcert TLS"]];
  stack.forEach(([l, col, v], i) => {
    const y = 1.85 + i * 0.48; pen(0.3 + i * 0.2, "wipe"); hair(s, 0.6, y, 8.8);
    pen(0.4 + i * 0.2, "left"); rect(s, 0.6, y + 0.17, 0.12, 0.12, { fill: col, oval: true, r: 0 }); txt(s, l, { x: 0.9, y, w: 1.6, h: 0.46, fontSize: 14, color: G1 }); txt(s, v, { x: 2.6, y, w: 6.8, h: 0.46, fontSize: 15 });
  });
  hair(s, 0.6, 1.85 + 6 * 0.48, 8.8, { t: 1.6 });
  nav(s);

  // ═══ 13 · METHODOLOGY ═══
  s = next("KEYNOTE"); transitions[SL] = MORPH;
  hdr(s, "METHODOLOGY", GREEN, "How we ship in 24 hours.", "Five habits that keep four people in sync.");
  [["Contract-first", "Schemas and tenants agreed before code."], ["Vertical slices", "Something works end to end early."], ["Test as we go", "Tests gate every merge."], ["Demo-driven", "Live scenarios scripted and rehearsed."], ["Freeze & polish", "No new features in the last hours."]].forEach(([h, b], i) => {
    const x = 0.6 + i * 1.78; pen(0.3 + i * 0.25, "rise");
    txt(s, String(i + 1), { x, y: 1.8, w: 1.6, h: 0.8, fontSize: 52, bold: true, color: GR1, charSpacing: -2 });
    txt(s, h, { x, y: 2.65, w: 1.65, h: 0.35, fontSize: 15, bold: true }); txt(s, b, { x, y: 3.02, w: 1.6, h: 0.7, fontSize: 12, color: G1, valign: "top" });
  });
  pen(1.7, "rise"); rect(s, 0.6, 3.95, 8.8, 0.85, { r: 0.2 });
  txt(s, "DEFINITION OF DONE", { x: 0.85, y: 4.0, w: 3, h: 0.22, fontSize: 10, bold: true, charSpacing: 2, color: G2 });
  ["Tests green", "No secret on the wire", "0 missing  ·  0 dupes", "Demo rehearsed"].forEach((t, i) => { pen(1.9 + i * 0.2, "fade"); rect(s, 0.85 + i * 2.15, 4.4, 0.12, 0.12, { fill: GREEN, oval: true, r: 0 }); txt(s, t, { x: 1.07 + i * 2.15, y: 4.33, w: 1.95, h: 0.26, fontSize: 13 }); });
  nav(s);

  // ═══ 14 · TEAM ═══
  s = next("KEYNOTE"); transitions[SL] = MORPH;
  hdr(s, "THE TEAM", PINK, "Four builders. 24 hours.", "Clear owners. One shared contract.");
  [["P1", "Collector", "Tier 1, redaction, outbox", TEAL], ["P2", "SaaS backend", "Ingest, dedup, tenants", BLUE], ["P3", "AIOps", "Health, anomalies, fixes", PURPLE], ["P4", "Frontend & demo", "Dashboard and story", PINK]].forEach(([p, r, d, col], i) => {
    const x = 0.6 + i * 2.3; pen(0.3 + i * 0.25, "rise");
    rect(s, x, 1.85, 0.62, 0.62, { fill: col, oval: true, r: 0 }); txt(s, p, { x, y: 1.85, w: 0.62, h: 0.62, fontSize: 16, bold: true, align: "center", color: col === TEAL ? BLACK : WHITE });
    txt(s, r, { x, y: 2.6, w: 2.1, h: 0.32, fontSize: 16, bold: true }); txt(s, d, { x, y: 2.95, w: 2.0, h: 0.5, fontSize: 13, color: G1, valign: "top" });
  });
  pen(1.5, "fade"); txt(s, "THE 24-HOUR PLAN", { x: 0.6, y: 3.7, w: 4, h: 0.22, fontSize: 10, bold: true, charSpacing: 2, color: G2 });
  [["0–4 h", "Contracts, scaffold", 4, TEAL], ["4–12 h", "Core build", 8, BLUE], ["12–20 h", "Integrate, demo runs", 8, PURPLE], ["20–24 h", "Polish", 4, GREEN]].reduce((x, [h, t, hrs, col], i) => {
    const w = hrs * (8.8 / 24); pen(1.7 + i * 0.5, "wipe"); rect(s, x, 4.0, w - 0.06, 0.09, { fill: col, r: 0.04, dur: 700 });
    pen(1.8 + i * 0.5, "fade"); txt(s, [{ text: h, options: { bold: true, breakLine: true } }, { text: t, options: { color: G1, fontSize: 12 } }], { x, y: 4.18, w: w - 0.1, h: 0.55, fontSize: 14, valign: "top" });
    return x + w;
  }, 0.6);
  nav(s);

  // ═══ 15 · SCORECARD ═══
  s = next("KEYNOTE"); transitions[SL] = MORPH;
  hdr(s, "THE SCORECARD", ORANGE, "Built to be judged.", "Criteria covered by design, proven in the live demo.");
  [["7/7", "Phase 1", "Problem and ideation"], ["6/6", "Phase 2", "Architecture and design"], ["6/6", "Phase 3", "Working prototype"], ["5/5", "Phase 4", "Demo and validation"]].forEach(([n, a, b], i) => {
    const x = 0.6 + i * 2.3; pen(0.3 + i * 0.25, "rise");
    txt(s, n, { x, y: 1.75, w: 2.1, h: 0.85, fontSize: 52, bold: true, color: GR1, charSpacing: -2 }); txt(s, a, { x, y: 2.62, w: 2.1, h: 0.3, fontSize: 16, bold: true }); txt(s, b, { x, y: 2.93, w: 2.1, h: 0.28, fontSize: 12, color: G1 });
  });
  hair(s, 0.6, 3.4, 8.8, { t: 1.3 });
  [["MANDATORY", GREEN, ["Real-time from timestamps", "Shared organiser stream", "Egress proof panel"], 3.6], ["BONUS", PURPLE, ["Privacy pipeline", "Local buffering", "Explainable AIOps"], 4.05], ["", PURPLE, ["Alert-noise reduction", "Safe remediation", "Global-ready delivery"], 4.5]].forEach(([lab, col, chips, y]) => {
    pen(1.5, "fade"); if (lab) txt(s, lab, { x: 0.6, y, w: 1.4, h: 0.34, fontSize: 10, bold: true, charSpacing: 2, color: col });
    chips.forEach((c, j) => { pen(1.6 + j * 0.2, "pop"); pill(s, c, { x: 2.0 + j * 2.5, y, w: 2.35, h: 0.34, fontSize: 12, bold: false, fill: { color: col, transparency: 100 }, line: { color: col, width: 1 } }); });
  });
  nav(s);

  // ═══ 16 · HONESTY ═══
  s = next("KEYNOTE"); transitions[SL] = MORPH;
  hdr(s, "HONESTY", RED, "What it can't do yet.", "Named limits, and where we go next.");
  pen(0.3, "fade"); txt(s, "LIMITATIONS", { x: 0.6, y: 1.85, w: 3, h: 0.22, fontSize: 10, bold: true, charSpacing: 2, color: ORANGE }); txt(s, "ROADMAP", { x: 5.2, y: 1.85, w: 3, h: 0.22, fontSize: 10, bold: true, charSpacing: 2, color: TEAL });
  ["Simulated telemetry, not a live fleet", "15-minute warm-up for baselines", "Single-node SQLite, not scaled out", "Remediation is advisory and approval-gated"].forEach((t, i) => {
    const y = 2.2 + i * 0.62; pen(0.5 + i * 0.25, "wipe"); hair(s, 0.6, y, 4.2);
    pen(0.6 + i * 0.25, "rise"); rect(s, 0.6, y + 0.24, 0.12, 0.12, { fill: ORANGE, oval: true, r: 0 }); txt(s, t, { x: 0.9, y, w: 3.9, h: 0.6, fontSize: 14 });
  });
  [["Now", "Privacy-first MVP", GREEN], ["Next", "OpenTelemetry-compatible agents", BLUE], ["Then", "Postgres and a message queue", PURPLE], ["Later", "Cross-tenant learning", PINK]].forEach(([a, b, col], i) => {
    const y = 2.2 + i * 0.62; pen(0.5 + i * 0.25, "wipe"); hair(s, 5.2, y, 4.2);
    pen(0.6 + i * 0.25, "rise"); rect(s, 5.2, y + 0.24, 0.12, 0.12, { fill: col, oval: true, r: 0 }); txt(s, [{ text: a + "  ", options: { bold: true, color: col } }, { text: b, options: { color: WHITE } }], { x: 5.5, y, w: 3.9, h: 0.6, fontSize: 14 });
  });
  nav(s);

  // ═══ 17 · CLOSING / DEMO ═══
  s = next("HERO"); transitions[SL] = { kind: "fade", xml: "<p:fade/>", dur: 1200 };
  loop("!!orbA", "pulse", { t: 1, dur: 5200, by: 106000 });
  pen(0.2, "fade"); txt(s, "LIVE DEMO", { x: 0.6, y: 0.4, w: 5, h: 0.25, fontSize: 11, bold: true, charSpacing: 4, color: GREEN });
  pen(0.4, "rise"); txt(s, "Let's prove it.", { x: 0.6, y: 0.7, w: 8.8, h: 0.95, fontSize: 52, bold: true, color: GR1, charSpacing: -2 });
  pen(0.8, "fade"); txt(s, "Four live proofs. Click to reveal each.", { x: 0.6, y: 1.65, w: 8.8, h: 0.35, fontSize: 18, color: G1 });
  const pf = [[fa.FaEyeSlash, RED, "Secrets stay home", "Visible in raw, never on the wire"], [fa.FaPlug, ORANGE, "Cut the network", "Buffered locally, delivered after"], [fa.FaCopy, PURPLE, "Send a duplicate", "Stored once, acknowledged"], [fa.FaCheckDouble, GREEN, "Delivery check", "0 missing, 0 duplicates, hashes match"]];
  for (let i = 0; i < 4; i++) {
    const x = 0.6 + (i % 2) * 4.5, y = 2.2 + Math.floor(i / 2) * 1.2, [Ic, col, h, b] = pf[i]; pen(0, "rise", i + 1);
    rect(s, x, y, 4.3, 1.05, { r: 0.2 }); await sq(s, Ic, x + 0.25, y + 0.27, 0.5, col, { fx: "pop" });
    txt(s, h, { x: x + 0.95, y: y + 0.2, w: 3.2, h: 0.3, fontSize: 17, bold: true }); txt(s, b, { x: x + 0.95, y: y + 0.55, w: 3.2, h: 0.3, fontSize: 13, color: G1 });
  }
  pen(0, "rise", 5); txt(s, [{ text: "Cloud intelligence. " }, { text: "Zero raw data leaving the customer.", options: { color: GR3 } }], { x: 0.6, y: 4.6, w: 8.8, h: 0.4, fontSize: 18, bold: true, align: "center" });
  nav(s);

  const file = "CICADA2026_AI_Platform_Keynote.pptx";
  await pres.writeFile({ fileName: file });
  await inject(file, { entries, transitions, links });
  await applyTheme(file, THEME);
  console.log("built", file);
})();
