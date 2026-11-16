"""Build the point-in-time S&P 500 universe with SEC CIKs. Writes data/universe.parquet and prints the coverage.
Each interval's candidate CIKs are checked against the SEC: the one that filed a 10-K or 10-Q during the membership
(+- 400 days) is kept (`universe.resolve`). Ambiguous or empty intervals stay unmapped.
Usage: python -u scripts/build_universe.py [--start 2010-01-01] [--end 2025-12-31]
"""
import argparse
import io
import json
from pathlib import Path

import pandas as pd
import requests

from ghostdesk.data.universe import (
    add_predecessors,
    add_valid_from,
    candidates,
    changes_table,
    coverage,
    load_intervals,
    names_over_time,
    parse_cik_lookup,
    resolve,
)
from ghostdesk.filings.edgar import DATA_DIR, SUBMISSIONS, EdgarClient, list_filings, tickers_to_ciks

FJA = "https://raw.githubusercontent.com/fja05680/sp500/master/sp500_ticker_start_end.csv"
WIKI_CURRENT = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
WIKI_HISTORY = "https://en.wikipedia.org/wiki/Historical_components_of_the_S%26P_500"
CIK_LOOKUP = "https://www.sec.gov/Archives/edgar/cik-lookup-data.txt"
UA = {"User-Agent": "ghostdesk-research/0.1"}

ap = argparse.ArgumentParser()
ap.add_argument("--start", default="2010-01-01")
ap.add_argument("--end", default="2025-12-31")
args = ap.parse_args()
src = DATA_DIR / "sources"
src.mkdir(parents=True, exist_ok=True)


def fetch(url, name):
    p = src / name
    if not p.exists():
        r = requests.get(url, headers=UA, timeout=60)
        r.raise_for_status()
        p.write_bytes(r.content)
    return p


iv = load_intervals(fetch(FJA, "sp500_ticker_start_end.csv"))
iv = iv[iv["end"].isna() | (iv["end"] >= args.start)].reset_index(drop=True)  # later starts are kept: renames
current = pd.read_html(io.StringIO(fetch(WIKI_CURRENT, "wiki_current.html").read_text()))[0]
changes = changes_table(pd.read_html(io.StringIO(fetch(WIKI_HISTORY, "wiki_history.html").read_text())))
sec = EdgarClient()
lookup = parse_cik_lookup(sec.get(CIK_LOOKUP).decode("latin-1"))
cands = candidates(iv, current, changes, lookup, tickers_to_ciks(sec))
dates: dict[int, list[str]] = {}


def has_filings(cik, lo, hi):
    if cik not in dates:
        try:
            dates[cik] = [f.filing_date for f in list_filings(sec, cik, forms=("10-K", "10-Q"), since="2008-01-01")]
        except requests.HTTPError:
            dates[cik] = []
    a, b = f"{lo:%Y-%m-%d}", f"{hi:%Y-%m-%d}"
    return any(a <= d <= b for d in dates[cik])


def names_at(cik, day):
    try:
        spans = names_over_time(sec.get_json(SUBMISSIONS.format(cik=cik)))
    except requests.HTTPError:
        return []
    d = f"{day:%Y-%m-%d}"
    return [n for n, a, b in spans if a <= d <= b]


added = dict(zip(current["Symbol"], pd.to_datetime(current["Date added"], errors="coerce"), strict=True))
mapped = resolve(cands, has_filings, changes, names_at=names_at, added=added)


def first_filing(cik):
    has_filings(cik, pd.Timestamp("2008-01-01"), pd.Timestamp("2008-01-01"))  # loads the dates
    return pd.Timestamp(min(dates[cik])) if dates[cik] else None


mapped = add_predecessors(mapped, first_filing, has_filings, names_at, lookup, args.start)
mapped = add_valid_from(mapped, {k: pd.Timestamp(min(v)) for k, v in dates.items() if v})
print(f"checked {len(dates)} CIKs against their SEC filings", flush=True)
cov = coverage(mapped, args.start, args.end)
print("after the filing check:", json.dumps(cov), flush=True)
out = Path(DATA_DIR) / "universe.parquet"
mapped.to_parquet(out, index=False)
unm = mapped[mapped["cik"].isna()]
print(f"unmapped intervals ({len(unm)}):", ", ".join(f"{t} {s:%Y}-{'' if pd.isna(e) else f'{e:%Y}'}"
                                               for t, s, e in zip(unm["ticker"], unm["start"], unm["end"], strict=True)))
(Path(DATA_DIR) / "universe_coverage.json").write_text(json.dumps(cov, indent=1))
