"""Daily bars (adjusted, and raw) for every index company of 2016-2025, plus SPY, and the daily returns with bad
corporate-action days removed. Writes data/prices_daily{,_raw}.parquet and data/returns_daily.parquet (not in git)
and prints the coverage of member-days.
Usage: python -u scripts/data/load_prices.py [--start 2016-01-01] [--end 2025-12-31] [--symbols AAPL,MSFT]
"""
import argparse
import json

import pandas as pd

from ghostdesk.data.alpaca_client import AlpacaClient, coverage
from ghostdesk.data.daily_returns import daily_returns
from ghostdesk.data.edgar_client import DATA_DIR, EdgarClient, tickers_to_ciks
from ghostdesk.data.sp500_universe import price_symbols

ap = argparse.ArgumentParser()
ap.add_argument("--start", default="2016-01-01")
ap.add_argument("--end", default="2025-12-31")
ap.add_argument("--symbols", default="")
args = ap.parse_args()

uni = pd.read_parquet(DATA_DIR / "universe.parquet")
mem = uni[(uni["end"].isna() | (uni["end"] > args.start)) & (uni["start"] <= args.end)].copy()
by_cik: dict[int, list[str]] = {}
for t, k in tickers_to_ciks(EdgarClient()).items():  # SEC order: the main ticker first
    by_cik.setdefault(k, []).append(t)
mem["price_symbol"] = price_symbols(mem, by_cik)  # prices follow the company (FB -> META), not the old ticker
mem[["ticker", "start", "end", "cik", "price_symbol"]].to_parquet(DATA_DIR / "price_symbols.parquet", index=False)
syms = args.symbols.split(",") if args.symbols else sorted(set(mem["price_symbol"].dropna()) | {"SPY"})
client = AlpacaClient()


def load(adjustment):
    parts = []
    for i in range(0, len(syms), 100):
        parts.append(client.bars(syms[i:i + 100], args.start, args.end, adjustment=adjustment))
        print(f"{adjustment}: {min(i + 100, len(syms))}/{len(syms)} symbols, {sum(len(p) for p in parts)} bars",
              flush=True)
    return pd.concat(parts, ignore_index=True)


daily, raw = load("all"), load("raw")
daily.to_parquet(DATA_DIR / "prices_daily.parquet", index=False)
raw.to_parquet(DATA_DIR / "prices_daily_raw.parquet", index=False)
rets = daily_returns(daily, raw)  # vendor errors on spin-off days are flagged and excluded
rets.to_parquet(DATA_DIR / "returns_daily.parquet", index=False)
bad = rets[rets["flag"]]
print(f"flagged {len(bad)} days:", ", ".join(f"{s} {d:%Y-%m-%d}" for s, d in zip(bad["symbol"], bad["day"],
                                                                                  strict=True)), flush=True)
cov = coverage(daily, mem, args.start, args.end)
missing = sorted(set(mem["price_symbol"].dropna()) - set(daily["symbol"]))
cov |= {"symbols_requested": len(syms), "symbols_with_data": int(daily["symbol"].nunique()), "no_data": missing,
        "flagged_days": len(bad)}
print(json.dumps({k: v for k, v in cov.items() if k != "no_data"}), f"\nno data ({len(missing)}):", ", ".join(missing))
(DATA_DIR / "prices_coverage.json").write_text(json.dumps(cov, indent=1))
