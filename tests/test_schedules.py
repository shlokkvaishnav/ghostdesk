import numpy as np
import pytest

from ghostdesk.execution.schedules import (
    ACParams,
    almgren_chriss,
    kappa,
    mean_variance,
    twap,
    vwap,
)

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
