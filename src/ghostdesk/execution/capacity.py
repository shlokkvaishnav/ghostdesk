"""Capacity of the signal strategy: the monthly trading cost, as a share of the fund, for a fund of A dollars.

Each month the long-short portfolio (`evaluation.portfolio_stats.portfolio` rules: equal weights in Q5 and Q1) changes weight
dw_i in stock i, so it trades dw_i x A dollars. A trade of X dollars, spread evenly over one day, costs (as a fraction
of X) the half-spread + gamma sigma (X / ADV$) / 2 + eta sigma (X / ADV$) ** beta, with the Almgren, Thum, Hauptmann
and Li (2005) values used by `execution.replay_simulator`. The fund's monthly cost is sum_i dw_i x cost_i. The break-even size
is the A at which this cost equals the strategy's gross monthly return.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ghostdesk.evaluation.portfolio_stats import quintiles
from ghostdesk.execution.replay_simulator import BETA, ETA, GAMMA


def monthly_trades(panel: pd.DataFrame, measure: str, n: int = 5) -> pd.DataFrame:
    """month, cik, dw (absolute weight change at that month's rebalance, both legs), adv_dollar, sigma."""
    p = quintiles(panel, measure, n)
    p = p[p["q"].isin([1, n])].copy()
    p["w"] = 1.0 / p.groupby(["month", "q"])["cik"].transform("size")
    p["key"] = p["cik"].astype(str) + "_" + p["q"].astype(int).astype(str)
    wide = p.pivot_table(index="month", columns="key", values="w", fill_value=0.0)
    dw = wide.diff().abs()
    dw.iloc[0] = wide.iloc[0]  # the first month builds the portfolio
    t = dw.stack().rename("dw").reset_index()
    t = t[t["dw"] > 0]
    t["cik"] = t["key"].str.split("_").str[0].astype(int)
    info = p.assign(cik=p["cik"].astype(int)).drop_duplicates(["month", "cik"]).set_index(["month", "cik"])
    # a stock that left the portfolio has no row in its exit month: use the last month it was held
    last = p.assign(cik=p["cik"].astype(int)).sort_values("month").drop_duplicates("cik", keep="last").set_index("cik")
    rows = []
    for month, cik, w in zip(t["month"], t["cik"], t["dw"], strict=True):
        src = info.loc[(month, cik)] if (month, cik) in info.index else last.loc[cik]
        rows.append((month, cik, w, float(np.exp(src["logdv"])), float(src["sigma"])))
    return pd.DataFrame(rows, columns=["month", "cik", "dw", "adv_dollar", "sigma"])


def cost_fraction(x_dollar: np.ndarray, adv_dollar: np.ndarray, sigma: np.ndarray, half_spread: float = 1e-4,
                  eta: float = ETA, beta: float = BETA, gamma: float = GAMMA) -> np.ndarray:
    """Cost of one day's even trading of x dollars, as a fraction of x."""
    part = x_dollar / adv_dollar
    return half_spread + 0.5 * gamma * sigma * part + eta * sigma * part**beta


def capacity_curve(trades: pd.DataFrame, aums, **kw) -> pd.Series:
    """Mean monthly cost (fraction of the fund) for each fund size."""
    out = {}
    for a in aums:
        c = trades["dw"] * cost_fraction(trades["dw"] * a, trades["adv_dollar"], trades["sigma"], **kw)
        out[a] = float(c.groupby(trades["month"]).sum().mean())
    return pd.Series(out)


def break_even(curve: pd.Series, gross_monthly: float) -> float:
    """The fund size at which the monthly cost reaches the gross return, by log-linear interpolation on the curve.
    NaN if the cost is already above the return at the smallest size, or never reaches it on the curve."""
    c = curve.sort_index()
    y = c.to_numpy()
    if not np.isfinite(gross_monthly) or y[0] >= gross_monthly or y[-1] < gross_monthly:
        return float("nan")
    i = int(np.nonzero(y >= gross_monthly)[0][0])
    x0, x1 = np.log(c.index[i - 1]), np.log(c.index[i])
    return float(np.exp(x0 + (gross_monthly - y[i - 1]) / (y[i] - y[i - 1]) * (x1 - x0)))
