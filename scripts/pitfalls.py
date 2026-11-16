"""The pitfall-bias table: rerun the signal study with one guard turned off at a time, and report how much each
common backtest mistake changes the result. Uses only 2016-2021 (build and check periods; never the test period).

Variants (each changes one thing against the baseline of scripts/signal_study.py):
- filing_date: a report is known at the open of its filing date (instead of the first open after SEC acceptance).
- period_end: a report is known at the end of the period it covers (a large look-ahead: reports come weeks later).
- survivors: the stock list is today's S&P 500 for all dates (survivorship bias).
- vendor_errors: the vendor's spin-off adjustment errors are kept in the returns.
- mixed_forms: 10-Ks and 10-Qs are ranked together (the signal partly sorts by form).
Writes data/pitfalls.json and prints a table.
Usage: python -u scripts/pitfalls.py [--start 2016-01-01] [--end 2021-12-31]
"""
import argparse
import json

import numpy as np
import pandas as pd

from ghostdesk.data.calendar import NY
from ghostdesk.data.factors import load_factors
from ghostdesk.filings.edgar import DATA_DIR, SUBMISSIONS, EdgarClient
from ghostdesk.signal.panel import build_panel
from ghostdesk.signal.study import FULL, PRIMARY, add_signals, ic, mean_t, portfolio

ap = argparse.ArgumentParser()
ap.add_argument("--start", default="2016-01-01")
ap.add_argument("--end", default="2021-12-31")
args = ap.parse_args()
if pd.Timestamp(args.end) >= pd.Timestamp("2022-01-01"):
    raise SystemExit("the pitfall table uses only 2016-2021; the test period is not used here")

features = pd.read_parquet(DATA_DIR / "features.parquet")
members = pd.read_parquet(DATA_DIR / "price_symbols.parquet").merge(
    pd.read_parquet(DATA_DIR / "universe.parquet")[["ticker", "start", "valid_from"]], on=["ticker", "start"],
    how="left")
returns = pd.read_parquet(DATA_DIR / "returns_daily.parquet")
raw = pd.read_parquet(DATA_DIR / "prices_daily_raw.parquet", columns=["symbol", "t", "h", "l", "c", "v"])
sec = EdgarClient()
sic = {int(k): str(sec.get_json(SUBMISSIONS.format(cik=int(k))).get("sic", "")) for k in members["cik"].dropna().unique()}
factors = load_factors(DATA_DIR / "sources" / "ff")


def at_9am(dates: pd.Series) -> pd.Series:
    """09:00 New York on each date, in UTC: the next open is 09:30 of that day."""
    return (pd.to_datetime(dates) + pd.Timedelta(hours=9)).dt.tz_localize(NY).dt.tz_convert("UTC")


def run(feat=features, mem=members, ret=returns, mixed=False) -> dict:
    p = add_signals(build_panel(feat, mem, ret, raw, sic, args.start, args.end))
    if mixed:  # rank on the whole month, not within the form
        p[PRIMARY] = p[FULL].rank(pct=True).mean(axis=1, skipna=False)
        p[PRIMARY] = p.groupby("month")[PRIMARY].rank(pct=True)
    pf = portfolio(p, PRIMARY)
    g, i = mean_t(pf["ls"], 3), mean_t(ic(p, PRIMARY), 3)
    sd = float(pf["ls"].std())
    return {"ls_monthly": g["mean"], "ls_t": g["t"], "sharpe": g["mean"] / sd * np.sqrt(12), "ic": i["mean"],
            "ic_t": i["t"], "stock_months": int(p[PRIMARY].notna().sum())}


survivors = members[members["end"].isna()].assign(start=pd.Timestamp("2000-01-01"), valid_from=pd.NaT)
kept = returns.sort_values(["symbol", "day"]).copy()
kept["ret"] = np.log(kept["close_adj"]).groupby(kept["symbol"]).diff()  # flagged days back in
variants = {
    "baseline": run(),
    "filing_date": run(feat=features.assign(accepted_utc=at_9am(features["filing_date"]))),
    "period_end": run(feat=features.assign(accepted_utc=at_9am(features["report_date"]))),
    "survivors": run(mem=survivors),
    "vendor_errors": run(ret=kept),
    "mixed_forms": run(mixed=True),
}
base = variants["baseline"]
for k, v in variants.items():
    v["ls_change_vs_baseline"] = v["ls_monthly"] - base["ls_monthly"]
    v["ic_change_vs_baseline"] = v["ic"] - base["ic"]
(DATA_DIR / "pitfalls.json").write_text(json.dumps({"period": [args.start, args.end], "variants": variants}, indent=1))
print(f"{'variant':15} {'LS %/mo':>8} {'t':>6} {'Sharpe':>7} {'IC':>7} {'IC t':>6} {'dLS':>7} {'stock-months':>12}")
for k, v in variants.items():
    print(f"{k:15} {v['ls_monthly']*100:8.2f} {v['ls_t']:6.2f} {v['sharpe']:7.2f} {v['ic']:7.3f} {v['ic_t']:6.2f} "
          f"{v['ls_change_vs_baseline']*100:7.2f} {v['stock_months']:12d}")
