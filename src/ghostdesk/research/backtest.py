"""Walk-forward backtests with purged splits and trading costs (decision D32).

- **Folds:** one per calendar year to predict. A fold trains on every session from the start up to the first
  session of its year minus `purge` sessions (the label of day t is known only at the open of t+2, so 2 sessions
  is the smallest purge that keeps a training label from overlapping the predicted days).
- **Portfolio of the score:** each session, equal weights long the top 10% and short the bottom 10% of members by
  score (dollar neutral, gross 2 = 1 long + 1 short). Weights are traded at the next open and held to the open after.
- **Return:** the raw open(t+1) -> open(t+2) return of the book (what trading earns), and the residual label.
- **Costs:** per stock, half the Corwin-Schultz spread (mean of the last 21 two-day estimates through t, floored at
  0) times the weight traded, plus a fixed grid of 0, 1, 2, 5 and 10 bps per unit traded.
- **Metrics per session:** rank IC (Spearman of score and residual label among members), hit rate (share of the
  long and short picks whose residual has the side's sign), gross and net return, turnover (sum of |weight change|).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ghostdesk.data.spread_estimate import corwin_schultz
from ghostdesk.research.models import Design, Model

FIXED_BPS = (0, 1, 2, 5, 10)
YEAR = 252


def folds(days: pd.DatetimeIndex, years: list[int], purge: int = 2) -> list[tuple[np.ndarray, np.ndarray]]:
    """(train rows, predict rows) per year; train ends `purge` sessions before the year's first session."""
    out = []
    for y in years:
        pred = np.where(days.year == y)[0]
        if not len(pred):
            continue
        out.append((np.arange(0, max(pred[0] - purge, 0)), pred))
    return out


def walk_forward(model: Model, d: Design, days: pd.DatetimeIndex, years: list[int], purge: int = 2,
                 first_train_row: int = 0) -> np.ndarray:
    """(T, N) out-of-sample scores (NaN outside the predicted years)."""
    scores = np.full(d.y.shape, np.nan)
    for train, pred in folds(days, years, purge):
        train = train[train >= first_train_row]
        if model.needs_fit:
            model.fit(d, train)
        scores[pred] = model.predict(d, pred)
    return scores


def half_spread(high: np.ndarray, low: np.ndarray, close: np.ndarray, window: int = 21) -> np.ndarray:
    """(T, N) half of the mean Corwin-Schultz two-day spread over the last `window` estimates through t."""
    out = np.full(close.shape, np.nan)
    for j in range(close.shape[1]):
        s = corwin_schultz(high[:, j], low[:, j], close[:, j], floor=False)
        out[:, j] = s.rolling(window, min_periods=5).mean().clip(lower=0).to_numpy() / 2
    return out


def decile_weights(scores: np.ndarray, mask: np.ndarray, q: float = 0.1) -> np.ndarray:
    """(T, N) weights: +1/n on the top q of members by score, -1/n on the bottom q."""
    w = np.zeros(scores.shape)
    for t in range(scores.shape[0]):
        s = np.where(mask[t], scores[t], np.nan)
        ok = np.where(np.isfinite(s))[0]
        k = int(len(ok) * q)
        if k < 1:
            continue
        order = ok[np.argsort(s[ok], kind="stable")]
        w[t, order[-k:]] = 1.0 / k
        w[t, order[:k]] = -1.0 / k
    return w


def rank_ic(scores: np.ndarray, label: np.ndarray, mask: np.ndarray) -> np.ndarray:
    from scipy.stats import spearmanr

    out = np.full(scores.shape[0], np.nan)
    for t in range(scores.shape[0]):
        m = mask[t] & np.isfinite(scores[t]) & np.isfinite(label[t])
        if m.sum() >= 30 and np.ptp(scores[t, m]) > 0:
            out[t] = spearmanr(scores[t, m], label[t, m]).statistic
    return out


def evaluate(weights: np.ndarray, scores: np.ndarray, label: np.ndarray, ret: np.ndarray, hspread: np.ndarray,
             mask: np.ndarray, rows: np.ndarray) -> dict:
    """Per-session series and summary over `rows`. `ret`: raw open(t+1) -> open(t+2) simple return."""
    w = weights[rows]
    prev = np.vstack([np.zeros((1, w.shape[1])), w[:-1]])
    trade = np.abs(w - prev)
    r = np.nan_to_num(ret[rows])
    gross = (w * r).sum(axis=1)
    spread_cost = (trade * np.nan_to_num(hspread[rows], nan=np.nanmedian(hspread[rows]))).sum(axis=1)
    turnover = trade.sum(axis=1)
    ic = rank_ic(scores[rows], label[rows], mask[rows])
    lab = label[rows]
    with np.errstate(invalid="ignore"):
        long_ok = ((w > 0) & (lab > 0)).sum(axis=1)
        short_ok = ((w < 0) & (lab < 0)).sum(axis=1)
        picks = ((w != 0) & np.isfinite(lab)).sum(axis=1)
        hit = np.where(picks > 0, (long_ok + short_ok) / np.maximum(picks, 1), np.nan)
    known = np.isfinite(lab).any(axis=1)  # the last two sessions have no label yet
    series = pd.DataFrame({"gross": gross, "spread_cost": spread_cost, "turnover": turnover, "ic": ic, "hit": hit})
    series = series[known]
    return {"series": series, "summary": summarize(series)}


def summarize(s: pd.DataFrame) -> dict:
    def ann(x):
        sd = x.std()
        return {"mean_bps": round(float(x.mean() * 1e4), 3), "ann_return": round(float(x.mean() * YEAR), 4),
                "sharpe": round(float(x.mean() / sd * np.sqrt(YEAR)), 3) if sd > 0 else None}

    ic = s["ic"].dropna()
    out = {"sessions": len(s), "ic_mean": round(float(ic.mean()), 5),
           "ic_t": round(float(ic.mean() / ic.std() * np.sqrt(len(ic))), 2) if len(ic) > 1 and ic.std() > 0 else None,
           "hit_rate": round(float(s["hit"].mean()), 4), "turnover": round(float(s["turnover"].mean()), 4),
           "gross": ann(s["gross"]), "net_spread": ann(s["gross"] - s["spread_cost"])}
    for b in FIXED_BPS:
        out[f"net_{b}bps"] = ann(s["gross"] - s["turnover"] * b / 1e4)
    return out
