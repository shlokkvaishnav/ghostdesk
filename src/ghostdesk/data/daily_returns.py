"""Daily returns from adjusted prices, with bad corporate-action days removed.

The vendor's adjusted series sometimes treats a spin-off as a split: ARNC on 2020-04-01 shows a log return of -2.23
(-89%) while the raw price fell -0.84 (the real value moved to the spun-off company). Such a day is not a market
move, and a backtest that keeps it gains or loses a fortune on one stock. A day is flagged when the adjusted move is
large and much larger than the raw move: |adj| > `big` and |adj| - |raw| > `excess`. A real split is not flagged
(the raw price jumps, the adjusted one does not), nor is a dividend (a small difference). A flagged day's return is
NaN (excluded), not guessed.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def daily_returns(adjusted: pd.DataFrame, raw: pd.DataFrame, big: float = 0.3, excess: float = 0.2) -> pd.DataFrame:
    """adjusted, raw: symbol, t, c (daily bars). Returns symbol, day, ret (log, NaN on flagged days), flag, close
    (raw), close_adj."""
    def logret(df):
        d = df.sort_values(["symbol", "t"]).assign(day=lambda x: x["t"].dt.tz_convert("America/New_York").dt
                                                    .normalize().dt.tz_localize(None))
        d["r"] = np.log(d["c"]).groupby(d["symbol"]).diff()
        return d[["symbol", "day", "c", "r"]]

    a, r = logret(adjusted), logret(raw)
    m = a.merge(r, on=["symbol", "day"], how="left", suffixes=("_adj", "_raw"))
    m["flag"] = (m["r_adj"].abs() > big) & ((m["r_adj"].abs() - m["r_raw"].abs()) > excess)
    m["ret"] = m["r_adj"].where(~m["flag"])
    return m.rename(columns={"c_adj": "close_adj", "c_raw": "close"})[
        ["symbol", "day", "ret", "flag", "close", "close_adj"]].reset_index(drop=True)
