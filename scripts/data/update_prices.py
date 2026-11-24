"""Daily incremental ingestion into the point-in-time price store (data/store/, `data.store`).

On the first run the store is seeded from data/prices_daily{,_raw}.parquet (the 2016-2025 load of load_prices.py)
as batch `seed`, dated by the time those files were written. Each run then appends every completed session after the
stored last day, for every symbol that is or was an index member in the window, plus SPY and today's members
(data/live/members.parquet). Prints the counts as JSON and writes data/store/ingest_log.json.
Usage: python -u scripts/data/update_prices.py [--until 2026-11-23]
"""
import argparse
import json

import pandas as pd

from ghostdesk.data.alpaca_client import AlpacaClient
from ghostdesk.data.store import PriceStore, bars_to_rows, ingest_daily
from ghostdesk.live.alpaca_broker import Broker
from ghostdesk.paths import DATA_DIR

ap = argparse.ArgumentParser()
ap.add_argument("--until", default="", help="last session to load (default: the last completed session)")
args = ap.parse_args()

store = PriceStore()
now = pd.Timestamp.now(tz="UTC")
if not store.batches("raw"):
    for kind, f in (("adj", "prices_daily.parquet"), ("raw", "prices_daily_raw.parquet")):
        p = DATA_DIR / f
        at = pd.Timestamp(p.stat().st_mtime, unit="s", tz="UTC")
        store.write_batch(kind, bars_to_rows(pd.read_parquet(p), at), "seed")
        print(f"seeded {kind} from {f} (ingested_at {at:%Y-%m-%d %H:%M})", flush=True)

if args.until:
    until = pd.Timestamp(args.until)
else:
    cal = Broker().sessions(f"{now - pd.Timedelta(days=15):%Y-%m-%d}", f"{now:%Y-%m-%d}")
    done = cal[cal["close_utc"] <= now - pd.Timedelta(minutes=20)]  # the free plan has no SIP data for 15 min
    until = done["date"].iloc[-1]

last = store.last_day("raw")
ps = pd.read_parquet(DATA_DIR / "price_symbols.parquet")
active = ps[ps["end"].isna() | (ps["end"] >= last - pd.Timedelta(days=30))]
syms = set(active["price_symbol"].dropna()) | {"SPY"}
live = DATA_DIR / "live" / "members.parquet"
if live.exists():
    syms |= set(pd.read_parquet(live)["symbol"])
client = AlpacaClient()


def fetch(symbols, start, end, adjustment):
    parts = [client.bars(sorted(symbols)[i:i + 100], start, end, adjustment=adjustment)
             for i in range(0, len(symbols), 100)]
    return pd.concat(parts, ignore_index=True)


out = ingest_daily(store, fetch, sorted(syms), until, now)
out |= {"until": f"{until:%Y-%m-%d}", "symbols": len(syms), "last_day": f"{store.last_day('raw'):%Y-%m-%d}",
        "at": now.isoformat(timespec="seconds")}
print(json.dumps(out), flush=True)
log = store.root / "ingest_log.json"
hist = json.loads(log.read_text()) if log.exists() else []
log.write_text(json.dumps(hist + [out], indent=1))
