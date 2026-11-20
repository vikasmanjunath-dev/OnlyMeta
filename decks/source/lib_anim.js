// Animation / transition / hyperlink injector for pptxgenjs output (pptxgenjs cannot author these).
const fs = require("fs");
const JSZip = require(require.resolve("jszip", { paths: [require.resolve("pptxgenjs")] }));

const MC = "http://schemas.openxmlformats.org/markup-compatibility/2006";
const P14 = "http://schemas.microsoft.com/office/powerpoint/2010/main";
const P159 = "http://schemas.microsoft.com/office/powerpoint/2015/09/main";

function transitionXml(t) {
  if (!t) return "";
  const fb = `<mc:Fallback><p:transition spd="med"><p:fade/></p:transition></mc:Fallback>`;
  if (t.kind === "morph")
    return `<mc:AlternateContent xmlns:mc="${MC}"><mc:Choice xmlns:p159="${P159}" xmlns:p14="${P14}" Requires="p159"><p:transition spd="slow" p14:dur="${t.dur || 1600}"><p159:morph option="byObject"/></p:transition></mc:Choice>${fb}</mc:AlternateContent>`;
  return `<mc:AlternateContent xmlns:mc="${MC}"><mc:Choice xmlns:p14="${P14}" Requires="p14"><p:transition spd="slow" p14:dur="${t.dur || 1500}">${t.xml}</p:transition></mc:Choice>${fb}</mc:AlternateContent>`;
}

function timingXml(entries, idOf) {
  let n = 2;
  const nid = () => ++n;
  const tgt = (id) => `<p:tgtEl><p:spTgt spid="${id}"/></p:tgtEl>`;
  const set = (id) => `<p:set><p:cBhvr><p:cTn id="${nid()}" dur="1" fill="hold"><p:stCondLst><p:cond delay="0"/></p:stCondLst></p:cTn>${tgt(id)}<p:attrNameLst><p:attrName>style.visibility</p:attrName></p:attrNameLst></p:cBhvr><p:to><p:strVal val="visible"/></p:to></p:set>`;
  const fx = (id, f, d) => `<p:animEffect transition="in" filter="${f}"><p:cBhvr><p:cTn id="${nid()}" dur="${d}"/>${tgt(id)}</p:cBhvr></p:animEffect>`;
  const anim = (id, attr, tavs, d, additive) => `<p:anim calcmode="lin" valueType="num"><p:cBhvr${additive ? ' additive="base"' : ""}><p:cTn id="${nid()}" dur="${d}" fill="hold"/>${tgt(id)}<p:attrNameLst><p:attrName>${attr}</p:attrName></p:attrNameLst></p:cBhvr><p:tavLst>${tavs.map(([tm, v, f]) => `<p:tav tm="${tm}"><p:val>${f ? `<p:fltVal val="${v}"/>` : `<p:strVal val="${v}"/>`}</p:val></p:tav>`).join("")}</p:tavLst></p:anim>`;

  const entrance = (e, id) => {
    const d = e.dur || 700;
    switch (e.fx) {
      case "fade": return [10, 0, set(id) + fx(id, "fade", d)];
      case "rise": return [2, 4, set(id) + anim(id, "ppt_y", [[0, "#ppt_y+0.1"], [100000, "#ppt_y"]], d, true) + fx(id, "fade", d)];
      case "left": return [2, 8, set(id) + anim(id, "ppt_x", [[0, "#ppt_x-0.45"], [100000, "#ppt_x"]], d, true) + fx(id, "fade", d)];
      case "right": return [2, 2, set(id) + anim(id, "ppt_x", [[0, "#ppt_x+0.45"], [100000, "#ppt_x"]], d, true) + fx(id, "fade", d)];
      case "pop": return [53, 16, set(id) + anim(id, "ppt_w", [[0, "0"], [70000, "#ppt_w*1.06"], [100000, "#ppt_w"]], d + 150) + anim(id, "ppt_h", [[0, "0"], [70000, "#ppt_h*1.06"], [100000, "#ppt_h"]], d + 150) + fx(id, "fade", d)];
      case "spin": return [31, 0, set(id) + anim(id, "ppt_w", [[0, "0"], [100000, "#ppt_w"]], d + 200) + anim(id, "ppt_h", [[0, "0"], [100000, "#ppt_h"]], d + 200) + anim(id, "style.rotation", [[0, 200, 1], [100000, 0, 1]], d + 200) + fx(id, "fade", d)];
      case "wipe": return [22, 8, set(id) + fx(id, "wipe(left)", e.dur || 500)];
      case "wipeup": return [22, 1, set(id) + fx(id, "wipe(down)", e.dur || 500)];
      default: throw new Error("fx " + e.fx);
    }
  };
  const loop = (e, id) => {
    const dist = e.p || {};
    if (e.kind === "orbit") return ["emph", 8, `<p:animRot by="${e.rev ? -21600000 : 21600000}"><p:cBhvr><p:cTn id="${nid()}" dur="${e.dur || 14000}" fill="hold"/>${tgt(id)}<p:attrNameLst><p:attrName>r</p:attrName></p:attrNameLst></p:cBhvr></p:animRot>`, ""];
    if (e.kind === "pulse") return ["emph", 26, `<p:animScale><p:cBhvr><p:cTn id="${nid()}" dur="${e.dur || 900}" autoRev="1" fill="hold"/>${tgt(id)}</p:cBhvr><p:by x="${e.by || 112000}" y="${e.by || 112000}"/></p:animScale>`, ""];
    if (e.kind === "float") return ["path", 0, `<p:animMotion origin="layout" path="M 0 0 L 0 -${e.amp || 0.014} E" pathEditMode="relative" rAng="0" ptsTypes="AA"><p:cBhvr><p:cTn id="${nid()}" dur="${e.dur || 2400}" autoRev="1" fill="hold"/>${tgt(id)}<p:attrNameLst><p:attrName>ppt_x</p:attrName><p:attrName>ppt_y</p:attrName></p:attrNameLst></p:cBhvr><p:rCtr x="0" y="0"/></p:animMotion>`, ""];
    if (e.kind === "packet") return ["path", 0, `<p:animMotion origin="layout" path="M 0 0 L ${e.dx} ${e.dy || 0} E" pathEditMode="relative" rAng="0" ptsTypes="AA"><p:cBhvr><p:cTn id="${nid()}" dur="${e.dur || 1800}" fill="hold"/>${tgt(id)}<p:attrNameLst><p:attrName>ppt_x</p:attrName><p:attrName>ppt_y</p:attrName></p:attrNameLst></p:cBhvr><p:rCtr x="${e.dx / 2}" y="0"/></p:animMotion>`, ""];
    throw new Error("loop " + e.kind);
  };

  const par = (e, nodeType) => {
    const id = idOf(e.name);
    if (!id) throw new Error("no shape id for " + e.name);
    const delay = Math.round((e.t || 0) * 1000);
    const cid = nid();
    let cls, preset, sub, body, extra = "";
    if (e.kind) { [cls, preset, body] = loop(e, id); sub = 0; extra = ' repeatCount="indefinite"'; }
    else { cls = "entr"; [preset, sub, body] = entrance(e, id); }
    return `<p:par><p:cTn id="${cid}" presetID="${preset}" presetClass="${cls}" presetSubtype="${sub}"${extra} fill="hold" nodeType="${nodeType}"><p:stCondLst><p:cond delay="${delay}"/></p:stCondLst><p:childTnLst>${body}</p:childTnLst></p:cTn></p:par>`;
  };

  const groups = {};
  for (const e of entries) (groups[e.click || 0] = groups[e.click || 0] || []).push(e);
  const keys = Object.keys(groups).map(Number).sort((a, b) => a - b);
  let seq = "";
  for (const k of keys) {
    const list = groups[k];
    const outerId = nid(), innerId = nid();
    const inner = list.map((e, i) => par(e, i === 0 ? (k === 0 ? "afterEffect" : "clickEffect") : "withEffect")).join("");
    const cond = k === 0 ? `<p:cond delay="indefinite"/><p:cond evt="onBegin" delay="0"><p:tn val="2"/></p:cond>` : `<p:cond delay="indefinite"/>`;
    seq += `<p:par><p:cTn id="${outerId}" fill="hold"><p:stCondLst>${cond}</p:stCondLst><p:childTnLst><p:par><p:cTn id="${innerId}" fill="hold"><p:stCondLst><p:cond delay="0"/></p:stCondLst><p:childTnLst>${inner}</p:childTnLst></p:cTn></p:par></p:childTnLst></p:cTn></p:par>`;
  }
  return `<p:timing><p:tnLst><p:par><p:cTn id="1" dur="indefinite" restart="never" nodeType="tmRoot"><p:childTnLst><p:seq concurrent="1" nextAc="seek"><p:cTn id="2" dur="indefinite" nodeType="mainSeq"><p:childTnLst>${seq}</p:childTnLst></p:cTn><p:prevCondLst><p:cond evt="onPrev" delay="0"><p:tgtEl><p:sldTgt/></p:tgtEl></p:cond></p:prevCondLst><p:nextCondLst><p:cond evt="onNext" delay="0"><p:tgtEl><p:sldTgt/></p:tgtEl></p:cond></p:nextCondLst></p:seq></p:childTnLst></p:cTn></p:par></p:tnLst></p:timing>`;
}

const GRAD = { "010203": [["0", "0A84FF"], ["55000", "BF5AF2"], ["100000", "FF375F"]], "010204": [["0", "64D2FF"], ["100000", "0A84FF"]], "010205": [["0", "30D158"], ["100000", "64D2FF"]], "010206": [["0", "FF9F0A"], ["100000", "FF375F"]] };
const gradXml = (stops) => `<a:gradFill rotWithShape="1"><a:gsLst>${stops.map(([p, c]) => `<a:gs pos="${p}"><a:srgbClr val="${c}"/></a:gs>`).join("")}</a:gsLst><a:lin ang="0" scaled="0"/></a:gradFill>`;
const esc = (s) => s.replace(/[.*+?^${}()|[\]\\!]/g, "\\$&");

async function inject(file, { entries, transitions, links }) {
  const zip = await JSZip.loadAsync(fs.readFileSync(file), { createFolders: false });
  for (const sn of Object.keys(entries)) {
    const path = `ppt/slides/slide${sn}.xml`, rpath = `ppt/slides/_rels/slide${sn}.xml.rels`;
    let xml = await zip.file(path).async("string");
    let rels = await zip.file(rpath).async("string");
    const idOf = (name) => {
      let m = xml.match(new RegExp(`<p:cNvPr id="(\\d+)" name="${esc(name)}"`));
      if (!m && name.startsWith("chart")) m = xml.match(/<p:cNvPr id="(\d+)" name="Chart[^"]*"/);
      return m ? m[1] : null;
    };
    // hyperlinks (slide jumps) on shapes
    let rid = Math.max(0, ...[...rels.matchAll(/Id="rId(\d+)"/g)].map((m) => +m[1]));
    let newRels = "";
    for (const l of links[sn] || []) {
      const id = idOf(l.name);
      if (!id) throw new Error(`link: no shape ${l.name} on slide ${sn}`);
      const r = `rId${++rid}`;
      newRels += `<Relationship Id="${r}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slide${l.to}.xml"/>`;
      const re = new RegExp(`(<p:cNvPr id="${id}" name="${esc(l.name)}"[^>]*?)(/>|>)`);
      xml = xml.replace(re, (_, a, end) => `${a.replace(/\/$/, "")}><a:hlinkClick r:id="${r}" action="ppaction://hlinksldjump" tooltip="${l.tip || ""}"/>${end === "/>" ? "</p:cNvPr>" : ""}`);
    }
    rels = rels.replace("</Relationships>", newRels + "</Relationships>");
    const tm = timingXml(entries[sn], idOf);
    xml = xml.replace("</p:clrMapOvr>", `</p:clrMapOvr>${transitionXml(transitions[sn])}${tm}`);
    for (const [k, v] of Object.entries(GRAD)) xml = xml.split(`<a:solidFill><a:srgbClr val="${k}"/></a:solidFill>`).join(gradXml(v));
    zip.file(path, xml);
    zip.file(rpath, rels);
  }
  const out = new JSZip();
  for (const [n, f] of Object.entries(zip.files)) if (!f.dir) out.file(n, await f.async('nodebuffer'));
  fs.writeFileSync(file, await out.generateAsync({ type: "nodebuffer", compression: "DEFLATE" }));
}
module.exports = { inject };
