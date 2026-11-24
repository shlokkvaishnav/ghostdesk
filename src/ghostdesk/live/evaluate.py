"""Forward scoring of the prediction ledger (decision D37).

The ledger is read as it is; a prediction is scored only after its two opens exist (`ledger.score` drops a session
whose open(t+2) is not known yet, so nothing is scored early). From the scored rows this module builds one row per
(session, model) and a summary per model, next to two baselines:

- **zero signal:** a model that makes no pick and has no ordering. Its rank IC is 0, it trades nothing, so its
  P&L is 0. A model must beat this after costs to be worth running.
- **reversal baselines:** `reversal_1d` and `reversal_5d` from the same ledger. Each model's mean IC and total
  P&L are also given as a difference to each of them.

Hit rate here is the directional accuracy of the picks before costs: the share of long and short picks whose
residual return has the pick's sign (the same definition as the backtest). `profitable_share` is the owner's
after-cost definition (D30). With no data every function returns well-formed empty results with `days = 0`.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

MIN_NAMES = 30  # fewest scored stocks for a rank IC (the backtest uses the same floor)
REVERSALS = ("reversal_1d", "reversal_5d")
DAILY_COLUMNS = ["session", "model", "ic", "hit", "profitable", "picks", "abs_error", "pnl"]


def daily_metrics(scored: pd.DataFrame) -> pd.DataFrame:
    """One row per (session, model) from `ledger.score` output: rank IC of score against the residual return,
    directional hit rate of the picks, share of picks profitable after costs, number of picks, mean absolute error
    of the return forecast (NaN if the model forecasts none) and the decile book's P&L (long mean + short mean)."""
    s = scored.dropna(subset=["realized"]) if len(scored) else scored
    rows = []
    for (sess, model), g in s.groupby(["session", "model"]):
        ok = g.dropna(subset=["score", "residual"])
        ic = ok["score"].corr(ok["residual"], method="spearman") if len(ok) >= MIN_NAMES else np.nan
        picks = g[g["side"] != 0].dropna(subset=["residual"])
        hit = float((np.sign(picks["residual"]) == picks["side"]).mean()) if len(picks) else np.nan
        pnl = float(picks.groupby("side")["pnl"].mean().sum()) if len(picks) else np.nan
        rows.append({"session": sess, "model": model, "ic": ic, "hit": hit,
                     "profitable": float(picks["profitable"].mean()) if len(picks) else np.nan,
                     "picks": len(picks), "abs_error": float(g["abs_error"].mean()) if g["abs_error"].notna().any()
                     else np.nan, "pnl": pnl})
    return pd.DataFrame(rows, columns=DAILY_COLUMNS)


def _num(x: float) -> float | None:
    return None if x is None or not np.isfinite(x) else round(float(x), 5)


def summarize(daily: pd.DataFrame) -> dict:
    """Per model: `days`, mean IC and its t statistic, hit rate, profitable share, mean abs error, mean and total
    P&L, and differences to the reversal baselines and to the zero-signal model. `forward_days` is the number of
    distinct scored sessions (0 on an empty ledger)."""
    days = int(daily["session"].nunique()) if len(daily) else 0
    models: dict[str, dict] = {}
    for m, g in daily.groupby("model"):
        ic = g["ic"].dropna()
        t = ic.mean() / ic.std() * np.sqrt(len(ic)) if len(ic) > 1 and ic.std() > 0 else np.nan
        pnl = g["pnl"].dropna()
        models[str(m)] = {"days": int(g["session"].nunique()), "ic_mean": _num(ic.mean() if len(ic) else np.nan),
                          "ic_t": _num(t), "hit_rate": _num(g["hit"].mean()),
                          "profitable_share": _num(g["profitable"].mean()),
                          "abs_error": _num(g["abs_error"].mean()), "pnl_mean": _num(pnl.mean() if len(pnl) else np.nan),
                          "pnl_total": _num(pnl.sum() if len(pnl) else np.nan)}
    for m, row in models.items():
        row["vs_zero_signal_pnl"] = row["pnl_total"]  # the zero-signal model earns exactly 0
        row["vs_zero_signal_ic"] = row["ic_mean"]  # and has IC 0
        for b in REVERSALS:
            base = models.get(b)
            for key, name in (("ic_mean", "ic"), ("pnl_total", "pnl")):
                a, c = row[key], (base or {}).get(key)
                row[f"vs_{b}_{name}"] = None if a is None or c is None else _num(a - c)
    return {"forward_days": days, "models": models,
            "baselines": {"zero_signal": {"ic_mean": 0.0, "pnl_total": 0.0, "days": days}}}
