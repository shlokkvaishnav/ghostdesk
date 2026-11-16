"""Study statistics: Newey-West against a known case, a planted signal is found, costs and alpha timing."""
import numpy as np
import pandas as pd

from ghostdesk.signal.study import alpha, ic, mean_t, newey_west, portfolio, summary


def test_newey_west_zero_lags_is_white():
    rng = np.random.default_rng(0)
    x = np.column_stack([np.ones(200), rng.normal(size=200)])
    y = 1 + 2 * x[:, 1] + rng.normal(size=200)
    b, se = newey_west(y, x, 0)
    u = (y - x @ b)[:, None] * x
    white = np.sqrt(np.diag(np.linalg.inv(x.T @ x) @ (u.T @ u) @ np.linalg.inv(x.T @ x)))
    assert np.allclose(se, white) and abs(b[1] - 2) < 0.2


def make_panel(effect=0.02, months=36, stocks=200, seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for m in pd.date_range("2016-01-31", periods=months, freq="ME"):
        sig = rng.uniform(size=stocks)
        ret = effect * (sig - 0.5) + rng.normal(0, 0.05, stocks)
        rows.append(pd.DataFrame({"month": m, "cik": np.arange(stocks), "sim_full_edit": sig, "fwd_ret": ret,
                                  "spread": 0.002, "mom": rng.normal(size=stocks), "logdv": rng.normal(size=stocks),
                                  "log_assets": rng.normal(size=stocks), "sic": rng.choice(["3571", "6022"], stocks)}))
    return pd.concat(rows, ignore_index=True)


def factors(index):
    f = pd.DataFrame(0.0, index=index, columns=["Mkt-RF", "SMB", "HML", "RMW", "CMA", "Mom", "RF"])
    f["Mkt-RF"] = np.random.default_rng(1).normal(0, 0.04, len(index))
    return f


def test_planted_signal_is_found_and_null_is_not():
    p = make_panel(0.04)
    r = summary(p, "sim_full_edit", factors(pd.date_range("2016-01-31", periods=40, freq="ME")))
    assert r["long_short_gross"]["t"] > 3 and r["ic"]["mean"] > 0.05 and r["fama_macbeth"]["signal"]["t"] > 3
    assert r["long_short_net"]["10bps"]["mean"] < r["long_short_net"]["2bps"]["mean"] < r["long_short_gross"]["mean"]
    assert 0 < r["mde_monthly_80pct_power"] < r["long_short_gross"]["mean"] * 2
    assert r["quintile_mean_monthly"][5] > r["quintile_mean_monthly"][1]
    null = summary(make_panel(0.0, seed=3), "sim_full_edit", factors(pd.date_range("2016-01-31", periods=40,
                                                                                    freq="ME")))
    assert abs(null["long_short_gross"]["t"]) < 2.5


def test_costs_follow_turnover():
    p = make_panel(0.0)
    pf = portfolio(p, "sim_full_edit")
    # signals are redrawn each month, so most of each leg is replaced: traded close to 2 x 2 x 0.8
    assert 2.5 < pf["traded"].iloc[1:].mean() < 4.0
    assert ((pf["ls"] - pf["net"]["5bps"]) - pf["traded"] * 5e-4).abs().max() < 1e-12
    assert (pf["net_cs"] < pf["ls"]).all()  # spread 0.2% -> half-spread 0.1% per trade


def test_alpha_uses_the_next_month():
    idx = pd.date_range("2016-01-31", periods=30, freq="ME")
    f = factors(pd.date_range("2016-01-31", periods=31, freq="ME"))
    ls = pd.Series(2.0 * f["Mkt-RF"].shift(-1).iloc[:30].to_numpy() + 0.01, index=idx)  # earned in month + 1
    a = alpha(ls, f, 0)
    assert abs(a["alpha_monthly"] - 0.01) < 1e-9 and abs(a["betas"]["Mkt-RF"] - 2) < 1e-9


def test_ic_and_mean_t():
    p = make_panel(0.04)
    assert ic(p, "sim_full_edit").mean() > 0.05
    assert mean_t(pd.Series([1.0, 1.0, 1.0, 1.0]), 1)["mean"] == 1.0


def test_signals_are_ranked_like_with_like():
    from ghostdesk.signal.study import add_signals

    m = pd.Timestamp("2016-01-31")
    p = pd.DataFrame({"month": m, "form": ["10-K", "10-K", "10-Q", "10-Q"], "sic": ["3571", "6022", "3571", "6022"],
                      "sim_full_cosine": [0.99, 0.98, 0.95, 0.94], "sim_full_jaccard": [0.9, 0.8, 0.7, 0.6],
                      "sim_full_edit": [0.8, 0.7, 0.5, 0.4]})
    s = add_signals(p)
    # each form gets the full rank range: the most similar 10-Q ranks as high as the most similar 10-K
    assert s["composite"].tolist() == [1.0, 0.5, 1.0, 0.5]
    assert s["sim_full_edit_r"].tolist() == [1.0, 0.5, 1.0, 0.5]
    assert (s["composite_ind"] == 1.0).all()  # one stock per (form, division) cell


def test_ci_contains_the_mean():
    r = mean_t(pd.Series(np.random.default_rng(2).normal(0.01, 0.02, 60)), 3)
    assert r["ci95"][0] < r["mean"] < r["ci95"][1]
