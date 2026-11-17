"""Realism checks for simulated order-book paths: stylised facts and a discriminator test.

stylised_facts: the facts of Cont (2001) that a simulator must reproduce, on log mid returns.
discriminator_score: can a simple classifier tell real windows from simulated ones? AUC near 0.5 means it cannot.
The classifier is an L2 logistic regression on per-window summary statistics, with k-fold cross-validation, written
in numpy so that the check has no extra dependency.
"""
from __future__ import annotations

import numpy as np


def acf(x: np.ndarray, lags) -> np.ndarray:
    x = np.asarray(x, float)
    x = x[np.isfinite(x)] - np.nanmean(x)
    d = x @ x
    return np.array([x[:-k] @ x[k:] / d for k in lags])


def hill(x: np.ndarray, tail: float = 0.05) -> float:
    """Hill estimator of the tail index of |x| over the top `tail` fraction (smaller = fatter tails)."""
    a = np.sort(np.abs(x[np.isfinite(x)]))[::-1]
    k = max(int(tail * len(a)), 2)
    if a[k] <= 0:  # discrete data (e.g. tick moves): the top tail is not continuous, the estimator is undefined
        return float("nan")
    return float(1.0 / np.mean(np.log(a[:k] / a[k])))


def stylised_facts(returns: np.ndarray, aggregations=(1, 10, 60), lags=(1, 10, 60), spread=None) -> dict:
    """- kurt_h: excess kurtosis of returns summed over h steps (fat tails that fade with aggregation);
    - acf_ret_l: autocorrelation of returns (near 0: no linear predictability);
    - acf_abs_l: autocorrelation of |returns| (positive and slowly decaying: volatility clustering);
    - hill: tail index of returns; with spread: its mean, std and lag-1 autocorrelation."""
    r = np.asarray(returns, float)
    r = r[np.isfinite(r)]
    out = {}
    for h in aggregations:
        s = r[: len(r) // h * h].reshape(-1, h).sum(1)
        z = (s - s.mean()) / s.std()
        out[f"kurt_{h}"] = float(np.mean(z**4) - 3)
    for k, v in zip(lags, acf(r, lags), strict=True):
        out[f"acf_ret_{k}"] = float(v)
    for k, v in zip(lags, acf(np.abs(r), lags), strict=True):
        out[f"acf_abs_{k}"] = float(v)
    out["hill"] = hill(r)
    if spread is not None:
        sp = np.asarray(spread, float)
        out.update(spread_mean=float(np.nanmean(sp)), spread_std=float(np.nanstd(sp)), spread_acf_1=float(acf(sp, [1])[0]))
    return out


def window_stats(w: np.ndarray) -> np.ndarray:
    """Summary of one window (T, F): per feature mean, std, lag-1 autocorrelation, mean |diff|, max |value|."""
    w = np.nan_to_num(np.asarray(w, float))
    c = w - w.mean(0)
    den = (c**2).sum(0) + 1e-12
    ac1 = (c[1:] * c[:-1]).sum(0) / den
    return np.concatenate([w.mean(0), w.std(0), ac1, np.abs(np.diff(w, axis=0)).mean(0), np.abs(w).max(0)])


def _logreg(x, y, l2=1.0, iters=50):
    w = np.zeros(x.shape[1])
    for _ in range(iters):  # Newton steps
        p = 1 / (1 + np.exp(-x @ w))
        g = x.T @ (p - y) + l2 * w
        h = (x * (p * (1 - p))[:, None]).T @ x + l2 * np.eye(len(w))
        w -= np.linalg.solve(h, g)
    return w


def auc(score, y) -> float:
    r = np.argsort(np.argsort(score)) + 1.0
    n1 = y.sum()
    return float((r[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * (len(y) - n1)))


def discriminator_score(real: np.ndarray, fake: np.ndarray, folds: int = 5, seed: int = 0) -> float:
    """real, fake: (n_windows, T, F). Mean out-of-fold AUC of telling real (1) from fake (0)."""
    x = np.stack([window_stats(w) for w in np.concatenate([real, fake])])
    y = np.r_[np.ones(len(real)), np.zeros(len(fake))]
    fold = np.random.default_rng(seed).permutation(len(y)) % folds
    scores = np.zeros(len(y))
    for f in range(folds):
        tr = fold != f
        mu, sd = x[tr].mean(0), x[tr].std(0) + 1e-9
        ztr, zte = (np.c_[np.ones(len(a)), (a - mu) / sd] for a in (x[tr], x[~tr]))
        scores[~tr] = zte @ _logreg(ztr, y[tr])
    return auc(scores, y)
