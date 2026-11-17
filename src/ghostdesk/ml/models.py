"""Walk-forward models of next month's cross-sectional return rank.

For each formation month m from `first`, a model is fit on all earlier months (rows with month < m, whose forward
returns ended by the formation close of m) and predicts the stocks of month m. So every prediction is out of sample,
and the model "learns" each month from one more month of 500 stocks, never from its own trades.

Target: the rank of `fwd_ret` within the month, in [-0.5, 0.5] (scale-free across calm and wild months).
Models (fixed settings; the grid in `GBM_GRID` is chosen on the check period only):
- `linear`: ridge regression on the ranked characteristics (the baseline a tree model must beat).
- `gbm`: LightGBM regression trees, averaged over `SEEDS` seeds.
"""
from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pandas as pd

SEEDS = (0, 1, 2)
GBM_BASE = {"objective": "regression", "learning_rate": 0.03, "n_estimators": 300, "num_leaves": 15,
            "min_child_samples": 200, "subsample": 0.8, "subsample_freq": 1, "colsample_bytree": 0.8,
            "reg_lambda": 1.0, "verbose": -1, "n_jobs": 4}
GBM_GRID = {  # chosen once on the check period (2020-2021), then fixed
    "small": {"num_leaves": 7, "n_estimators": 200},
    "base": {},
    "large": {"num_leaves": 31, "n_estimators": 500, "learning_rate": 0.02},
}
RIDGE_ALPHA = 10.0

Predictor = Callable[[pd.DataFrame], np.ndarray]
Fit = Callable[[pd.DataFrame, pd.Series], Predictor]  # fit(x, y) -> predict(x_new)


def target(panel: pd.DataFrame) -> pd.Series:
    """Rank of the forward return within each month, in [-0.5, 0.5]."""
    return panel.groupby("month")["fwd_ret"].rank(pct=True) - 0.5


def ridge(alpha: float = RIDGE_ALPHA) -> Fit:
    def fit(x: pd.DataFrame, y: pd.Series) -> Predictor:
        a = np.column_stack([np.ones(len(x)), x.to_numpy()])
        reg = alpha * np.eye(a.shape[1])
        reg[0, 0] = 0.0  # no penalty on the constant
        b = np.linalg.solve(a.T @ a + reg, a.T @ y.to_numpy())
        return lambda x_new: np.column_stack([np.ones(len(x_new)), x_new.to_numpy()]) @ b
    return fit


def gbm(params: dict | None = None, seeds=SEEDS) -> Fit:
    import lightgbm as lgb

    def fit(x: pd.DataFrame, y: pd.Series) -> Predictor:
        # the native API (no scikit-learn); the parameter names above are LightGBM aliases
        models = [lgb.train(GBM_BASE | (params or {}) | {"random_state": s}, lgb.Dataset(x, y)) for s in seeds]
        return lambda x_new: np.mean([m.predict(x_new) for m in models], axis=0)
    return fit


def walk_forward(panel: pd.DataFrame, features: list[str], fit: Fit, first: str, min_train_months: int = 24,
                 refit_every: int = 12) -> pd.DataFrame:
    """Out-of-sample predictions (`pred`) for each month from `first`. panel: ranked characteristics
    (`characteristics.rank_features`) with month, cik and fwd_ret. The model is refit every `refit_every` months
    (12: each January) on all earlier months; months with fewer than `min_train_months` earlier months are skipped.
    `fit_month` records which months trained each prediction (all are < month)."""
    p = panel.dropna(subset=["fwd_ret"]).copy()
    p["y"] = target(p)
    months = sorted(panel["month"].unique())
    out, fit_i, predict = [], None, None
    for i, m in enumerate(months):
        if m < pd.Timestamp(first) or i < min_train_months:
            continue
        if fit_i is None or i - fit_i >= refit_every:
            train = p[p["month"] < m]
            predict, fit_i = fit(train[features], train["y"]), i
        new = panel[panel["month"] == m]
        out.append(new[["month", "cik"]].assign(pred=predict(new[features]), fit_month=months[fit_i]))
    return pd.concat(out, ignore_index=True)
