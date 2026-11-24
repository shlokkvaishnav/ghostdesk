"""From target weights to orders: whole-share targets and the trades that reach them.

The nightly loop (decision D30) sends market-on-open orders, which Alpaca accepts only in whole shares, so every
target is whole shares; a stock whose target rounds to 0 shares is left out. A trade smaller than `min_frac` of the
stock's target value is skipped, so a rerun on the same night does not trade again. A position never crosses zero
inside one order (Alpaca rejects that): `orders_for` closes the old side first.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def target_shares_from_weights(weights: pd.Series, prices: pd.Series, equity: float) -> dict[str, float]:
    """weights: symbol -> signed share of equity. Whole shares (rounded to the nearest); stocks without a positive
    price or with 0 shares are left out."""
    out = {}
    for s, w in weights.items():
        p = float(prices.get(s, 0) or 0)
        if p > 0 and w:
            q = float(round(w * equity / p))
            if q:
                out[s] = q
    return out


def orders_for(current: float, target: float) -> list[float]:
    """Signed orders that move `current` to `target` without crossing zero: a flip is a close, then an open."""
    if current and target and np.sign(current) != np.sign(target):
        return [-current, target]
    d = round(target - current, 4)
    return [d] if d else []


def trades(target: dict[str, float], current: dict[str, float], prices: pd.Series, per_name: float,
           min_frac: float = 0.2) -> dict[str, tuple[float, float]]:
    """symbol -> (current shares, target shares) for every change worth trading. Closing a position and any
    change of side are always traded; other changes only if worth at least `min_frac` x `per_name`."""
    out = {}
    for s in sorted(set(target) | set(current)):
        a, b = current.get(s, 0), target.get(s, 0)
        if abs(a - b) < 0.5e-4:
            continue
        if b == 0 or a == 0 or np.sign(a) != np.sign(b) or abs(b - a) * float(prices.get(s, 0)) >= min_frac * per_name:
            out[s] = (a, b)
    return out


def side_of(order_qty: float) -> str:
    return "buy" if order_qty > 0 else "sell"
