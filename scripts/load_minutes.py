"""Minute bars for the execution study: 20 S&P 500 stocks (members on 2023-01-03), 10 large (top by 2022 dollar
volume) and 10 smaller (the 20th-30th percentile of dollar volume, price under $150 in 2022: see data-quality P8),
2023-2024, first 60 minutes after the open.
Raw prices (no adjustment: a day is short and the study measures costs against that day's arrival price).
Writes data/minutes.parquet and data/minutes_sample.json (not in git).
Usage: python -u scripts/load_minutes.py [--start 2023-01-01] [--end 2024-12-31] [--minutes 60]
"""
import argparse
import json

import numpy as np
import pandas as pd

from ghostdesk.data.alpaca import AlpacaClient
from ghostdesk.data.calendar import NY
from ghostdesk.filings.edgar import DATA_DIR

ap = argparse.ArgumentParser()
ap.add_argument("--start", default="2023-01-01")
ap.add_argument("--end", default="2024-12-31")
ap.add_argument("--minutes", type=int, default=60)
args = ap.parse_args()

mem = pd.read_parquet(DATA_DIR / "price_symbols.parquet").dropna(subset=["price_symbol", "cik"])
d0 = pd.Timestamp("2023-01-03")
mem = mem[(mem["start"] <= d0) & (mem["end"].isna() | (mem["end"] > pd.Timestamp(args.end)))]
raw = pd.read_parquet(DATA_DIR / "prices_daily_raw.parquet", columns=["symbol", "t", "c", "v"])
y22 = raw[(raw["t"] >= "2022-01-01") & (raw["t"] < "2023-01-01")]
dv = (y22["c"] * y22["v"]).groupby(y22["symbol"]).mean()
px = y22.groupby("symbol")["c"].mean()
mem = mem.assign(dv=mem["price_symbol"].map(dv), px=mem["price_symbol"].map(px)).dropna(subset=["dv"])
mem = mem.sort_values("dv", ascending=False)
mem = mem.drop_duplicates("cik")  # one share class per company
large = mem.head(10)
q = mem["dv"].rank(pct=True)
# odd lots (< 100 shares) do not count in consolidated bar volume, so a high-priced, less traded stock shows only a
# part of its volume in minute bars (data-quality P8); the smaller group is taken from stocks under $150 in 2022
small = mem[(q >= 0.20) & (q <= 0.30) & (mem["px"] < 150)].sample(10, random_state=0)
sample = {"large": large["price_symbol"].tolist(), "small": small["price_symbol"].tolist()}
print(json.dumps(sample), flush=True)

client = AlpacaClient()
parts = []
for group, syms in sample.items():
    for s in syms:
        b = client.bars([s], args.start, args.end, timeframe="1Min", adjustment="raw")
        t = b["t"].dt.tz_convert(NY)
        mins = (t.dt.hour * 60 + t.dt.minute) - (9 * 60 + 30)
        b = b[(mins >= 0) & (mins < args.minutes)].assign(minute=mins[(mins >= 0) & (mins < args.minutes)],
                                                          day=t.dt.normalize().dt.tz_localize(None), group=group)
        parts.append(b)
        print(f"{s}: {len(b)} bars, {b['day'].nunique()} days", flush=True)
m = pd.concat(parts, ignore_index=True)
m.to_parquet(DATA_DIR / "minutes.parquet", index=False)
full = m.groupby(["symbol", "day"]).size()
summary = sample | {"bars": len(m), "symbol_days": len(full), "share_complete_days": float((full == args.minutes).mean()),
                    "median_bars_per_day": float(np.median(full))}
(DATA_DIR / "minutes_sample.json").write_text(json.dumps(summary, indent=1))
print(json.dumps({k: v for k, v in summary.items() if k not in sample}))
