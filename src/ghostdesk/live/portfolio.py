"""Forward tracking of the paper book from the nightly target books (decision D37).

The nightly record `night_<YYYYMMDD>.json` holds `target` (signed whole shares per stock the optimizer wanted held
after that session) and `equity`. For a session s, the book is bought at the open of the next session (o1) and held
to the one after (o2), the same window as the ledger label. So, per stock, value = shares x o1, weight = value /
equity, and the book's gross return = sum(shares x (o2 - o1)) / equity.

- **Turnover:** sum of |w_new - w_prev| where both are valued at o1 (the earlier book's shares carry over); the first
  book trades from cash.
- **Cost:** per stock, turnover weight x (half Corwin-Schultz spread through s + `fixed_bps`), the cost model of the
  backtest (`research.backtest.half_spread`) and of `ledger.score`.
- **Metrics:** cumulative net return (compounded), Sharpe (mean / std of the daily net return x sqrt(252); needs two
  or more days and a non-zero spread), maximum drawdown of the compounded curve, mean turnover, total cost.

This is the book the optimizer asked for, priced at opens; it is not the account's fills (the site shows the account
against SPY). Sessions whose two opens are not both known are not counted.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

YEAR = 252
FIXED_BPS = 2.0


def book_days(books: dict[pd.Timestamp, dict], opens: pd.DataFrame, half_spread: pd.DataFrame | None = None,
              fixed_bps: float = FIXED_BPS) -> pd.DataFrame:
    """One row per matured session: gross, cost, net (fractions of equity), turnover, gross_exposure, missing (stocks
    without both opens). `books`: session -> {"target": {symbol: shares}, "equity": float}; `opens`: session x symbol."""
    days = opens.index
    out = []
    prev: dict[str, float] = {}
    for s in sorted(books):
        i = days.searchsorted(pd.Timestamp(s), side="right")
        book = books[s]
        eq = float(book.get("equity") or 0)
        if i + 1 >= len(days) or eq <= 0:
            continue
        o1, o2 = opens.iloc[i], opens.iloc[i + 1]
        tgt = {k: float(v) for k, v in (book.get("target") or {}).items()}
        syms = sorted(set(tgt) | set(prev))
        px1 = o1.reindex(syms)
        px2 = o2.reindex(syms)
        sh = pd.Series({k: tgt.get(k, 0.0) for k in syms}, dtype=float)
        sh0 = pd.Series({k: prev.get(k, 0.0) for k in syms}, dtype=float)
        known = px1.notna() & px2.notna() & (px1 > 0)
        gross = float((sh[known] * (px2[known] - px1[known])).sum() / eq)
        trade_w = ((sh - sh0).abs() * px1)[known] / eq
        if half_spread is not None and len(half_spread.loc[:s]):
            hs = half_spread.loc[:s].iloc[-1].reindex(syms)[known].fillna(0.0)
        else:
            hs = pd.Series(0.0, index=trade_w.index)
        cost = float((trade_w * (hs + fixed_bps / 1e4)).sum())
        out.append({"session": pd.Timestamp(s), "gross": gross, "cost": cost, "net": gross - cost,
                    "turnover": float(trade_w.sum()), "gross_exposure": float((sh.abs() * px1)[known].sum() / eq),
                    "missing": int((~known & (sh != 0)).sum())})
        prev = {k: v for k, v in tgt.items()}
    return pd.DataFrame(out, columns=["session", "gross", "cost", "net", "turnover", "gross_exposure", "missing"])


def _curve(net: pd.Series) -> tuple[np.ndarray, np.ndarray]:
    """Compounded curve (start 1) and its drawdown from the running peak."""
    c = np.cumprod(1 + net.to_numpy(dtype=float))
    peak = np.maximum.accumulate(np.concatenate([[1.0], c]))[1:]
    return c, c / peak - 1


def book_summary(days: pd.DataFrame) -> dict:
    """Cumulative return, Sharpe, max drawdown, turnover and cost over the matured days. Values that cannot be
    computed from the sample (Sharpe on one day) are None; `days` is always given."""
    n = len(days)
    if not n:
        return {"days": 0, "cum_return": None, "sharpe": None, "max_drawdown": None, "turnover_mean": None,
                "cost_total": None, "gross_return_cum": None}
    c, dd = _curve(days["net"])
    sd = days["net"].std()
    sharpe = float(days["net"].mean() / sd * np.sqrt(YEAR)) if n > 1 and sd > 0 else None
    return {"days": n, "cum_return": float(c[-1] - 1), "sharpe": sharpe, "max_drawdown": float(dd.min()),
            "turnover_mean": float(days["turnover"].mean()), "cost_total": float(days["cost"].sum()),
            "gross_return_cum": float(np.prod(1 + days["gross"].to_numpy(dtype=float)) - 1)}


def curve(days: pd.DataFrame) -> list[dict]:
    """Date, cumulative net return and drawdown per day, for the site."""
    if days.empty:
        return []
    c, dd = _curve(days["net"])
    return [{"day": f"{d:%Y-%m-%d}", "cum": round(float(v - 1), 6), "dd": round(float(x), 6)}
            for d, v, x in zip(days["session"], c, dd, strict=True)]
