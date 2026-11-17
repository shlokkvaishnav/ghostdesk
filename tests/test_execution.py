import numpy as np
import pytest
from gymnasium.utils.env_checker import check_env

from ghostdesk.execution.impact_simulator import ImpactSimulator
from ghostdesk.execution.schedules import (
    ACParams,
    almgren_chriss,
    cost_variance,
    expected_cost,
    kappa,
    mean_variance,
    twap,
    vwap,
)
from ghostdesk.execution.trading_env import ExecutionEnv, run_schedule

# the worked example of Almgren and Chriss (2000): S0 = 50, sigma = 0.95 per day, 1e6 shares over 5 days
P = ACParams(sigma=0.95, gamma=2.5e-7, eta=2.5e-6, eps=0.0625, T=5.0, N=5)
X, LAM = 1e6, 1e-6


def test_twap_and_vwap_holdings():
    assert np.allclose(twap(10, 5), [10, 8, 6, 4, 2, 0])
    assert np.allclose(vwap(10, [1, 3, 1]), [10, 8, 2, 0])
    with pytest.raises(ValueError):
        vwap(10, [0, 0])


def test_kappa_solves_the_discrete_equation_and_lam_zero_is_twap():
    k = kappa(P, LAM)
    assert np.isclose(2 / P.tau**2 * (np.cosh(k * P.tau) - 1), LAM * P.sigma**2 / P.eta_tilde)
    assert np.allclose(almgren_chriss(X, P, 0.0), twap(X, P.N))
    x = almgren_chriss(X, P, LAM)
    assert x[0] == X and abs(x[-1]) < 1e-6 and np.all(np.diff(x) < 0)
    assert x[1] < twap(X, P.N)[1]  # risk aversion front-loads the selling


def test_almgren_chriss_minimises_mean_variance():
    x = almgren_chriss(X, P, LAM)
    best = mean_variance(x, P, LAM)
    rng = np.random.default_rng(0)
    for _ in range(200):
        y = x.copy()
        y[1:-1] += rng.normal(0, 0.02 * X, P.N - 1)
        assert mean_variance(y, P, LAM) >= best - 1e-6 * abs(best)


def test_simulator_matches_the_closed_form_mean_and_variance():
    x = almgren_chriss(X, P, LAM)
    env = ExecutionEnv(ImpactSimulator(P, S0=50.0), X=X)
    costs = np.array([run_schedule(env, x, seed=s) for s in range(4000)])
    se = costs.std(ddof=1) / np.sqrt(len(costs))
    assert abs(costs.mean() - expected_cost(x, P)) < 4 * se
    assert abs(costs.var(ddof=1) / cost_variance(x, P) - 1) < 0.1


def test_env_api_invariants():
    env = ExecutionEnv(ImpactSimulator(P, S0=50.0), X=X, lam=LAM)
    check_env(env, skip_render_check=True)
    obs, _ = env.reset(seed=3)
    total, sold, n = 0.0, 0.0, 0
    done = False
    while not done:
        obs, r, done, trunc, info = env.step(np.array([0.3], np.float32))
        total += r
        sold += info["sold"]
        n += 1
        assert env.observation_space.contains(obs) and not trunc
    assert n == P.N and np.isclose(sold, X) and info["inventory"] == 0.0
    assert np.isclose(total * env.scale, -(info["shortfall"] + info["risk"]))


def test_same_seed_same_episode():
    env = ExecutionEnv(ImpactSimulator(P, S0=50.0), X=X)
    x = twap(X, P.N)
    assert run_schedule(env, x, seed=11) == run_schedule(env, x, seed=11)
    assert run_schedule(env, x, seed=11) != run_schedule(env, x, seed=12)


def test_price_blind_observation_hides_the_price():
    from ghostdesk.execution.impact_simulator import ImpactSimulator
    from ghostdesk.execution.schedules import ACParams
    from ghostdesk.execution.trading_env import ExecutionEnv

    p = ACParams(sigma=0.95, gamma=2.5e-7, eta=2.5e-6, eps=0.0625, T=5.0, N=20)
    seen, blind = (ExecutionEnv(ImpactSimulator(p, S0=50.0, beta=1.0), X=1e6, observe_price=o) for o in (True, False))
    for env in (seen, blind):
        env.reset(seed=3)
    for _ in range(5):
        a, _, _, _, ia = seen.step(np.array([0.1], np.float32))
        b, _, _, _, ib = blind.step(np.array([0.1], np.float32))
        assert b[2] == 0.0 and np.allclose(a[:2], b[:2]) and ia["shortfall"] == ib["shortfall"]
    assert a[2] != 0.0
