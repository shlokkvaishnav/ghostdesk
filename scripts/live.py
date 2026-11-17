"""The live job (Step 5, decision D15). Three modes; each writes its result to data/live/health.json and never exits
with an error code (silent automation: the site shows the health).

  score   today's S&P 500 (Wikipedia), each company's report list (SEC), and the text-change features of every
          latest pair that is not in data/live/scores.parquet yet. About 2 minutes a day; about 30 minutes from
          an empty cache.
  trade   `live.runner.run_trade`: rebalances in the first sessions of a month until one run completes (or at
          once on an empty account), from the open to 150 minutes after it: quintiles of `composite` at the
          last close, targets, VWAP child orders, fills, and a reconciliation of the book. Elsewhere it does
          nothing. --dry-run prints the plan and sends no order.
  flatten close every position and cancel open orders (market orders). The strategy enters again on the next
          first session of a month, so set the repository variable TRADING=off first to keep it stopped.
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

import pandas as pd
import requests

from ghostdesk.data.alpaca import AlpacaClient
from ghostdesk.filings.edgar import DATA_DIR, REPO_ROOT, EdgarClient, Filing, download_filing_html
from ghostdesk.filings.index import index_for, pair_previous
from ghostdesk.live.broker import Broker
from ghostdesk.live.runner import Config, Deps, run_trade
from ghostdesk.live.signal import (
    WIKI_CURRENT,
    current_members,
    latest_pairs,
)
from ghostdesk.signal.features import pair_features, parts

LIVE = DATA_DIR / "live"
SITE_DATA = REPO_ROOT / "site-data"
START = Config().start  # the trade settings live in `live.runner.Config`

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
            failed.append(int(cik))
            print(f"report list failed for CIK {cik}: {type(e).__name__}", flush=True)
    fresh = pd.concat(frames, ignore_index=True)
    old_path = LIVE / "index.parquet"
    if failed and old_path.exists():  # a company whose list failed keeps its last rows (pairs are found again below)
        old = pd.read_parquet(old_path)
        keep = old[old["cik"].isin(failed)][fresh.columns.intersection(old.columns)]
        fresh = pd.concat([fresh, keep], ignore_index=True)
    index = pair_previous(fresh)
    index.to_parquet(old_path, index=False)
    past = pd.DatetimeIndex(cal["date"])
    last_close = cal.loc[cal["close_utc"] <= now(), "close_utc"].iloc[-1]
    latest = pd.concat([latest_pairs(index, past, now() + pd.Timedelta(days=1)),  # tradeable by the next session
                        latest_pairs(index, past, last_close)]).drop_duplicates(["cik", "accession"])

    path = LIVE / "scores.parquet"
    have = pd.read_parquet(path) if path.exists() else pd.DataFrame(columns=["cik", "accession"])
    ok_rows = have if have.empty else have[have["error"].fillna("") == ""]
    done = set(zip(ok_rows["cik"], ok_rows["accession"], strict=True))  # errored rows are tried again
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
def trade() -> None:
    """One trade run through `live.runner` (gate, plan, VWAP orders, fills, reconciliation)."""
    broker = Broker()
    deps = Deps(broker=broker, now=now, sleep=time.sleep, dollar_volume=_dollar_volume, minute_bars=_minute_bars,
                store=LIVE, log=lambda m: print(m, flush=True))
    ok, message, extra = run_trade(deps, sessions(broker), Config(), dry_run=args.dry_run)
    health("trade", ok, message, **extra)


def _dollar_volume(symbols: list[str]) -> pd.Series:
    end = now() - pd.Timedelta(minutes=20)  # the free plan has no SIP data for the last 15 minutes
    bars = AlpacaClient().bars(symbols, f"{end - pd.Timedelta(days=95):%Y-%m-%d}", end.isoformat(),
                               adjustment="raw")
    if bars.empty:
        return pd.Series(dtype=float)
    bars["dv"] = bars["c"] * bars["v"]
    return bars.sort_values("t").groupby("symbol")["dv"].apply(lambda s: s.tail(63).mean())


def _minute_bars(symbols: list[str], start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    return AlpacaClient().bars(symbols, start.isoformat(), end.isoformat(), timeframe="1Min", adjustment="raw")


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
