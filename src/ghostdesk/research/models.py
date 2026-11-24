"""The model zoo: one interface for every model (decision D31).

A model sees a `Design`: features as a (T, N, F) float32 array (each feature cross-sectionally ranked to [-0.5, 0.5]
per session, missing = 0), the label (T, N), and a mask of usable cells. `fit(design, rows)` trains on the sessions
in `rows`; `predict(design, rows)` returns (len(rows), N) scores, high = expected to beat its sector.

Local models: 1-day and 5-day reversal (no fit), ridge regression and LightGBM. The Transformer and the foundation
models run on Kaggle (`kaggle/`); `ExternalScores` wraps their saved scores in the same interface.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ghostdesk.features import ops


@dataclass
class Design:
    X: np.ndarray            # (T, N, F) float32, ranked features, 0 where missing
    y: np.ndarray            # (T, N) label (NaN where unknown)
    mask: np.ndarray         # (T, N) bool: member with enough history
    names: list[str]
    close: np.ndarray        # (T, N) adjusted close (for the reversal models)


def rank_features(feats: dict[str, np.ndarray], mask: np.ndarray) -> tuple[np.ndarray, list[str]]:
    """Each feature -> cross-sectional percentile rank among the masked cells, centred to [-0.5, 0.5]; 0 elsewhere."""
    names = list(feats)
    T, N = mask.shape
    X = np.zeros((T, N, len(names)), dtype=np.float32)
    for k, name in enumerate(names):
        a = np.where(mask, feats[name], np.nan)
        r = ops.cs_rank(a) - 0.5
        X[:, :, k] = np.nan_to_num(r, nan=0.0)
    return X, names


def cs_rank_label(y: np.ndarray, mask: np.ndarray) -> np.ndarray:
    return ops.cs_rank(np.where(mask, y, np.nan)) - 0.5


class Model:
    name = "model"
    needs_fit = True

    def fit(self, d: Design, rows: np.ndarray) -> Model:
        return self

    def predict(self, d: Design, rows: np.ndarray) -> np.ndarray:
        raise NotImplementedError

    def config(self) -> dict:
        return {"name": self.name}


class Reversal(Model):
    """Score = minus the past `days`-day log return through the close of t (short-term reversal)."""
    needs_fit = False

    def __init__(self, days: int):
        self.days = days
        self.name = f"reversal_{days}d"

    def predict(self, d, rows):
        lc = np.log(d.close)
        r = lc - ops.ref(lc, self.days)
        return np.where(d.mask[rows], -r[rows], np.nan)

    def config(self):
        return {"name": self.name, "days": self.days}


def _train_cells(d: Design, rows: np.ndarray):
    y = cs_rank_label(d.y, d.mask)[rows]
    m = d.mask[rows] & np.isfinite(y)
    return d.X[rows][m], y[m]


class Ridge(Model):
    """Ridge regression on the ranked features against the ranked label (closed form, float64)."""
    name = "ridge"

    def __init__(self, alpha: float = 100.0):
        self.alpha = alpha

    def fit(self, d, rows):
        X, y = _train_cells(d, rows)
        X = X.astype(np.float64)
        A = X.T @ X + self.alpha * len(y) / 1e4 * np.eye(X.shape[1])
        self.w = np.linalg.solve(A, X.T @ y)
        return self

    def predict(self, d, rows):
        s = d.X[rows].astype(np.float64) @ self.w
        return np.where(d.mask[rows], s, np.nan)

    def config(self):
        return {"name": self.name, "alpha": self.alpha}


@dataclass
class LightGBM(Model):
    """Gradient-boosted trees on the ranked features against the ranked label. Deterministic: fixed seed, one
    thread layout, `deterministic=True`, so a rerun gives the same bytes."""
    rounds: int = 300
    params: dict = field(default_factory=lambda: {
        "objective": "regression", "learning_rate": 0.05, "num_leaves": 31, "min_data_in_leaf": 500,
        "feature_fraction": 0.7, "bagging_fraction": 0.7, "bagging_freq": 1, "lambda_l2": 10.0, "verbose": -1,
        "seed": 7, "deterministic": True, "force_col_wise": True, "num_threads": 8})
    name: str = "lightgbm"

    def fit(self, d, rows):
        import lightgbm as lgb

        X, y = _train_cells(d, rows)
        self.booster = lgb.train(self.params, lgb.Dataset(X, y, free_raw_data=True), num_boost_round=self.rounds)
        return self

    def predict(self, d, rows):
        T, N, F = d.X[rows].shape
        s = self.booster.predict(d.X[rows].reshape(-1, F), num_threads=self.params["num_threads"]).reshape(T, N)
        return np.where(d.mask[rows], s, np.nan)

    def config(self):
        return {"name": self.name, "rounds": self.rounds, **self.params}


class ExternalScores(Model):
    """Scores computed elsewhere (Kaggle): `days` (YYYYMMDD ints) and `scores` (sessions x symbols, same symbol
    order as the panel). Sessions not in the file get NaN."""
    needs_fit = False

    def __init__(self, name: str, days: np.ndarray, scores: np.ndarray, panel_days):
        self.name = name
        pos = {int(x): i for i, x in enumerate(days)}
        self.rows_of = np.array([pos.get(int(f"{d:%Y%m%d}"), -1) for d in panel_days])
        self.scores = scores

    def predict(self, d, rows):
        idx = self.rows_of[rows]
        out = np.full((len(rows), d.mask.shape[1]), np.nan)
        ok = idx >= 0
        out[ok] = self.scores[idx[ok]]
        return np.where(d.mask[rows], out, np.nan)


def zoo() -> list[Model]:
    """The local models of the pre-registered comparison."""
    return [Reversal(1), Reversal(5), Ridge(), LightGBM()]
