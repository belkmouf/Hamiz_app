/* Hamiz Pulse math, shared by the app and the Node tests. Mirrors pulse/calc.py and pulse/stages.py.
   Basis names: "raw" = orders placed, "confirmed", "delivered". */
(function (root) {
  "use strict";

  function classify(state, status) {
    const s = String(status || "").normalize("NFKD").replace(/[\u0300-\u036f]/g, "").toLowerCase(), has = ks => ks.some(k => s.includes(k));
    if (state === "cancel" || has(["cancel", "annul", "refus", "fraud"]))
      return has(["return", "retour", "refus"]) ? "returned" : "cancelled";
    if (has(["return", "retour", "rto"])) return "returned";
    if (has(["deliver", "livr", "complete", "closed"])) return "delivered";
    if (state === "sale" || state === "done" || has(["process", "confirm", "ship", "expedi"])) return "confirmed";
    return "pending";
  }

  const basisMult = (b, c, d) => ({ raw: 1 / c, confirmed: 1, delivered: d })[b];
  const toDeliv = (t, b, c, d) => ({ raw: t * c * d, confirmed: t * d, delivered: t })[b];
  const capConfUsd = (cac, aov, fx, basis, c, d) => cac * aov * basisMult(basis, c, d) / fx;

  function cacBudget(I) {
    const perConf = I.cac * I.aov * basisMult(I.basis, I.c, I.d), perDeliv = perConf / I.d, perRaw = perConf * I.c;
    const daily = [I.low, I.high].map(t => {
      const td = toDeliv(t, "raw", I.c, I.d);
      return { t, placed: td / (I.c * I.d), conf: td / I.d, deliv: td, spend: td * perDeliv };
    });
    return { perConf, perDeliv, perRaw, daily };
  }

  /* Landing conversion needed so Meta CPA stays <= the cap. ctrPct is a percent (2.5 = 2.5%). */
  const landingNeeded = (cpm, ctrPct, perPlacedUsd) => perPlacedUsd > 0 ? (cpm / (1000 * ctrPct / 100)) / perPlacedUsd : Infinity;

  function newGroup() { return { raw: 0, pending: 0, conf: 0, deliv: 0, val: [], approx: false }; }
  function addOrder(g, stage, value) {
    g.raw++;
    if (stage === "pending") g.pending++;
    if (stage === "confirmed" || stage === "delivered" || stage === "returned") { g.conf++; if (value) g.val.push(+value); }
    if (stage === "delivered") g.deliv++;
  }

  /* One ad's decision, rules in PRD order. daysRunning (live mode) holds back CAC and no-order kills before 3 full days. */
  function decide(name, g, sp, I, daysRunning) {
    const resolved = g.raw - g.pending, rate = resolved ? g.conf / resolved : 0;
    const aov = g.val.length ? g.val.reduce((a, b) => a + b, 0) / g.val.length : I.aov;
    const capRaw = I.cac * aov / I.fx;
    const cac = I.basis === "raw" ? (g.raw ? sp * I.fx / g.raw / aov : Infinity)
      : (g.conf ? (sp / g.conf / basisMult(I.basis, I.c, I.d)) * I.fx / aov : Infinity);
    const nBasis = I.basis === "raw" ? g.raw : g.conf;
    let code, label;
    if (name === "UNATTRIBUTED") { code = "fix"; label = "Fix tracking"; }
    else if (g.raw && g.pending / g.raw > .5) { code = "wait"; label = "Wait: most orders still pending"; }
    else if (resolved >= 10 && rate < .5) { code = "kill"; label = "Kill: junk orders"; }
    else if (nBasis >= 3 && g.conf >= 2 && cac <= I.cac) { code = "promote"; label = "Promote"; }
    else if (nBasis >= 3 && cac > 1.5 * I.cac && sp >= 2.5 * capRaw) { code = "kill"; label = "Kill: CAC " + (cac * 100).toFixed(1) + "%"; }
    else if (!g.raw && sp >= 2.5 * capRaw) { code = "kill"; label = "Kill: no orders"; }
    else { code = "wait"; label = "Wait: not enough data"; }
    if (daysRunning != null && daysRunning < 3 && code === "kill" && label !== "Kill: junk orders") {
      code = "wait"; label = "Wait: under 3 full days (would " + label.replace("Kill: ", "kill: ") + ")";
    }
    return { code, label, cac, aov, rate };
  }

  /* spend: {ad: usd}; groups: {ad: group}; daysRunning: {ad: n} or null. Rows sorted by CAC % ascending. */
  function review(spend, groups, I, daysRunning) {
    const names = [...new Set([...Object.keys(spend), ...Object.keys(groups)])].sort();
    const rows = names.map(n => {
      const g = groups[n] || newGroup(), sp = spend[n] || 0;
      const r = decide(n, g, sp, I, daysRunning ? daysRunning[n] : null);
      return { n, sp, g, ...r, days: daysRunning ? daysRunning[n] : null };
    });
    rows.sort((a, b) => a.cac === b.cac ? 0 : a.cac < b.cac ? -1 : 1);
    const spAll = rows.reduce((a, r) => a + r.sp, 0), rawAll = rows.reduce((a, r) => a + r.g.raw, 0),
      confAll = rows.reduce((a, r) => a + r.g.conf, 0);
    const vals = rows.flatMap(r => r.g.val), avg = vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : I.aov;
    const blended = I.basis === "raw" ? (rawAll ? spAll * I.fx / rawAll / avg : Infinity)
      : (confAll ? spAll * I.fx / (confAll / basisMult(I.basis, I.c, I.d)) / avg : Infinity);
    return {
      rows, account: {
        spAll, rawAll, confAll, avg, blended, ok: blended <= I.cac,
        perDelivPct: confAll ? spAll * I.fx / (confAll * I.d) / avg : null
      }
    };
  }

  /* ---------- upload mode CSV helpers ---------- */
  function parseCSV(text) {
    const rows = []; let row = [], f = "", q = false;
    for (let i = 0; i < text.length; i++) {
      const ch = text[i];
      if (q) { if (ch === '"') { if (text[i + 1] === '"') { f += '"'; i++; } else q = false; } else f += ch; }
      else if (ch === '"') q = true; else if (ch === "," || ch === ";" || ch === "\t") { row.push(f); f = ""; }
      else if (ch === "\n") { row.push(f); rows.push(row); row = []; f = ""; } else if (ch !== "\r") f += ch;
    }
    if (f || row.length) { row.push(f); rows.push(row); }
    const hdr = (rows.shift() || []).map(h => h.trim().toLowerCase().replace(/^﻿/, ""));
    return rows.filter(r => r.some(x => x.trim())).map(r => Object.fromEntries(hdr.map((h, i) => [h, (r[i] || "").trim()])));
  }
  const col = (row, names) => {
    for (const n of names) { const k = Object.keys(row).find(k => k === n || k.includes(n)); if (k != null && row[k] !== "") return row[k]; }
    return "";
  };
  const num = s => parseFloat(String(s).replace(/[^\d.,-]/g, "").replace(/,(?=\d{3}\b)/g, "").replace(",", ".")) || 0;

  /* Meta Ads Manager export -> {ad: usd}. Accepts ad_name/"Ad name" and spend/"Amount spent (USD)". */
  function spendFromCsv(text) {
    const spend = {};
    parseCSV(text).forEach(r => {
      const n = col(r, ["ad_name", "ad name", "campaign name", "campaign"]); if (!n) return;
      spend[n] = (spend[n] || 0) + num(col(r, ["spend", "amount spent"]));
    });
    return spend;
  }
  /* Orders CSV (ad_name, status, value) -> {ad: group}. */
  function groupsFromCsv(text) {
    const groups = {};
    parseCSV(text).forEach(r => {
      const n = col(r, ["ad_name", "ad name", "utm_content", "campaign"]) || "UNATTRIBUTED";
      const g = groups[n] = groups[n] || newGroup();
      addOrder(g, classify(null, col(r, ["status", "stage"])), num(col(r, ["value", "total"])));
    });
    return groups;
  }

  const api = { classify, basisMult, toDeliv, capConfUsd, cacBudget, landingNeeded, newGroup, addOrder, decide, review,
    parseCSV, col, num, spendFromCsv, groupsFromCsv };
  if (typeof module !== "undefined" && module.exports) module.exports = api; else root.PulseCalc = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
