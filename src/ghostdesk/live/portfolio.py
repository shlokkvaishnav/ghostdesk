"""From quintiles to orders: target shares, the trades to reach them, and a VWAP schedule of child orders.

Decision D15: long Q5 and short Q1, equal weights, each leg `leg` of equity (the live job uses 0.9). Longs in fractionable stocks use
fractional shares (4 decimals, `UNIT_FRACTIONAL`); shorts and other stocks use whole shares (Alpaca does not allow
fractional short sales); a stock whose whole-share target rounds to 0 is left out and reported. A trade smaller
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


UNIT_FRACTIONAL = 0.0001


def target_shares(sides: pd.Series, prices: pd.Series, equity: float, leg: float = 1.0,
                  fractional: set[str] | frozenset = frozenset()) -> dict[str, float]:
    """sides: symbol -> +1 (long), -1 (short), 0. Equal value per stock in each leg. Longs in `fractional` get
    shares to 4 decimals; all other positions whole shares. Stocks without a positive price, or whose whole-share
    target rounds to 0, get no position (see `too_expensive`)."""
    out: dict[str, float] = {}
    for sign in (1, -1):
        names = [s for s, v in sides.items() if v == sign and prices.get(s, 0) > 0]
        if not names:
            continue
        per = leg * equity / len(names)
        for s in names:
            q = per / float(prices[s])
            out[s] = sign * (round(q, 4) if sign == 1 and s in fractional else float(round(q)))
    return {s: q for s, q in out.items() if q != 0}


def too_expensive(sides: pd.Series, target: dict[str, float], prices: pd.Series) -> list[str]:
    """Selected stocks with a price but no target (their whole-share target rounded to 0)."""
    return sorted(s for s, v in sides.items() if v != 0 and prices.get(s, 0) > 0 and s not in target)


def unit_of(symbol: str, current: float, target: float, fractional: set[str] | frozenset) -> float:
    """Order unit: 0.0001 when the long side of a fractionable stock is traded (long now or long at the target, a
    flip included), or when a fractional long is closed; else 1. In a flip, `child_orders` closes the old side in
    one order of the exact current size and opens a new short side in whole shares, so a mixed flip is safe."""
    if (symbol in fractional and (current > 0 or target > 0)) or (current > 0 and current != round(current)):
        return UNIT_FRACTIONAL
    return 1.0


def per_name_value(sides: pd.Series, equity: float, leg: float = 1.0) -> float:
    n = max(int((sides == 1).sum()), int((sides == -1).sum()), 1)
    return leg * equity / n


def trades(target: dict[str, float], current: dict[str, float], prices: pd.Series, per_name: float,
           min_frac: float = 0.2) -> dict[str, tuple[float, float]]:
    """symbol -> (current shares, target shares) for every change worth trading. Closing a position and any
    change of side are always traded; other changes only if worth at least `min_frac` x `per_name`."""
    out = {}
    for s in sorted(set(target) | set(current)):
        a, b = current.get(s, 0), target.get(s, 0)
        if abs(a - b) < UNIT_FRACTIONAL / 2:
            continue
        if b == 0 or a == 0 or np.sign(a) != np.sign(b) or abs(b - a) * float(prices.get(s, 0)) >= min_frac * per_name:
            out[s] = (a, b)
    return out


def learned_profile(minutes: pd.DataFrame, min_days: int = 200) -> tuple[tuple[float, ...], int]:
    """The first-hour 5-minute volume profile from recent minute bars (`symbol, t` (UTC), `v`), as the mean over
    stock-days of each bucket's share of that stock-day's first-hour volume. Decision D16: this is the only part
    of the desk that adapts; it learns from market data, never from the desk's own (simulated) fills.
    Returns (profile, stock-days used); `FIRST_HOUR_PROFILE` when fewer than `min_days` stock-days."""
    if minutes.empty:
        return FIRST_HOUR_PROFILE, 0
    m = minutes.copy()
    t = pd.to_datetime(m["t"], utc=True).dt.tz_convert("America/New_York")
    m["day"] = t.dt.normalize()
    m["minute"] = (t - m["day"]).dt.total_seconds() / 60 - 570  # minutes after 09:30
    m = m[(m["minute"] >= 0) & (m["minute"] < BUCKET_MIN * len(FIRST_HOUR_PROFILE))]
    m["b"] = (m["minute"] // BUCKET_MIN).astype(int)
    g = m.groupby(["symbol", "day", "b"])["v"].sum().unstack(fill_value=0.0)
    g = g.reindex(columns=range(len(FIRST_HOUR_PROFILE)), fill_value=0.0)
    g = g[g.sum(axis=1) > 0]
    if len(g) < min_days:
        return FIRST_HOUR_PROFILE, len(g)
    w = g.div(g.sum(axis=1), axis=0).mean().to_numpy()
    return tuple(round(float(x), 4) for x in w / w.sum()), len(g)


def buckets_left(minutes_since_open: float, after_hour: int = 6,
                 profile=FIRST_HOUR_PROFILE) -> list[tuple[int, float]]:
    """(bucket start in minutes after the open, weight) for the first-hour buckets that have not started; weights
    sum to 1. After the first hour: `after_hour` equal buckets from the next 5-minute mark."""
    k = int(np.ceil(max(minutes_since_open, 0) / BUCKET_MIN))
    if k < len(profile):
        w = np.array(profile[k:])
        return [(BUCKET_MIN * (k + i), float(x)) for i, x in enumerate(w / w.sum())]
    return [(BUCKET_MIN * (k + i), 1.0 / after_hour) for i in range(after_hour)]


def split(qty: float, weights, unit: float = 1.0) -> list[float]:
    """Parts of `qty` (>= 0) in multiples of `unit`, proportional to `weights`, by cumulative rounding (the sum is
    exact to the unit)."""
    n = round(qty / unit)
    c = np.round(np.cumsum(weights) / np.sum(weights) * n).astype(int)
    return [round(int(k) * unit, 4) for k in np.diff(np.concatenate([[0], c]))]


def child_orders(current: float, target: float, weights, unit: float = 1.0) -> list[list[float]]:
    """Signed child orders per bucket (one list per bucket) that move `current` to `target`. No order crosses zero:
    a flip closes the whole position in bucket 0 and opens the new side over the other buckets (all in bucket 0
    after the close if there is only one bucket). `unit` is the share unit of the orders (1 or 0.0001)."""
    n = len(weights)
    out: list[list[float]] = [[] for _ in range(n)]
    if current != 0 and target != 0 and np.sign(current) != np.sign(target):
        out[0].append(-current)
        rest = weights[1:] if n > 1 else weights
        start = 1 if n > 1 else 0
        new_unit = 1.0 if target < 0 else unit
        for i, q in enumerate(split(abs(target), rest, new_unit)):
            if q:
                out[start + i].append(float(np.sign(target)) * q)
        return out
    d = target - current
    for i, q in enumerate(split(abs(d), weights, unit)):
        if q:
            out[i].append(float(np.sign(d)) * q)
    return out


def side_of(order_qty: float) -> str:
    return "buy" if order_qty > 0 else "sell"
