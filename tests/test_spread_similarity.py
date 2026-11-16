"""Corwin-Schultz spread on simulated prices with a known spread; the text-similarity measures on small texts."""
import numpy as np
import pandas as pd

from ghostdesk.data.spread import corwin_schultz, monthly_spread
from ghostdesk.signal.similarity import all_measures, cosine, edit, jaccard


def simulate(spread, days=400, steps=390, vol=0.01, seed=0):
    """Trades at mid * (1 +- spread/2) on a random-walk mid; daily high, low and close of the trades."""
    rng = np.random.default_rng(seed)
    logmid = np.cumsum(rng.normal(0, vol / np.sqrt(steps), days * steps)).reshape(days, steps)
    side = rng.choice([-1, 1], size=(days, steps))
    px = 100 * np.exp(logmid) * (1 + side * spread / 2)
    return px.max(1), px.min(1), px[:, -1]


def test_recovers_a_known_spread():
    for s in (0.002, 0.005, 0.02):
        h, lo, c = simulate(s, days=1000)
        est = corwin_schultz(h, lo, c, floor=False).mean()
        assert abs(est - s) < 0.001, (s, est)
    # flooring each two-day estimate biases the mean up (here about 2.5x at a 0.2% spread)
    h, lo, c = simulate(0.002, days=1000)
    assert corwin_schultz(h, lo, c).mean() > 2 * corwin_schultz(h, lo, c, floor=False).mean()


def test_zero_spread_and_bad_pairs_are_not_negative():
    h, lo, c = simulate(0.0, days=300)
    est = corwin_schultz(h, lo, c)
    assert est.isna().iloc[0] and (est.dropna() >= 0).all()
    assert abs(corwin_schultz(h, lo, c, floor=False).mean()) < 0.001


def test_overnight_gap_is_removed():
    h, lo, c = np.array([101.0, 111.0]), np.array([99.0, 109.0]), np.array([100.0, 110.0])  # gap up of 10
    no_adj, adj = corwin_schultz(h, lo, floor=False).iloc[1], corwin_schultz(h, lo, c, floor=False).iloc[1]
    assert adj > no_adj  # without the adjustment the gap looks like variance and hides the spread


def test_monthly_mean():
    h, lo, c = simulate(0.005, days=60)
    m = monthly_spread(h, lo, c, pd.bdate_range("2024-01-01", periods=60))
    assert len(m) == 3 and m.notna().all()


A = "Revenue grew. We face risks from competition. Our supply chain is stable."
B = "Revenue grew. We face new risks from competition and from regulation. Our supply chain is stable."


def test_same_text_is_one_and_order_is_right():
    assert all(abs(v - 1) < 1e-12 for v in all_measures(A, A.upper()).values())  # case does not count
    sims = all_measures(A, B)
    assert all(0 < v < 1 for v in sims.values())
    c = "Completely different words appear here today."
    assert cosine(A, c) < cosine(A, B) and jaccard(A, c) < jaccard(A, B) and edit(A, c) < edit(A, B)


def test_edit_counts_changed_words():
    # 2 sentences are the same (7 words); in the changed one, all 5 old words are kept in order and 4 are added:
    # 2 * (7 + 5) same words / (12 + 16 words)
    assert abs(edit(A, B) - 2 * 12 / 28) < 1e-12
    # one changed number changes one word, not the whole sentence
    long = "In fiscal 2010 our net sales grew because of strong demand for our products in all regions."
    assert edit(long, long.replace("2010", "2011")) > 0.9


def test_empty_text_is_nan():
    assert np.isnan(cosine("", A)) and np.isnan(jaccard(A, "")) and np.isnan(edit("", ""))
