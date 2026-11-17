"""Book risk: Ledoit-Wolf shrinkage behaves as the theory says, and the book numbers (volatility, beta, sectors)
are right on books whose answer is known."""
import numpy as np
import pandas as pd

from ghostdesk.live.book_risk import book_risk, ledoit_wolf


def test_shrinkage_is_small_with_much_data_and_makes_a_singular_sample_invertible():
    rng = np.random.default_rng(0)
    a = rng.normal(size=(5000, 5)) @ np.diag([1, 2, 3, 4, 5]) * 0.01
    cov, d = ledoit_wolf(a)
    assert 0 <= d < 0.05 and np.allclose(cov, np.cov(a.T, bias=True), rtol=0.1)
    b = rng.normal(size=(60, 200)) * 0.01  # more stocks than days
    sample = np.cov(b.T, bias=True)
    cov, d = ledoit_wolf(b)
    assert np.linalg.matrix_rank(sample) < 200 and np.linalg.eigvalsh(cov).min() > 0 and 0 < d <= 1


def test_book_numbers_on_a_known_book():
    rng = np.random.default_rng(1)
    days = pd.bdate_range("2025-01-01", periods=300)
    m = pd.Series(rng.normal(0, 0.01, len(days)), index=days)
    noise = lambda: rng.normal(0, 0.002, len(days))
    r = pd.DataFrame({"A": m + noise(), "B": m + noise(), "C": 2 * m + noise(),
                      "D": pd.Series(noise(), index=days).where(days > days[250])}, index=days)
    sectors = {"A": "Tech", "B": "Tech", "C": "Energy", "D": "Energy"}
    out = book_risk({"A": 50.0, "B": -50.0, "C": 25.0, "D": 10.0}, 100.0, r, m, sectors)
    assert abs(out["beta_spy"] - 0.5) < 0.05  # A and B cancel; C has beta 2 at weight 0.25; D is left out
    assert out["stocks_without_history"] == 1 and out["stocks"] == 4
    assert abs(out["net"] - 0.35) < 1e-9 and abs(out["gross"] - 1.35) < 1e-9
    assert out["largest"]["weight"] in (0.5, -0.5)
    sec = {x["sector"]: x for x in out["sectors"]}
    assert sec["Tech"]["net"] == 0.0 and sec["Tech"]["gross"] == 1.0 and sec["Energy"]["net"] == 0.35
    # the hedged pair adds only its noise: volatility close to that of 0.25 x C
    assert abs(out["vol_annual"] - 0.25 * 0.02 * np.sqrt(252)) < 0.02
