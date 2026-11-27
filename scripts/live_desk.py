"""The live job (decisions D30, D38). Each mode writes its result to data/live/health.json. `site` and `flatten` never
exit with an error code; `night` exits with code 1 when the models fail their check or the run fails (D38), so the
workflow run fails and the failure is seen. A successful run prints only its log.

  night    after each session: today's members (Wikipedia), new bars into the live price store, every model's
           prediction for every member into the append-only ledger, then (inside Alpaca's market-on-open window
           and only with TRADING exactly "on") the ensemble's optimized book as OPG orders (`live.nightly.run_night`).
           The models are the release `models-v1`, checked against docs/results/MODEL_MANIFEST.json first.
           Last, every ledger prediction whose two next opens are known is scored.
  flatten  close every position and cancel open orders (market orders). Set TRADING=off first to keep it closed.
  site     data for the web page: site-data/live.json (account, equity against SPY, tonight's predictions, the
           model leaderboard from the ledger, positions, health). Only what the page shows; no raw prices.

Usage: python -u scripts/live_desk.py night|flatten|site
Environment: ALPACA_API_KEY, ALPACA_SECRET_KEY; TRADING (orders only when exactly "on"; anything else: predictions
only). GHOSTDESK_MODELS: the folder with the release files (default data/live/models).
"""
import argparse
import json
import os
import time
import traceback
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from ghostdesk.data.alpaca_client import AlpacaClient
from ghostdesk.data.store import PriceStore, add_symbols, ingest_daily
from ghostdesk.live.alpaca_broker import Broker
from ghostdesk.live.compare import load_validation
from ghostdesk.live.forward import build_report, read_books
from ghostdesk.live.ledger import Ledger, model_summary, refused, score
from ghostdesk.live.members import WIKI_CURRENT, current_members, one_class_per_company
from ghostdesk.live.model_release import load_manifest, verify
from ghostdesk.live.nightly import Deps, last_closed, run_night, trading_enabled
from ghostdesk.live.predict import (
    LIVE_MODELS,
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
VALIDATION = REPO_ROOT / "docs" / "results" / "validation.json"
MANIFEST = REPO_ROOT / "docs" / "results" / "MODEL_MANIFEST.json"
MODELS = Path(os.environ.get("GHOSTDESK_MODELS") or LIVE / "models")
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
class NightFailed(RuntimeError):
    """The night run did not write its ledger or its evaluation (D38: the workflow run fails)."""


def night() -> None:
    # The models first: a missing, changed or incompatible file stops the night before any data is fetched (D38).
    hashes = verify(MODELS, load_manifest(MANIFEST), LIVE_MODELS)
    models = load_models(MODELS)
    print(f"models: {len(hashes)} files match MODEL_MANIFEST.json; loaded {', '.join(models)}", flush=True)
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

    meta = json.loads((MODELS / "meta.json").read_text())
    sectors = json.loads((MODELS / "sectors.json").read_text())
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
                store=LIVE, trading=trading_enabled(os.environ.get("TRADING")), log=lambda x: print(x, flush=True))
    ok, message, extra = run_night(deps, cal)
    health("night", ok, message, **extra, store_rows=ing.get("new_rows"))
    scored_ok = score_ledger(store, sectors)
    if not ok:
        raise NightFailed(message)
    if not scored_ok:
        raise NightFailed("the ledger check or the forward evaluation failed (see health.json)")


def score_ledger(store: PriceStore, sectors: dict) -> bool:
    """Score the ledger and write forward_eval.json. Returns False when the chain check or the report fails."""
    led = Ledger(LIVE / "ledger")
    rows = led.read()
    if rows.empty:
        report = build_report(rows, {}, pd.DataFrame(), None, load_validation(VALIDATION))
        (LIVE / "forward_eval.json").write_text(json.dumps(report, separators=(",", ":"), allow_nan=False))
        health("forward", True, report["compare"]["headline"])
        return True
    raw = store.read("raw", start=rows["session"].min() - pd.Timedelta(days=40))
    opens = raw.pivot(index="day", columns="symbol", values="o").sort_index()
    hi = raw.pivot(index="day", columns="symbol", values="h").reindex_like(opens)
    lo = raw.pivot(index="day", columns="symbol", values="l").reindex_like(opens)
    cl = raw.pivot(index="day", columns="symbol", values="c").reindex_like(opens)
    hs = pd.DataFrame(half_spread(hi.to_numpy(), lo.to_numpy(), cl.to_numpy()), index=opens.index,
                      columns=opens.columns)
    late = refused(rows, opens)
    if len(late):
        print(f"score: refused {len(late)} predictions made at or after their first realized open", flush=True)
    sc = score(rows, opens, hs, pd.Series(sectors))
    sc.to_parquet(LIVE / "ledger_scores.parquet", index=False)
    summ = model_summary(sc) if len(sc) else pd.DataFrame()
    (LIVE / "ledger_summary.json").write_text(summ.to_json(orient="records"))
    ok, why = led.verify()
    health("score", ok, f"{sc['session'].nunique() if len(sc) else 0} sessions scored; ledger {why}")
    try:  # the forward evaluation (D37) runs even when the chain check failed; both results are recorded
        report = build_report(rows, read_books(LIVE), raw, sectors, load_validation(VALIDATION))
        (LIVE / "forward_eval.json").write_text(json.dumps(report, separators=(",", ":"), allow_nan=False))
        health("forward", True, report["compare"]["headline"])
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        health("forward", False, f"{type(e).__name__}: {e}")
        return False
    return ok


# ---------------------------------------------------------------------------------------------------- flatten
def flatten() -> None:
    broker = Broker()
    before = broker.positions()
    broker.close_all()
    health("night", True, f"flatten: close orders sent for {len(before)} positions", flatten=True)


# ---------------------------------------------------------------------------------------------------- site
def site() -> None:
    """Public data for the page: research only. The paper account (equity, positions, curve, reconciliation)
    belongs to the retired monthly desk and is kept out of the public site (see docs/archive, D38)."""
    led = Ledger(LIVE / "ledger")
    rows = led.read()
    latest = rows[rows["session"] == rows["session"].max()] if len(rows) else rows
    meta_p = MODELS / "meta.json"
    weights = json.loads(meta_p.read_text())["ensemble_weights"] if meta_p.exists() else {}
    ens = ensemble_score(latest, weights).sort_values() if len(latest) and weights else pd.Series(dtype=float)
    summ_p = LIVE / "ledger_summary.json"
    board = json.loads(summ_p.read_text()) if summ_p.exists() else []
    fe = LIVE / "forward_eval.json"
    nights = sorted(LIVE.glob("night_*.json"))
    last_night = json.loads(nights[-1].read_text()) if nights else {}
    h = json.loads((LIVE / "health.json").read_text()) if (LIVE / "health.json").exists() else {}
    data = {
        "updated": now().isoformat(timespec="minutes"),
        "predictions": {"session": f"{pd.Timestamp(latest['session'].iloc[0]):%Y-%m-%d}" if len(latest) else None,
                        "models": sorted(latest["model"].unique().tolist()) if len(latest) else [],
                        "stocks": int(latest["symbol"].nunique()) if len(latest) else 0,
                        "top": [{"symbol": s, "score": round(float(v), 4)} for s, v in ens.tail(10)[::-1].items()],
                        "bottom": [{"symbol": s, "score": round(float(v), 4)} for s, v in ens.head(10).items()]},
        "leaderboard": board,
        "forward_eval": json.loads(fe.read_text()) if fe.exists() else None,
        "ledger": {"sessions": int(rows["session"].nunique()) if len(rows) else 0, "rows": len(rows),
                   "verified": led.verify()[0]},
        "last_night": {k: last_night.get(k) for k in ("session", "complete", "runs", "rejected", "unreached")},
        "health": h,
    }
    data["health"] = {**h, "site": {"at": now().isoformat(timespec="seconds"), "ok": True,
                                    "message": f"{data['ledger']['sessions']} ledger sessions"}}
    SITE_DATA.mkdir(exist_ok=True)
    (SITE_DATA / "live.json").write_text(json.dumps(data, separators=(",", ":"), default=_json))
    health("site", True, data["health"]["site"]["message"])


def _json(x):
    if isinstance(x, (np.floating, np.integer)):
        return x.item()
    return str(x)


if __name__ == "__main__":
    t0 = time.time()
    code = 0
    try:
        {"night": night, "flatten": flatten, "site": site}[args.mode]()
    except Exception as e:  # noqa: BLE001 - recorded in health.json; only the night fails the run (D38)
        traceback.print_exc()
        health(args.mode, False, f"{type(e).__name__}: {e}")
        if args.mode == "night":
            print(f"::error::night failed: {type(e).__name__}: {e}", flush=True)
            code = 1
    print(f"{args.mode}: {time.time() - t0:.0f} s", flush=True)
    raise SystemExit(code)
