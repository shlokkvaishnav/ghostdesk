"""Daily bars (adjusted for splits and dividends) for every index ticker of 2016-2025, plus SPY.
Writes data/prices_daily.parquet (not in git) and prints the coverage of member-days.
Usage: python -u scripts/load_prices.py [--start 2016-01-01] [--end 2025-12-31] [--symbols AAPL,MSFT]
"""
import argparse
import json

import pandas as pd

from ghostdesk.data.alpaca import AlpacaClient, alpaca_symbol, coverage
from ghostdesk.filings.edgar import DATA_DIR

ap = argparse.ArgumentParser()
ap.add_argument("--start", default="2016-01-01")
ap.add_argument("--end", default="2025-12-31")
ap.add_argument("--symbols", default="")
args = ap.parse_args()

uni = pd.read_parquet(DATA_DIR / "universe.parquet")
mem = uni[(uni["end"].isna() | (uni["end"] > args.start)) & (uni["start"] <= args.end)]
syms = args.symbols.split(",") if args.symbols else sorted({alpaca_symbol(t) for t in mem["ticker"]} | {"SPY"})
client = AlpacaClient()
parts = []
for i in range(0, len(syms), 100):
    parts.append(client.bars(syms[i:i + 100], args.start, args.end))
    print(f"{min(i + 100, len(syms))}/{len(syms)} symbols, {sum(len(p) for p in parts)} bars", flush=True)
daily = pd.concat(parts, ignore_index=True)
daily.to_parquet(DATA_DIR / "prices_daily.parquet", index=False)
cov = coverage(daily, mem, args.start, args.end)
missing = sorted({alpaca_symbol(t) for t in mem["ticker"]} - set(daily["symbol"]))
cov |= {"symbols_requested": len(syms), "symbols_with_data": int(daily["symbol"].nunique()), "no_data": missing}
print(json.dumps({k: v for k, v in cov.items() if k != "no_data"}), f"\nno data ({len(missing)}):", ", ".join(missing))
(DATA_DIR / "prices_coverage.json").write_text(json.dumps(cov, indent=1))
