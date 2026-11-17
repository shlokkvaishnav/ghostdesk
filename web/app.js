// ghostdesk live page. Reads data/live.json (written by scripts/live.py site) and draws inline SVG at the real width.
"use strict";
const $ = (id) => document.getElementById(id);
const NS = "http://www.w3.org/2000/svg";
const tip = $("tip");
let D = null;

function el(tag, attrs = {}, parent) {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  if (parent) parent.appendChild(e);
  return e;
}
function svg(host, h) {
  host.innerHTML = "";
  const w = Math.max(280, host.clientWidth);
  const s = el("svg", { viewBox: `0 0 ${w} ${h}`, width: w, height: h, role: "img" }, host);
  return [s, w];
}
const pct = (v, d = 1) => (v > 0 ? "+" : v < 0 ? "−" : "") + Math.abs(v).toFixed(d) + "%";
const money = (v) => "$" + Math.round(v).toLocaleString("en-US");
const dfmt = (s) => new Date(s + "T12:00:00Z").toLocaleDateString("en-US", { month: "short", day: "numeric" });

function showTip(ev, html) {
  tip.innerHTML = html;
  const x = Math.min(ev.clientX + 14, innerWidth - tip.offsetWidth - 8);
  tip.style.left = x + "px";
  tip.style.top = ev.clientY + 14 + "px";
  tip.style.opacity = 1;
}
const hideTip = () => (tip.style.opacity = 0);

function stats() {
  const c = D.curve, last = c.length ? c[c.length - 1] : null;
  const longN = D.positions.filter((p) => p.qty > 0).length, shortN = D.positions.filter((p) => p.qty < 0).length;
  const vs = last && last.spy != null ? last.account - last.spy : null;
  const items = [
    [money(D.account.equity), "Account value"],
    [last ? `<span class="${last.account >= 0 ? "pos" : "neg"}">${pct(last.account, 2)}</span>` : "—", "Since the start"],
    [vs == null ? "—" : `<span class="${vs >= 0 ? "pos" : "neg"}">${pct(vs, 2)}</span>`, "Against SPY"],
    [D.positions.length ? `${longN} / ${shortN}` : "—", D.positions.length ? "Long / short stocks"
      : (D.next_rebalance ? `First trades ${dfmt(D.next_rebalance)}` : "No positions yet")],
  ];
  $("stats").innerHTML = items.map(([b, s]) => `<div class="stat"><b>${b}</b><span>${s}</span></div>`).join("");
}

function curve() {
  const host = $("curve"), c = D.curve;
  if (c.length < 2) { host.innerHTML = `<p class="empty">The line starts after the first full trading day.</p>`; return; }
  const [s, w] = svg(host, 260), m = { l: 44, r: 12, t: 12, b: 26 };
  const vals = c.flatMap((p) => [p.account, p.spy]).filter((v) => v != null);
  let lo = Math.min(0, ...vals), hi = Math.max(0, ...vals);
  const pad = Math.max((hi - lo) * 0.12, 0.25); lo -= pad; hi += pad;
  const X = (i) => m.l + (i / (c.length - 1)) * (w - m.l - m.r), Y = (v) => m.t + (1 - (v - lo) / (hi - lo)) * (260 - m.t - m.b);
  const step = niceStep((hi - lo) / 4);
  for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) {
    el("line", { x1: m.l, x2: w - m.r, y1: Y(v), y2: Y(v), class: "axis", "stroke-width": Math.abs(v) < 1e-9 ? 1.4 : 1 }, s);
    el("text", { x: m.l - 6, y: Y(v) + 4, "text-anchor": "end", class: "tick" }, s).textContent = pct(v, step < 1 ? 1 : 0);
  }
  const n = Math.min(5, c.length);
  for (let k = 0; k < n; k++) {
    const i = Math.round((k / (n - 1 || 1)) * (c.length - 1));
    el("text", { x: X(i), y: 252, "text-anchor": k === 0 ? "start" : k === n - 1 ? "end" : "middle", class: "tick" }, s).textContent = dfmt(c[i].day);
  }
  const ex = D.expected_month;
  if (ex) {  // trading days since the start -> months; 95% range of the cumulative return
    const band = (i, z) => { const m = i / 21; return 100 * (ex.mean * m + z * 1.96 * ex.sd * Math.sqrt(m)); };
    const up = c.map((_, i) => `${X(i)},${Y(Math.min(hi, band(i, 1)))}`), dn = c.map((_, i) => `${X(i)},${Y(Math.max(lo, band(i, -1)))}`).reverse();
    el("path", { d: "M" + up.join(" L") + " L" + dn.join(" L") + " Z", fill: "var(--chip)", stroke: "var(--rule)" }, s);
  }
  const path = (key) => c.map((p, i) => (p[key] == null ? null : `${X(i)},${Y(p[key])}`)).filter(Boolean).join(" L");
  el("path", { d: "M" + path("spy"), fill: "none", stroke: "var(--muted)", "stroke-width": 1.6, "stroke-dasharray": "4 4" }, s);
  el("path", { d: "M" + path("account"), fill: "none", stroke: "var(--accent)", "stroke-width": 2.4, "stroke-linejoin": "round" }, s);
  const hit = el("rect", { x: m.l, y: m.t, width: w - m.l - m.r, height: 260 - m.t - m.b, fill: "transparent" }, s);
  const cross = el("line", { y1: m.t, y2: 260 - m.b, stroke: "var(--ink)", "stroke-width": 1, opacity: 0 }, s);
  hit.addEventListener("pointermove", (ev) => {
    const r = s.getBoundingClientRect(), i = Math.round(((ev.clientX - r.left) * (w / r.width) - m.l) / (w - m.l - m.r) * (c.length - 1));
    const p = c[Math.max(0, Math.min(c.length - 1, i))];
    cross.setAttribute("x1", X(c.indexOf(p))); cross.setAttribute("x2", X(c.indexOf(p))); cross.setAttribute("opacity", .35);
    showTip(ev, `<b>${dfmt(p.day)}</b><br>ghostdesk ${pct(p.account, 2)}<br>SPY ${p.spy == null ? "—" : pct(p.spy, 2)}`);
  });
  hit.addEventListener("pointerleave", () => { hideTip(); cross.setAttribute("opacity", 0); });
}
function niceStep(x) {
  const p = Math.pow(10, Math.floor(Math.log10(x))), f = x / p;
  return (f < 1.5 ? 1 : f < 3.5 ? 2 : f < 7.5 ? 5 : 10) * p;
}

let dots = [];
function strip() {
  const host = $("strip"), u = D.universe;
  if (!u.length) { host.innerHTML = `<p class="empty">The desk is reading the reports.</p>`; return; }
  const H = host.clientWidth < 560 ? 300 : 340, r = host.clientWidth < 560 ? 3.4 : 4.4;
  const [s, w] = svg(host, H), m = { l: 52, r: 10, t: 8, b: 30 };
  const t = u.map((d) => Date.parse(d.accepted + "T12:00:00Z")), t1 = Math.max(...t), t0 = t1 - 120 * 864e5;
  const X = (v) => m.l + v * (w - m.l - m.r), Y = (ms) => m.t + (t1 - ms) / (t1 - t0) * (H - m.t - m.b);
  el("rect", { x: X(0), y: m.t - 4, width: X(.2) - X(0), height: H - m.t - m.b + 8, rx: 10, fill: "var(--cool-soft)" }, s);
  el("rect", { x: X(.8), y: m.t - 4, width: X(1) - X(.8), height: H - m.t - m.b + 8, rx: 10, fill: "var(--accent-soft)" }, s);
  for (let k = 0; k <= 4; k++) {
    const ms = t1 - k * 30 * 864e5;
    el("line", { x1: m.l, x2: w - m.r, y1: Y(ms), y2: Y(ms), class: "axis", "stroke-dasharray": "2 4" }, s);
    el("text", { x: m.l - 8, y: Y(ms) + 4, "text-anchor": "end", class: "tick" }, s).textContent = dfmt(new Date(ms).toISOString().slice(0, 10));
  }
  el("text", { x: X(0), y: H - 8, class: "tick" }, s).textContent = "← rewrote the most";
  el("text", { x: X(1), y: H - 8, "text-anchor": "end", class: "tick" }, s).textContent = "changed the least →";
  dots = u.map((d, i) => {
    const c = el("circle", { cx: X(d.rank), cy: Y(t[i]), r, class: d.q === 1 ? "q1" : d.q === 5 ? "q5" : "qm" }, s);
    c.addEventListener("pointerenter", (ev) => showTip(ev, `<b>${d.symbol}</b> · ${d.form} of ${dfmt(d.accepted)}<br>Change rank ${(d.rank * 100).toFixed(0)} of 100<br>${d.q === 5 ? "Buy" : d.q === 1 ? "Sell short" : "No position"}`));
    c.addEventListener("pointerleave", hideTip);
    return { c, d };
  });
  highlight();
}
function highlight() {
  const q = $("find").value.trim().toUpperCase();
  for (const { c, d } of dots) c.classList.toggle("hl", q !== "" && d.symbol.startsWith(q));
}

function sectors() {
  const host = $("sectors"), rows = D.sectors;
  if (!rows.length) { host.innerHTML = `<p class="empty">${D.next_rebalance ? "First trades on " + dfmt(D.next_rebalance) + "." : "No positions yet."}</p>`; return; }
  const lh = 30, [s, w] = svg(host, rows.length * lh + 26), lab = Math.min(150, w * .36), half = (w - lab) / 2;
  const mx = Math.max(...rows.flatMap((r) => [r.long, r.short]), 1), cx = lab + half;
  rows.forEach((r, i) => {
    const y = i * lh + 6;
    el("text", { x: 0, y: y + 15, class: "bar-lbl", style: "font-size:13px;fill:var(--ink)" }, s).textContent = r.sector.replace("Information Technology", "Tech").replace("Communication Services", "Communication").replace("Consumer Discretionary", "Discretionary");
    el("rect", { x: cx - (r.short / mx) * (half - 6), y, width: (r.short / mx) * (half - 6), height: 20, rx: 4, fill: "var(--cool)" }, s);
    el("rect", { x: cx, y, width: (r.long / mx) * (half - 6), height: 20, rx: 4, fill: "var(--accent)" }, s);
  });
  el("line", { x1: cx, x2: cx, y1: 0, y2: rows.length * lh + 4, stroke: "var(--ink)", "stroke-width": 1 }, s);
  el("text", { x: cx - 6, y: rows.length * lh + 22, "text-anchor": "end", class: "tick" }, s).textContent = "short";
  el("text", { x: cx + 6, y: rows.length * lh + 22, class: "tick" }, s).textContent = "long";
}

function feed() {
  const r = D.reports.slice(0, 10);
  $("feed").innerHTML = r.length ? r.map((x) => `<li><span class="tk">${x.symbol}</span><span class="nm">${x.name} · ${x.form} · ${dfmt(x.accepted)}</span>
    <span class="meter" title="change rank ${(x.rank * 100).toFixed(0)} of 100"><i style="left:${x.rank * 100}%;background:${x.q === 5 ? "var(--accent)" : x.q === 1 ? "var(--cool)" : "var(--muted)"}"></i></span></li>`).join("")
    : `<li class="empty">No new reports yet.</li>`;
}

function vwap() {
  const host = $("vwap"), prof = D.profile, done = new Map(D.buckets.map((b) => [b.minute, b.share]));
  const [s, w] = svg(host, 190), m = { l: 8, r: 8, t: 10, b: 26 }, n = prof.length, bw = (w - m.l - m.r) / n;
  const mx = Math.max(...prof, ...D.buckets.map((b) => b.share));
  const H = (v) => (v / mx) * (190 - m.t - m.b);
  prof.forEach((v, i) => {
    const x = m.l + i * bw;
    el("rect", { x: x + bw * .12, y: 190 - m.b - H(v), width: bw * .76, height: H(v), rx: 4, fill: "var(--chip)", stroke: "var(--rule)" }, s);
    const got = done.get(i * 5);
    if (got) el("rect", { x: x + bw * .3, y: 190 - m.b - H(got), width: bw * .4, height: H(got), rx: 3, fill: "var(--accent)" }, s);
    if (i % (w < 500 ? 3 : 1) === 0) el("text", { x: x + bw / 2, y: 190 - 8, "text-anchor": "middle", class: "tick" }, s).textContent = `9:${String(30 + i * 5).padStart(2, "0")}`.replace("9:60", "10:00").replace(/9:(6|7|8)(\d)/, (_, a, b) => `10:${a - 6}${b}`);
  });
}

function badge() {
  const hours = (Date.now() - Date.parse(D.updated)) / 36e5;
  const failed = Object.entries(D.health).filter(([, h]) => !h.ok).map(([k]) => k);
  const b = $("badge");
  if (failed.length) { b.className = "badge bad"; b.textContent = `Problem: ${failed.join(", ")}`; }
  else if (hours > 30) { b.className = "badge bad"; b.textContent = `Data ${Math.round(hours)} h old`; }
  else { b.className = "badge"; b.innerHTML = `<i class="dot" style="background:var(--ok);margin:0"></i>Live`; }
}

function recon() {
  const r = D.recon, host = $("recon"), g = $("gross");
  if (!r) {
    const msg = `<p class="empty">The check starts after the first rebalance${D.next_rebalance ? " (" + dfmt(D.next_rebalance) + ")" : ""}.</p>`;
    host.innerHTML = msg; g.innerHTML = msg; return;
  }
  const last = D.rebalances[D.rebalances.length - 1] || {};
  host.innerHTML = `<div class="big">${r.on_target}<span style="font-size:1.2rem;color:var(--muted)"> / ${r.stocks_target}</span></div>
    <span style="color:var(--muted);font-size:.9rem">stocks within 20% of their target value</span>
    <div class="kv"><span>Value off target</span><span>${r.off_pct.toFixed(1)}% of the account</span>
    <span>Planned but not held</span><span>${r.missing.length}</span><span>Held but not planned</span><span>${r.extra.length}</span>
    <span>Orders rejected (last rebalance)</span><span>${last.rejected ?? "—"}</span>
    <span>Fill cost vs arrival price</span><span>${last.cost_bps == null ? "—" : last.cost_bps.toFixed(1) + " bps"}</span></div>
    <p class="tip" style="position:static;opacity:1;background:none;color:var(--muted);padding:0;margin-top:.8rem">Fill costs are simulated by Alpaca.</p>`;
  const rows = [["Long", r.gross.long], ["Short", r.gross.short]];
  const [s, w] = svg(g, 150), mx = Math.max(100, ...rows.flatMap(([, v]) => [v.target, v.actual])), lab = 56;
  rows.forEach(([name, v], i) => {
    const y = 18 + i * 62, W = (x) => (x / mx) * (w - lab - 50);
    el("text", { x: 0, y: y + 22, class: "tick", style: "font-size:13px;fill:var(--ink)" }, s).textContent = name;
    el("rect", { x: lab, y, width: W(v.target), height: 14, rx: 4, fill: "var(--chip)", stroke: "var(--rule)" }, s);
    el("rect", { x: lab, y: y + 18, width: W(v.actual), height: 14, rx: 4, fill: i ? "var(--cool)" : "var(--accent)" }, s);
    el("text", { x: lab + W(v.target) + 6, y: y + 11, class: "tick" }, s).textContent = `plan ${v.target.toFixed(0)}%`;
    el("text", { x: lab + W(v.actual) + 6, y: y + 29, class: "tick" }, s).textContent = `held ${v.actual.toFixed(0)}%`;
  });
}

function risk() {
  const r = D.risk, host = $("risk"), g = $("risksec");
  if (!r) { const msg = `<p class="empty">Shown when the desk holds positions.</p>`; host.innerHTML = msg; g.innerHTML = msg; return; }
  const pct = (x) => (x * 100).toFixed(1) + "%";
  host.innerHTML = `<div class="big">${pct(r.vol_annual)}</div>
    <span style="color:var(--muted);font-size:.9rem">expected yearly volatility of the account</span>
    <div class="kv"><span>Beta to SPY</span><span>${r.beta_spy.toFixed(2)}</span>
    <span>Net exposure</span><span>${pct(r.net)}</span><span>Gross exposure</span><span>${pct(r.gross)}</span>
    <span>Largest position</span><span>${r.largest ? r.largest.symbol + " " + pct(r.largest.weight) : "—"}</span>
    <span>Stocks without a year of prices</span><span>${r.stocks_without_history} of ${r.stocks}</span></div>
    <p class="tip" style="position:static;opacity:1;background:none;color:var(--muted);padding:0;margin-top:.8rem">Covariance with Ledoit-Wolf shrinkage (${r.days} days, intensity ${r.shrinkage.toFixed(2)}).</p>`;
  const rows = r.sectors.slice(0, 8), [s, w] = svg(g, 22 + rows.length * 26), lab = 150;
  const mx = Math.max(0.02, ...rows.map((x) => Math.abs(x.net))), mid = lab + (w - lab) / 2, W = (x) => (x / mx) * ((w - lab) / 2 - 40);
  el("line", { x1: mid, x2: mid, y1: 0, y2: rows.length * 26 + 6, stroke: "var(--rule)" }, s);
  rows.forEach((x, i) => {
    const y = 6 + i * 26;
    el("text", { x: 0, y: y + 12, class: "tick", style: "font-size:12px;fill:var(--ink)" }, s).textContent = x.sector;
    el("rect", { x: x.net >= 0 ? mid : mid + W(x.net), y, width: Math.abs(W(x.net)), height: 14, rx: 3, fill: x.net >= 0 ? "var(--accent)" : "var(--cool)" }, s);
    el("text", { x: x.net >= 0 ? mid + W(x.net) + 6 : mid + W(x.net) - 6, y: y + 12, class: "tick", "text-anchor": x.net >= 0 ? "start" : "end" }, s).textContent = pct(x.net);
  });
  el("text", { x: lab, y: rows.length * 26 + 18, class: "tick" }, s).textContent = "Net weight by sector (long minus short)";
}

function health() {
  const names = { score: "Reports read", trade: "Trading", site: "Page" };
  $("health").innerHTML = Object.entries(D.health).map(([k, h]) =>
    `<span title="${h.message.replace(/"/g, "'")}"><i class="dot" style="background:${h.ok ? "var(--ok)" : "var(--accent)"}"></i>${names[k] || k} · ${new Date(h.at).toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}</span>`).join("")
    + `<span>Updated ${new Date(D.updated).toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}</span>`;
}

function draw() { if (!D) return; badge(); stats(); curve(); strip(); sectors(); feed(); recon(); risk(); vwap(); health(); }

fetch("data/live.json", { cache: "no-cache" }).then((r) => r.json()).then((d) => { D = d; draw(); })
  .catch(() => { $("stats").innerHTML = `<div class="stat"><b>—</b><span>Live data is not available now.</span></div>`; });
let rt; addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(draw, 120); });
$("find").addEventListener("input", highlight);
