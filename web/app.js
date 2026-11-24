// ghostdesk page. Reads data/live.json (written by scripts/live_desk.py site): ledger, tonight's calls, scores, forward test.
"use strict";
const $ = (id) => document.getElementById(id);
const tip = $("tip");
let D = null;

const pct = (v, d = 1) => (v > 0 ? "+" : v < 0 ? "−" : "") + Math.abs(v).toFixed(d) + "%";
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
  const F = D.forward_eval, days = F && F.compare ? F.compare.forward_days : 0;
  const items = [
    [String(D.ledger.sessions), "Nights in the ledger"],
    [String((D.predictions.models || []).length || "—"), "Models predicting"],
    [String(days || 0), "Days of forward data"],
    ["Off", "Order execution"],
  ];
  $("stats").innerHTML = items.map(([b, s]) => `<div class="stat"><b>${b}</b><span>${s}</span></div>`).join("");
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

function forward() {
  const F = D.forward_eval, host = $("forward");
  if (!F) { host.innerHTML = `<p class="empty">0 days of forward data. The forward evaluation has not run yet.</p>`; return; }
  const C = F.compare, n = C.forward_days, B = F.book || {};
  $("fwd-cap").textContent = `${C.headline}. The 2021-2022 numbers (${C.labels.validation}) were used to choose the models. Only the ${C.labels.forward}, scored on days after the models were frozen, is independent evidence.`;
  const f = (v, d) => (v == null || Number.isNaN(v) ? "—" : v.toFixed(d));
  const dash = `<span title="no forward data yet">—</span>`;
  const rows = (C.rows || []).filter((r) => ["reversal_1d", "reversal_5d", "ridge", "lightgbm"].includes(r.model) || r.forward != null);
  let html = `<table class="board"><thead><tr><th>Model</th><th>Metric</th><th>${esc(C.labels.validation)}<br><small>sessions</small></th><th>${esc(C.labels.forward)}<br><small>days</small></th></tr></thead><tbody>` +
    rows.map((r) => `<tr><td>${esc(r.model)}</td><td>${esc(r.metric)}</td><td>${f(r.validation, 4)} <small>(${r.validation_sessions ?? "—"} sessions)</small></td>` +
      `<td>${r.forward == null ? dash : f(r.forward, 4)} <small>(${r.forward_days} days)</small></td></tr>`).join("") + `</tbody></table>`;
  if (n === 0) html += `<p class="empty" style="margin-top:12px">0 days of forward data: no prediction has both of its next opens yet, so there is nothing to compare.</p>`;
  html += `<h3>Optimizer book, forward (${B.days || 0} days)</h3>`;
  html += B.days ? `<table class="board"><tbody><tr><td>Cumulative net return</td><td>${pct(B.cum_return * 100, 2)}</td></tr>` +
    `<tr><td>Sharpe (annualized)</td><td>${f(B.sharpe, 2)}</td></tr><tr><td>Max drawdown</td><td>${pct(B.max_drawdown * 100, 2)}</td></tr>` +
    `<tr><td>Mean daily turnover</td><td>${f(B.turnover_mean, 3)}</td></tr><tr><td>Total transaction cost</td><td>${pct(B.cost_total * 100, 3)}</td></tr></tbody></table>`
    : `<p class="empty">No matured target book yet.</p>`;
  host.innerHTML = html;
}

function health() {
  const h = D.health || {};
  const names = { night: "Night run", score: "Ledger", forward: "Forward test", site: "Page" };
  const bad = Object.values(h).some((x) => x && x.ok === false);
  $("badge").innerHTML = `<span class="dot" style="background:${bad ? "var(--accent)" : "var(--ok)"}"></span>${bad ? "Needs a look" : "All systems normal"}`;
  if (bad) $("badge").classList.add("bad");
  $("health").innerHTML = Object.entries(names).filter(([k]) => h[k]).map(([k, n]) =>
    `<span class="badge${h[k].ok ? "" : " bad"}" title="${esc(h[k].message || "")}"><span class="dot" style="background:${h[k].ok ? "var(--ok)" : "var(--accent)"}"></span>${n} · ${new Date(h[k].at).toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}</span>`).join("");
}

function draw() { stats(); picks(); board(); forward(); health(); }

fetch("data/live.json", { cache: "no-store" }).then((r) => r.json()).then((d) => { D = d; draw(); })
  .catch(() => { $("stats").innerHTML = `<p class="empty">Live data is not available right now.</p>`; });
