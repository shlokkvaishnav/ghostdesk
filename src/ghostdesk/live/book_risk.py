"""Risk of the live book, measured each day (decision D22). It describes the book; it does not change the
pre-registered portfolio.

- **Covariance:** Ledoit and Wolf (2004) shrinkage of the sample covariance of daily returns toward a scaled
  identity. With about 200 stocks and 252 days the sample covariance is noisy; shrinkage gives a stable estimate.
- **Expected volatility:** sqrt(w' S w x 252), with w = position value / equity.
- **Beta to SPY:** sum of w_i x beta_i, each beta from the same daily window.
- **Sectors:** net and gross weight per sector; the largest single position.
A stock with fewer than `MIN_DAYS` daily returns in the window is left out of the covariance and counted.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

WINDOW, MIN_DAYS, YEAR = 252, 120, 252


def ledoit_wolf(x: np.ndarray) -> tuple[np.ndarray, float]:
    """x: (T, N) demeaned-or-not returns without NaN. Returns (shrunk covariance, shrinkage intensity in [0, 1])."""
    x = np.asarray(x, float)
    t, n = x.shape
    x = x - x.mean(axis=0)
    s = x.T @ x / t
    mu = np.trace(s) / n
    d2 = np.sum((s - mu * np.eye(n)) ** 2) / n
    b2_bar = sum(np.sum((np.outer(r, r) - s) ** 2) for r in x) / (n * t ** 2)
    b2 = min(b2_bar, d2)
    delta = b2 / d2 if d2 > 0 else 1.0
    return delta * mu * np.eye(n) + (1 - delta) * s, float(delta)


def book_risk(values: dict[str, float], equity: float, returns: pd.DataFrame, spy: pd.Series,
              sectors: dict[str, str]) -> dict:
    """values: symbol -> signed market value; returns: day x symbol simple daily returns; spy: SPY daily returns."""
    w = pd.Series(values, dtype=float) / equity
    r = returns.reindex(columns=w.index).tail(WINDOW)
    enough = r.notna().sum() >= MIN_DAYS
    used = w.index[enough.reindex(w.index, fill_value=False).to_numpy()]
    r = r[used].fillna(0.0)
    cov, delta = ledoit_wolf(r.to_numpy()) if len(used) else (np.zeros((0, 0)), float("nan"))
    wu = w[used].to_numpy()
    vol = float(np.sqrt(max(wu @ cov @ wu, 0.0) * YEAR)) if len(used) else float("nan")
    m = spy.reindex(r.index).fillna(0.0)
    var_m = float(m.var())
    betas = r.apply(lambda c: c.cov(m) / var_m if var_m > 0 else np.nan)
    sec = pd.Series({s: sectors.get(s) or "Unknown" for s in w.index})
    by = pd.DataFrame({"w": w, "sector": sec}).groupby("sector")["w"]
    sector_rows = pd.DataFrame({"net": by.sum(), "gross": by.apply(lambda x: x.abs().sum())})
    sector_rows = sector_rows.reindex(sector_rows["net"].abs().sort_values(ascending=False).index)
    top = w.abs().idxmax() if len(w) else None
    return {
        "vol_annual": vol,
        "beta_spy": float((betas * w[used]).sum()) if len(used) else float("nan"),
        "gross": float(w.abs().sum()), "net": float(w.sum()),
        "largest": {"symbol": top, "weight": float(w[top])} if top else None,
        "sectors": [{"sector": k, "net": round(float(v.net), 4), "gross": round(float(v.gross), 4)}
                    for k, v in sector_rows.iterrows()],
        "shrinkage": delta, "stocks": len(w), "stocks_without_history": int(len(w) - len(used)),
        "days": len(r),
    }
