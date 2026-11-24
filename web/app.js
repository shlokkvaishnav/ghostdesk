// ghostdesk live page. Reads data/live.json (written by scripts/live_desk.py site) and draws inline SVG at the real width.
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
const pct = (v, d = 1) => (v > 0 ? "+" : v < 0 ? "−" : "") + Math.abs(v).toFixed(d) + "%";
const money = (v) => "$" + Math.round(v).toLocaleString("en-US");
const dfmt = (s) => new Date(s + "T12:00:00Z").toLocaleDateString("en-US", { month: "short", day: "numeric" });
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function showTip(ev, html) {
  tip.innerHTML = html;
  tip.style.left = Math.min(ev.clientX + 14, innerWidth - tip.offsetWidth - 8) + "px";
  tip.style.top = ev.clientY + 14 + "px";
  tip.style.opacity = 1;
}
const hideTip = () => (tip.style.opacity = 0);

function stats() {
  const c = D.equity_curve || [], last = c.length ? c[c.length - 1] : null;
  const vs = last && last.spy != null ? last.account - last.spy : null;
  const items = [
    [money(D.account.equity), "Account value"],
    [vs == null ? "—" : `<span class="${vs >= 0 ? "pos" : "neg"}">${pct(vs, 2)}</span>`, "Against SPY"],
    [String(D.ledger.sessions), "Nights in the ledger"],
    [String((D.predictions.models || []).length || "—"), "Models predicting"],
  ];
  $("stats").innerHTML = items.map(([b, s]) => `<div class="stat"><b>${b}</b><span>${s}</span></div>`).join("");
}

function niceStep(x) {
  const p = Math.pow(10, Math.floor(Math.log10(x || 1)));
  return [1, 2, 5, 10].map((k) => k * p).find((k) => k >= x) || p;
}

function curve() {
  const host = $("curve"), c = D.equity_curve || [];
  if (c.length < 2) { host.innerHTML = `<p class="empty">The line starts after the first full trading day.</p>`; return; }
  host.innerHTML = "";
  const h = 260, w = Math.max(280, host.clientWidth), m = { l: 44, r: 12, t: 12, b: 26 };
  const s = el("svg", { viewBox: `0 0 ${w} ${h}`, width: w, height: h, role: "img", "aria-label": "Account and SPY return" }, host);
  const vals = c.flatMap((p) => [p.account, p.spy]).filter((v) => v != null);
  let lo = Math.min(0, ...vals), hi = Math.max(0, ...vals);
  const pad = Math.max((hi - lo) * 0.12, 0.25); lo -= pad; hi += pad;
  const X = (i) => m.l + (i / (c.length - 1)) * (w - m.l - m.r), Y = (v) => m.t + (1 - (v - lo) / (hi - lo)) * (h - m.t - m.b);
  const step = niceStep((hi - lo) / 4);
  for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) {
    el("line", { x1: m.l, x2: w - m.r, y1: Y(v), y2: Y(v), class: "axis", "stroke-width": Math.abs(v) < 1e-9 ? 1.4 : 1 }, s);
    el("text", { x: m.l - 6, y: Y(v) + 4, "text-anchor": "end", class: "tick" }, s).textContent = pct(v, step < 1 ? 1 : 0);
  }
  const n = Math.min(5, c.length);
  for (let k = 0; k < n; k++) {
    const i = Math.round((k / (n - 1 || 1)) * (c.length - 1));
    el("text", { x: X(i), y: h - 6, "text-anchor": "middle", class: "tick" }, s).textContent = dfmt(c[i].day);
  }
  const line = (key, color, width) => el("path", { d: c.map((p, i) => p[key] == null ? "" : `${i ? "L" : "M"}${X(i)},${Y(p[key])}`).join(""),
    fill: "none", stroke: color, "stroke-width": width, "stroke-linejoin": "round" }, s);
  line("spy", "var(--muted)", 1.6);
  line("account", "var(--accent)", 2.4);
  const hit = el("rect", { x: m.l, y: m.t, width: w - m.l - m.r, height: h - m.t - m.b, fill: "transparent" }, s);
  hit.addEventListener("mousemove", (ev) => {
    const r = s.getBoundingClientRect(), i = Math.round(((ev.clientX - r.left - m.l) / (w - m.l - m.r)) * (c.length - 1));
    const p = c[Math.max(0, Math.min(c.length - 1, i))];
    showTip(ev, `${dfmt(p.day)}<br>ghostdesk ${pct(p.account, 2)}<br>SPY ${p.spy == null ? "—" : pct(p.spy, 2)}`);
  });
  hit.addEventListener("mouseleave", hideTip);
}

function picks() {
  const P = D.predictions || {};
  if (P.session) $("tonight-cap").textContent = `The ensemble's strongest calls after the close of ${dfmt(P.session)}, out of ${P.stocks} stocks.`;
  const draw = (id, rows, color) => {
    const host = $(id);
    if (!rows || !rows.length) { host.innerHTML = `<li class="empty" style="display:block">The first predictions appear after the first night.</li>`; return; }
    host.innerHTML = rows.map((r) => {
      const v = Math.abs(r.score - 0.5) * 2;  // the score is a mean rank in [0, 1]
      return `<li><span class="tk">${esc(r.symbol)}</span><span class="bar"><i style="width:${(v * 100).toFixed(0)}%;background:${color}"></i></span><span class="v">${(r.score * 100).toFixed(0)}</span></li>`;
    }).join("");
  };
  draw("top", P.top, "var(--ok)");
  draw("bottom", P.bottom, "var(--accent)");
}

function board() {
  const host = $("board"), rows = (D.leaderboard || []).slice().sort((a, b) => b.cum_pnl - a.cum_pnl);
  if (!rows.length) { host.innerHTML = `<p class="empty">Scores start two sessions after the first prediction (the trade opens at the next open and closes at the one after).</p>`; return; }
  const f = (v, d) => (v == null || Number.isNaN(v) ? "—" : v.toFixed(d));
  host.innerHTML = `<table class="board"><thead><tr><th>Model</th><th>Nights</th><th>Right picks</th><th>P&amp;L, decile book</th><th>Rank IC</th></tr></thead><tbody>` +
    rows.map((r) => `<tr><td>${esc(r.model)}</td><td>${r.sessions}</td><td>${f(r.profitable_share * 100, 1)}%</td>` +
      `<td class="${r.cum_pnl >= 0 ? "pos" : "neg"}">${pct(r.cum_pnl * 100, 2)}</td><td>${f(r.ic_mean, 3)}</td></tr>`).join("") +
    `</tbody></table>`;
}

function health() {
  const h = D.health || {};
  const names = { night: "Night run", score: "Ledger", site: "Page" };
  const bad = Object.values(h).some((x) => x && x.ok === false);
  $("badge").innerHTML = `<span class="dot" style="background:${bad ? "var(--accent)" : "var(--ok)"}"></span>${bad ? "Needs a look" : "All systems normal"}`;
  if (bad) $("badge").classList.add("bad");
  $("health").innerHTML = Object.entries(names).filter(([k]) => h[k]).map(([k, n]) =>
    `<span class="badge${h[k].ok ? "" : " bad"}" title="${esc(h[k].message || "")}"><span class="dot" style="background:${h[k].ok ? "var(--ok)" : "var(--accent)"}"></span>${n} · ${new Date(h[k].at).toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}</span>`).join("");
}

function draw() { stats(); curve(); picks(); board(); health(); }

fetch("data/live.json", { cache: "no-store" }).then((r) => r.json()).then((d) => { D = d; draw(); })
  .catch(() => { $("stats").innerHTML = `<p class="empty">Live data is not available right now.</p>`; });
let rt;
addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(() => D && curve(), 120); });
