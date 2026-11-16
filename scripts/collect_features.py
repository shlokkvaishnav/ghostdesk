"""Download the shard artifacts of a `features` workflow run, join them into data/features.parquet, and check that
every target report is present (the same selection as scripts/extract_features.py).
Usage: python -u scripts/collect_features.py RUN_ID [--shards 6]
Needs the `gh` CLI, logged in. A failed download of one shard is tried again (artifact downloads can time out).
"""
import argparse
import json
import subprocess
from pathlib import Path

import pandas as pd

from ghostdesk.filings.edgar import DATA_DIR

ap = argparse.ArgumentParser()
ap.add_argument("run_id")
ap.add_argument("--shards", type=int, default=6)
args = ap.parse_args()
out = DATA_DIR / "features_run"
for i in range(args.shards):
    d = out / f"features-shard-{i}"
    if (d / f"shard_{i}.parquet").exists():
        continue
    for attempt in range(3):
        r = subprocess.run(["gh", "run", "download", args.run_id, "-n", f"features-shard-{i}", "--dir", str(d)],
                           check=False)
        if r.returncode == 0:
            break
        print(f"shard {i}: download failed (attempt {attempt + 1})", flush=True)
files = sorted(out.glob("features-shard-*/shard_*.parquet"))
if len(files) != args.shards:
    raise SystemExit(f"only {len(files)} of {args.shards} shard files: run again to retry the missing ones")
f = pd.concat([pd.read_parquet(p) for p in files], ignore_index=True)
assert not f.duplicated(["cik", "accession"]).any(), "a report is in two shards"

idx = pd.read_parquet(DATA_DIR / "filings_index.parquet")
uni = pd.read_parquet(DATA_DIR / "universe.parquet").dropna(subset=["cik"])
t = idx[~idx["amendment"] & idx["prev_accession"].notna() & idx["filing_date"].between("2009-06-01", "2025-12-31")]
m = t.merge(uni[["cik", "start", "end", "valid_from"]], on="cik")
m = m[(m["valid_from"].fillna(m["start"]) <= m["filing_date"]) & (m["end"].isna() | (m["filing_date"] < m["end"]))]
target = set(zip(m["cik"], m["accession"], strict=True))
missing = target - set(zip(f["cik"], f["accession"], strict=True))
f.to_parquet(DATA_DIR / "features.parquet", index=False)
cov = f.filter(regex=r"^sim_.*_edit$|^xbrl_").notna().groupby(f["form"]).mean().round(3)
summary = {"run_id": args.run_id, "reports": len(f), "ciks": int(f["cik"].nunique()), "target": len(target),
           "missing": len(missing), "errors": int((f["error"] != "").sum()),
           "coverage_by_form": {k: {c: float(v) for c, v in r.items()} for k, r in cov.iterrows()}}
Path(DATA_DIR / "features_summary.json").write_text(json.dumps(summary, indent=1))
print(json.dumps({k: v for k, v in summary.items() if k != "coverage_by_form"}))
if missing:
    raise SystemExit(f"{len(missing)} target reports are missing")
