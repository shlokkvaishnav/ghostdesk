"""Build the report index for every CIK in data/universe.parquet: data/filings_index.parquet (not in git).
Usage: python -u scripts/data/build_filing_index.py [--since 2009-01-01]
"""
import argparse
import json

import pandas as pd

from ghostdesk.filings.edgar_client import DATA_DIR, EdgarClient
from ghostdesk.filings.filing_index import index_for, no_future_pairs, pair_previous

ap = argparse.ArgumentParser()
ap.add_argument("--since", default="2009-01-01")
args = ap.parse_args()
uni = pd.read_parquet(DATA_DIR / "universe.parquet")
ciks = sorted(int(c) for c in uni["cik"].dropna().unique())
sec = EdgarClient()
idx = pair_previous(pd.concat([index_for(sec, c, args.since) for c in ciks], ignore_index=True))
assert no_future_pairs(idx), "a report is paired with a later one"
idx.to_parquet(DATA_DIR / "filings_index.parquet", index=False)
orig = idx[~idx["amendment"]]
summary = {"ciks": len(ciks), "reports": len(idx), "amendments": int(idx["amendment"].sum()),
           "by_form": orig["base_form"].value_counts().to_dict(),
           "paired_share": float(orig["prev_accession"].notna().mean()),
           "missing_acceptance_time": int(idx["accepted_utc"].isna().sum()),
           "by_year": orig.groupby(orig["filing_date"].dt.year).size().to_dict()}
print(json.dumps(summary, default=int))
(DATA_DIR / "filings_index_summary.json").write_text(json.dumps(summary, indent=1, default=int))
