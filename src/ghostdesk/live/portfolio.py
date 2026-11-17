"""From quintiles to orders: target shares, the trades to reach them, and a VWAP schedule of child orders.

Decision D15: long Q5 and short Q1, equal weights, each leg `leg` (0.5) of equity, whole shares. A trade smaller
than `min_frac` of the per-stock target value is skipped, so a rerun on the same day does not trade again. Child
orders follow the first-hour volume profile of the Step 4 minute bars; a position never crosses zero inside one
order (Alpaca rejects that), so a flip is closed in the first bucket and opened over the rest.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# Mean share of the first hour's volume in each 5-minute bucket: 20 stocks, 2023-2024 (data/minutes.parquet).
FIRST_HOUR_PROFILE = (0.1841, 0.0871, 0.0816, 0.0804, 0.0753, 0.0709,
                      0.0816, 0.0737, 0.0706, 0.0670, 0.0643, 0.0635)
BUCKET_MIN = 5


def target_shares(sides: pd.Series, prices: pd.Series, equity: float, leg: float = 0.5) -> dict[str, int]:
    """sides: symbol -> +1 (long), -1 (short), 0. Equal value per stock in each leg; rounded to whole shares.
    Stocks without a positive price get no position."""
    out: dict[str, int] = {}
    for sign in (1, -1):
        names = [s for s, v in sides.items() if v == sign and prices.get(s, 0) > 0]
        if not names:
            continue
        per = leg * equity / len(names)
        for s in names:
            out[s] = sign * round(per / float(prices[s]))
    return {s: q for s, q in out.items() if q != 0}


def per_name_value(sides: pd.Series, equity: float, leg: float = 0.5) -> float:
    n = max(int((sides == 1).sum()), int((sides == -1).sum()), 1)
    return leg * equity / n


def trades(target: dict[str, int], current: dict[str, int], prices: pd.Series, per_name: float,
           min_frac: float = 0.2) -> dict[str, tuple[int, int]]:
    """symbol -> (current shares, target shares) for every change worth trading. Closing a position and any
    change of side are always traded; other changes only if worth at least `min_frac` x `per_name`."""
    out = {}
    for s in sorted(set(target) | set(current)):
        a, b = current.get(s, 0), target.get(s, 0)
        if a == b:
            continue
        if b == 0 or a == 0 or np.sign(a) != np.sign(b) or abs(b - a) * float(prices.get(s, 0)) >= min_frac * per_name:
            out[s] = (a, b)
    return out


def buckets_left(minutes_since_open: float, after_hour: int = 6) -> list[tuple[int, float]]:
    """(bucket start in minutes after the open, weight) for the first-hour buckets that have not started; weights
    sum to 1. After the first hour: `after_hour` equal buckets from the next 5-minute mark."""
    k = int(np.ceil(max(minutes_since_open, 0) / BUCKET_MIN))
    if k < len(FIRST_HOUR_PROFILE):
        w = np.array(FIRST_HOUR_PROFILE[k:])
        return [(BUCKET_MIN * (k + i), float(x)) for i, x in enumerate(w / w.sum())]
    return [(BUCKET_MIN * (k + i), 1.0 / after_hour) for i in range(after_hour)]


def split(qty: int, weights) -> list[int]:
    """Whole-share parts of `qty` (>= 0) proportional to `weights`, by cumulative rounding (sum is exact)."""
    c = np.round(np.cumsum(weights) / np.sum(weights) * qty).astype(int)
    return np.diff(np.concatenate([[0], c])).tolist()


def child_orders(current: int, target: int, weights) -> list[list[int]]:
    """Signed child orders per bucket (one list per bucket) that move `current` to `target`. No order crosses zero:
    a flip closes the whole position in bucket 0 and opens the new side over the other buckets (all in bucket 0
    after the close if there is only one bucket)."""
    n = len(weights)
    out: list[list[int]] = [[] for _ in range(n)]
    if current != 0 and target != 0 and np.sign(current) != np.sign(target):
        out[0].append(-current)
        rest = weights[1:] if n > 1 else weights
        start = 1 if n > 1 else 0
        for i, q in enumerate(split(abs(target), rest)):
            if q:
                out[start + i].append(int(np.sign(target)) * q)
        return out
    d = target - current
    for i, q in enumerate(split(abs(d), weights)):
        if q:
            out[i].append(int(np.sign(d)) * q)
    return out


def side_of(order_qty: int) -> str:
    return "buy" if order_qty > 0 else "sell"
