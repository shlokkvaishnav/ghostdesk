"""Models, walk-forward folds, the backtest metrics, the optimizer constraints, and the registry's bit-identical
check, on small made-up panels."""
import numpy as np
import pandas as pd
import pytest

from ghostdesk.research.backtest import decile_weights, evaluate, folds, rank_ic, walk_forward
from ghostdesk.research.models import Design, LightGBM, Reversal, Ridge, rank_features
from ghostdesk.research.optimizer import OptConfig, Optimizer, grinold_alpha, pca_risk
from ghostdesk.research.registry import Registry, array_sha256, run_key


def design(t=400, n=60, seed=0):
    rng = np.random.default_rng(seed)
    signal = rng.normal(size=(t, n))
    y = 0.3 * signal + rng.normal(size=(t, n))
    close = 50 * np.exp(np.cumsum(rng.normal(0, 0.01, (t, n)), axis=0))
    mask = np.ones((t, n), dtype=bool)
    X, names = rank_features({"sig": signal, "noise": rng.normal(size=(t, n))}, mask)
    return Design(X, y, mask, names, close), pd.bdate_range("2018-01-01", periods=t)


def test_folds_purge_and_never_train_on_predicted_days():
    days = pd.bdate_range("2018-01-01", "2020-12-31")
    for train, pred in folds(days, [2019, 2020], purge=2):
        assert train.max() + 2 < pred.min() and days[pred].year.nunique() == 1


def test_ridge_and_lightgbm_find_the_signal_out_of_sample():
    d, days = design()
    for m in (Ridge(), LightGBM(rounds=50, params={**LightGBM().params, "min_data_in_leaf": 50})):
        s = walk_forward(m, d, days, [2019])
        rows = np.where(days.year == 2019)[0]
        assert np.nanmean(rank_ic(s[rows], d.y[rows], d.mask[rows])) > 0.15, m.name
        assert np.isnan(s[days.year == 2018]).all()


def test_lightgbm_is_bit_identical_on_rerun(tmp_path):
    d, days = design(t=300, n=40)
    m = LightGBM(rounds=30, params={**LightGBM().params, "min_data_in_leaf": 50})
    a = walk_forward(m, d, days, [2019])
    reg = Registry(tmp_path)
    key = reg.record("lgb", "data", m.config(), a, {"x": 1}, 0.1, commit="abc")
    assert key == run_key("data", "abc", __import__("ghostdesk.research.registry", fromlist=["x"]).config_hash(
        m.config()))
    assert reg.verify(key, lambda cfg: walk_forward(LightGBM(rounds=30, params=cfg_params(cfg)), d, days, [2019]))
    assert reg.get(key)["scores_sha256"] == array_sha256(a)
    with pytest.raises(RuntimeError):
        reg.record("lgb", "data", {}, a, {}, 0.1, commit="abc-dirty")


def cfg_params(cfg):
    return {k: v for k, v in cfg.items() if k not in ("name", "rounds")}


def test_reversal_score_is_minus_past_return():
    d, _ = design(t=20, n=5)
    s = Reversal(5).predict(d, np.arange(20))
    assert np.isnan(s[:5]).all()
    assert np.allclose(s[10], -np.log(d.close[10] / d.close[5]))


def test_decile_book_and_costs():
    rng = np.random.default_rng(3)
    scores = rng.normal(size=(30, 50))
    mask = np.ones((30, 50), dtype=bool)
    w = decile_weights(scores, mask)
    assert np.allclose(w.sum(axis=1), 0) and np.allclose(np.abs(w).sum(axis=1), 2)
    ret = 0.01 * scores  # perfect foresight: the book earns
    r = evaluate(w, scores, scores, ret, np.full((30, 50), 0.001), mask, np.arange(30))["summary"]
    assert r["ic_mean"] == pytest.approx(1.0) and r["hit_rate"] > 0.99 and r["gross"]["mean_bps"] > 0
    assert r["net_10bps"]["mean_bps"] < r["net_0bps"]["mean_bps"]


def test_optimizer_respects_every_constraint():
    rng = np.random.default_rng(5)
    n, g = 80, 4
    rets = rng.normal(0, 0.01, (252, n)) + rng.normal(0, 0.01, (252, 1))
    B, f, spec = pca_risk(rets, 12)
    assert B.shape == (n, 12) and (spec > 0).all()
    sector = np.arange(n) % g
    S = np.eye(g)[sector]
    member = np.ones(n, dtype=bool)
    member[:5] = False
    cfg = OptConfig()
    opt = Optimizer(n, S, cfg)
    beta = rng.uniform(0.5, 1.5, n)
    a = grinold_alpha(rng.normal(size=n), spec, member, 0.05)
    w, info = opt.solve(a, B, f, spec, beta, np.full(n, 5e-4), np.zeros(n), member)
    assert info["status"].startswith("optimal")
    tol = 1e-4
    assert abs(w.sum()) < tol and abs(beta @ w) <= cfg.beta_band + tol
    assert (np.abs(S.T @ w) <= cfg.sector_band + tol).all() and (np.abs(w) <= cfg.max_weight + tol).all()
    assert np.abs(w).sum() <= cfg.gross + tol and (w[:5] == 0).all()
    w2, _ = opt.solve(a, B, f, spec, beta, np.full(n, 0.05), w, member)  # a huge cost: keep the old book
    assert np.abs(w2 - w).sum() < 0.05
