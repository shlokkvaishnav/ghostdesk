"""Vectorized kernels of the expression language on (session x symbol) float64 matrices.

Every time-series operator looks back only (row t uses rows <= t). A window needs all `d` values: a NaN in the window
gives NaN (the same as pandas `rolling(d)` with its default `min_periods=d`). Sums, means, variances, regressions
and correlations use running sums (O(T N) for any window); each column is first shifted by a constant (its first
valid value), which changes none of these results but keeps the running sums small and exact enough. Max, min,
quantile, rank and arg-max use a strided window view (O(T N d), no copy).
"""
from __future__ import annotations

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

EPS_DDOF = 1  # sample standard deviation, as pandas


def _shift_const(x: np.ndarray) -> np.ndarray:
    """Per column, the first finite value (0 if none): a constant shift that leaves variances unchanged."""
    ok = np.isfinite(x)
    first = np.argmax(ok, axis=0)
    c = x[first, np.arange(x.shape[1])]
    return np.where(ok.any(axis=0), c, 0.0)


def _wsum(x: np.ndarray, d: int) -> tuple[np.ndarray, np.ndarray]:
    """Window sums of x (NaN as 0) and the count of finite values in each window, aligned to the window's last row."""
    ok = np.isfinite(x)
    z = np.where(ok, x, 0.0)
    cs = np.cumsum(z, axis=0)
    cn = np.cumsum(ok, axis=0)
    s = cs.copy()
    n = cn.copy()
    s[d:] -= cs[:-d]
    n[d:] -= cn[:-d]
    s[: d - 1] = np.nan
    return s, n


def _full(s: np.ndarray, n: np.ndarray, d: int) -> np.ndarray:
    return np.where(n == d, s, np.nan)


def ref(x, d: int):
    if d < 0:
        raise ValueError("Ref with a negative lag would read the future")
    if d == 0:
        return x
    out = np.full_like(x, np.nan)
    out[d:] = x[:-d]
    return out


def delta(x, d: int):
    return x - ref(x, d)


def tsum(x, d: int):
    s, n = _wsum(x, d)
    return _full(s, n, d)


def mean(x, d: int):
    return tsum(x, d) / d


def var(x, d: int):
    c = _shift_const(x)
    y = x - c
    s, n = _wsum(y, d)
    s2, _ = _wsum(y * y, d)
    v = (s2 - s * s / d) / (d - EPS_DDOF)
    v = np.where(_flat(x, d), 0.0, np.maximum(v, 0.0))  # a constant window has variance exactly 0
    return _full(v, n, d)


def std(x, d: int):
    return np.sqrt(var(x, d))


def _regress(x, d: int):
    """Least squares of x on t = 1..d in each window: slope, intercept at t = d (the fitted last value), R^2."""
    c = _shift_const(x)
    y = x - c
    rows = np.arange(x.shape[0], dtype=float)[:, None]
    s, n = _wsum(y, d)
    sy2, _ = _wsum(y * y, d)
    sgy, _ = _wsum(y * rows, d)  # NaN stays NaN, so the window count is the same
    first = rows - (d - 1)  # global row of t = 1
    sty = sgy - (first - 1) * s  # sum of t * y with t = 1..d
    st, stt = d * (d + 1) / 2, d * (d + 1) * (2 * d + 1) / 6
    sxx = stt - st * st / d
    sxy = sty - st * s / d
    slope = sxy / sxx
    syy = sy2 - s * s / d
    fit_last = s / d + slope * (d - st / d)
    flat = _flat(x, d)
    with np.errstate(invalid="ignore", divide="ignore"):
        r2 = np.where((syy > 0) & ~flat, sxy * sxy / (sxx * syy), np.nan)
    # A constant window has slope exactly 0 and a fit equal to the value; the running sums leave a residue (1e-12).
    slope = np.where(flat, 0.0, slope)
    fit_last = np.where(flat, x - c, fit_last)
    ok = n == d
    return (np.where(ok, slope, np.nan), np.where(ok, fit_last + c, np.nan), np.where(ok, r2, np.nan))


def slope(x, d: int):
    return _regress(x, d)[0]


def rsquare(x, d: int):
    return _regress(x, d)[2]


def resi(x, d: int):
    return x - _regress(x, d)[1]


def cov(x, y, d: int):
    bad = ~(np.isfinite(x) & np.isfinite(y))
    a = np.where(bad, np.nan, x - _shift_const(x))
    b = np.where(bad, np.nan, y - _shift_const(y))
    sa, n = _wsum(a, d)
    sb, _ = _wsum(b, d)
    sab, _ = _wsum(a * b, d)
    return _full((sab - sa * sb / d) / (d - EPS_DDOF), n, d)


def corr(x, y, d: int):
    bad = ~(np.isfinite(x) & np.isfinite(y))
    a, b = np.where(bad, np.nan, x), np.where(bad, np.nan, y)
    va, vb = var(a, d), var(b, d)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where((va > 0) & (vb > 0), cov(a, b, d) / np.sqrt(va * vb), np.nan)


def _flat(x, d: int) -> np.ndarray:
    """True where the window ending at a row is constant (max == min, exact); False where incomplete."""
    w = _windows(x, d)
    out = np.zeros(x.shape, dtype=bool)
    if len(w):
        out[d - 1:] = w.max(axis=-1) == w.min(axis=-1)
    return out


def _windows(x, d: int):
    """(T - d + 1, N, d) read-only view of the windows ending at rows d-1 .. T-1."""
    if d > x.shape[0]:
        return np.empty((0, x.shape[1], d))
    return sliding_window_view(x, d, axis=0)


def _place(x, d: int, vals):
    out = np.full(x.shape, np.nan)
    if len(vals):
        out[d - 1:] = vals
    return out


def tmax(x, d: int):
    return _place(x, d, _windows(x, d).max(axis=-1))  # NaN in a window -> NaN


def tmin(x, d: int):
    return _place(x, d, _windows(x, d).min(axis=-1))


def quantile(x, d: int, q: float):
    return _place(x, d, np.quantile(_windows(x, d), q, axis=-1))  # linear interpolation, as pandas


def trank(x, d: int):
    """Percentile rank of the last value in its window (average rank of ties, divided by d), as pandas
    `rolling(d).rank(pct=True)`."""
    w = _windows(x, d)
    last = w[..., -1:]
    less = (w < last).sum(axis=-1)
    eq = (w == last).sum(axis=-1)
    r = (less + (eq + 1) / 2) / d
    nan = np.isnan(w).any(axis=-1)
    return _place(x, d, np.where(nan, np.nan, r))


def idxmax(x, d: int):
    """1-based position of the window maximum, counted from the oldest row (first occurrence)."""
    w = _windows(x, d)
    nan = np.isnan(w).any(axis=-1)
    return _place(x, d, np.where(nan, np.nan, np.argmax(np.where(np.isnan(w), -np.inf, w), axis=-1) + 1.0))


def idxmin(x, d: int):
    w = _windows(x, d)
    nan = np.isnan(w).any(axis=-1)
    return _place(x, d, np.where(nan, np.nan, np.argmin(np.where(np.isnan(w), np.inf, w), axis=-1) + 1.0))


def ema(x, d: int):
    """Exponential mean with alpha = 2 / (d + 1), started at the first full window's mean; NaN stays NaN."""
    a = 2.0 / (d + 1)
    m = mean(x, d)
    out = np.full_like(x, np.nan)
    prev = np.full(x.shape[1], np.nan)
    for t in range(x.shape[0]):
        cur = np.where(np.isnan(prev), m[t], a * x[t] + (1 - a) * prev)
        prev = np.where(np.isfinite(x[t]), cur, np.nan)
        out[t] = prev
    return out


def cs_rank(x):
    """Cross-sectional percentile rank in (0, 1] per row (average ties), NaN kept."""
    from scipy.stats import rankdata

    r = rankdata(x, axis=1, nan_policy="omit")
    n = np.isfinite(x).sum(axis=1, keepdims=True)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(np.isfinite(x), r / n, np.nan)


def cs_zscore(x):
    with np.errstate(invalid="ignore", divide="ignore"):
        m = np.nanmean(x, axis=1, keepdims=True)
        s = np.nanstd(x, axis=1, keepdims=True)
        return np.where(s > 0, (x - m) / s, np.nan)
