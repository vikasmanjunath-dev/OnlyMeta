  // ═════════ 7 · FEATURES ═════════
  s = next("APPLE");
  transitions[SL] = { kind: "morph" };
  eyebrow(s, "06 · FEATURES", C.accent1); hint(s, "Tap a tile to jump");
  s.addText("Everything the platform does", { placeholder: "title" });
  const feats = [[fa.FaServer, TEAL, "Local collector", "Reads the stream, filters, redacts, buffers and proves egress.", 3], [fa.FaShieldAlt, GREEN, "Privacy pipeline", "Allow-list, scrub, scan and HMAC pseudonyms.", 4],
    [fa.FaTachometerAlt, BLUE, "Rich telemetry", "CPU, memory, disk, bandwidth, latency, packet loss.", 5], [fa.FaBrain, PURPLE, "AIOps brain", "Baselines, anomalies and incident correlation.", 9],
    [fa.FaDesktop, INDIGO, "Live dashboard", "Four health states, alerts and tenant views.", 17], [fa.FaWrench, ORANGE, "Safe remediation", "Policy, approval gate and audit trail.", 10]];
  for (let i = 0; i < 6; i++) {
    const [Ic, col, h, b, to] = feats[i], x = 0.5 + (i % 3) * 3.05, y = 1.4 + Math.floor(i / 3) * 1.6, t0 = 0.3 + i * 0.25;
    pen(t0, "rise"); const g = glass(s, x, y, 2.9, 1.45); link(g, to, h);
    await sq(s, Ic, x + 0.2, y + 0.18, 0.5, col, { t: t0 + 0.15 });
    txt(s, h, { x: x + 0.85, y: y + 0.18, w: 1.95, h: 0.5, fontSize: 16, bold: true });
    txt(s, b, { x: x + 0.2, y: y + 0.76, w: 2.5, h: 0.62, fontSize: 13, valign: "top", transparency: 20 });
  }
  pen(2.2, "fade"); txt(s, "Every tick on the evaluation sheet has a feature behind it.", { x: 0.5, y: 4.62, w: 9, h: 0.25, fontSize: 12, transparency: 30 });
  dock(s);

  // ═════════ 8 · APPROACH ═════════
  s = next("APPLE");
  transitions[SL] = { kind: "p14", xml: '<p14:pan dir="r"/>', dur: 1500 };
  eyebrow(s, "07 · APPROACH", C.accent6);
  s.addText("From raw stream to safe action", { placeholder: "title" });
  pen(0.2, "fade");
  pill(s, "TIER 1 · LOCAL", { x: 0.5, y: 1.4, w: 4.38, h: 0.32, fontSize: 12, charSpacing: 2, fill: { color: TEAL, transparency: 75 }, line: { color: TEAL, width: 1 } });
  pill(s, "TIER 2 · SAAS", { x: 5.12, y: 1.4, w: 4.38, h: 0.32, fontSize: 12, charSpacing: 2, fill: { color: BLUE, transparency: 75 }, line: { color: BLUE, width: 1 } });
  const stages = [[fa.FaFileAlt, TEAL, "Collect", "Read the stream"], [fa.FaFilter, GREEN, "Filter + redact", "Allow-list, scrub, scan"], [fa.FaClock, BLUE, "Aggregate", "5 s windows per node"],
    [fa.FaBrain, PURPLE, "Analyse", "Baselines, z-score, graph"], [fa.FaBalanceScale, ORANGE, "Policy", "Severity, rules, explain"], [fa.FaWrench, PINK, "Act", "Recommend, approve, audit"]];
  for (let i = 0; i < 6; i++) {
    const [Ic, col, h, b] = stages[i], x = 0.5 + i * 1.54, t0 = 0.5 + i * 0.35;
    pen(t0, "rise"); glass(s, x, 1.85, 1.3, 1.75);
    await sq(s, Ic, x + 0.4, 2.0, 0.5, col, { t: t0 + 0.15 });
    txt(s, h, { x, y: 2.55, w: 1.3, h: 0.45, fontSize: 14, bold: true, align: "center" });
    txt(s, b, { x: x + 0.05, y: 3.0, w: 1.2, h: 0.55, fontSize: 12, align: "center", valign: "top", transparency: 20 });
    if (i < 5) arrow(s, x + 1.31, 2.72, 0.22, 0, W, { t: t0 + 0.2 });
  }
  const bd2 = NM("boundary", { fx: "wipeup", t: 1.2, dur: 800 });
  s.addShape(S.line, { x: 5.0, y: 1.8, w: 0, h: 1.9, line: { color: RED, width: 2.5, dashType: "dash" }, objectName: bd2 });
  s.addShape(S.line, { x: 1.15, y: 3.85, w: 7.7, h: 0, line: { color: W, transparency: 70, width: 1, dashType: "dash" }, objectName: "track" });
  const pk2 = NM("packet", { stat: true });
  s.addShape(S.ellipse, { x: 1.05, y: 3.75, w: 0.2, h: 0.2, fill: { color: YELLOW }, line: { color: W, width: 0.75 }, objectName: pk2 });
  loop(pk2, "packet", { t: 3.0, dx: 0.77, dur: 4500 });
  pen(3.0, "rise"); pill(s, "Every hop is persisted and idempotent: same payload_id, same result.", { x: 0.5, y: 4.15, w: 9, h: 0.65, fontSize: 15, fill: { color: W, transparency: 88 }, line: { color: W, transparency: 70, width: 1 } });
  dock(s);
