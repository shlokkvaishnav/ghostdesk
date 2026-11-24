"""Portfolio optimizer with a statistical factor risk model (decision D33).

**Risk model** (`pca_risk`): from the last 252 sessions of daily close-to-close returns through t of the stocks
that are members at t (missing returns = 0 after demeaning), the top K = 12 principal components are the factors:
B (N x K) loadings, f (K) factor variances, and the specific variance of each stock (variance of what the factors
leave, floored at a 10th of the median). Covariance = B diag(f) B' + diag(spec).

**Problem** (one cvxpy problem with parameters, built once per universe size and re-solved each session):

    maximize   alpha'w - risk_aversion * (||sqrt(f) * (B'w)||^2 + ||sqrt(spec) * w||^2) - cost' |w - w_prev|
    subject to sum(w) = 0 (dollar neutral)       |beta'w| <= 0.01 (beta neutral)
               |S'w| <= 0.05 per sector          |w_i| <= 0.02 (2% of the book), 0 for non-members
               sum |w| <= 2 (1 long + 1 short)

alpha = IC x specific volatility x z-score of the model score (Grinold's rule; IC = 0.02 assumed before any
result); cost = half spread + fixed bps per unit traded. Solved with OSQP after cvxpy compiles the parameterized
problem once, so each session only updates numbers.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import cvxpy as cp
import numpy as np


@dataclass(frozen=True)
class OptConfig:
    factors: int = 12
    window: int = 252
    risk_aversion: float = 10.0
    max_weight: float = 0.02
    sector_band: float = 0.05
    beta_band: float = 0.01
    gross: float = 2.0
    ic: float = 0.02
    fixed_bps: float = 2.0


def pca_risk(returns: np.ndarray, k: int = 12) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """returns: (W, N) daily returns (NaN allowed). Returns B (N, k), factor variances (k,), specific variances (N,)."""
    r = np.where(np.isfinite(returns), returns, np.nan)
    r = r - np.nanmean(r, axis=0, keepdims=True)
    r = np.nan_to_num(r, nan=0.0)
    _, s, vt = np.linalg.svd(r, full_matrices=False)
    k = min(k, len(s))
    B = vt[:k].T                                  # (N, k) orthonormal loadings
    fvar = s[:k] ** 2 / max(len(r) - 1, 1)
    resid = r - (r @ B) @ B.T
    spec = resid.var(axis=0, ddof=1)
    floor = 0.1 * np.median(spec[spec > 0]) if (spec > 0).any() else 1e-6
    return B, fvar, np.maximum(spec, floor)


class Optimizer:
    """A parameterized problem for `n` stocks and the sector matrix `S` (n x G, one-hot)."""

    def __init__(self, n: int, S: np.ndarray, cfg: OptConfig = OptConfig()):
        self.cfg, self.n = cfg, n
        k = cfg.factors
        self.alpha = cp.Parameter(n)
        self.B = cp.Parameter((n, k))
        self.sqrt_f = cp.Parameter(k, nonneg=True)
        self.sqrt_spec = cp.Parameter(n, nonneg=True)
        self.beta = cp.Parameter(n)
        self.cost = cp.Parameter(n, nonneg=True)
        self.prev = cp.Parameter(n)
        self.cap = cp.Parameter(n, nonneg=True)
        self.w = cp.Variable(n)
        f = cp.Variable(k)
        trade = cp.Variable(n)  # w - w_prev as its own variable keeps the problem DPP (cost @ |trade|)
        risk = cp.sum_squares(cp.multiply(self.sqrt_f, f)) + cp.sum_squares(cp.multiply(self.sqrt_spec, self.w))
        obj = self.alpha @ self.w - cfg.risk_aversion * risk - self.cost @ cp.abs(trade)
        cons = [f == self.B.T @ self.w, trade == self.w - self.prev, cp.sum(self.w) == 0, cp.abs(self.beta @ self.w) <= cfg.beta_band,
                cp.abs(S.T @ self.w) <= cfg.sector_band, cp.abs(self.w) <= self.cap,
                cp.norm1(self.w) <= cfg.gross]
        self.problem = cp.Problem(cp.Maximize(obj), cons)
        assert self.problem.is_dpp()

    def solve(self, alpha, B, fvar, spec, beta, cost, prev, member) -> tuple[np.ndarray, dict]:
        cfg = self.cfg
        self.alpha.value = np.where(member, alpha, 0.0)
        self.B.value = B
        self.sqrt_f.value = np.sqrt(fvar)
        self.sqrt_spec.value = np.sqrt(spec)
        self.beta.value = np.where(member, beta, 0.0)
        self.cost.value = cost
        self.prev.value = prev
        self.cap.value = np.where(member, cfg.max_weight, 0.0)
        t0 = time.perf_counter()
        try:
            self.problem.solve(solver=cp.OSQP, warm_start=True, max_iter=20000, eps_abs=1e-6, eps_rel=1e-6)
        except cp.SolverError:
            self.problem.solve(solver=cp.CLARABEL)
        dt = time.perf_counter() - t0
        ok = self.problem.status in ("optimal", "optimal_inaccurate") and self.w.value is not None
        w = np.where(member, self.w.value, 0.0) if ok else prev.copy()
        return w, {"status": self.problem.status, "solve_s": dt}


def grinold_alpha(score: np.ndarray, spec: np.ndarray, member: np.ndarray, ic: float) -> np.ndarray:
    """IC x volatility x z-score of the score among members (0 elsewhere)."""
    s = np.where(member & np.isfinite(score), score, np.nan)
    with np.errstate(invalid="ignore"):
        z = (s - np.nanmean(s)) / np.nanstd(s)
    return np.nan_to_num(ic * np.sqrt(spec) * np.clip(z, -3, 3))


def optimize_path(scores: np.ndarray, daily_ret: np.ndarray, beta: np.ndarray, member: np.ndarray, S: np.ndarray,
                  hspread: np.ndarray, rows: np.ndarray, cfg: OptConfig = OptConfig(), log=None) -> tuple[np.ndarray, list]:
    """Weights for every session in `rows`, each from the previous session's weights (turnover penalty)."""
    n = scores.shape[1]
    opt = Optimizer(n, S, cfg)
    W = np.zeros(scores.shape)
    prev = np.zeros(n)
    info = []
    for i, t in enumerate(rows):
        m = member[t] & np.isfinite(scores[t])
        win = daily_ret[max(0, t - cfg.window + 1): t + 1]
        B, fvar, spec = pca_risk(np.where(m[None, :], win, 0.0), cfg.factors)
        cost = np.nan_to_num(hspread[t], nan=np.nanmedian(hspread[t])) + cfg.fixed_bps / 1e4
        a = grinold_alpha(scores[t], spec, m, cfg.ic)
        w, st = opt.solve(a, B, fvar, spec, np.nan_to_num(beta[t], nan=1.0), cost, prev, m)
        W[t], prev = w, w
        info.append(st)
        if log and i % 100 == 0:
            log(f"optimizer {i}/{len(rows)}: {st['status']} {st['solve_s'] * 1e3:.0f} ms")
    return W, info
