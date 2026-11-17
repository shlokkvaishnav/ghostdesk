"""The live job (Step 5, decision D15). Three modes; each writes its result to data/live/health.json and never exits
with an error code (silent automation: the site shows the health).

  score   today's S&P 500 (Wikipedia), each company's report list (SEC), and the text-change features of every
          latest pair that is not in data/live/scores.parquet yet. About 2 minutes a day; about 30 minutes from
          an empty cache.
  trade   on the first session of a month (or the first run on an empty account), between the open and 150
          minutes after it: quintiles of `composite` at the last close, targets, and VWAP child orders over the
          buckets left in the first hour. Elsewhere it does nothing. --dry-run prints the plan, sends no order.
  flatten close every position and cancel open orders (market orders; the strategy stops until the next run of
          `trade` on an empty account, so set the repository variable TRADING=off first to keep it stopped).
  off     record that trading is switched off (repository variable TRADING=off); sends nothing.
  site    data for the web page: site-data/live.json (account, equity against SPY, positions, new reports,
          rebalances, health). No raw prices, only what the page shows.

Usage: python -u scripts/live.py score|trade|site [--dry-run] [--per-sec 5] [--limit N]
"""
import argparse
import json
import tempfile
import time
import traceback
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from ghostdesk.data.alpaca import AlpacaClient
from ghostdesk.filings.edgar import DATA_DIR, REPO_ROOT, EdgarClient, Filing, download_filing_html
from ghostdesk.filings.index import index_for, pair_previous
from ghostdesk.live.broker import Broker, BrokerError
from ghostdesk.live.portfolio import (
    buckets_left,
    child_orders,
    per_name_value,
    side_of,
    target_shares,
    too_expensive,
    trades,
    unit_of,
)
from ghostdesk.live.signal import (
    WIKI_CURRENT,
    composite,
    current_members,
    latest_pairs,
    one_class_per_company,
    quintile,
)
from ghostdesk.signal.features import pair_features, parts
from ghostdesk.signal.study import FULL

LIVE = DATA_DIR / "live"
SITE_DATA = REPO_ROOT / "site-data"
START = "2026-11-16"  # the paper account was opened on this day
WINDOW_MIN = 150
LEG = 0.9  # each leg 90% of equity: gross 1.8x, inside the 2x margin with room for price moves (D15)

ap = argparse.ArgumentParser()
ap.add_argument("mode", choices=["score", "trade", "flatten", "off", "site"])
ap.add_argument("--dry-run", action="store_true")
ap.add_argument("--per-sec", type=float, default=5.0)
ap.add_argument("--limit", type=int, default=0, help="score: only the first N companies (a local test)")
args = ap.parse_args()
LIVE.mkdir(parents=True, exist_ok=True)


def now() -> pd.Timestamp:
    return pd.Timestamp.now(tz="UTC")


def health(mode: str, ok: bool, message: str, **extra) -> None:
    p = LIVE / "health.json"
    h = json.loads(p.read_text()) if p.exists() else {}
    h[mode] = {"at": now().isoformat(timespec="seconds"), "ok": ok, "message": message[:300], **extra}
    p.write_text(json.dumps(h, indent=1))
    print(f"[{mode}] {'ok' if ok else 'ERROR'}: {message}", flush=True)


def sessions(broker: Broker) -> pd.DataFrame:
    today = now().tz_convert("America/New_York").normalize().tz_localize(None)
    return broker.sessions(f"{today - pd.Timedelta(days=500):%Y-%m-%d}", f"{today + pd.Timedelta(days=40):%Y-%m-%d}")


def members() -> pd.DataFrame:
    html = requests.get(WIKI_CURRENT, headers={"User-Agent": "ghostdesk research (live job)"}, timeout=60).text
    m = current_members(html)
    if len(m) < 480:  # the page changed or failed: keep the last good list
        raise RuntimeError(f"only {len(m)} rows in the Wikipedia S&P 500 table")
    m.to_parquet(LIVE / "members.parquet", index=False)
    return m


# ---------------------------------------------------------------------------------------------------- score
def score() -> None:
    broker = Broker()
    cal = sessions(broker)
    m = members()
    sec = EdgarClient(cache_dir=Path(tempfile.mkdtemp()), max_per_sec=args.per_sec)  # empty cache: fresh lists
    since = f"{now() - pd.Timedelta(days=560):%Y-%m-%d}"
    frames, failed = [], []
    ciks = sorted(m["cik"].unique())
    for cik in ciks[:args.limit] if args.limit else ciks:
        try:
            frames.append(index_for(sec, int(cik), since=since))
        except Exception as e:  # noqa: BLE001 - one company's error does not stop the run
            failed.append(f"{cik}: {type(e).__name__}")
    index = pair_previous(pd.concat(frames, ignore_index=True))
    index.to_parquet(LIVE / "index.parquet", index=False)
    past = pd.DatetimeIndex(cal["date"])
    last_close = cal.loc[cal["close_utc"] <= now(), "close_utc"].iloc[-1]
    latest = pd.concat([latest_pairs(index, past, now() + pd.Timedelta(days=1)),  # tradeable by the next session
                        latest_pairs(index, past, last_close)]).drop_duplicates(["cik", "accession"])

    path = LIVE / "scores.parquet"
    have = pd.read_parquet(path) if path.exists() else pd.DataFrame(columns=["cik", "accession"])
    done = set(zip(have["cik"], have["accession"], strict=True))
    todo = latest[[(c, a) not in done for c, a in zip(latest["cik"], latest["accession"], strict=True)]]
    by = index.drop_duplicates(["cik", "accession"]).set_index(["cik", "accession"])

    def filing(cik, acc) -> Filing:
        r = by.loc[(cik, acc)]
        return Filing(int(cik), acc, r["form"], f"{r['filing_date']:%Y-%m-%d}", f"{r['report_date']:%Y-%m-%d}",
                      r["primary_doc"], str(r["accepted_utc"]))

    rows, t0 = [], time.time()
    for i, r in enumerate(todo.itertuples()):
        row = {"cik": int(r.cik), "accession": r.accession, "prev_accession": r.prev_accession, "form": r.form,
               "report_date": r.report_date, "accepted_utc": r.accepted_utc, "error": ""}
        try:
            cur = parts(download_filing_html(sec, filing(r.cik, r.accession), store=False), r.form)
            prev = parts(download_filing_html(sec, filing(r.cik, r.prev_accession), store=False), r.form)
            row |= pair_features(cur, prev)
        except Exception as e:  # noqa: BLE001
            row["error"] = f"{type(e).__name__}: {e}"[:200]
        rows.append(row)
        if (i + 1) % 25 == 0:
            _save_scores(have, rows, path)
            print(f"{i + 1}/{len(todo)} pairs, {(time.time() - t0) / (i + 1):.1f} s each", flush=True)
    _save_scores(have, rows, path)
    errors = sum(1 for r in rows if r["error"])
    health("score", True, f"{len(m)} members, {len(latest)} with a recent pair, {len(rows)} new pairs scored "
           f"({errors} errors), {len(failed)} report lists failed", members=len(m), new_pairs=len(rows),
           errors=errors, failed_lists=len(failed))


def _save_scores(have: pd.DataFrame, rows: list[dict], path: Path) -> None:
    if rows:
        new = pd.DataFrame(rows)
        out = new if have.empty else pd.concat([have, new], ignore_index=True)
        out.drop_duplicates(["cik", "accession"], keep="last").to_parquet(path, index=False)


# ---------------------------------------------------------------------------------------------------- trade
def formation(cal: pd.DataFrame, today: pd.Timestamp) -> tuple[pd.DataFrame, int, pd.Timestamp]:
    """Members with the features of their latest pair at the last close before `today`'s session, the count of
    pairs without features, and that close."""
    prev_close = cal.loc[cal["date"] < today, "close_utc"].iloc[-1]
    m = pd.read_parquet(LIVE / "members.parquet")
    index = pd.read_parquet(LIVE / "index.parquet")
    scores = pd.read_parquet(LIVE / "scores.parquet")
    lp = latest_pairs(index, pd.DatetimeIndex(cal["date"]), prev_close)
    lp = lp.merge(scores[["cik", "accession", *FULL]], on=["cik", "accession"], how="left")
    missing = int(lp[FULL[0]].isna().sum())
    f = m.merge(lp[["cik", "accession", "form", "tradeable", *FULL]], on="cik", how="left")
    return f, missing, prev_close


def trade() -> None:
    broker = Broker()
    clock = broker.clock()
    cal = sessions(broker)
    t = now()
    today_row = cal[cal["date"] == t.tz_convert("America/New_York").normalize().tz_localize(None)]
    if today_row.empty:
        return health("trade", True, "not a trading day")
    today, open_utc = today_row["date"].iloc[0], today_row["open_utc"].iloc[0]
    month_sessions = cal[cal["date"].dt.to_period("M") == today.to_period("M")]
    first_of_month = today == month_sessions["date"].iloc[0]
    account = broker.account()
    first_run = not broker.positions() and not broker.orders(after=f"{START}T00:00:00Z")
    minutes = (t - open_utc).total_seconds() / 60
    if not args.dry_run:  # a dry run sends no order, so it may show the plan on any day and at any time
        if not (first_of_month or first_run):
            return health("trade", True, f"no rebalance today ({today:%Y-%m-%d})")
        if not clock["is_open"] or not (0 <= minutes <= WINDOW_MIN):
            return health("trade", True, f"rebalance day, but {minutes:.0f} min from the open (window 0-{WINDOW_MIN})")
    minutes = min(max(minutes, 0.0), WINDOW_MIN)

    f, missing, prev_close = formation(cal, today)
    one = one_class_per_company(f, _dollar_volume(f["symbol"].tolist()))
    one = one.dropna(subset=[FULL[0]]).copy()
    one["composite"] = composite(one).to_numpy()
    one["q"] = quintile(one["composite"]).to_numpy()
    sides = pd.Series(np.where(one["q"] == 5, 1, np.where(one["q"] == 1, -1, 0)), index=one["symbol"])
    current = broker.positions()
    assets = {s: _asset(broker, s) for s in sorted(set(sides[sides != 0].index) | set(current))}
    shortable = {s: bool(assets[s].get("shortable") and assets[s].get("easy_to_borrow"))
                 for s in sides[sides == -1].index}
    sides[[s for s, ok in shortable.items() if not ok]] = 0
    fractional = {s for s, a in assets.items() if a.get("fractionable")}
    prices = pd.Series(broker.latest_prices(sorted(assets)))
    equity = float(account["equity"])
    target = target_shares(sides, prices, equity, leg=LEG, fractional=fractional)
    per = per_name_value(sides, equity, leg=LEG)
    plan = trades(target, current, prices, per)
    gross = {k: sum(abs(q) * float(prices.get(s, 0)) for s, q in target.items() if np.sign(q) == sign) / equity
             for k, sign in (("long", 1), ("short", -1))}
    weights = buckets_left(minutes)
    log = {"date": f"{today:%Y-%m-%d}", "formation_close": prev_close.isoformat(), "equity": equity,
           "first_run": bool(first_run), "stocks_with_signal": len(one), "missing_scores": missing,
           "long": int((sides == 1).sum()), "short": int((sides == -1).sum()),
           "not_shortable": [s for s, ok in shortable.items() if not ok], "start_minute": round(minutes, 1),
           "buckets": [b for b, _ in weights], "arrival": {s: float(prices[s]) for s in plan if s in prices},
           "target": {s: float(q) for s, q in target.items()}, "leg": LEG,
           "target_gross": {k: round(v, 4) for k, v in gross.items()},
           "too_expensive": too_expensive(sides, target, prices),
           "signal": one[["symbol", "form", "composite", "q"]].to_dict("records"), "orders": []}
    print(f"rebalance {today:%Y-%m-%d}: {len(plan)} stocks to trade, {len(weights)} buckets from minute "
          f"{weights[0][0]}; long {log['long']}, short {log['short']}, equity {equity:,.0f}; target gross long "
          f"{gross['long']:.3f}, short {gross['short']:.3f}; fractional longs "
          f"{sum(1 for s, q in target.items() if q > 0 and q != round(q))}; too expensive {log['too_expensive']}",
          flush=True)
    if args.dry_run:
        for s, (a, b) in list(plan.items())[:15]:
            print(f"  {s:6} {a:>6} -> {b:>6}")
        return health("trade", True, f"dry run: {len(plan)} stocks would trade", dry_run=True)

    w = [x for _, x in weights]
    kids = {s: child_orders(a, b, w, unit_of(s, a, b, fractional)) for s, (a, b) in plan.items()}
    stopped: set[str] = set()
    for k, (start_min, _) in enumerate(weights):
        wait = (open_utc + pd.Timedelta(minutes=start_min) - now()).total_seconds()
        if wait > 0:
            time.sleep(wait)
        for s, per_bucket in kids.items():
            for j, q in enumerate(per_bucket[k]):
                if s in stopped:
                    break
                cid = f"gd-{today:%Y%m%d}-{k:02d}{j}-{s}"
                try:
                    o = broker.submit(s, abs(q), side_of(q), cid)
                    log["orders"].append({"symbol": s, "bucket": k, "qty": q, "id": o["id"], "status": o["status"]})
                    if j == 0 and len(per_bucket[k]) > 1:
                        _wait_filled(broker, o["id"])  # a flip: the close must fill before the open
                except BrokerError as e:
                    stopped.add(s)  # this stock's later children would fail the same way
                    log["orders"].append({"symbol": s, "bucket": k, "qty": q, "error": e.message})
        (LIVE / f"rebalance_{today:%Y%m%d}.json").write_text(json.dumps(log, indent=1, default=str))
    _final_fills(broker, log)
    (LIVE / f"rebalance_{today:%Y%m%d}.json").write_text(json.dumps(log, indent=1, default=str))
    errs = sum(1 for o in log["orders"] if "error" in o)
    health("trade", errs == 0, f"rebalance {today:%Y-%m-%d}: {len(log['orders'])} orders, {errs} rejected",
           orders=len(log["orders"]), rejected=errs)


def _dollar_volume(symbols: list[str]) -> pd.Series:
    end = now() - pd.Timedelta(minutes=20)  # the free plan has no SIP data for the last 15 minutes
    bars = AlpacaClient().bars(symbols, f"{end - pd.Timedelta(days=95):%Y-%m-%d}", end.isoformat(),
                               adjustment="raw")
    if bars.empty:
        return pd.Series(dtype=float)
    bars["dv"] = bars["c"] * bars["v"]
    return bars.sort_values("t").groupby("symbol")["dv"].apply(lambda s: s.tail(63).mean())


def _asset(broker: Broker, symbol: str) -> dict:
    try:
        return broker.asset(symbol)
    except BrokerError:
        return {}


def _wait_filled(broker: Broker, order_id: str, timeout_s: float = 120) -> None:
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        if broker.order(order_id)["status"] in ("filled", "canceled", "rejected", "expired"):
            return
        time.sleep(2)


def _final_fills(broker: Broker, log: dict) -> None:
    time.sleep(20)
    for o in log["orders"]:
        if "id" in o:
            try:
                r = broker.order(o["id"])
                o.update(status=r["status"], filled_qty=float(r.get("filled_qty") or 0),
                         price=float(r["filled_avg_price"]) if r.get("filled_avg_price") else None,
                         filled_at=r.get("filled_at"))
            except BrokerError as e:
                o["fill_error"] = e.message


def flatten() -> None:
    broker = Broker()
    before = broker.positions()
    broker.close_all()
    health("trade", True, f"flatten: close orders sent for {len(before)} positions", flatten=True)


def off() -> None:
    health("trade", True, "trading is off (repository variable TRADING=off); no order sent", off=True)


# ---------------------------------------------------------------------------------------------------- site
def site() -> None:
    from ghostdesk.live.site import build

    broker = Broker()
    hist = broker.history()
    spy = AlpacaClient().bars(["SPY"], f"{hist['day'].min():%Y-%m-%d}" if len(hist) else START, (now() - pd.Timedelta(minutes=20)).isoformat(), adjustment="all")
    rebal = [json.loads(p.read_text()) for p in sorted(LIVE.glob("rebalance_*.json"))]
    scores = pd.read_parquet(LIVE / "scores.parquet") if (LIVE / "scores.parquet").exists() else None
    m = pd.read_parquet(LIVE / "members.parquet") if (LIVE / "members.parquet").exists() else None
    h = json.loads((LIVE / "health.json").read_text()) if (LIVE / "health.json").exists() else {}
    positions = broker.position_rows()
    data = build(account=broker.account(), positions=positions, history=hist, spy=spy,
                 rebalances=rebal, scores=scores, members=m, health=h, at=now(),
                 next_rebalance=None if positions else _next_rebalance(broker))
    SITE_DATA.mkdir(exist_ok=True)
    (SITE_DATA / "live.json").write_text(json.dumps(data, separators=(",", ":"), default=str))
    health("site", True, f"live.json: {len(data['positions'])} positions, {len(data['reports'])} new reports")


def _next_rebalance(broker: Broker) -> str | None:
    """The first session of the next month (the first run on an empty account is started by hand)."""
    cal = sessions(broker)
    today = now().tz_convert("America/New_York").normalize().tz_localize(None)
    d = cal["date"]
    firsts = d[d.dt.to_period("M") != d.shift().dt.to_period("M")]
    nxt = firsts[firsts > today]
    return f"{nxt.iloc[0]:%Y-%m-%d}" if len(nxt) else None


if __name__ == "__main__":
    try:
        {"score": score, "trade": trade, "flatten": flatten, "off": off, "site": site}[args.mode]()
    except Exception as e:  # noqa: BLE001 - silent automation: record, do not fail the workflow
        traceback.print_exc()
        health(args.mode, False, f"{type(e).__name__}: {e}")
