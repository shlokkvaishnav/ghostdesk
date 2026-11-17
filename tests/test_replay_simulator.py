"""Replay simulator: closed form on a flat day, liquidity timing pays, env reward = cost, no look-ahead in inputs."""
import numpy as np
import pandas as pd

from ghostdesk.execution.replay_simulator import (
    BETA,
    ETA,
    GAMMA,
    Day,
    ReplayEnv,
    ac_weights,
    make_days,
    schedule_trades,
    shortfall_bps,
    twap_weights,
    volume_profile,
)


def flat_day(vol, sigma=0.02, adv=1e6):
    return Day("X", pd.Timestamp("2024-01-02"), 100.0, np.full(len(vol), 100.0), np.asarray(vol, float), adv, sigma)


def test_twap_matches_the_closed_form_on_a_flat_day():
    n, size = 12, 0.01
    d = flat_day(np.full(n, 20_000.0))
    q = size * d.adv
    got = shortfall_bps(d, schedule_trades(twap_weights(n), size, d), size, half_spread=1e-4)
    perm = GAMMA * d.sigma * (q / n) * np.arange(n) / d.adv  # permanent shift before each equal fill
    temp = ETA * d.sigma * ((q / n) / 20_000.0) ** BETA
    exact = np.mean(1 - (1 - perm) * (1 - 1e-4 - temp)) * 1e4  # fill = mid x (1 - half spread - temporary)
    assert abs(got - exact) < 1e-9


def test_trading_with_the_volume_costs_less():
    u = np.array([6, 3, 2, 1.5, 1, 1, 1, 1, 1, 1.5, 2, 3]) * 10_000
    d = flat_day(u)
    twap = shortfall_bps(d, schedule_trades(twap_weights(12), 0.05, d), 0.05)
    vwap = shortfall_bps(d, schedule_trades(u, 0.05, d), 0.05)
    assert vwap < twap
    # front-loading raises the temporary cost but lowers the permanent cost of later fills
    assert ac_weights(12, 3.0)[0] > ac_weights(12, 3.0)[-1] and abs(ac_weights(12, 3.0).sum() - 1) < 1e-12


def test_env_return_is_minus_the_shortfall():
    rng = np.random.default_rng(0)
    days = [Day("X", pd.Timestamp("2024-01-02"), 100.0, 100 + np.cumsum(rng.normal(0, 0.1, 12)),
                rng.uniform(5e3, 5e4, 12), 1e6, 0.02)]
    env = ReplayEnv(days, volume_profile(days))
    env.set_episode(days[0], 0.01)
    env.reset()
    total, done, info = 0.0, False, {}
    while not done:
        _, r, done, _, info = env.step(np.array([0.3], np.float32))
        total += r
    assert abs(-total * 100 - info["shortfall_bps"]) < 1e-9
    env.set_episode(days[0], 0.01)  # action 0 is exactly TWAP
    env.reset()
    done = False
    while not done:
        *_, done, _, info = env.step(np.array([0.0], np.float32))
    twap = shortfall_bps(days[0], schedule_trades(twap_weights(12), 0.01, days[0]), 0.01)
    assert abs(info["shortfall_bps"] - twap) < 1e-9


def test_inputs_use_only_earlier_days():
    days = pd.bdate_range("2024-01-01", periods=80)
    daily = pd.DataFrame({"symbol": "X", "t": (days + pd.Timedelta(hours=5)).tz_localize("UTC"),
                          "c": 100.0, "v": 1e6})
    daily.loc[daily.index[-1], "v"] = 1e9  # a huge volume on the trading day itself must not enter its ADV
    last = days[-1]
    minutes = pd.DataFrame({"symbol": "X", "day": last, "minute": range(60), "o": 100.0, "c": 100.0,
                            "v": 1000.0, "vw": 100.0})
    (d,) = make_days(minutes, daily)
    assert d.adv == 1e6 and len(d.px) == 12 and d.vol[0] == 5000.0


def test_impact_reward_removes_only_the_market_move():
    from ghostdesk.execution.replay_simulator import impact_part, shortfall_part

    px = np.linspace(100, 99, 12)  # the market falls 1% during the hour
    d = Day("X", pd.Timestamp("2024-01-02"), 100.0, px, np.full(12, 2e4), 1e6, 0.02)
    tr = schedule_trades(twap_weights(12), 0.01, d)
    q = 0.01 * d.adv
    full = sum(shortfall_part(d, tr, k, q, 1e-4, ETA) for k in range(12))
    own = sum(impact_part(d, tr, k, q, 1e-4, ETA) for k in range(12))
    market = float(np.sum(tr * (d.arrival - px)) / (q * d.arrival) * 1e4)
    assert abs(full - own - market) < 0.05 and own > 0  # small cross term: costs scale with the lower price
