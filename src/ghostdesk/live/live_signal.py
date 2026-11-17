"""The live signal: today's S&P 500 and, for each company, the `composite` of its latest paired report.

The same rules as the study (docs/preregistration.md): like-with-like pairs (`filings.filing_index.pair_previous`), a
report counts from the first open strictly after its SEC acceptance, only if it was tradeable at or before the
formation close and at most `window_days` (120) before it; ranks within form (`evaluation.portfolio_stats.add_signals`).
One row per CIK: a company with two share classes (GOOGL, GOOG) keeps the class with the higher dollar volume.
"""
from __future__ import annotations

import io

import numpy as np
import pandas as pd

from ghostdesk.evaluation.portfolio_stats import FULL, PRIMARY, add_signals
from ghostdesk.text_signal.stock_month_panel import tradeable_times

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


def latest_pairs(index: pd.DataFrame, sessions: pd.DatetimeIndex, formation_close_utc: pd.Timestamp,
                 window_days: int = 120) -> pd.DataFrame:
    """For each CIK, the latest original paired report (from `pair_previous`) that is tradeable at or before the
    formation close and less than `window_days` before it. Adds `tradeable` (UTC)."""
    p = index[~index["amendment"] & index["prev_accession"].notna()].copy()
    p["tradeable"] = tradeable_times(p["accepted_utc"], sessions)
    t = pd.Timestamp(formation_close_utc)
    p = p[(p["tradeable"] <= t) & (p["tradeable"] > t - pd.Timedelta(days=window_days))]
    return p.sort_values(["cik", "accepted_utc"]).drop_duplicates("cik", keep="last").reset_index(drop=True)


def composite(scores: pd.DataFrame) -> pd.Series:
    """The primary signal for one formation date. `scores` has `form` and the three full-text similarities
    (`evaluation.portfolio_stats.FULL`); the result is in (0, 1], high = little change, NaN when a measure is missing."""
    p = scores[["form", *FULL]].copy()
    p["month"] = 0
    p["sic"] = ""
    return add_signals(p)[PRIMARY]


def quintile(signal: pd.Series, n: int = 5) -> pd.Series:
    """Quintile 1..n of each non-missing value (n = least change), as in `evaluation.portfolio_stats.quintiles`."""
    s = signal.dropna()
    q = pd.Series(np.nan, index=signal.index)
    if len(s) >= n:
        q[s.index] = pd.qcut(s.rank(method="first"), n, labels=False) + 1
    return q
