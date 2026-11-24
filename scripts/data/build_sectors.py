"""The sector of every company with prices: its SEC SIC code (from the submissions JSON, through the EdgarClient disk
cache) grouped by `data.industry.industry_groups` over all companies. Writes data/sectors.parquet (cik, sic,
sector). Today's members (data/live/members.parquet) are added so the live loop has a sector for each of them.
Usage: python -u scripts/data/build_sectors.py
"""
import pandas as pd

from ghostdesk.data.edgar_client import DATA_DIR, SUBMISSIONS, EdgarClient
from ghostdesk.data.industry import industry_groups

ps = pd.read_parquet(DATA_DIR / "price_symbols.parquet")
ciks = set(ps["cik"].dropna().astype(int))
live = DATA_DIR / "live" / "members.parquet"
if live.exists():
    ciks |= set(pd.read_parquet(live)["cik"].astype(int))
sec = EdgarClient(max_per_sec=5)
rows = []
for cik in sorted(ciks):
    try:
        rows.append({"cik": cik, "sic": str(sec.get_json(SUBMISSIONS.format(cik=cik)).get("sic") or "")})
    except Exception as e:  # noqa: BLE001 - a missing company gets the group "unknown"
        print(f"CIK {cik}: {type(e).__name__}", flush=True)
        rows.append({"cik": cik, "sic": ""})
out = pd.DataFrame(rows)
out["sector"] = industry_groups(out["sic"]).to_numpy()
out.to_parquet(DATA_DIR / "sectors.parquet", index=False)
print(f"{len(out)} companies, {out['sector'].nunique()} groups, network calls {sec.network_calls}")
print(out["sector"].value_counts().to_string())
