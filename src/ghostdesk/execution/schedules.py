"""Execution benchmarks: TWAP, VWAP and the discrete Almgren-Chriss (2000) optimum.

Model (Almgren and Chriss 2000, discrete time): sell X over N intervals of length tau = T / N; holdings x_0 = X,
x_N = 0, trades n_k = x_{k-1} - x_k. Price S_k = S_{k-1} + sigma sqrt(tau) xi_k - gamma n_k (permanent impact);
execution price S_{k-1} - eps sgn(n_k) - eta n_k / tau (temporary impact). With eta_tilde = eta - gamma tau / 2,
    E[cost] = gamma X^2 / 2 + eps sum |n_k| + (eta_tilde / tau) sum n_k^2,    Var[cost] = sigma^2 tau sum_{k>=1} x_k^2,
and the mean-variance optimum for risk aversion lam is x_j = X sinh(kappa (T - t_j)) / sinh(kappa T), with
(2 / tau^2) (cosh(kappa tau) - 1) = lam sigma^2 / eta_tilde.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class ACParams:
    sigma: float  # price volatility per unit time (price units)
    gamma: float  # permanent impact per share
    eta: float  # temporary impact per (share / time)
    eps: float = 0.0  # fixed cost per share (half spread)
    T: float = 1.0
    N: int = 20

    @property
    def tau(self) -> float:
        return self.T / self.N

    @property
    def eta_tilde(self) -> float:
        et = self.eta - 0.5 * self.gamma * self.tau
        if et <= 0:
            raise ValueError("eta - gamma tau / 2 must be positive")
        return et


def twap(X: float, N: int) -> np.ndarray:
    """Holdings x_0..x_N for equal trades."""
    return X * (1 - np.arange(N + 1) / N)


def vwap(X: float, volume_profile) -> np.ndarray:
    """Holdings for trades proportional to an expected volume profile (one value per interval)."""
    v = np.asarray(volume_profile, float)
    if v.ndim != 1 or (v < 0).any() or v.sum() <= 0:
        raise ValueError("volume profile must be non-negative with a positive sum")
    return X * (1 - np.concatenate([[0.0], np.cumsum(v) / v.sum()]))


def kappa(p: ACParams, lam: float) -> float:
    if lam <= 0:
        return 0.0
    kt2 = lam * p.sigma**2 / p.eta_tilde
    return float(np.arccosh(1 + 0.5 * kt2 * p.tau**2) / p.tau)


def almgren_chriss(X: float, p: ACParams, lam: float) -> np.ndarray:
    """Optimal holdings x_0..x_N; lam = 0 gives TWAP."""
    k = kappa(p, lam)
    if k == 0.0:
        return twap(X, p.N)
    t = np.arange(p.N + 1) * p.tau
    x = X * np.sinh(k * (p.T - t)) / np.sinh(k * p.T)
    x[0], x[-1] = X, 0.0  # exact end points (no rounding residue in the inventory)
    return x


def expected_cost(x: np.ndarray, p: ACParams) -> float:
    n = -np.diff(x)
    return float(0.5 * p.gamma * x[0] ** 2 + p.eps * np.abs(n).sum() + p.eta_tilde / p.tau * (n**2).sum())


def cost_variance(x: np.ndarray, p: ACParams) -> float:
    return float(p.sigma**2 * p.tau * (x[1:] ** 2).sum())


def mean_variance(x: np.ndarray, p: ACParams, lam: float) -> float:
    return expected_cost(x, p) + lam * cost_variance(x, p)
