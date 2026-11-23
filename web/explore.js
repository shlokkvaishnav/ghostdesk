// ghostdesk research explorer. Reads data/research.json (written by scripts/explorer/export_research.py; statistics
// only) and draws inline SVG at the real width. Every control is a button, a select or a range input, and each chart
// has a sentence next to it (aria-live) that says what it shows.
"use strict";
const $ = (id) => document.getElementById(id);
const NS = "http://www.w3.org/2000/svg";
let R = null;
const state = { mistake: "survivors", period: "test", measure: "composite", group: "large", size: "0.05", aum: 8 };

function el(tag, attrs = {}, parent) {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  if (parent) parent.appendChild(e);
  return e;
}
function text(parent, x, y, s, attrs = {}) {
  const t = el("text", { x, y, ...attrs }, parent);
  t.textContent = s;
  return t;
}
function svg(host, h, label) {
  host.innerHTML = "";
  const w = Math.max(280, host.clientWidth);
  const s = el("svg", { viewBox: `0 0 ${w} ${h}`, width: w, height: h, role: "img", "aria-label": label }, host);
  return [s, w];
}
// A share as a signed percent. The sign comes from the rounded value, so a tiny negative shows as 0.00%, not −0.00%.
const pct = (v, d = 2) => { const r = +(v * 100).toFixed(d); return (r > 0 ? "+" : r < 0 ? "−" : "") + Math.abs(r).toFixed(d) + "%"; };
const num = (v, d = 2) => (v < 0 ? "−" : "") + Math.abs(v).toFixed(d);
const money = (v) => (v >= 1e9 ? "$" + +(v / 1e9).toPrecision(3) + " billion" : "$" + +(v / 1e6).toPrecision(3) + " million");
const kv = (rows) => rows.map(([k, v, cls]) => `<span class="${cls || ""}">${k}</span><span class="${cls || ""}">${v}</span>`).join("");

// A group of toggle buttons; the pressed one is the current choice.
function seg(host, options, current, onPick) {
  host.innerHTML = "";
  for (const [value, label] of options) {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = label;
    b.setAttribute("aria-pressed", String(value === current));
    b.addEventListener("click", () => onPick(value));
    host.appendChild(b);
  }
}

// Vertical bars with a zero line, for values that can be below zero.
function bars(host, items, h, label, fmt) {
  const [s, w] = svg(host, h, label);
  const top = 22, bottom = h - 26, left = 8, right = w - 8;
  const vals = items.map((i) => i.value);
  const hi = Math.max(0, ...vals), lo = Math.min(0, ...vals);
  const span = hi - lo || 1;
  const y = (v) => top + ((hi - v) / span) * (bottom - top);
  const slot = (right - left) / items.length, bw = Math.min(64, slot * 0.6);
  el("line", { x1: left, x2: right, y1: y(0), y2: y(0), class: "zero" }, s);
  items.forEach((it, i) => {
    const cx = left + slot * (i + 0.5), y0 = y(0), y1 = y(it.value);
    el("rect", { x: cx - bw / 2, y: Math.min(y0, y1), width: bw, height: Math.max(1, Math.abs(y1 - y0)), rx: 4, class: it.cls }, s);
    text(s, cx, it.value >= 0 ? y1 - 6 : y1 + 15, fmt(it.value), { class: "val", "text-anchor": "middle" });
    text(s, cx, h - 8, it.label, { class: "tick", "text-anchor": "middle" });
  });
}

// 1. Switch off one guard.
function drawMistakes() {
  const P = R.pitfalls, base = P.baseline, m = P.mistakes[state.mistake];
  seg($("mistake-pick"), Object.entries(P.mistakes).map(([k, v]) => [k, v.label]), state.mistake, (v) => { state.mistake = v; drawMistakes(); });
  $("mistake-explain").textContent = m.explain;
  $("mistake-kv").innerHTML = kv([
    ["", "Honest · With the mistake", "head"],
    ["Long-short return per month", `${pct(base.ls_monthly)} · ${pct(m.ls_monthly)}`],
    ["t value", `${num(base.ls_t)} · ${num(m.ls_t)}`],
    ["Sharpe ratio (annual)", `${num(base.sharpe)} · ${num(m.sharpe)}`],
    ["Information coefficient", `${num(base.ic, 3)} · ${num(m.ic, 3)}`],
    ["Stock-months", `${base.stock_months.toLocaleString("en-US")} · ${m.stock_months.toLocaleString("en-US")}`],
  ]);
  bars($("mistake-chart"), [
    { label: "Honest", value: base.ls_monthly, cls: "bar-honest" },
    { label: "With the mistake", value: m.ls_monthly, cls: "bar-mistake" },
  ], 220, "Long-short return per month, honest and with the mistake", (v) => pct(v));
  const diff = m.ls_monthly - base.ls_monthly;
  $("mistake-say").textContent =
    `With "${m.label.toLowerCase()}", the return per month is ${pct(m.ls_monthly)} instead of ${pct(base.ls_monthly)} ` +
    `(${pct(diff).replace("%", "")} percentage points). ` + (Math.abs(diff) >= 0.001 ? "That is a large change for a signal of this size." : "For a slow monthly signal, this mistake changes little.");
}

// 2. The signal, period by period.
function drawSignal() {
  const S = R.signal, p = S.periods[state.period], m = p.measures[state.measure];
  seg($("period-pick"), Object.entries(S.periods).map(([k, v]) => [k, v.label]), state.period, (v) => { state.period = v; drawSignal(); });
  const pick = $("measure-pick");
  if (!pick.options.length) {
    for (const [k, label] of Object.entries(S.measures)) pick.add(new Option(label, k));
    pick.addEventListener("change", () => { state.measure = pick.value; drawSignal(); });
  }
  pick.value = state.measure;
  bars($("signal-chart"), m.quintiles.map((v, i) => ({
    label: i === 0 ? "1 · changed most" : i === 4 ? "5 · changed least" : String(i + 1),
    value: v, cls: i === 0 ? "q1" : i === 4 ? "q5" : "qm",
  })), 240, `Mean return per month of the five groups, ${p.label}`, (v) => pct(v));
  $("signal-badge").innerHTML = p.confirmatory
    ? `<span class="badge">Pre-registered · run once</span><p class="note">The rules were committed (<code>${p.prereg_commit}</code>) and timestamped before this period was used; the test ran once with code <code>${p.code_commit}</code>. <a href="docs/preregistration/">Read the pre-registration</a>.</p>`
    : `<p class="note">${p.label} is not the confirmatory test. Only the test period was fixed in advance and run once.</p>`;
  const net = m.ls_net_5bps, ci = net.ci95;
  $("signal-kv").innerHTML = kv([
    ["Long-short, before costs (t)", `${pct(m.ls_gross.mean)} (${num(m.ls_gross.t)})`],
    ["Long-short, after 5 bps costs (t)", `${pct(net.mean)} (${num(net.t)})`],
    ["95% interval after costs", `${pct(ci[0])} to ${pct(ci[1])}`],
    ["Information coefficient (t)", `${num(m.ic.mean, 3)} (${num(m.ic.t)})`],
    ["Smallest effect this test can find (80% power)", pct(m.mde_monthly_80pct_power)],
    ["Months", String(m.months)],
  ]);
  const found = ci[0] > 0;
  $("signal-say").textContent =
    `${S.measures[state.measure]}, ${p.label}: buying group 5 and selling group 1 earned ${pct(net.mean)} a month after costs. ` +
    (found ? "The 95% interval is above zero." : "The 95% interval includes zero, so no effect is detected.");
}

// 3a. Execution cost per strategy.
function drawExecution() {
  const E = R.execution, cost = E.cost_bps[state.group][state.size];
  seg($("group-pick"), Object.entries(E.groups).map(([k, v]) => [k, v]), state.group, (v) => { state.group = v; drawExecution(); });
  seg($("size-pick"), Object.keys(E.cost_bps[state.group]).map((k) => [k, `${+(k * 100).toPrecision(2)}% of volume`]), state.size, (v) => { state.size = v; drawExecution(); });
  const fixed = E.strategies.filter((s) => !s.startsWith("PPO"));
  const best = fixed.reduce((a, b) => (cost[a] <= cost[b] ? a : b));
  const host = $("exec-chart");
  const rows = E.strategies.map((s) => ({ s, v: cost[s] }));
  const rowH = 30, h = rows.length * rowH + 8;
  const [svgEl, w] = svg(host, h, "Cost in basis points per strategy");
  const labelW = 118, max = Math.max(...rows.map((r) => r.v));
  rows.forEach((r, i) => {
    const y = 4 + i * rowH, bw = ((w - labelW - 70) * r.v) / max;
    text(svgEl, 0, y + 19, r.s, { class: "tick", style: "font-size:12px" });
    el("rect", { x: labelW, y: y + 6, width: Math.max(2, bw), height: rowH - 12, rx: 4, class: r.s === best ? "best" : r.s.startsWith("PPO") ? "agent" : "other" }, svgEl);
    text(svgEl, labelW + bw + 8, y + 19, `${r.v.toFixed(2)} bps`, { class: "val" });
  });
  const extra = cost.PPO - cost[best];
  $("exec-say").textContent =
    `${E.groups[state.group]}, ${+(state.size * 100).toPrecision(2)}% of daily volume: ${best} is the cheapest schedule at ${cost[best].toFixed(2)} bps. ` +
    `The learned agent costs ${extra >= 0 ? extra.toFixed(2) + " bps more" : Math.abs(extra).toFixed(2) + " bps less"} (mean of ${E.seeds} training runs on ${E.test_days} test days).`;
}

// 3b. Capacity: monthly cost as the fund grows, against the edge.
function drawCapacity() {
  const C = R.capacity, curve = C.cost_curve, i = state.aum;
  const [aum, cost] = curve[i];
  $("aum").max = String(curve.length - 1);
  $("aum-out").textContent = money(aum);
  const levels = Object.entries(C.gross_levels);
  const [s, w] = svg($("cap-chart"), 220, "Monthly trading cost by fund size, with the size of the edge");
  const top = 10, bottom = 190, left = 44, right = w - 8;
  const lx = (a) => left + ((Math.log10(a) - Math.log10(curve[0][0])) / (Math.log10(curve.at(-1)[0]) - Math.log10(curve[0][0]))) * (right - left);
  const ymax = Math.max(...levels.map(([, v]) => v)) * 1.3;
  const ly = (v) => bottom - (Math.min(v, ymax) / ymax) * (bottom - top);
  el("line", { x1: left, x2: right, y1: bottom, y2: bottom, class: "axis" }, s);
  for (const t of [0, ymax / 2, ymax]) text(s, left - 6, ly(t) + 4, pct(t, 2).replace("+", ""), { class: "tick", "text-anchor": "end" });
  for (const a of [1e6, 1e8, 1e10]) text(s, lx(a), bottom + 16, money(a).replace(" million", "M").replace(" billion", "B"), { class: "tick", "text-anchor": "middle" });
  levels.forEach(([name, v], k) => {
    el("line", { x1: left, x2: right, y1: ly(v), y2: ly(v), class: `level lv${k}` }, s);
    const atRight = k % 2 === 1; // neighbouring levels get labels at opposite ends, so they do not overlap
    text(s, atRight ? right - 4 : left + 4, ly(v) - 5, `edge: ${name} ${pct(v).replace("+", "")}`, { class: "tick", "text-anchor": atRight ? "end" : "start" });
  });
  el("path", { d: curve.map(([a, c], k) => `${k ? "L" : "M"}${lx(a).toFixed(1)},${ly(c).toFixed(1)}`).join(""), class: "curve" }, s);
  el("circle", { cx: lx(aum), cy: ly(cost), r: 6, class: "marker" }, s);
  const edge = C.gross_levels["pooled estimate"], be = C.break_even_aum["pooled estimate"];
  $("cap-say").textContent =
    `At ${money(aum)}, trading costs about ${pct(cost, 3).replace("+", "")} a month. ` +
    (cost < edge ? "That is below" : "That is above") +
    ` the pooled estimate of the edge (${pct(edge).replace("+", "")} a month), which is used up at about ${money(be)}. ` +
    "The edge itself was not detected in the test, so this is the limit if it is real.";
}

function drawAll() {
  drawMistakes(); drawSignal(); drawExecution(); drawCapacity();
}

$("aum").addEventListener("input", (e) => { state.aum = +e.target.value; drawCapacity(); });
let resizeTimer;
addEventListener("resize", () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(() => R && drawAll(), 150); });

fetch("data/research.json")
  .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
  .then((data) => { R = data; drawAll(); })
  .catch(() => {
    for (const id of ["mistake-chart", "signal-chart", "exec-chart", "cap-chart"]) $(id).innerHTML = '<p class="empty">The study data could not be loaded.</p>';
  });
