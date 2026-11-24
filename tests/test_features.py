"""The expression language and its engine: parsing, canonical forms and reuse, no look-ahead, the cache, and
agreement with a plain pandas implementation on all 158 Alpha158 factors."""
import numpy as np
import pandas as pd
import pytest

from ghostdesk.features.alpha158 import alpha158
from ghostdesk.features.engine import FeatureEngine, data_hash
from ghostdesk.features.expr import ExprError, canonical, lookback, parse
from ghostdesk.features.pandas_reference import alpha158_pandas


def market(t=90, n=6, seed=0, holes=True):
    rng = np.random.default_rng(seed)
    c = 50 * np.exp(np.cumsum(rng.normal(0, 0.02, (t, n)), axis=0))
    o = c * np.exp(rng.normal(0, 0.005, (t, n)))
    h = np.maximum(o, c) * (1 + rng.uniform(0, 0.01, (t, n)))
    lo = np.minimum(o, c) * (1 - rng.uniform(0, 0.01, (t, n)))
    v = rng.integers(1_000, 100_000, (t, n)).astype(float)
    vw = (h + lo + c) / 3
    f = {"open": o, "high": h, "low": lo, "close": c, "volume": v, "vwap": vw}
    if holes:  # a stock that starts late and one with a missing day
        for m in f.values():
            m[:15, 1] = np.nan
            m[40, 2] = np.nan
    return f


def to_long(f):
    t, n = f["close"].shape
    rows = {k: f[k].T.reshape(-1) for k in f}
    df = pd.DataFrame({"symbol": np.repeat([f"S{i}" for i in range(n)], t), "day": np.tile(np.arange(t), n), **rows})
    return df


def test_parse_canonical_and_reuse():
    a, b = parse("Rank(Ref($close,5)/$close)"), parse("CSRank(Ref($close, 5) / $close)")
    assert canonical(a) == canonical(b)
    assert canonical(parse("$close+$open")) == canonical(parse("$open+$close"))  # commutative
    assert canonical(parse("$close-$open")) != canonical(parse("$open-$close"))
    assert lookback(parse("Mean(Ref($close,5),20)")) == 24
    for bad in ("Ref($close,-1)", "Mean($close)", "Foo($close)", "$price", "Mean($close,5", "Quantile($close,5,2)"):
        with pytest.raises(ExprError):
            parse(bad)


def test_engine_reuses_subexpressions_and_frees_them():
    e = FeatureEngine(market())
    e.compute({"a": "Mean($close,5)/$close", "b": "Std($close,5)/$close", "c": "Mean($close,5)-Ref($close,1)"})
    assert e.stats["unique"] < e.stats["nodes"]
    assert e.stats["computed"] == e.stats["unique"]
    assert e.stats["peak_live"] <= e.stats["unique"]


def test_no_feature_reads_a_later_session():
    """Changing every value after row k changes no factor value at rows <= k."""
    f = market(holes=False)
    k = 60
    g = {key: m.copy() for key, m in f.items()}
    for m in g.values():
        m[k + 1:] *= 1.7
    exprs = alpha158()
    a, b = FeatureEngine(f).compute(exprs), FeatureEngine(g).compute(exprs)
    for name in exprs:
        np.testing.assert_array_equal(a[name][: k + 1], b[name][: k + 1], err_msg=name)


def test_all_158_factors_match_plain_pandas():
    f = market()
    exprs = alpha158()
    assert len(exprs) == 158
    eng = FeatureEngine(f).compute(exprs)
    ref = alpha158_pandas(to_long(f))
    t, n = f["close"].shape
    for name in exprs:
        want = ref[name].to_numpy().reshape(n, t).T
        got = eng[name]
        np.testing.assert_array_equal(np.isnan(got), np.isnan(want), err_msg=f"{name}: missing values differ")
        ok = ~np.isnan(want)
        np.testing.assert_allclose(got[ok], want[ok], rtol=1e-6, atol=1e-9, err_msg=name)


def test_cache_warm_run_computes_nothing_and_new_data_misses(tmp_path):
    f = market()
    exprs = {k: v for k, v in list(alpha158().items())[:20]}
    cold = FeatureEngine(f, cache_dir=tmp_path)
    a = cold.compute(exprs)
    warm = FeatureEngine(f, cache_dir=tmp_path)
    b = warm.compute(exprs)
    assert warm.stats["cache_hits"] == 20 and warm.stats["computed"] == 0
    for k in exprs:
        np.testing.assert_array_equal(a[k], b[k])
    g = {k: v.copy() for k, v in f.items()}
    g["close"][-1, 0] += 1
    assert data_hash(g) != data_hash(f)
    other = FeatureEngine(g, cache_dir=tmp_path)
    other.compute(exprs)
    assert other.stats["cache_hits"] == 0


def test_cross_sectional_rank_and_comparisons_keep_missing():
    f = market(t=10, n=4, holes=False)
    f["close"][3, 2] = np.nan
    r = FeatureEngine(f).compute({"r": "Rank($close)", "g": "$close>Ref($close,1)"})
    assert np.isnan(r["r"][3, 2]) and np.nanmax(r["r"][3]) == 1.0
    assert np.isnan(r["g"][0]).all() and np.isnan(r["g"][3, 2]) and np.isnan(r["g"][4, 2])


def test_flat_price_windows_give_exact_zero_regression_factors():
    """A real stock (ADT) has a price that stays at one value for weeks. Slope and residual are then exactly 0, as
    are the standard deviations; the running sums used to leave a residue of about 1e-12 in slope and residual, and
    plain pandas leaves about 1e-8 in the standard deviation."""
    f = market(t=120, n=2, holes=False)
    for m in f.values():
        m[50:100, 0] = m[50, 0]
    f["close"][50:100, 0] = 31.96
    exprs = alpha158()
    got = FeatureEngine(f).compute(exprs)
    for d in (5, 10, 20, 30):
        rows = slice(50 + d, 100)  # windows that lie fully inside the flat stretch
        for name in (f"BETA{d}", f"RESI{d}", f"STD{d}"):
            assert (got[name][rows, 0] == 0).all(), name
        assert np.isnan(got[f"RSQR{d}"][rows, 0]).all()
