"""The same 158 Alpha158 factors written in plain pandas, one stock at a time (`groupby("symbol").rolling`).

This is the baseline of the speed benchmark (`scripts/research/bench_features.py`) and the oracle of the engine's
tests: `tests/test_features.py` checks that the engine and this code agree on every factor. It is written the way a
research notebook would write it: long table, a group-by per operation, no reuse of shared parts.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ghostdesk.features.alpha158 import WINDOWS

E = 1e-12


def _g(s: pd.Series, sym: pd.Series):
    return s.groupby(sym, sort=False)


def alpha158_pandas(df: pd.DataFrame) -> pd.DataFrame:
    """df: long rows sorted by (symbol, day) with symbol, open, high, low, close, volume, vwap. Returns one column per
    factor on the same rows."""
    sym = df["symbol"]
    o, h, lo, c, v, vw = (df[k].astype(float) for k in ("open", "high", "low", "close", "volume", "vwap"))

    def roll(s, d):
        return _g(s, sym).rolling(d)

    def back(r):  # a groupby-rolling result has the symbol as an extra index level
        return r.reset_index(level=0, drop=True).sort_index()

    def ref(s, d):
        return _g(s, sym).shift(d)

    def gt(a, b):
        return (a > b).astype(float).where(a.notna() & b.notna())

    def lt(a, b):
        return (a < b).astype(float).where(a.notna() & b.notna())

    def greater(a, b):
        return np.maximum(a, b).where(a.notna() & b.notna())

    def less(a, b):
        return np.minimum(a, b).where(a.notna() & b.notna())

    def slope_fit(s, d):
        t = np.arange(1, d + 1, dtype=float)

        def f(w):
            return np.polyfit(t, w, 1)[0]

        def last_fit(w):
            b, a = np.polyfit(t, w, 1)
            return a + b * d

        def r2(w):
            if np.ptp(w) == 0:  # a constant window (np.var of equal floats can be a tiny nonzero)
                return np.nan
            return np.corrcoef(t, w)[0, 1] ** 2

        return f, last_fit, r2

    out = {}
    with np.errstate(divide="ignore", invalid="ignore"):
        out["KMID"] = (c - o) / o
        out["KLEN"] = (h - lo) / o
        out["KMID2"] = (c - o) / (h - lo + E)
        out["KUP"] = (h - greater(o, c)) / o
        out["KUP2"] = (h - greater(o, c)) / (h - lo + E)
        out["KLOW"] = (less(o, c) - lo) / o
        out["KLOW2"] = (less(o, c) - lo) / (h - lo + E)
        out["KSFT"] = (2 * c - h - lo) / o
        out["KSFT2"] = (2 * c - h - lo) / (h - lo + E)
        out["OPEN0"], out["HIGH0"], out["LOW0"], out["VWAP0"] = o / c, h / c, lo / c, vw / c
        c1, v1 = ref(c, 1), ref(v, 1)
        logv = np.log((v + 1).where(v + 1 > 0))
        cord_x = c / c1
        cord_y = np.log((v / v1 + 1).where(v / v1 + 1 > 0))
        bad = cord_x.isna() | cord_y.isna()
        cord_x, cord_y = cord_x.where(~bad), cord_y.where(~bad)
        up, dn, ab = greater(c - c1, 0 * c), greater(c1 - c, 0 * c), (c - c1).abs()
        vup, vdn, vab = greater(v - v1, 0 * v), greater(v1 - v, 0 * v), (v - v1).abs()
        wv = (c / c1 - 1).abs() * v
        for d in WINDOWS:
            f_slope, f_fit, f_r2 = slope_fit(c, d)
            mx_h, mn_l = back(roll(h, d).max()), back(roll(lo, d).min())
            out[f"ROC{d}"] = ref(c, d) / c
            out[f"MA{d}"] = back(roll(c, d).mean()) / c
            out[f"STD{d}"] = back(roll(c, d).std()) / c
            out[f"BETA{d}"] = back(roll(c, d).apply(f_slope, raw=True)) / c
            out[f"RSQR{d}"] = back(roll(c, d).apply(f_r2, raw=True))
            out[f"RESI{d}"] = (c - back(roll(c, d).apply(f_fit, raw=True))) / c
            out[f"MAX{d}"] = mx_h / c
            out[f"MIN{d}"] = mn_l / c
            out[f"QTLU{d}"] = back(roll(c, d).quantile(0.8)) / c
            out[f"QTLD{d}"] = back(roll(c, d).quantile(0.2)) / c
            out[f"RANK{d}"] = back(roll(c, d).rank(pct=True))
            out[f"RSV{d}"] = (c - mn_l) / (mx_h - mn_l + E)
            imax = back(roll(h, d).apply(lambda w: np.argmax(w) + 1.0, raw=True))
            imin = back(roll(lo, d).apply(lambda w: np.argmin(w) + 1.0, raw=True))
            out[f"IMAX{d}"], out[f"IMIN{d}"], out[f"IMXD{d}"] = imax / d, imin / d, (imax - imin) / d
            out[f"CORR{d}"] = _corr(c, logv, sym, d, back)
            out[f"CORD{d}"] = _corr(cord_x, cord_y, sym, d, back)
            p, n = back(roll(gt(c, c1), d).mean()), back(roll(lt(c, c1), d).mean())
            out[f"CNTP{d}"], out[f"CNTN{d}"], out[f"CNTD{d}"] = p, n, p - n
            su, sd, sa = back(roll(up, d).sum()), back(roll(dn, d).sum()), back(roll(ab, d).sum())
            out[f"SUMP{d}"], out[f"SUMN{d}"], out[f"SUMD{d}"] = su / (sa + E), sd / (sa + E), (su - sd) / (sa + E)
            out[f"VMA{d}"] = back(roll(v, d).mean()) / (v + E)
            out[f"VSTD{d}"] = back(roll(v, d).std()) / (v + E)
            out[f"WVMA{d}"] = back(roll(wv, d).std()) / (back(roll(wv, d).mean()) + E)
            su, sd, sa = back(roll(vup, d).sum()), back(roll(vdn, d).sum()), back(roll(vab, d).sum())
            out[f"VSUMP{d}"], out[f"VSUMN{d}"], out[f"VSUMD{d}"] = su / (sa + E), sd / (sa + E), (su - sd) / (sa + E)
    res = pd.DataFrame(out, index=df.index)
    return res.replace([np.inf, -np.inf], np.nan)


def _corr(x, y, sym, d, back):
    """Rolling correlation per stock; NaN where either side has zero variance in the window."""
    frame = pd.DataFrame({"x": x, "y": y, "s": sym})
    r = frame.groupby("s", sort=False)[["x", "y"]].rolling(d)
    cxy = r.cov().xs("y", level=-1)["x"]
    var = r.var()
    cx, cy = back(var["x"]), back(var["y"])
    cxy = cxy.reset_index(level=0, drop=True).sort_index()
    gx, gy = x.groupby(sym, sort=False).rolling(d), y.groupby(sym, sort=False).rolling(d)
    flat = (back(gx.max()) == back(gx.min())) | (back(gy.max()) == back(gy.min()))  # rolling var of equal values
    return (cxy / np.sqrt(cx * cy)).where((cx > 0) & (cy > 0) & ~flat)              # can be a tiny nonzero
