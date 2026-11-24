"""The label: open(t+1) -> open(t+2), market and sector removed, missing where it is not known or not valid."""
import numpy as np
import pandas as pd

from ghostdesk.research.dataset import Panel, open_to_open, residual_label, rolling_beta


def panel(t=300, n=4, seed=1):
    rng = np.random.default_rng(seed)
    mkt = np.cumsum(rng.normal(0, 0.01, t))
    beta = np.array([0.5, 1.0, 1.5, 2.0])[:n]
    logp = 4 + mkt[:, None] * beta + np.cumsum(rng.normal(0, 0.01, (t, n)), axis=0)
    o = np.exp(logp)
    member = np.ones((t, n), dtype=bool)
    member[:50, 3] = False
    return Panel(pd.bdate_range("2020-01-01", periods=t), [f"S{i}" for i in range(n)],
                 {"open": o, "close": o * 1.001}, member, np.array(["a", "a", "b", "b"])[:n], np.exp(4 + mkt),
                 np.exp(4 + mkt), o, np.zeros((t, n), dtype=bool), "k"), beta


def test_open_to_open_is_the_next_two_opens():
    o = np.array([[1.0], [2.0], [4.0], [8.0]])
    r = open_to_open(o)
    assert np.allclose(r[:2, 0], np.log(2.0)) and np.isnan(r[2:]).all()


def test_beta_uses_only_past_rows_and_recovers_the_true_value():
    p, beta = panel()
    cc = np.diff(np.log(p.fields["close"]), axis=0, prepend=np.nan)
    m = np.diff(np.log(p.spy_close), prepend=np.nan)
    b = rolling_beta(cc, m)
    assert np.allclose(b[-1], beta, atol=0.25)
    cc2 = cc.copy()
    cc2[200:] *= 3  # later data does not change beta at row 199
    assert np.array_equal(rolling_beta(cc2, m)[:200], b[:200])


def test_residual_label_is_sector_neutral_and_missing_where_unknown():
    p, _ = panel()
    y = residual_label(p)
    assert np.isnan(y[-2:]).all() and np.isnan(y[:50, 3]).all()
    for s in ("a", "b"):
        cols = p.sector == s
        rows = np.isfinite(y[:, cols]).all(axis=1)
        assert np.allclose(y[rows][:, cols].sum(axis=1), 0, atol=1e-12)
    p.flag[100, 0] = True  # a vendor error on the close-to-close move into day 100
    y2 = residual_label(p)
    assert np.isnan(y2[98, 0]) and np.isnan(y2[99, 0]) and np.isfinite(y2[97, 0])
