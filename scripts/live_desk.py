"""The live job (decision D30). Each mode writes its result to data/live/health.json and never exits with an error
code (silent automation: the site shows the health).

  night    after each session: today's members (Wikipedia), new bars into the live price store, every model's
           prediction for every member into the append-only ledger, then (inside Alpaca's market-on-open window
           and with TRADING not "off") the ensemble's optimized book as OPG orders (`live.nightly.run_night`).
           Last, every ledger prediction whose two next opens are known is scored.
  flatten  close every position and cancel open orders (market orders). Set TRADING=off first to keep it closed.
  site     data for the web page: site-data/live.json (account, equity against SPY, tonight's predictions, the
           model leaderboard from the ledger, positions, health). Only what the page shows; no raw prices.

Usage: python -u scripts/live_desk.py night|flatten|site
Environment: ALPACA_API_KEY, ALPACA_SECRET_KEY; TRADING ("off" = kill switch: predictions only).
"""
import argparse
import json
import os
import time
import traceback

import numpy as np
import pandas as pd
import requests

from ghostdesk.data.alpaca_client import AlpacaClient
from ghostdesk.data.store import PriceStore, add_symbols, ingest_daily
from ghostdesk.live.alpaca_broker import Broker
from ghostdesk.live.ledger import Ledger, model_summary, score
from ghostdesk.live.members import WIKI_CURRENT, current_members, one_class_per_company
from ghostdesk.live.nightly import Deps, last_closed, run_night
from ghostdesk.live.predict import (
    ensemble_score,
    load_models,
    night_design,
    optimizer_target,
    predict_night,
)
from ghostdesk.paths import DATA_DIR, REPO_ROOT
from ghostdesk.research.backtest import half_spread

LIVE = DATA_DIR / "live"
SITE_DATA = REPO_ROOT / "site-data"
FIRST_DAY_BACK = 600  # the live store keeps about 600 calendar days

ap = argparse.ArgumentParser()
ap.add_argument("mode", choices=["night", "flatten", "site"])
args = ap.parse_args()
LIVE.mkdir(parents=True, exist_ok=True)


def now() -> pd.Timestamp:
    return pd.Timestamp.now(tz="UTC")


def health(mode: str, ok: bool, message: str, **extra) -> None:
    p = LIVE / "health.json"
    h = json.loads(p.read_text()) if p.exists() else {}
    h[mode] = {"at": now().isoformat(timespec="seconds"), "ok": ok, "message": message[:300], **extra}
    p.write_text(json.dumps(h, indent=1, default=str))
    print(f"[{mode}] {'ok' if ok else 'ERROR'}: {message}", flush=True)


def calendar(broker: Broker) -> pd.DataFrame:
    t = now().tz_convert("America/New_York").normalize().tz_localize(None)
    return broker.sessions(f"{t - pd.Timedelta(days=30):%Y-%m-%d}", f"{t + pd.Timedelta(days=10):%Y-%m-%d}")


def members() -> pd.DataFrame:
    path = LIVE / "members.parquet"
    try:
        html = requests.get(WIKI_CURRENT, headers={"User-Agent": "ghostdesk research (live job)"}, timeout=60).text
        m = current_members(html)
        if len(m) < 480:
            raise RuntimeError(f"only {len(m)} rows in the Wikipedia S&P 500 table")
        m.to_parquet(path, index=False)
        return m
    except Exception as e:
        if path.exists():
            print(f"members: {type(e).__name__}; using the last good list", flush=True)
            return pd.read_parquet(path)
        raise


def fetcher():
    client = AlpacaClient()

    def fetch(symbols, start, end, adjustment):
        parts = [client.bars(sorted(symbols)[i:i + 100], start, end, adjustment=adjustment)
                 for i in range(0, len(symbols), 100)]
        return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    return fetch


# ---------------------------------------------------------------------------------------------------- night
def night() -> None:
    broker = Broker()
    cal = calendar(broker)
    t = now()
    s = last_closed(cal, t)
    if s is None:
        health("night", True, "no closed session in the calendar window")
        return
    session = s["date"]
    m = members()
    store = PriceStore(LIVE / "store")
    fetch = fetcher()
    first = f"{session - pd.Timedelta(days=FIRST_DAY_BACK):%Y-%m-%d}"
    syms = sorted(set(m["symbol"]) | {"SPY"})
    ing = ingest_daily(store, fetch, syms, session, t, first_day=first)
    end = min(session.tz_localize("UTC") + pd.Timedelta(hours=23, minutes=59), t - pd.Timedelta(minutes=16))
    added = add_symbols(store, fetch, syms, first, end.isoformat().replace("+00:00", "Z"), t)
    print(f"store: {ing}; {added} new symbols", flush=True)

    models_dir = LIVE / "models"
    models = load_models(models_dir)
    meta = json.loads((models_dir / "meta.json").read_text())
    sectors = json.loads((models_dir / "sectors.json").read_text())
    adj = store.read("adj", start=session - pd.Timedelta(days=100), end=session)
    dv = (adj.assign(dv=adj["c"] * adj["v"]).sort_values("day").groupby("symbol")["dv"]
          .apply(lambda x: x.tail(63).mean()))
    one = one_class_per_company(m, dv)
    cache: dict = {}

    def get_night(sess):
        if sess not in cache:
            cache[sess] = night_design(store, one["symbol"].tolist(), sess, sectors, asof=t)
        return cache[sess]

    def predict(sess):
        n = get_night(sess)
        if n.session != sess:
            raise RuntimeError(f"store ends {n.session:%Y-%m-%d}, not {sess:%Y-%m-%d}: no prediction from old data")
        return predict_night(n, models)

    def target(rows):
        sess = pd.Timestamp(rows["session"].iloc[0])
        eq = float(broker.account()["equity"])
        held = {p["symbol"]: float(p["market_value"]) / eq for p in broker.position_rows()} if eq else {}
        return optimizer_target(get_night(sess), ensemble_score(rows, meta["ensemble_weights"]), pd.Series(held))

    deps = Deps(broker=broker, now=now, predict=predict, target=target, ledger=Ledger(LIVE / "ledger"),
                store=LIVE, trading=os.environ.get("TRADING", "on") != "off", log=lambda x: print(x, flush=True))
    ok, message, extra = run_night(deps, cal)
    health("night", ok, message, **extra, store_rows=ing.get("new_rows"))
    score_ledger(store, sectors)


def score_ledger(store: PriceStore, sectors: dict) -> None:
    led = Ledger(LIVE / "ledger")
    rows = led.read()
    if rows.empty:
        return
    raw = store.read("raw", start=rows["session"].min() - pd.Timedelta(days=40))
    opens = raw.pivot(index="day", columns="symbol", values="o").sort_index()
    hi = raw.pivot(index="day", columns="symbol", values="h").reindex_like(opens)
    lo = raw.pivot(index="day", columns="symbol", values="l").reindex_like(opens)
    cl = raw.pivot(index="day", columns="symbol", values="c").reindex_like(opens)
    hs = pd.DataFrame(half_spread(hi.to_numpy(), lo.to_numpy(), cl.to_numpy()), index=opens.index,
                      columns=opens.columns)
    sc = score(rows, opens, hs, pd.Series(sectors))
    sc.to_parquet(LIVE / "ledger_scores.parquet", index=False)
    summ = model_summary(sc) if len(sc) else pd.DataFrame()
    (LIVE / "ledger_summary.json").write_text(summ.to_json(orient="records"))
    ok, why = led.verify()
    health("score", ok, f"{sc['session'].nunique() if len(sc) else 0} sessions scored; ledger {why}")


# ---------------------------------------------------------------------------------------------------- flatten
def flatten() -> None:
    broker = Broker()
    before = broker.positions()
    broker.close_all()
    health("night", True, f"flatten: close orders sent for {len(before)} positions", flatten=True)


# ---------------------------------------------------------------------------------------------------- site
def site() -> None:
    from ghostdesk.live.dashboard_data import equity_curve, reconcile

    broker = Broker()
    acct = broker.account()
    hist = broker.history()
    start = f"{hist['day'].min():%Y-%m-%d}" if len(hist) else f"{now() - pd.Timedelta(days=30):%Y-%m-%d}"
    spy = AlpacaClient().bars(["SPY"], start, (now() - pd.Timedelta(minutes=20)).isoformat(), adjustment="all")
    led = Ledger(LIVE / "ledger")
    rows = led.read()
    latest = rows[rows["session"] == rows["session"].max()] if len(rows) else rows
    meta_p = LIVE / "models" / "meta.json"
    weights = json.loads(meta_p.read_text())["ensemble_weights"] if meta_p.exists() else {}
    ens = ensemble_score(latest, weights).sort_values() if len(latest) and weights else pd.Series(dtype=float)
    summ_p = LIVE / "ledger_summary.json"
    board = json.loads(summ_p.read_text()) if summ_p.exists() else []
    nights = sorted(LIVE.glob("night_*.json"))
    last_night = json.loads(nights[-1].read_text()) if nights else {}
    positions = broker.position_rows()
    eq = float(acct.get("equity") or 0)
    h = json.loads((LIVE / "health.json").read_text()) if (LIVE / "health.json").exists() else {}
    data = {
        "updated": now().isoformat(timespec="minutes"),
        "account": {"equity": eq, "cash": float(acct.get("cash") or 0)},
        "equity_curve": equity_curve(hist, spy),
        "predictions": {"session": f"{pd.Timestamp(latest['session'].iloc[0]):%Y-%m-%d}" if len(latest) else None,
                        "models": sorted(latest["model"].unique().tolist()) if len(latest) else [],
                        "stocks": int(latest["symbol"].nunique()) if len(latest) else 0,
                        "top": [{"symbol": s, "score": round(float(v), 4)} for s, v in ens.tail(10)[::-1].items()],
                        "bottom": [{"symbol": s, "score": round(float(v), 4)} for s, v in ens.head(10).items()]},
        "leaderboard": board,
        "ledger": {"sessions": int(rows["session"].nunique()) if len(rows) else 0, "rows": len(rows),
                   "verified": led.verify()[0]},
        "positions": [{"symbol": p["symbol"], "qty": float(p["qty"]), "value": float(p["market_value"]),
                       "pnl": float(p.get("unrealized_pl") or 0)} for p in positions],
        "recon": reconcile(last_night.get("target", {}), positions, eq) if last_night and eq else None,
        "last_night": {k: last_night.get(k) for k in ("session", "complete", "runs", "rejected", "unreached")},
        "health": h,
    }
    data["health"] = {**h, "site": {"at": now().isoformat(timespec="seconds"), "ok": True,
                                    "message": f"{len(positions)} positions, {data['ledger']['sessions']} ledger sessions"}}
    SITE_DATA.mkdir(exist_ok=True)
    (SITE_DATA / "live.json").write_text(json.dumps(data, separators=(",", ":"), default=_json))
    health("site", True, data["health"]["site"]["message"])


def _json(x):
    if isinstance(x, (np.floating, np.integer)):
        return x.item()
    return str(x)


if __name__ == "__main__":
    t0 = time.time()
    try:
        {"night": night, "flatten": flatten, "site": site}[args.mode]()
    except Exception as e:  # noqa: BLE001 - silent automation: record, do not fail the workflow
        traceback.print_exc()
        health(args.mode, False, f"{type(e).__name__}: {e}")
    print(f"{args.mode}: {time.time() - t0:.0f} s", flush=True)
