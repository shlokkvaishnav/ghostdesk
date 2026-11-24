"""Today's S&P 500 for the live loop: the Wikipedia table of current members, one share class per company.

The research data uses the point-in-time intervals (`data.sp500_universe`); the live loop needs only the members of
today, which the intervals do not have for changes after their last build.
"""
from __future__ import annotations

import io

import pandas as pd

WIKI_CURRENT = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"


def current_members(html: str) -> pd.DataFrame:
    """Wikipedia's current S&P 500 table -> `symbol` (Alpaca form, BRK.B), `cik`, `name`, `sector`."""
    t = pd.read_html(io.StringIO(html))[0]
    out = pd.DataFrame({"symbol": t["Symbol"].astype(str).str.replace("-", ".", regex=False).str.strip(),
                        "cik": pd.to_numeric(t["CIK"], errors="coerce"),
                        "name": t["Security"].astype(str), "sector": t["GICS Sector"].astype(str)})
    out = out.dropna(subset=["cik"])
    out["cik"] = out["cik"].astype(int)
    return out.reset_index(drop=True)


def one_class_per_company(members: pd.DataFrame, dollar_volume: pd.Series) -> pd.DataFrame:
    """Keep, for each CIK, the symbol with the highest dollar volume (`dollar_volume` indexed by symbol)."""
    m = members.copy()
    m["_dv"] = m["symbol"].map(dollar_volume).fillna(-1.0)
    m = m.sort_values(["cik", "_dv"], ascending=[True, False]).drop_duplicates("cik")
    return m.drop(columns="_dv").sort_values("symbol").reset_index(drop=True)
