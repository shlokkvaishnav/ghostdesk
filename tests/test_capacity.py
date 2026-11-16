"""Capacity: trading cost rises with fund size; break-even is where cost meets the gross return."""
import numpy as np
import pandas as pd

from ghostdesk.execution.capacity import break_even, capacity_curve, cost_fraction, monthly_trades


def test_cost_rises_with_size_and_break_even_interpolates():
    t = pd.DataFrame({"month": [1, 1, 2], "dw": [0.2, 0.2, 0.4], "adv_dollar": 1e8, "sigma": 0.02})
    aums = [1e6, 1e7, 1e8, 1e9, 1e10]
    c = capacity_curve(t, aums)
    assert (np.diff(c.to_numpy()) > 0).all()
    m1 = 2 * 0.2 * cost_fraction(np.array(0.2e6), 1e8, 0.02)  # month 1: two trades of 0.2
    m2 = 0.4 * cost_fraction(np.array(0.4e6), 1e8, 0.02)  # month 2: one trade of 0.4
    assert abs(c[1e6] - (m1 + m2) / 2) < 1e-15
    be = break_even(c, float(c[1e8]))
    assert abs(be - 1e8) / 1e8 < 1e-6
    assert np.isnan(break_even(c, 1.0)) and np.isnan(break_even(c, 0.0))


def test_monthly_trades_counts_entries_and_exits():
    rows = []
    for m, members in [(pd.Timestamp("2020-01-31"), range(10)), (pd.Timestamp("2020-02-29"), range(5, 15))]:
        for c in members:
            rows.append({"month": m, "cik": c, "sim": float(c if m.month == 1 else -c), "fwd_ret": 0.0,
                         "logdv": np.log(1e8), "sigma": 0.02})
    t = monthly_trades(pd.DataFrame(rows), "sim", n=5)
    first = t[t["month"] == pd.Timestamp("2020-01-31")]
    assert abs(first["dw"].sum() - 2.0) < 1e-12  # both legs built from cash
    assert (t["adv_dollar"] > 0).all()
