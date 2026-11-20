  // ═════════ 10 · EXPLAINABLE AIOPS ═════════
  s = next("APPLE");
  transitions[SL] = { kind: "p14", xml: '<p14:flip dir="l"/>', dur: 1500 };
  eyebrow(s, "09 · EXPLAINABLE AIOPS", C.accent5); hint(s, "Weighted higher by the judges");
  s.addText("Why flagged. Which signals. Why this action.", { placeholder: "title" });
  pen(0.3, "left"); glass(s, 0.5, 1.4, 4.5, 3.45);
  pen(0.5, "fade");
  txt(s, "Incident A-102 · db-01", { x: 0.7, y: 1.5, w: 2.9, h: 0.4, fontSize: 16, bold: true });
  pill(s, "POOR", { x: 4.0, y: 1.53, w: 0.8, h: 0.32, fontSize: 12, fill: { color: RED } });
  txt(s, "Weighted risk score 0.82 (illustrative)", { x: 0.7, y: 1.95, w: 4.0, h: 0.28, fontSize: 12, transparency: 30 });
  [["db-01 CPU   z = 4.2", "35%", 0.35, RED], ["net-01 latency   z = 3.6", "25%", 0.25, ORANGE], ["Failed logins   12 / 60 s", "25%", 0.25, PURPLE], ["Packet loss   3.1%", "15%", 0.15, BLUE]].forEach(([l, p, wgt, col], i) => {
    const y = 2.4 + i * 0.6; pen(0.9 + i * 0.3, "fade");
    txt(s, l, { x: 0.7, y, w: 3.0, h: 0.26, fontSize: 13 }); txt(s, p, { x: 3.9, y, w: 0.8, h: 0.26, fontSize: 13, bold: true, align: "right" });
    s.addShape(S.roundRect, { x: 0.7, y: y + 0.3, w: 4.0, h: 0.13, rectRadius: 0.06, fill: { color: W, transparency: 85 }, line: { type: "none" }, objectName: NM("track", { stat: true }) });
    pen(1.1 + i * 0.3, "wipe"); solid(s, 0.7, y + 0.3, (4.0 * wgt) / 0.4, 0.13, col, { r: 0.06, dur: 700 });
  });
  [[fa.FaQuestion, BLUE, "Why flagged", "Two signals crossed z > 3 inside one 30 s window."], [fa.FaSignal, PURPLE, "Which signals", "db-01 CPU, net-01 latency and 12 failed logins."], [fa.FaBolt, ORANGE, "Why this action", "The dependency map points at net-01 first: throttle the source, then page on-call."]].forEach(([Ic, col, h, b], i) => {
    const y = 1.4 + i * 1.05; pen(1.6 + i * 0.5, "right"); glass(s, 5.2, y, 4.3, 0.95);
    sq(s, Ic, 5.35, y + 0.25, 0.45, col, { t: 1.8 + i * 0.5 });
    txt(s, h, { x: 5.95, y: y + 0.06, w: 3.4, h: 0.3, fontSize: 14, bold: true, color: col === BLUE ? C.accent1 : col === PURPLE ? C.accent5 : C.accent4 });
    txt(s, b, { x: 5.95, y: y + 0.36, w: 3.45, h: 0.55, fontSize: 12, valign: "top", transparency: 15 });
  });
  pen(3.0, "fade"); txt(s, "Narration is template-based; an optional LLM only ever sees allow-listed metadata.", { x: 5.2, y: 4.5, w: 4.3, h: 0.4, fontSize: 12, valign: "top", transparency: 30 });
  dock(s);

  // ═════════ 11 · REAL-TIME + GLOBAL ═════════
  s = next("APPLE");
  transitions[SL] = { kind: "morph" };
  eyebrow(s, "10 · REAL-TIME & GLOBAL", C.accent4);
  s.addText("Fast, correct, worldwide", { placeholder: "title" });
  [["≤ 10 s", "event to dashboard", BLUE], ["≤ 15 s", "event to alert", ORANGE], ["≤ 60 s", "offline detected (we alert at 30 s)", PURPLE], ["0", "payloads lost or duplicated", GREEN]].forEach(([n, l, col], i) => {
    const x = 0.5 + (i % 2) * 2.25, y = 1.4 + Math.floor(i / 2) * 1.75; pen(0.3 + i * 0.3, "pop");
    glass(s, x, y, 2.1, 1.6, { tint: col, ta: 86 });
    txt(s, n, { x: x + 0.15, y: y + 0.15, w: 1.8, h: 0.7, fontSize: 34, bold: true, color: col === BLUE ? C.accent1 : col === ORANGE ? C.accent4 : col === PURPLE ? C.accent5 : C.accent3 });
    txt(s, l, { x: x + 0.15, y: y + 0.9, w: 1.8, h: 0.6, fontSize: 13, valign: "top", transparency: 15 });
  });
  pen(0.6, "right"); glass(s, 5.1, 1.4, 4.4, 3.35);
  pen(0.9, "fade"); txt(s, "GLOBAL-READY", { x: 5.35, y: 1.5, w: 3.5, h: 0.28, fontSize: 12, bold: true, charSpacing: 2, color: C.accent6 });
  [["Regional ingest", "IN and EU stores, never mixed"], ["UTC everywhere", "local timezone for display only"], ["Out-of-order safe", "event-time windows, late-safe"], ["Idempotent", "payload_id dedup, safe retries"]].forEach(([h, b], i) => {
    const y = 1.95 + i * 0.7; pen(1.1 + i * 0.3, "rise");
    solid(s, 5.35, y + 0.08, 0.4, 0.4, GREEN, { oval: true });
    txt(s, "✓", { x: 5.35, y: y + 0.08, w: 0.4, h: 0.4, fontSize: 16, bold: true, align: "center" });
    txt(s, h, { x: 5.95, y, w: 3.4, h: 0.3, fontSize: 14, bold: true });
    txt(s, b, { x: 5.95, y: y + 0.3, w: 3.4, h: 0.28, fontSize: 13, transparency: 25 });
  });
  dock(s);

  // ═════════ 12 · TECH STACK ═════════
  s = next("APPLE");
  transitions[SL] = { kind: "p14", xml: '<p14:doors dir="vert"/>', dur: 1500 };
  eyebrow(s, "11 · TECH STACK", C.accent1); hint(s, "Proposed stack");
  s.addText("Lean tools, strong guarantees", { placeholder: "title" });
  const stack = [[fa.FaServer, TEAL, "Collector", ["Python 3.12", "FastAPI", "SQLite WAL", "httpx", "pydantic v2"]], [fa.FaShieldAlt, GREEN, "Privacy", ["HMAC-SHA256", "Regex scanners", "Allow-list schema"]],
    [fa.FaCloud, BLUE, "SaaS", ["FastAPI", "SQLite per region", "API-key auth", "TLS"]], [fa.FaBrain, PURPLE, "AIOps", ["NumPy stats", "z-score + EWMA", "Dependency graph", "Rules + explainer"]],
    [fa.FaDesktop, INDIGO, "Frontend", ["React", "Recharts", "Live updates (SSE)"]], [fa.FaCheckDouble, ORANGE, "Quality", ["pytest", "Docker Compose", "mkcert TLS"]]];
  for (let i = 0; i < 6; i++) {
    const [Ic, col, h, chips] = stack[i], y = 1.4 + i * 0.58;
    pen(0.3 + i * 0.3, "left"); glass(s, 0.5, y, 9, 0.5);
    await sq(s, Ic, 0.6, y + 0.07, 0.36, col, { t: 0.45 + i * 0.3 });
    txt(s, h, { x: 1.1, y, w: 1.3, h: 0.5, fontSize: 14, bold: true });
    let cx = 2.5;
    chips.forEach((c, j) => { const w = c.length * 0.085 + 0.3; pen(0.7 + i * 0.3 + j * 0.1, "pop"); pill(s, c, { x: cx, y: y + 0.1, w, h: 0.3, fontSize: 12, bold: false, fill: { color: col, transparency: 72 }, line: { color: col, width: 1 } }); cx += w + 0.1; });
  }
  dock(s);

  // ═════════ 13 · METHODOLOGY ═════════
  s = next("APPLE");
  transitions[SL] = { kind: "morph" };
  eyebrow(s, "12 · METHODOLOGY", C.accent3);
  s.addText("How we build in 24 hours", { placeholder: "title" });
  [["Contract-first", "schemas before code", BLUE], ["Vertical slices", "end-to-end early", PURPLE], ["Test as we go", "tests gate every merge", GREEN], ["Demo-driven", "scripted live scenarios", ORANGE], ["Freeze + polish", "no new features at the end", PINK]].forEach(([a, b, col], i) => {
    const x = 0.5 + i * 1.845; pen(0.3 + i * 0.3, "pop");
    pill(s, [{ text: a, options: { bold: true, fontSize: 14, breakLine: true } }, { text: b, options: { fontSize: 12, bold: false } }], { x, y: 1.4, w: 1.62, h: 0.95, fill: { color: col, transparency: 8 }, color: col === GREEN ? C.text1 : W });
    if (i < 4) arrow(s, x + 1.63, 1.875, 0.2, 0, W, { t: 0.5 + i * 0.3 });
  });
  [["Ground rules", BLUE, ["Shared schema, tenants, thresholds", "One owner per module, hourly merges", "Simulated stream before real sources", "Mock SaaS keeps every role unblocked"], 0.5, "left"], ["Definition of done", GREEN, ["Tests green on every module", "Privacy scan: no secret on the wire", "Delivery check: 0 missing, 0 dupes", "Demo scenario scripted and rehearsed"], 5.1, "right"]].forEach(([h, col, rows, x, side]) => {
    pen(1.8, side); glass(s, x, 2.6, 4.4, 2.25);
    pen(2.0, "fade"); txt(s, h, { x: x + 0.25, y: 2.7, w: 3.5, h: 0.4, fontSize: 16, bold: true, color: col === BLUE ? C.accent1 : C.accent3 });
    rows.forEach((r, i) => { pen(2.2 + i * 0.25, "rise"); solid(s, x + 0.25, 3.3 + i * 0.38 + 0.08, 0.12, 0.12, col, { oval: true }); txt(s, r, { x: x + 0.5, y: 3.3 + i * 0.38, w: 3.8, h: 0.3, fontSize: 13 }); });
  });
  dock(s);

  // ═════════ 14 · BUILT TO SCORE ═════════
  s = next("APPLE");
  transitions[SL] = { kind: "p14", xml: '<p14:ferris dir="r"/>', dur: 1500 };
  eyebrow(s, "13 · BUILT TO SCORE", C.accent4); hint(s, "Criteria covered by design");
  s.addText("Every tick has a feature", { placeholder: "title" });
  [["7/7", "Phase 1", "Problem & ideation", TEAL], ["6/6", "Phase 2", "Architecture & design", BLUE], ["6/6", "Phase 3", "Working prototype", PURPLE], ["5/5", "Phase 4", "Demo & validation", PINK]].forEach(([n, a, b, col], i) => {
    const x = 0.5 + i * 2.3; pen(0.3 + i * 0.3, "pop"); glass(s, x, 1.4, 2.15, 1.45, { tint: col, ta: 86 });
    txt(s, n, { x: x + 0.2, y: 1.5, w: 1.8, h: 0.65, fontSize: 32, bold: true });
    txt(s, a, { x: x + 0.2, y: 2.15, w: 1.8, h: 0.3, fontSize: 14, bold: true });
    txt(s, b, { x: x + 0.2, y: 2.45, w: 1.85, h: 0.3, fontSize: 12, transparency: 20 });
  });
  const rowsS = [["MANDATORY", GREEN, ["Real-time from timestamps", "Shared organiser stream", "Egress proof panel"], 3.1], ["BONUS", PURPLE, ["Privacy pipeline", "Local buffering", "Explainable AIOps"], 3.7], ["", PURPLE, ["Alert-noise reduction", "Safe remediation", "Global-ready delivery"], 4.2]];
  rowsS.forEach(([lab, col, chips, y]) => {
    pen(1.6, "fade"); if (lab) txt(s, lab, { x: 0.5, y, w: 1.4, h: 0.4, fontSize: 12, bold: true, charSpacing: 2, color: col === GREEN ? C.accent3 : C.accent5 });
    chips.forEach((c, j) => { pen(1.7 + j * 0.2, "pop"); pill(s, c, { x: 2.0 + j * 2.5, y, w: 2.35, h: 0.4, fontSize: 13, bold: false, fill: { color: col, transparency: 75 }, line: { color: col, width: 1 } }); });
  });
  dock(s);

  // ═════════ 15 · LIMITS + ROADMAP ═════════
  s = next("APPLE");
  transitions[SL] = { kind: "morph" };
  eyebrow(s, "14 · HONEST LIMITS", C.accent2);
  s.addText("What it can't do yet", { placeholder: "title" });
  pen(0.3, "left"); glass(s, 0.5, 1.4, 4.4, 3.45);
  pen(0.5, "fade"); txt(s, "LIMITATIONS", { x: 0.75, y: 1.5, w: 3.5, h: 0.28, fontSize: 12, bold: true, charSpacing: 2, color: C.accent4 });
  ["Simulated telemetry, not a live fleet", "Baselines need about 15 min to warm up", "Single-node SQLite, not horizontally scaled", "Remediation is advisory and approval-gated"].forEach((t, i) => {
    const y = 1.95 + i * 0.7; pen(0.7 + i * 0.3, "rise");
    solid(s, 0.75, y + 0.1, 0.4, 0.4, ORANGE, { oval: true }); txt(s, "!", { x: 0.75, y: y + 0.1, w: 0.4, h: 0.4, fontSize: 18, bold: true, align: "center" });
    txt(s, t, { x: 1.35, y, w: 3.4, h: 0.6, fontSize: 14 });
  });
  pen(0.3, "right"); glass(s, 5.1, 1.4, 4.4, 3.45);
  pen(0.5, "fade"); txt(s, "ROADMAP", { x: 5.35, y: 1.5, w: 3.5, h: 0.28, fontSize: 12, bold: true, charSpacing: 2, color: C.accent6 });
  s.addShape(S.line, { x: 5.5, y: 2.1, w: 0, h: 2.35, line: { color: W, transparency: 65, width: 2 }, objectName: "road" });
  [["Now", "Privacy-first MVP", GREEN], ["Next", "OpenTelemetry-compatible agents", BLUE], ["Then", "Postgres and a message queue", PURPLE], ["Later", "Cross-tenant learning without raw data", PINK]].forEach(([a, b, col], i) => {
    const y = 1.95 + i * 0.7; pen(0.8 + i * 0.35, "pop");
    solid(s, 5.39, y + 0.12, 0.22, 0.22, col, { oval: true });
    pen(0.9 + i * 0.35, "rise"); txt(s, [{ text: a, options: { bold: true, breakLine: true, color: col === GREEN ? C.accent3 : col === BLUE ? C.accent1 : col === PURPLE ? C.accent5 : C.text1 } }, { text: b, options: { fontSize: 13 } }], { x: 5.85, y, w: 3.5, h: 0.6, fontSize: 14, valign: "top" });
  });
  dock(s);
