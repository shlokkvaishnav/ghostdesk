// ghostdesk page. Reads data/live.json (written by scripts/live_desk.py site): ledger, tonight's calls, scores, forward
// test. Reads assets/validation.json (a copy of docs/results/validation.json; a test keeps them equal) for the
// historical validation, which shows even when live.json is missing.
"use strict";
const $ = (id) => document.getElementById(id);
let D = null;

const DASH = "—", MINUS = "−";
const bad = (v) => v == null || typeof v !== "number" || !Number.isFinite(v);
// fixed decimals, a true minus sign, a plus sign only when asked for
const num = (v, d, sign = false) => {
  if (bad(v)) return DASH;
  const s = Math.abs(v).toFixed(d);
  if (Number(s) === 0) return s;
  return (v < 0 ? MINUS : sign ? "+" : "") + s;
};
const pct = (v, d = 1, sign = false) => (bad(v) ? DASH : num(v * 100, d, sign) + "%");  // v is a fraction
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const date = (s, opts) => {
  if (!s) return null;
  const t = new Date(/^\d{4}-\d{2}-\d{2}$/.test(s) ? s + "T12:00:00Z" : s);
  return Number.isNaN(t.getTime()) ? null : t.toLocaleString("en-US", opts);
};
const dfmt = (s) => date(s, { month: "short", day: "numeric", year: "numeric" });
const cell = (txt, cls = "") => `<td${txt === DASH ? ' class="dash"' : cls ? ` class="${cls}"` : ""}>${txt}</td>`;

const MODELS = {  // display order and kind
  reversal_1d: "baseline", reversal_5d: "baseline", ridge: "linear", lightgbm: "gradient boosting",
  transformer: "deep learning", chronos2: "deep learning, pretrained", timesfm25: "deep learning, pretrained",
};
const order = (a, b) => Object.keys(MODELS).indexOf(a) - Object.keys(MODELS).indexOf(b);
const mcell = (m) => `<td>${esc(m)}${MODELS[m] ? `<span class="kind">${MODELS[m]}</span>` : ""}</td>`;

// ------------------------------------------------------------------------------------------- historical validation
function validation(V) {
  const opt = V && V.optimizer, ms = (V && V.models) || {};
  if (!opt || !Object.keys(ms).length) {
    $("val-opt").innerHTML = "";
    $("val-models").innerHTML = `<p class="empty">The validation results could not be loaded.</p>`;
    return;
  }
  const [from, to] = V.validation || [];
  if (from && to) $("val-cap").textContent = `Historical validation, not an independent test: ${dfmt(from)} to ${dfmt(to)} ` +
    `(${opt.optimizer.sessions} sessions) was used to choose the models and the optimizer settings, so it is in-sample ` +
    `for those choices. Net figures include the bid-ask spread cost.`;
  const O = opt.optimizer, B = opt.decile_book;
  const tile = (head, o, b) => `<div class="stat"><b data-v="${head}">${o}<small>vs ${b}</small></b><span>${head}</span></div>`;
  $("val-opt").innerHTML =
    tile(`Net Sharpe: optimizer vs ${esc(opt.model)} decile book`, num(O.net_spread.sharpe, 2), num(B.net_spread.sharpe, 2)) +
    tile("Daily turnover: optimizer vs decile book", num(O.turnover, 2), num(B.turnover, 2));
  const rows = Object.keys(ms).sort(order).map((m) => {
    const v = ms[m].validation || {};
    return `<tr data-model="${esc(m)}">${mcell(m)}${cell(num(v.ic_mean, 4))}${cell(num(v.ic_t, 2))}${cell(pct(v.hit_rate, 1))}` +
      `${cell(num(v.gross && v.gross.sharpe, 2))}${cell(num(v.net_spread && v.net_spread.sharpe, 2))}${cell(num(v.turnover, 2))}</tr>`;
  }).join("");
  $("val-models").innerHTML = `<table class="board"><thead><tr><th>Model</th><th>Rank IC</th><th>IC t stat</th>` +
    `<th>Hit rate</th><th>Gross Sharpe</th><th>Net Sharpe</th><th>Turnover</th></tr></thead><tbody>${rows}</tbody></table>` +
    `<p class="note">Each model alone, as an equal-weight decile long-short book. The optimizer above uses the ${esc(opt.model)} scores. ` +
    `Rank IC: mean daily Spearman correlation of the score with the next-day residual return.</p>`;
}

// ------------------------------------------------------------------------------------------- live panels
function stats() {
  const F = D && D.forward_eval, days = F && F.compare ? F.compare.forward_days : null;
  const L = (D && D.ledger) || {}, P = (D && D.predictions) || {};
  const items = [
    [bad(L.sessions) ? DASH : String(L.sessions), "Nights in the ledger"],
    [(P.models || []).length ? String(P.models.length) : DASH, "Models predicting"],
    [bad(days) ? DASH : String(days), "Days of forward data"],
    ["Off", "Order execution"],
  ];
  $("stats").innerHTML = items.map(([b, s]) => `<div class="stat"><b>${b}</b><span>${s}</span></div>`).join("");
  if (P.stocks > 0) $("n-stocks").textContent = `all ${P.stocks}`;
  const note = $("stats-note");
  if (!D) { note.hidden = false; note.textContent = "Live data is not available right now. The live panels fill in after the next nightly run; the historical validation below does not depend on it."; }
  else { const u = date(D.updated, { month: "short", day: "numeric", year: "numeric", hour: "2-digit", minute: "2-digit", timeZoneName: "short" });
    note.hidden = !u; if (u) note.textContent = `Live data updated ${u}.`; }
}

function picks() {
  const P = (D && D.predictions) || {};
  const when = dfmt(P.session);
  if (when) $("tonight-cap").textContent = `The ensemble's strongest calls after the close of ${when}, out of ${P.stocks} stocks. They are recorded, not traded.`;
  const draw = (id, rows, color) => {
    const host = $(id);
    if (!rows || !rows.length) {
      host.innerHTML = `<li class="empty" style="display:block">${D ? "No predictions yet. The first calls appear after the first nightly run." : "Live data is not available right now, so there are no calls to show."}</li>`;
      return;
    }
    host.innerHTML = `<li class="head"><span>Stock</span><span>Strength</span><span class="v">Score</span></li>` + rows.map((r) => {
      const v = bad(r.score) ? 0 : Math.abs(r.score - 0.5) * 2;  // the score is a mean rank in [0, 1]
      return `<li><span class="tk">${esc(r.symbol)}</span><span class="bar"><i style="width:${(v * 100).toFixed(0)}%;background:${color}"></i></span><span class="v" title="score out of 100">${num(bad(r.score) ? null : r.score * 100, 0)}</span></li>`;
    }).join("");
  };
  draw("top", P.top, "var(--ok)");
  draw("bottom", P.bottom, "var(--accent)");
}

function board() {
  const host = $("board");
  if (!D) { host.innerHTML = `<p class="empty">Live data is not available right now, so the leaderboard cannot be shown.</p>`; return; }
  const rows = (D.leaderboard || []).slice().sort((a, b) => (bad(b.cum_pnl) ? -Infinity : b.cum_pnl) - (bad(a.cum_pnl) ? -Infinity : a.cum_pnl));
  if (!rows.length) { host.innerHTML = `<p class="empty">No scores yet. Scores start two sessions after the first prediction (the trade opens at the next open and closes at the one after).</p>`; return; }
  host.innerHTML = `<table class="board"><thead><tr><th>Model</th><th>Nights</th><th>Right picks</th><th>P&amp;L, decile book</th><th>Rank IC</th></tr></thead><tbody>` +
    rows.map((r) => `<tr>${mcell(r.model)}${cell(bad(r.sessions) ? DASH : String(r.sessions))}${cell(pct(r.profitable_share, 1))}` +
      `${cell(pct(r.cum_pnl, 2, true), bad(r.cum_pnl) ? "" : r.cum_pnl >= 0 ? "pos" : "neg")}${cell(num(r.ic_mean, 4))}</tr>`).join("") +
    `</tbody></table>`;
}

const METRICS = {  // label in forward_eval.json -> short label and format, the same as the validation table
  "rank IC (mean)": ["Rank IC", (v) => num(v, 4)], "rank IC t statistic": ["IC t stat", (v) => num(v, 2)],
  "hit rate of picks": ["Hit rate", (v) => pct(v, 1)],
};

function forward() {
  const host = $("forward"), F = D && D.forward_eval;
  if (!D) { host.innerHTML = `<p class="empty">Live data is not available right now, so the forward test cannot be shown.</p>`; return; }
  if (!F || !F.compare) { host.innerHTML = `<p class="empty">0 days of forward data. The forward evaluation has not run yet.</p>`; return; }
  const C = F.compare, n = C.forward_days || 0, B = F.book || {}, lab = C.labels || {};
  $("fwd-cap").textContent = `${C.headline}. The 2021-2022 numbers (${lab.validation}) were used to choose the models. Only the ${lab.forward}, scored on days after the models were frozen, is independent evidence.`;
  const rows = (C.rows || []).slice().sort((a, b) => order(a.model, b.model));
  const sess = [...new Set(rows.map((r) => r.validation_sessions).filter((v) => !bad(v)))];
  const vhead = `<span title="${esc(lab.validation)}">Validation</span>${sess.length === 1 ? `<br><small>${sess[0]} sessions</small>` : ""}`;
  const span = (m) => rows.filter((r) => r.model === m).length;
  let html = `<table class="board fw"><thead><tr><th>Model</th><th style="text-align:left">Metric</th><th>${vhead}</th><th><span title="${esc(lab.forward)}">Forward</span><br><small>${n} days</small></th></tr></thead><tbody>` +
    rows.map((r, i) => {
      const [name, fmt] = METRICS[r.metric] || [r.metric, (v) => num(v, 4)];
      const first = i === 0 || rows[i - 1].model !== r.model;
      const vs = sess.length === 1 || bad(r.validation_sessions) ? "" : ` <small>(${r.validation_sessions})</small>`;
      return `<tr data-model="${esc(r.model)}" data-metric="${esc(r.metric)}"${first ? "" : ' class="cont"'}>${first ? `<td rowspan="${span(r.model)}">${esc(r.model)}</td>` : ""}` +
        `<td class="metric">${esc(name)}</td>${cell(fmt(r.validation) + vs)}${cell(fmt(r.forward)).replace("<td", `<td title="${bad(r.forward_days) ? "no" : r.forward_days} forward days"`)}</tr>`;
    }).join("") + `</tbody></table>`;
  if (n === 0) html += `<p class="empty" style="margin-top:12px">0 days of forward data: no prediction has both of its next opens yet, so there is nothing to compare.</p>`;
  html += `<h3>Optimizer book, forward (${B.days || 0} days)</h3>`;
  html += B.days ? `<table class="board kv"><tbody><tr><td>Cumulative net return</td>${cell(pct(B.cum_return, 2, true))}</tr>` +
    `<tr><td>Sharpe (annualized)</td>${cell(num(B.sharpe, 2))}</tr><tr><td>Max drawdown</td>${cell(pct(B.max_drawdown, 2))}</tr>` +
    `<tr><td>Mean daily turnover</td>${cell(num(B.turnover_mean, 2))}</tr><tr><td>Total transaction cost</td>${cell(pct(B.cost_total == null ? null : Math.abs(B.cost_total), 3))}</tr></tbody></table>`
    : `<p class="empty">No matured target book yet.</p>`;
  host.innerHTML = html;
}

function health() {
  const badge = $("badge");
  if (!D) {
    badge.innerHTML = `<span class="dot" style="background:var(--muted)"></span>Live data unavailable`;
    $("health").innerHTML = `<span class="badge">No health report: live data is not available</span>`;
    return;
  }
  const h = D.health || {};
  const names = { night: "Night run", score: "Ledger", forward: "Forward test", site: "Page" };
  const isBad = Object.values(h).some((x) => x && x.ok === false);
  badge.innerHTML = `<span class="dot" style="background:${isBad ? "var(--accent)" : "var(--ok)"}"></span>${isBad ? "Needs a look" : "All systems normal"}`;
  badge.classList.toggle("bad", isBad);
  const shown = Object.entries(names).filter(([k]) => h[k]);
  $("health").innerHTML = shown.length ? shown.map(([k, n]) => {
    const at = date(h[k].at, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
    return `<span class="badge${h[k].ok ? "" : " bad"}" title="${esc(h[k].message || "")}"><span class="dot" style="background:${h[k].ok ? "var(--ok)" : "var(--accent)"}"></span>${n}${at ? " · " + at : ""}</span>`;
  }).join("") : `<span class="badge">No health report yet</span>`;
}

function draw() { stats(); picks(); board(); forward(); health(); }

fetch("assets/validation.json").then((r) => (r.ok ? r.json() : null)).catch(() => null).then(validation);
fetch("data/live.json", { cache: "no-store" })
  .then((r) => (r.ok ? r.json() : null))
  .catch(() => null)
  .then((d) => { D = d && typeof d === "object" ? d : null; draw(); });
