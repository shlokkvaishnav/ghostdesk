"""The signal study on a stock-month panel (`text_signal.stock_month_panel`): portfolios, costs, information coefficient, Fama-MacBeth
regressions and factor alpha. All t-statistics use Newey-West standard errors (`nw_lags` lags).

Direction: the measures are similarities, so a high value means little change. The paper's finding is that low-change
("lazy") reports are followed by higher returns, so the long-short portfolio buys the top quintile (Q5, most similar)
and sells the bottom quintile (Q1, most changed).

Costs: each month the portfolio is rebalanced to its target weights. The cost of a month is the weight traded times
a cost per trade: a fixed grid (2, 5, 10 bps; the main net results) and, as a noisy secondary estimate, half the
Corwin-Schultz spread. The weight drift inside the month is ignored (a stated simplification).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ghostdesk.data.industry import industry_groups

FACTORS = ["Mkt-RF", "SMB", "HML", "RMW", "CMA", "Mom"]
FULL = ["sim_full_cosine", "sim_full_jaccard", "sim_full_edit"]
PRIMARY = "composite"
NEUTRAL = "composite_ind"


def add_signals(panel: pd.DataFrame) -> pd.DataFrame:
    """Signals compared like with like. A 10-Q changes more from year to year than a 10-K (in 2016-2019 the most
    changed quintile of raw similarity was 11% 10-Ks, the least changed 37%), so raw ranks partly sort by form.
    - `<measure>_r`: percentile rank within (month, form);
    - `composite`: mean of the three full-text ranks, re-ranked within (month, form) (the primary signal: no single
      measure is chosen on the data);
    - `composite_ind`: `composite` ranked within (month, form, SIC division) (industry-neutral)."""
    from ghostdesk.data.industry import sic_division

    p = panel.copy()
    p["_form"] = p["form"].fillna("none")
    p["_div"] = p["sic"].map(sic_division)
    measures = [c for c in p.columns if c.startswith("sim_") and not c.endswith("_r")]
    for m in measures:
        p[f"{m}_r"] = p.groupby(["month", "_form"])[m].rank(pct=True)
    p["composite"] = p[[f"{m}_r" for m in FULL]].mean(axis=1, skipna=False)
    p["composite"] = p.groupby(["month", "_form"])["composite"].rank(pct=True)
    p["composite_ind"] = p.groupby(["month", "_form", "_div"])["composite"].rank(pct=True)
    return p.drop(columns=["_form", "_div"])


def newey_west(y: np.ndarray, x: np.ndarray, lags: int) -> tuple[np.ndarray, np.ndarray]:
    """OLS coefficients and Newey-West (Bartlett) standard errors. x includes the constant column."""
    y, x = np.asarray(y, float), np.asarray(x, float)
    xtx_inv = np.linalg.pinv(x.T @ x)  # pinv: a constant-zero column gives a zero coefficient, not an error
    b = xtx_inv @ x.T @ y
    u = (y - x @ b)[:, None] * x
    s = u.T @ u
    for lag in range(1, lags + 1):
        w = 1 - lag / (lags + 1)
        g = u[lag:].T @ u[:-lag]
        s += w * (g + g.T)
    v = xtx_inv @ s @ xtx_inv
    return b, np.sqrt(np.diag(v))


def mean_t(series: pd.Series, lags: int) -> dict:
    """Mean of a time series, its Newey-West t-statistic and 95% confidence interval."""
    s = series.dropna()
    if len(s) < 3:
        return {"mean": float("nan"), "t": float("nan"), "n": len(s), "ci95": [float("nan"), float("nan")]}
    b, se = newey_west(s.to_numpy(), np.ones((len(s), 1)), lags)
    return {"mean": float(b[0]), "t": float(b[0] / se[0]), "n": len(s),
            "ci95": [float(b[0] - 1.96 * se[0]), float(b[0] + 1.96 * se[0])]}


def quintiles(panel: pd.DataFrame, measure: str, n: int = 5) -> pd.DataFrame:
    """Rows with a signal and a forward return, with `q` = 1..n (n = most similar) within each month."""
    p = panel.dropna(subset=[measure, "fwd_ret"]).copy()
    p["q"] = p.groupby("month")[measure].transform(
        lambda s: pd.qcut(s.rank(method="first"), n, labels=False) + 1 if len(s) >= n else np.nan)
    return p.dropna(subset=["q"])


COST_BPS = (2.0, 5.0, 10.0)


def portfolio(panel: pd.DataFrame, measure: str, weighting: str = "equal", n: int = 5) -> dict:
    """Quintile returns and the long-short (Qn - Q1) per month, with the weight traded at each rebalance.

    weighting: "equal", or "dv" (weights proportional to 63-day dollar volume: a size-weighted check; market value
    is not in the panel). `traded` = sum of |weight change| over both legs (1.0 = one full leg replaced); the cost
    of a month is traded x cost per trade. `cs_cost` uses half the Corwin-Schultz spread of each traded stock
    instead of a fixed rate (a noisy estimate at large-cap spreads, so only a secondary result)."""
    p = quintiles(panel, measure, n)
    p["w_raw"] = np.exp(p["logdv"]).fillna(np.exp(p["logdv"]).median()) if weighting == "dv" else 1.0
    p["w"] = p["w_raw"] / p.groupby(["month", "q"])["w_raw"].transform("sum")
    q = (p["w"] * p["fwd_ret"]).groupby([p["month"], p["q"]]).sum().unstack()
    ls = q[n] - q[1]
    half = (p["spread"] / 2).fillna((p["spread"] / 2).median())
    p = p.assign(half=half)
    traded, cs_cost, prev = {}, {}, {}
    for month, g in p.groupby("month"):
        t_sum, c_sum = 0.0, 0.0
        for leg in (n, 1):
            h = g[g["q"] == leg]
            w = pd.Series(h["w"].to_numpy(), index=h["cik"].to_numpy())
            rate = pd.Series(h["half"].to_numpy(), index=h["cik"].to_numpy())
            old = prev.get(leg, pd.Series(dtype=float))
            idx = w.index.union(old.index)
            dw = (w.reindex(idx, fill_value=0.0) - old.reindex(idx, fill_value=0.0)).abs()
            t_sum += float(dw.sum())
            c_sum += float((dw * rate.reindex(idx).fillna(float(rate.median()))).sum())
            prev[leg] = w
        traded[month], cs_cost[month] = t_sum, c_sum
    traded, cs_cost = pd.Series(traded), pd.Series(cs_cost)
    return {"quintiles": q, "ls": ls, "traded": traded, "cs_cost": cs_cost,
            "net": {f"{b:g}bps": ls - traded.reindex(ls.index) * b / 1e4 for b in COST_BPS},
            "net_cs": ls - cs_cost.reindex(ls.index)}


def ic(panel: pd.DataFrame, measure: str) -> pd.Series:
    """Monthly Spearman rank correlation of the signal with the next month's return."""
    p = panel.dropna(subset=[measure, "fwd_ret"])
    return p.groupby("month").apply(lambda g: g[measure].rank().corr(g["fwd_ret"].rank()) if len(g) > 10 else np.nan)


def fama_macbeth(panel: pd.DataFrame, measure: str, lags: int = 3) -> dict:
    """Monthly cross-section OLS: next-month return on the signal's rank (0-1), standardised size (log dollar
    volume, log assets) and momentum, and industry dummies; the mean signal coefficient and its NW t."""
    coefs = {}
    cols = [measure, "fwd_ret", "mom", "logdv", "log_assets"]
    ok = np.isfinite(panel[cols].astype(float)).all(axis=1)
    for month, g in panel[ok].groupby("month"):
        if len(g) < 50:
            continue
        x = pd.DataFrame({"signal": g[measure].rank(pct=True)})
        for c in ("logdv", "log_assets", "mom"):
            x[c] = (g[c] - g[c].mean()) / g[c].std()
        ind = pd.get_dummies(industry_groups(g["sic"]), drop_first=True, dtype=float)
        x = pd.concat([pd.Series(1.0, index=g.index, name="const"), x, ind], axis=1)
        b, *_ = np.linalg.lstsq(x.to_numpy(), g["fwd_ret"].to_numpy(), rcond=None)
        coefs[month] = dict(zip(x.columns, b, strict=True))
    c = pd.DataFrame(coefs).T
    return {k: mean_t(c[k], lags) for k in ("signal", "logdv", "log_assets", "mom")} | {"months": len(c)}


def alpha(ls: pd.Series, factors: pd.DataFrame, lags: int = 3) -> dict:
    """Alpha of the long-short return (a zero-cost portfolio, so no risk-free rate) on FF5 + momentum."""
    y = ls.copy()
    y.index = pd.DatetimeIndex(y.index).to_period("M")
    f = factors.copy()
    f.index = f.index.to_period("M")
    # the return of formation month m is earned in month m + 1
    y.index = y.index + 1
    d = pd.concat([y.rename("ls"), f[FACTORS]], axis=1, join="inner").dropna()
    x = np.column_stack([np.ones(len(d)), d[FACTORS].to_numpy()])
    b, se = newey_west(d["ls"].to_numpy(), x, lags)
    return {"alpha_monthly": float(b[0]), "t": float(b[0] / se[0]), "months": len(d),
            "betas": dict(zip(FACTORS, map(float, b[1:]), strict=True))}


def summary(panel: pd.DataFrame, measure: str, factors: pd.DataFrame, lags: int = 3) -> dict:
    """All results for one measure: equal-weighted (main) and dollar-volume-weighted, costs on a fixed grid and from
    Corwin-Schultz, IC, Fama-MacBeth, alpha, and the minimum detectable effect of this sample."""
    pf = portfolio(panel, measure)
    vw = portfolio(panel, measure, weighting="dv")
    ic_m = ic(panel, measure)
    ic_by_year = ic_m.groupby(pd.DatetimeIndex(ic_m.index).year).mean()
    gross = mean_t(pf["ls"], lags)
    traded = float(pf["traded"].iloc[1:].mean())  # the first month builds the portfolio from cash
    sd, months = float(pf["ls"].std()), int(pf["ls"].notna().sum())
    return {
        "measure": measure, "months": months,
        "stocks_per_month": float(quintiles(panel, measure).groupby("month").size().mean()),
        "quintile_mean_monthly": {int(k): float(v) for k, v in pf["quintiles"].mean().items()},
        "long_short_gross": gross,
        "long_short_net": {k: mean_t(v, lags) for k, v in pf["net"].items()} | {"cs": mean_t(pf["net_cs"], lags)},
        "long_short_dv_weighted_gross": mean_t(vw["ls"], lags),
        "sd_monthly": sd, "sharpe_annual_gross": float(gross["mean"] / sd * np.sqrt(12)) if sd else float("nan"),
        "mde_monthly_80pct_power": float(2.8 * sd / np.sqrt(months)) if months else float("nan"),
        "traded_monthly": traded,
        "break_even_bps": float(gross["mean"] / traded * 1e4) if traded else float("nan"),
        "ic": mean_t(ic_m, lags), "ic_by_year": {int(k): float(v) for k, v in ic_by_year.items()},
        "fama_macbeth": fama_macbeth(panel, measure, lags),
        "alpha_gross": alpha(pf["ls"], factors, lags), "alpha_net_5bps": alpha(pf["net"]["5bps"], factors, lags),
        "signal_age_days_median": float(panel.loc[panel[measure].notna(), "signal_age"].median())
        if "signal_age" in panel else float("nan"),
    }
