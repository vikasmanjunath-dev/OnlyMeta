const pptxgen = require("pptxgenjs");
const React = require("react"), RDS = require("react-dom/server"), sharp = require("sharp");
const fa = require("react-icons/fa");
const SK = "/root/.claude/skills/synced/b13cfb69-ef4e-491b-acce-aff69d020884_2e1c70c3-b6cd-4c0e-9843-7b9aeec52338/pptx";
const { applyTheme } = require(SK + "/scripts/apply_theme.js");
const { inject } = require("./lib_anim");

// Apple system colours (dark mode)
const BLUE = "0A84FF", GREEN = "30D158", ORANGE = "FF9F0A", RED = "FF453A", PURPLE = "BF5AF2", PINK = "FF375F", TEAL = "64D2FF", INDIGO = "5E5CE6", YELLOW = "FFD60A";
const THEME = { name: "Glass Dark", headFontFace: "Arial", bodyFontFace: "Arial",
  colors: { dk1: "0A0A0F", lt1: "FFFFFF", dk2: "1C1C1E", lt2: "F5F5F7", accent1: BLUE, accent2: RED, accent3: GREEN, accent4: ORANGE, accent5: PURPLE, accent6: TEAL, hlink: TEAL, folHlink: PURPLE } };
const pres = new pptxgen();
pres.layout = "LAYOUT_16x9";
pres.theme = { headFontFace: "Arial", bodyFontFace: "Arial" };
pres.title = "CICADA 2026 · Phase 1 · Secure AIOps Observability";
const C = pres.SchemeColor, S = pres.ShapeType;
const W = C.background1;           // white
const A = { blue: C.accent1, red: C.accent2, green: C.accent3, orange: C.accent4, purple: C.accent5, teal: C.accent6 };

pres.defineSlideMaster({ title: "APPLE", background: { color: C.text1 },
  objects: [{ placeholder: { options: { name: "title", type: "title", x: 0.5, y: 0.52, w: 9, h: 0.75, fontSize: 32, bold: true, color: W, margin: 0, valign: "middle", align: "left" }, text: "" } }] });
pres.defineSlideMaster({ title: "HERO", background: { color: C.text1 }, objects: [] });

// ---------- registry (animations, links, transitions) ----------
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

// ---------- drawing helpers ----------
async function iconPng(Comp, hex, px = 256) {
  const svg = RDS.renderToStaticMarkup(React.createElement(Comp, { color: "#" + hex, size: px }));
  return sharp(Buffer.from(svg)).png().toBuffer();
}
const b64 = (buf) => "image/png;base64," + buf.toString("base64");
async function orbPng(hex) {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="400" height="400"><defs><radialGradient id="g"><stop offset="0" stop-color="#${hex}" stop-opacity="0.95"/><stop offset="0.55" stop-color="#${hex}" stop-opacity="0.35"/><stop offset="1" stop-color="#${hex}" stop-opacity="0"/></radialGradient></defs><circle cx="200" cy="200" r="200" fill="url(#g)"/></svg>`;
  return b64(await sharp(Buffer.from(svg)).png().toBuffer());
}
async function ringPng(dots, dashed) {
  const r = 190, pts = dots.map(([deg, hex, rad]) => { const a = (deg * Math.PI) / 180; return `<circle cx="${200 + r * Math.cos(a)}" cy="${200 + r * Math.sin(a)}" r="${rad}" fill="#${hex}"/><circle cx="${200 + r * Math.cos(a)}" cy="${200 + r * Math.sin(a)}" r="${rad * 2.2}" fill="#${hex}" opacity="0.25"/>`; }).join("");
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="400" height="400"><circle cx="200" cy="200" r="${r}" fill="none" stroke="#FFFFFF" stroke-opacity="0.28" stroke-width="2" ${dashed ? 'stroke-dasharray="4 10"' : ""}/>${pts}</svg>`;
  return b64(await sharp(Buffer.from(svg)).png().toBuffer());
}
async function dockTile(Comp, hex, glyph = "FFFFFF") {
  const base = `<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128"><defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#${hex}"/><stop offset="1" stop-color="#${hex}" stop-opacity="0.72"/></linearGradient></defs><rect width="128" height="128" rx="30" fill="url(#g)"/></svg>`;
  const ic = await sharp(await iconPng(Comp, glyph, 256)).resize(62, 62).png().toBuffer();
  return b64(await sharp(Buffer.from(base)).composite([{ input: ic, gravity: "center" }]).png().toBuffer());
}

const glass = (s, x, y, w, h, o = {}) => {
  const name = NM("glass", o);
  s.addShape(S.roundRect, { x, y, w, h, rectRadius: o.r || 0.14, fill: o.tint ? { color: o.tint, transparency: o.ta || 84 } : { color: W, transparency: 92 }, line: { color: o.tint || W, transparency: o.tint ? 55 : 82, width: 1 }, objectName: name });
  return name;
};
const solid = (s, x, y, w, h, color, o = {}) => {
  const name = NM("solid", o);
  s.addShape(o.oval ? S.ellipse : S.roundRect, { x, y, w, h, rectRadius: o.r || 0.12, fill: { color }, line: { type: "none" }, objectName: name });
  return name;
};
const txt = (s, t, o) => {
  const name = NM("text", o);
  const { id, fx, t: _t, click, stat, dur, ...rest } = o;
  s.addText(t, Object.assign({ isTextBox: true, margin: 0, color: W, fontSize: 14, valign: "middle", objectName: name }, rest));
  return name;
};
const pill = (s, t, o) => {
  const name = NM("pill", o);
  const { id, fx, t: _t, click, stat, dur, ...rest } = o;
  s.addText(t, Object.assign({ isTextBox: true, shape: S.roundRect, rectRadius: 0.12, align: "center", valign: "middle", margin: 0.06, color: W, fontSize: 14, bold: true, objectName: name }, rest));
  return name;
};
const arrow = (s, x, y, w, h, color, o = {}) => {
  const name = NM("arrow", Object.assign({ fx: "wipe" }, o));
  s.addShape(S.line, { x, y, w, h, line: { color: color || W, width: 2.25, endArrowType: "triangle", dashType: o.dash }, objectName: name });
  return name;
};
async function sq(s, Comp, x, y, d, color, o = {}) {      // squircle app-icon
  const bg = NM("squircle", Object.assign({ fx: "pop" }, o));
  s.addShape(S.roundRect, { x, y, w: d, h: d, rectRadius: d * 0.26, fill: { color }, line: { type: "none" }, objectName: bg });
  const k = d * 0.5;
  const im = NM("glyph", Object.assign({ fx: "pop" }, o, { id: undefined }));
  s.addImage({ data: b64(await iconPng(Comp, "FFFFFF")), x: x + (d - k) / 2, y: y + (d - k) / 2, w: k, h: k, altText: "icon", objectName: im });
  return [bg, im];
}
const eyebrow = (s, t, color) => txt(s, t, { x: 0.5, y: 0.3, w: 6, h: 0.25, fontSize: 12, bold: true, charSpacing: 3, color, fx: "fade", t: 0 });
const hint = (s, t) => txt(s, t, { x: 6.0, y: 0.3, w: 3.5, h: 0.25, fontSize: 12, align: "right", transparency: 45, fx: "fade", t: 1.2 });

// ---------- ambient orbs (morph targets) ----------
let ORB;
const ORBPOS = {   // per slide: [x,y,w] for A (blue), B (purple), C (teal/pink)
  1: [[-1.4, -1.6, 5.2], [6.0, 1.6, 5.6], [3.2, -2.6, 4.2]],
  2: [[-2.2, 2.0, 5.0], [5.8, -2.0, 6.0], [1.5, 3.6, 4.0]],
  3: [[0.5, -2.4, 5.4], [6.8, 2.6, 5.0], [-2.0, 3.0, 4.4]],
  4: [[6.0, -2.0, 5.2], [-1.8, 2.4, 5.6], [3.6, 3.4, 3.8]],
  5: [[-1.5, -1.8, 5.8], [6.4, 2.2, 5.2], [2.8, 3.8, 3.6]],
  6: [[2.4, -2.6, 5.0], [-2.4, 1.8, 5.4], [6.6, 3.2, 4.6]],
  7: [[6.2, -1.8, 5.4], [-1.6, 3.0, 5.0], [3.0, -3.0, 4.2]],
  8: [[-2.0, 0.0, 5.6], [5.6, 3.0, 5.4], [3.5, -2.8, 4.6]],
  9: [[0.0, -2.8, 6.2], [6.2, -1.0, 5.6], [2.5, 3.4, 4.8]],
};
function orbs(s) {
  const p = ORBPOS[SL], names = ["!!orbA", "!!orbB", "!!orbC"];
  names.forEach((n, i) => s.addImage({ data: ORB[i], x: p[i][0], y: p[i][1], w: p[i][2], h: p[i][2], transparency: 42, altText: "", objectName: n }));
}

// ---------- dock (interactive nav) ----------
let DOCK;
function dock(s) {
  const x0 = 2.55, y0 = 5.04;
  s.addShape(S.roundRect, { x: x0, y: y0, w: 4.9, h: 0.54, rectRadius: 0.2, fill: { color: W, transparency: 88 }, line: { color: W, transparency: 72, width: 1 }, objectName: "dock-bg" });
  DOCK.forEach((d, i) => {
    const nm = `dock-${i + 1}`;
    s.addImage({ data: d.img, x: x0 + 0.2 + i * 0.5, y: y0 + 0.08, w: 0.38, h: 0.38, altText: d.tip, objectName: nm });
    link(nm, i + 1, d.tip);
  });
  s.addShape(S.ellipse, { x: x0 + 0.2 + (SL - 1) * 0.5 + 0.16, y: y0 + 0.47, w: 0.06, h: 0.06, fill: { color: W }, line: { type: "none" }, objectName: "dock-dot" });
}

const NOTES = {
  1: "Hook: monitoring vendors want your data, security teams want to keep it. We keep both happy. Tap the dock to jump anywhere.",
  2: "Three forces collide: logs contain secrets, SaaS AIOps needs data, and shipping raw logs breaks trust. Tap a card to jump to the fix.",
  3: "Tier 1 stays inside the customer network and keeps raw logs. Tier 2 only ever sees allow-listed metadata over HTTPS with a per-collector API key. Packets crossing the line are metadata only.",
  4: "Walk the story: raw line, secrets get redacted, only numbers and pseudonyms leave. Three layers: schema allow-list, regex scrub, outbound scanner that blocks.",
  5: "Persist first, send second. Click to reveal each failure case: offline buffering with backoff, crash recovery with the same payload id, lost ACK handled by dedup.",
  6: "Every API key binds to one tenant, the region must match, and pseudonym keys are per tenant. Tenants never mix.",
  7: "Four health states, z-score anomaly detection against a 15 minute baseline, and incident correlation along the dependency map within 30 seconds.",
  8: "Four builders: collector, SaaS backend, AIOps, frontend and demo. 24 hours in four stages.",
  9: "Click through the four live proofs. Secret in raw but absent on the wire, network cut, duplicate send, delivery check with zero missing and zero duplicates.",
};

(async () => {
  ORB = [await orbPng(BLUE), await orbPng(PURPLE), await orbPng(TEAL)];
  DOCK = [
    { tip: "Home", img: await dockTile(fa.FaHome, BLUE) }, { tip: "Problem", img: await dockTile(fa.FaExclamationTriangle, RED) },
    { tip: "Architecture", img: await dockTile(fa.FaProjectDiagram, INDIGO) }, { tip: "Redaction", img: await dockTile(fa.FaShieldAlt, GREEN) },
    { tip: "Reliability", img: await dockTile(fa.FaSyncAlt, ORANGE) }, { tip: "Tenants", img: await dockTile(fa.FaLayerGroup, "30B0C7") },
    { tip: "AIOps", img: await dockTile(fa.FaBrain, PURPLE) }, { tip: "Team", img: await dockTile(fa.FaUsers, PINK) },
    { tip: "Live demo", img: await dockTile(fa.FaPlay, YELLOW, "1C1C1E") } ];
  const next = (master) => { SL++; entries[SL] = []; cnt = 0; const s = pres.addSlide({ masterName: master }); orbs(s); s.addNotes(NOTES[SL]); return s; };

  // ═════════ 1 · HERO ═════════
  let s = next("HERO");
  transitions[1] = { kind: "fade", xml: "<p:fade/>", dur: 1200 };
  pen(0.2, "fade"); txt(s, "CICADA 2026  ·  PHASE 1", { x: 0.6, y: 1.25, w: 5, h: 0.3, fontSize: 13, bold: true, charSpacing: 4, color: C.accent6 });
  pen(0.5, "rise"); txt(s, "Secure AIOps\nObservability", { x: 0.6, y: 1.6, w: 5.2, h: 1.65, fontSize: 44, bold: true, valign: "top" });
  pen(1.1, "rise");
  txt(s, [{ text: "Cloud-level smarts.", options: { breakLine: true } }, { text: "Zero secrets leaked.", options: { color: C.accent3, bold: true } }], { x: 0.6, y: 3.4, w: 5.2, h: 0.85, fontSize: 22, valign: "top" });
  pen(1.5, "fade"); pill(s, "Problem Understanding & Ideation", { x: 0.6, y: 4.4, w: 3.3, h: 0.38, fontSize: 13, bold: false, fill: { color: W, transparency: 88 }, line: { color: W, transparency: 70, width: 1 } });
  const cx = 7.6, cy = 2.7;
  pen(0.3, "fade");
  const r1 = NM("ring", {}); s.addImage({ data: await ringPng([[0, "0A84FF", 9], [140, "FF375F", 8], [250, "30D158", 8]], true), x: cx - 1.9, y: cy - 1.9, w: 3.8, h: 3.8, altText: "orbit", objectName: r1 });
  const r2 = NM("ring", {}); s.addImage({ data: await ringPng([[60, "FFD60A", 9], [200, "BF5AF2", 8]], false), x: cx - 1.3, y: cy - 1.3, w: 2.6, h: 2.6, altText: "orbit", objectName: r2 });
  loop(r1, "orbit", { dur: 18000, t: 0.3 }); loop(r2, "orbit", { dur: 11000, rev: true, t: 0.3 });
  pen(0.8, "spin");
  const [hb, hg] = await sq(s, fa.FaLock, cx - 0.6, cy - 0.6, 1.2, BLUE);
  loop(hb, "float", { t: 1.6, amp: 0.02 }); loop(hg, "float", { t: 1.6, amp: 0.02 });
  pen(1.8, "pop");
  pill(s, "Tier 1 · raw local", { x: 6.2, y: 4.62, w: 1.6, h: 0.3, fontSize: 12, fill: { color: C.accent6, transparency: 70 }, line: { color: C.accent6, width: 1 } });
  pill(s, "Tier 2 · metadata", { x: 7.9, y: 4.62, w: 1.6, h: 0.3, fontSize: 12, fill: { color: C.accent1, transparency: 70 }, line: { color: C.accent1, width: 1 } });
  pen(2.6, "fade"); txt(s, "Tap the dock to explore", { x: 0.6, y: 4.82, w: 3, h: 0.22, fontSize: 12, transparency: 45 });
  dock(s);

  // ═════════ 2 · PROBLEM ═════════
  s = next("APPLE");
  transitions[2] = { kind: "morph" };
  eyebrow(s, "01 · THE PROBLEM", C.accent2);
  s.addText("Great monitoring, risky data", { placeholder: "title" });
  const probs = [[fa.FaKey, RED, "Logs spill secrets", "Passwords, API keys, tokens and IPs hide in everyday logs.", 4, "Tap to see the fix"], [fa.FaCloud, BLUE, "SaaS needs the data", "Cloud AIOps only spots anomalies if metrics keep flowing.", 3, "Tap to see the idea"], [fa.FaBalanceScale, ORANGE, "A trust gap", "Raw logs at a vendor break security and residency rules.", 6, "Tap to see tenancy"]];
  for (let i = 0; i < 3; i++) {
    const x = 0.5 + i * 3.05, [Ic, col, h, b, to, tap] = probs[i], t0 = 0.4 + i * 0.35;
    pen(t0, "rise");
    const g = glass(s, x, 1.5, 2.9, 2.6); link(g, to, tap);
    await sq(s, Ic, x + 0.25, 1.75, 0.7, col, { t: t0 + 0.2 });
    txt(s, h, { x: x + 0.25, y: 2.65, w: 2.45, h: 0.4, fontSize: 18, bold: true });
    txt(s, b, { x: x + 0.25, y: 3.08, w: 2.45, h: 0.75, valign: "top", transparency: 25 });
    txt(s, tap + "  →", { x: x + 0.25, y: 3.78, w: 2.45, h: 0.25, fontSize: 12, bold: true, color: col === RED ? C.accent2 : col === BLUE ? C.accent1 : C.accent4 });
  }
  pen(1.8, "pop"); pill(s, "The fix: full AIOps insight, zero raw data out.", { x: 0.5, y: 4.3, w: 9, h: 0.55, fontSize: 16, fill: { color: BLUE } });
  dock(s);

  // ═════════ 3 · ARCHITECTURE ═════════
  s = next("APPLE");
  transitions[3] = { kind: "p14", xml: '<p14:ripple dir="center"/>', dur: 1800 };
  eyebrow(s, "02 · THE IDEA", C.accent5); hint(s, "Tap a block to dive in");
  s.addText("Two tiers. One trust boundary.", { placeholder: "title" });
  pen(0.3, "left"); glass(s, 0.4, 1.35, 4.2, 3.05, { tint: TEAL, ta: 88 });
  pen(0.3, "right"); glass(s, 5.4, 1.35, 4.2, 3.05, { tint: BLUE, ta: 88 });
  pen(0.6, "fade"); txt(s, "TIER 1 · CUSTOMER NETWORK", { x: 0.6, y: 1.45, w: 3.8, h: 0.3, fontSize: 12, bold: true, charSpacing: 2, color: C.accent6 });
  txt(s, "TIER 2 · MULTI-TENANT SAAS", { x: 5.6, y: 1.45, w: 3.8, h: 0.3, fontSize: 12, bold: true, charSpacing: 2, color: C.accent1 });
  pen(0.8, "rise");
  let n1 = pill(s, "Servers · DB ·\nnetwork", { x: 0.6, y: 1.95, w: 1.4, h: 0.9, fontSize: 14, fill: { color: W, transparency: 86 }, line: { color: W, transparency: 65, width: 1 } }); link(n1, 2, "Problem");
  arrow(s, 2.03, 2.4, 0.3, 0, W, { t: 1.0 });
  let n2 = pill(s, [{ text: "Collector", options: { bold: true, breakLine: true } }, { text: "raw stays here", options: { fontSize: 13, bold: false } }], { x: 2.35, y: 1.95, w: 2.05, h: 0.9, fontSize: 16, fill: { color: TEAL, transparency: 10 }, color: C.text1, t: 1.1 }); link(n2, 4, "Redaction");
  pill(s, "Local raw store + egress log", { x: 0.6, y: 3.3, w: 3.8, h: 0.7, fontSize: 14, bold: false, fill: { color: W, transparency: 86 }, line: { color: W, transparency: 65, width: 1 }, t: 1.3 });
  const saasBoxes = [["Ingest + dedup", 5, "Reliability"], ["AIOps engine", 7, "AIOps"], ["Dashboard", 9, "Live demo"]];
  saasBoxes.forEach(([t, to, tip], i) => {
    const y = 1.95 + i * 0.75, nmv = pill(s, t, { x: 5.65, y, w: 3.7, h: 0.55, fontSize: 16, fill: { color: BLUE, transparency: 8 }, t: 1.2 + i * 0.25 });
    link(nmv, to, tip);
    if (i < 2) arrow(s, 7.5, y + 0.56, 0, 0.18, W, { t: 1.5 + i * 0.25 });
  });
  const bd = NM("boundary", { fx: "wipeup", t: 0.9, dur: 900 });
  s.addShape(S.line, { x: 5.0, y: 1.25, w: 0, h: 3.3, line: { color: RED, width: 2.5, dashType: "dash" }, objectName: bd });
  pen(1.6, "pop"); const [lk1, lk2] = await sq(s, fa.FaLock, 4.76, 2.85, 0.48, RED);
  loop(lk1, "pulse", { t: 2.2, dur: 700 }); loop(lk2, "pulse", { t: 2.2, dur: 700 });
  for (let i = 0; i < 3; i++) {       // metadata packets crossing the boundary
    const pk = NM("packet", { stat: true });
    s.addShape(S.ellipse, { x: 4.45, y: 2.32, w: 0.16, h: 0.16, fill: { color: GREEN }, line: { color: W, width: 0.75 }, objectName: pk });
    loop(pk, "packet", { t: 2.2 + i * 0.6, dx: 0.125, dur: 1800 });
  }
  pen(1.9, "rise"); pill(s, "HTTPS + per-collector API key · allow-listed metadata only", { x: 1.45, y: 4.52, w: 7.1, h: 0.36, fontSize: 13, fill: { color: RED, transparency: 80 }, line: { color: RED, width: 1 } });
  dock(s);

  // ═════════ 4 · REDACTION ═════════
  s = next("APPLE");
  transitions[4] = { kind: "morph" };
  eyebrow(s, "03 · REDACTION", C.accent3);
  s.addText("Numbers go out. Secrets don't.", { placeholder: "title" });
  pen(0.3, "left"); glass(s, 0.5, 1.4, 3.7, 2.3, { tint: RED, ta: 88 });
  pen(0.3, "fade"); txt(s, "RAW · STAYS ON CUSTOMER SIDE", { x: 0.7, y: 1.5, w: 3.4, h: 0.28, fontSize: 12, bold: true, charSpacing: 1, color: C.accent2 });
  const MONO = { fontFace: "Courier New", fontSize: 12, halign: "left", align: "left" };
  const raw = ["deploy password=Summer@2026", "token=ghp_FAKE1234 user=root", "from 192.168.1.50", "host prod-db-01.corp.local"];
  raw.forEach((l, i) => { pen(0.7 + i * 0.25, "wipe"); txt(s, l, Object.assign({ x: 0.7, y: 1.95 + i * 0.3, w: 3.4, h: 0.25 }, MONO)); });
  const secrets = [[7, 20], [6, 12], [5, 12], [5, 21]];
  secrets.forEach(([c0, len], i) => { pen(2.4 + i * 0.35, "wipe"); solid(s, 0.7 + c0 * 0.1 - 0.02, 1.945 + i * 0.3, len * 0.1 + 0.04, 0.26, RED, { r: 0.05, dur: 350 }); });
  pen(2.2, "pop"); await sq(s, fa.FaShieldAlt, 4.6, 2.3, 0.8, GREEN);
  pen(2.0, "wipe"); arrow(s, 4.22, 2.7, 0.34, 0, C.accent3); arrow(s, 5.44, 2.7, 0.34, 0, C.accent3, { t: 3.6 });
  pen(3.7, "right"); glass(s, 5.8, 1.4, 3.7, 2.3, { tint: GREEN, ta: 88 });
  pen(3.7, "fade"); txt(s, "OUTBOUND · WHAT IS SENT", { x: 6.0, y: 1.5, w: 3.4, h: 0.28, fontSize: 12, bold: true, charSpacing: 1, color: C.accent3 });
  ['{"node": "n-b7cd652869",', ' "cpu": 40.0,', ' "latency_ms": 20.0,', ' "auth_failures_60s": 12,', ' "severity": "critical"}'].forEach((l, i) => { pen(4.0 + i * 0.25, "wipe"); txt(s, l, Object.assign({ x: 6.0, y: 1.95 + i * 0.3, w: 3.4, h: 0.25 }, MONO)); });
  [["1", "Schema allow-list", BLUE], ["2", "Regex scrub", PURPLE], ["3", "Outbound scanner: BLOCK", PINK]].forEach(([k, t, col], i) => {
    const x = 0.5 + i * 3.05; pen(5.0 + i * 0.25, "rise");
    glass(s, x, 3.95, 2.9, 0.62); solid(s, x + 0.15, 4.08, 0.36, 0.36, col, { oval: true });
    txt(s, k, { x: x + 0.15, y: 4.08, w: 0.36, h: 0.36, align: "center", bold: true });
    txt(s, t, { x: x + 0.65, y: 3.95, w: 2.2, h: 0.62, fontSize: 14, bold: true });
  });
  pen(5.8, "fade"); txt(s, "Any hit in layer 3 means the payload is blocked and never sent.", { x: 0.5, y: 4.65, w: 8, h: 0.25, fontSize: 12, transparency: 35 });
  dock(s);

  // ═════════ 5 · RELIABILITY ═════════
  s = next("APPLE");
  transitions[5] = { kind: "morph" };
  eyebrow(s, "04 · NEVER LOSE DATA", C.accent4);
  s.addText("Save first. Send second.", { placeholder: "title" });
  const stepsD = [["1 · Persist", "local outbox first", BLUE], ["2 · Send", "HTTPS batch", INDIGO], ["3 · Dedup", "SaaS dedups by ID", PURPLE], ["4 · ACK", "then mark delivered", GREEN]];
  stepsD.forEach(([a, b, col], i) => {
    const x = 0.5 + i * 2.333; pen(0.3 + i * 0.35, "pop");
    pill(s, [{ text: a, options: { bold: true, fontSize: 18, breakLine: true } }, { text: b, options: { fontSize: 14, bold: false } }], { x, y: 1.5, w: 2.0, h: 0.95, fill: { color: col, transparency: 5 } });
    if (i < 3) arrow(s, x + 2.02, 1.975, 0.3, 0, W, { t: 0.5 + i * 0.35 });
  });
  const pkt = NM("packet", { stat: true });
  s.addShape(S.ellipse, { x: 1.4, y: 2.62, w: 0.2, h: 0.2, fill: { color: YELLOW }, line: { color: W, width: 0.75 }, objectName: pkt });
  s.addShape(S.line, { x: 1.5, y: 2.72, w: 7.0, h: 0, line: { color: W, transparency: 70, width: 1, dashType: "dash" }, objectName: "track" });
  loop(pkt, "packet", { t: 1.8, dx: 0.7, dur: 3600 });
  const rel = [[fa.FaWifi, ORANGE, "Offline?", "Buffer locally, then retry at 1, 2, 4, 5 s intervals."], [fa.FaPowerOff, BLUE, "Crash?", "Same payload_id is re-sent, never duplicated."], [fa.FaCopy, PURPLE, "Lost ACK?", "Duplicate is acknowledged, stored once."]];
  for (let i = 0; i < 3; i++) {
    const x = 0.5 + i * 3.05, [Ic, col, h, b] = rel[i]; pen(0, "pop", i + 1);
    glass(s, x, 3.05, 2.9, 1.75); await sq(s, Ic, x + 0.2, 3.25, 0.55, col, { fx: "pop" });
    txt(s, h, { x: x + 0.9, y: 3.25, w: 1.9, h: 0.55, fontSize: 18, bold: true });
    txt(s, b, { x: x + 0.2, y: 3.92, w: 2.5, h: 0.8, valign: "top", transparency: 20 });
  }
  pen(1.2, "fade"); txt(s, "Click to reveal each failure case", { x: 6.0, y: 0.3, w: 3.5, h: 0.25, fontSize: 12, align: "right", transparency: 45 });
  dock(s);

  // ═════════ 6 · TENANTS ═════════
  s = next("APPLE");
  transitions[6] = { kind: "morph" };
  eyebrow(s, "05 · MULTI-TENANT", C.accent6);
  s.addText("Your tenant. Your lane.", { placeholder: "title" });
  [["Tenant Alpha", "IN", "col-alpha-01", "India data store", TEAL, "left"], ["Tenant Beta", "EU", "col-beta-01", "EU data store", INDIGO, "right"]].forEach(([t, r, c, d, col, side], i) => {
    const x = 0.5 + i * 4.85; pen(0.3, side);
    glass(s, x, 1.4, 4.15, 2.3, { tint: col, ta: 88 });
    txt(s, t, { x: x + 0.25, y: 1.5, w: 2.5, h: 0.4, fontSize: 18, bold: true });
    pill(s, "Region " + r, { x: x + 2.7, y: 1.55, w: 1.2, h: 0.3, fontSize: 12, fill: { color: col, transparency: 10 }, color: C.text1 });
    pen(0.9, "pop"); pill(s, c, { x: x + 0.7, y: 2.1, w: 2.75, h: 0.5, fill: { color: col, transparency: 10 }, color: C.text1 });
    arrow(s, x + 2.07, 2.62, 0, 0.3, W, { t: 1.2 });
    pen(1.4, "pop"); pill(s, d, { x: x + 0.7, y: 2.95, w: 2.75, h: 0.5, fill: { color: W, transparency: 88 }, line: { color: col, width: 1.5 } });
  });
  const wall = NM("wall", { fx: "wipeup", t: 0.6, dur: 800 });
  s.addShape(S.line, { x: 5.0, y: 1.3, w: 0, h: 2.5, line: { color: RED, width: 2.5, dashType: "dash" }, objectName: wall });
  pen(1.6, "pop"); const [w1, w2] = await sq(s, fa.FaLock, 4.76, 2.35, 0.48, RED);
  loop(w1, "pulse", { t: 2.2, dur: 800 }); loop(w2, "pulse", { t: 2.2, dur: 800 });
  [["API key", "binds to one tenant", BLUE], ["Wrong region", "payload rejected", ORANGE], ["Pseudonym key", "unique per tenant", PURPLE]].forEach(([a, b, col], i) => {
    pen(2.0 + i * 0.3, "rise");
    const x = 0.5 + i * 3.05; glass(s, x, 3.95, 2.9, 0.8); solid(s, x + 0.15, 4.12, 0.46, 0.46, col, { oval: true });
    txt(s, [{ text: a, options: { bold: true, breakLine: true } }, { text: b, options: { fontSize: 13, transparency: 25 } }], { x: x + 0.75, y: 3.95, w: 2.1, h: 0.8, fontSize: 14 });
  });
  dock(s);

  // ═════════ 7 · AIOPS ═════════
  s = next("APPLE");
  transitions[7] = { kind: "p14", xml: '<p14:vortex dir="r"/>', dur: 1800 };
  eyebrow(s, "06 · AIOPS", C.accent5);
  s.addText("Spot it. Link it. Explain it.", { placeholder: "title" });
  [["Excellent", "all normal", GREEN], ["Good", "minor drift", BLUE], ["Fair", "5+ failed / 60 s", ORANGE], ["Poor", "10+ failed / 60 s", RED]].forEach(([a, b, col], i) => {
    pen(0.3 + i * 0.25, "pop"); const x = 0.5 + i * 2.3;
    glass(s, x, 1.4, 2.15, 0.85, { tint: col, ta: 82 }); solid(s, x + 0.15, 1.7, 0.24, 0.24, col, { oval: true });
    txt(s, [{ text: a, options: { bold: true, fontSize: 16, breakLine: true } }, { text: b, options: { fontSize: 12, transparency: 20 } }], { x: x + 0.5, y: 1.4, w: 1.6, h: 0.85 });
  });
  pen(1.4, "left"); glass(s, 0.5, 2.5, 4.3, 2.35);
  pen(1.6, "fade"); await sq(s, fa.FaChartLine, 0.7, 2.62, 0.45, BLUE, { fx: "pop" });
  txt(s, "Anomaly detection", { x: 1.3, y: 2.62, w: 3.3, h: 0.45, fontSize: 18, bold: true });
  const sig = [41, 43, 40, 42, 44, 41, 43, 42, 45, 43, 44, 88, 92, 46, 43, 42];
  pen(1.9, "wipe");
  const chn = NM("chart-spark", {});
  s.addChart(pres.charts.LINE, [{ name: "z-score signal", labels: sig.map((_, i) => String(i)), values: sig }, { name: "3σ threshold", labels: sig.map((_, i) => String(i)), values: sig.map(() => 66) }],
    { x: 0.6, y: 3.12, w: 4.1, h: 1.3, chartColors: [BLUE, ORANGE], lineSize: 3, lineDataSymbol: "none", catAxisHidden: true, valAxisHidden: true, valGridLine: { style: "none" }, catGridLine: { style: "none" }, showLegend: false, valAxisMinVal: 20, valAxisMaxVal: 100, objectName: chn });
  pen(2.3, "pop"); pill(s, "z = 4.2", { x: 3.3, y: 3.1, w: 0.8, h: 0.28, fontSize: 12, fill: { color: RED } });
  pen(2.4, "fade"); txt(s, "z > 3 vs a 15-minute baseline = flagged", { x: 0.7, y: 4.48, w: 4.0, h: 0.28, fontSize: 13, transparency: 20 });
  pen(1.6, "right"); glass(s, 5.2, 2.5, 4.3, 2.35);
  pen(1.8, "fade"); await sq(s, fa.FaProjectDiagram, 5.4, 2.62, 0.45, PURPLE, { fx: "pop" });
  txt(s, "Incident correlation", { x: 6.0, y: 2.62, w: 3.3, h: 0.45, fontSize: 18, bold: true });
  ["app-01", "db-01", "net-01"].forEach((t, i) => {
    pen(2.2 + i * 0.35, "pop"); const rc = i === 2;
    const nmv = pill(s, t, { x: 5.45 + i * 1.3, y: 3.3, w: 0.95, h: 0.45, fill: { color: rc ? RED : W, transparency: rc ? 0 : 82 }, line: rc ? undefined : { color: W, transparency: 60, width: 1 } });
    if (rc) loop(nmv, "pulse", { t: 3.4, dur: 700, by: 110000 });
    if (i < 2) arrow(s, 6.42 + i * 1.3, 3.525, 0.3, 0, W, { t: 2.4 + i * 0.35 });
  });
  pen(3.0, "fade"); txt(s, "root cause", { x: 7.95, y: 3.78, w: 1.0, h: 0.22, fontSize: 12, bold: true, color: C.accent2, align: "center" });
  txt(s, "Alerts within 30 s follow the dependency map into one incident.", { x: 5.45, y: 4.1, w: 3.8, h: 0.65, valign: "top", transparency: 20 });
  dock(s);

  // ═════════ 8 · TEAM ═════════
  s = next("APPLE");
  transitions[8] = { kind: "morph" };
  eyebrow(s, "07 · TEAM", C.accent4);
  s.addText("Four builders. 24 hours.", { placeholder: "title" });
  [["P1", "Collector", "Tier 1, redaction, outbox", TEAL], ["P2", "SaaS backend", "Ingest, dedup, tenants", BLUE], ["P3", "AIOps", "Health, anomalies, fixes", PURPLE], ["P4", "Frontend + demo", "Dashboard, story", PINK]].forEach(([p, r, d, col], i) => {
    const x = 0.5 + i * 2.3; pen(0.3 + i * 0.3, "rise");
    glass(s, x, 1.4, 2.15, 1.85); solid(s, x + 0.2, 1.58, 0.62, 0.62, col, { oval: true });
    txt(s, p, { x: x + 0.2, y: 1.58, w: 0.62, h: 0.62, fontSize: 16, bold: true, align: "center", color: p === "P1" ? C.text1 : W });
    txt(s, r, { x: x + 0.2, y: 2.3, w: 1.85, h: 0.32, fontSize: 16, bold: true });
    txt(s, d, { x: x + 0.2, y: 2.62, w: 1.85, h: 0.55, valign: "top", transparency: 25 });
  });
  pen(1.6, "fade"); txt(s, "THE 24-HOUR PLAN", { x: 0.5, y: 3.5, w: 6, h: 0.25, fontSize: 12, bold: true, charSpacing: 2, color: C.accent4 });
  [["0–4 h", "Contracts, scaffold", 1.8, TEAL], ["4–12 h", "Core build", 3.0, BLUE], ["12–20 h", "Integrate, demo runs", 3.0, PURPLE], ["20–24 h", "Polish", 1.2, GREEN]].reduce((x, [h, t, w, col], i) => {
    pen(1.9 + i * 0.6, "wipe"); const nm = pill(s, [{ text: h, options: { bold: true, breakLine: true } }, { text: t, options: { fontSize: 13, bold: false } }], { x, y: 3.85, w: w - 0.06, h: 0.9, fontSize: 14, fill: { color: col, transparency: 8 }, color: col === TEAL || col === GREEN ? C.text1 : W, dur: 700 });
    return x + w;
  }, 0.5);
  dock(s);

  // ═════════ 9 · PROOF ═════════
  s = next("APPLE");
  transitions[9] = { kind: "p14", xml: '<p14:glitter pattern="hexagon" dir="r"/>', dur: 1800 };
  eyebrow(s, "08 · THE DEMO", C.accent3); hint(s, "Click to reveal each proof");
  s.addText("Watch us prove it live", { placeholder: "title" });
  const proofs = [[fa.FaEyeSlash, RED, "Secrets stay home", "Visible in raw, never on the wire"], [fa.FaPlug, ORANGE, "Cut the network", "Buffered locally, delivered after"], [fa.FaCopy, PURPLE, "Send a duplicate", "Stored once, acknowledged"], [fa.FaCheckDouble, GREEN, "Delivery check", "0 missing, 0 duplicates, hashes match"]];
  for (let i = 0; i < 4; i++) {
    const x = 0.5 + (i % 2) * 4.6, y = 1.4 + Math.floor(i / 2) * 1.45, [Ic, col, h, b] = proofs[i];
    pen(0, "pop", i + 1);
    glass(s, x, y, 4.4, 1.3, { tint: col, ta: 86 }); await sq(s, Ic, x + 0.25, y + 0.3, 0.7, col, { fx: "pop" });
    txt(s, h, { x: x + 1.15, y: y + 0.22, w: 3.1, h: 0.45, fontSize: 16, bold: true });
    txt(s, b, { x: x + 1.15, y: y + 0.68, w: 3.1, h: 0.4, valign: "top", transparency: 25 });
  }
  pen(0, "rise", 5); txt(s, "Cloud intelligence. Zero raw data leaving the customer.", { x: 0.5, y: 4.3, w: 9, h: 0.5, fontSize: 20, bold: true, align: "center", color: C.accent3 });
  dock(s);

  const file = "CICADA2026_Phase1_Interactive.pptx";
  await pres.writeFile({ fileName: file });
  await inject(file, { entries, transitions, links });
  await applyTheme(file, THEME);
  console.log("built", file);
})();
