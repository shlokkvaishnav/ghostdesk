"""Bid-ask spread from daily high and low prices (Corwin and Schultz 2012), so no historical quotes are needed.

The high of a day is usually a trade at the ask and the low a trade at the bid. Over two days the variance part of
ln(H/L)^2 doubles but the spread part does not; the difference gives the spread. Overnight moves are removed first
(the paper's adjustment). Negative two-day estimates are set to 0, as in the paper; `monthly_spread` instead
floors the monthly mean, which is less biased.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

K = 3 - 2 * np.sqrt(2)


def corwin_schultz(high, low, close=None, floor: bool = True) -> pd.Series:
    """Two-day spread estimates (proportion of price, 0.01 = 1%), one per day t from the pair (t-1, t); the first is
    NaN. If `close` is given, day t's high and low are shifted by the overnight gap beyond day t-1's close.
    floor=False keeps negative estimates, so that an average is not biased up by the floor."""
    h = pd.Series(high, dtype=float).reset_index(drop=True)
    lo = pd.Series(low, dtype=float).reset_index(drop=True)
    idx = pd.Series(high).index
    if close is not None:
        c = pd.Series(close, dtype=float).reset_index(drop=True).shift(1)
        up = (lo - c).clip(lower=0).fillna(0)  # day opened above yesterday's close
        down = (c - h).clip(lower=0).fillna(0)  # day opened below it
        h, lo = h - up + down, lo - up + down
    hl2 = np.log(h / lo) ** 2
    beta = hl2 + hl2.shift(1)
    gamma = np.log(np.maximum(h, h.shift(1)) / np.minimum(lo, lo.shift(1))) ** 2
    alpha = (np.sqrt(2 * beta) - np.sqrt(beta)) / K - np.sqrt(gamma / K)
    s = 2 * (np.exp(alpha) - 1) / (1 + np.exp(alpha))
    s = s.clip(lower=0) if floor else s
    s.index = idx
    return s


def monthly_spread(high, low, close, dates) -> pd.Series:
    """Mean of the two-day estimates in each calendar month, with the floor at 0 applied to the mean, not to each
    estimate (flooring each two-day value biases the mean up)."""
    s = corwin_schultz(high, low, close, floor=False)
    return s.groupby(pd.DatetimeIndex(dates).to_period("M")).mean().clip(lower=0)
