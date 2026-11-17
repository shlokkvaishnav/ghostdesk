"""Replay simulator: sell an order over the first hour of a real trading day, on that day's real prices and volume.

Each day is cut into `steps` intervals (12 x 5 minutes). The order's own effect is added to the real path with the
published calibration of Almgren, Thum, Hauptmann and Li (2005, "Direct estimation of equity market impact"):
- permanent impact: the price falls by gamma * sigma * (shares sold so far / ADV) (gamma = 0.314);
- temporary impact on a step's fill: eta * sigma * (n_k / v_k) ** beta (eta = 0.142, beta = 0.6), where n_k / v_k is
  the order's share of that step's real volume. With the same volume in every step this is exactly their model in
  "participation of the daily volume rate"; with real volume it rewards trading when the market is liquid;
- a constant half-spread `half_spread` (the same for every schedule, so it does not change their order).
sigma is the stock's daily volatility (63 days before the day), ADV its mean daily volume (63 days before the day).
Fills are at the step's volume-weighted price. Cost = implementation shortfall against the arrival price (the first
minute's open), in basis points of the order's value. A step without volume has a volume floor of 10% of the day's
median step volume (trading into an empty market is expensive, not free).
"""
from __future__ import annotations

from dataclasses import dataclass

import gymnasium as gym
import numpy as np
import pandas as pd
from gymnasium import spaces

ETA, BETA, GAMMA = 0.142, 0.6, 0.314  # Almgren, Thum, Hauptmann and Li (2005)


@dataclass(frozen=True)
class Day:
    symbol: str
    day: pd.Timestamp
    arrival: float          # first minute's open
    px: np.ndarray          # volume-weighted price of each step
    vol: np.ndarray         # real volume of each step (shares)
    adv: float              # mean daily volume, 63 days before
    sigma: float            # daily volatility (fraction), 63 days before


def make_days(minutes: pd.DataFrame, daily: pd.DataFrame, steps: int = 12, minutes_per_step: int = 5) -> list[Day]:
    """minutes: symbol, day, minute (0 = 09:30), o, c, v, vw; daily: raw daily bars (symbol, t, c, v)."""
    d = daily.assign(day=daily["t"].dt.tz_convert("America/New_York").dt.normalize().dt.tz_localize(None))
    d = d.sort_values(["symbol", "day"])
    d["r"] = np.log(d["c"]).groupby(d["symbol"]).diff()
    g = d.groupby("symbol")
    d["adv"] = g["v"].transform(lambda s: s.shift(1).rolling(63, min_periods=40).mean())
    d["sigma"] = g["r"].transform(lambda s: s.shift(1).rolling(63, min_periods=40).std())
    ctx = d.set_index(["symbol", "day"])[["adv", "sigma"]]
    m = minutes[minutes["minute"] < steps * minutes_per_step].copy()
    m["step"] = m["minute"] // minutes_per_step
    m["pv"] = m["vw"].fillna(m["c"]) * m["v"]
    out = []
    for (sym, day), x in m.groupby(["symbol", "day"]):
        if (sym, day) not in ctx.index or x["minute"].min() != 0:
            continue
        adv, sig = ctx.loc[(sym, day)]
        if not (np.isfinite(adv) and np.isfinite(sig)) or adv <= 0:
            continue
        s = x.groupby("step").agg(pv=("pv", "sum"), v=("v", "sum"), c=("c", "last")).reindex(range(steps))
        vol = s["v"].fillna(0.0).to_numpy()
        px = (s["pv"] / s["v"]).where(s["v"] > 0).fillna(s["c"]).ffill().bfill().to_numpy()
        out.append(Day(sym, day, float(x.loc[x["minute"] == 0, "o"].iloc[0]), px, vol, float(adv), float(sig)))
    return out


def shortfall_bps(day: Day, trades: np.ndarray, size: float, half_spread: float = 1e-4, eta: float = ETA) -> float:
    """Implementation shortfall (bps) of selling `trades` (shares per step, sum = size x ADV) on `day`."""
    q = size * day.adv
    return float(sum(shortfall_part(day, trades, k, q, half_spread, eta) for k in range(len(trades))))


def schedule_trades(weights: np.ndarray, size: float, day: Day) -> np.ndarray:
    w = np.asarray(weights, float)
    return w / w.sum() * size * day.adv


def twap_weights(steps: int) -> np.ndarray:
    return np.ones(steps)


def ac_weights(steps: int, kappa_T: float) -> np.ndarray:
    """Almgren-Chriss shape: holdings sinh(kappa (T - t)) / sinh(kappa T); trades are the holdings' differences."""
    t = np.arange(steps + 1) / steps
    x = np.sinh(kappa_T * (1 - t)) / np.sinh(kappa_T)
    return -np.diff(x)


def volume_profile(days: list[Day]) -> dict[str, np.ndarray]:
    """Expected share of the hour's volume in each step, per symbol (from the given, earlier days)."""
    by: dict[str, list[np.ndarray]] = {}
    for d in days:
        if d.vol.sum() > 0:
            by.setdefault(d.symbol, []).append(d.vol / d.vol.sum())
    return {s: np.mean(v, axis=0) for s, v in by.items()}


class ReplayEnv(gym.Env):
    """Sell `size` x ADV over the steps of a random day from `days`. Action a in [-3, 3]: sell
    (order left / steps left) x exp(a), at most the order left; a = 0 is TWAP, so the policy learns changes from the
    TWAP pace. The last step sells the rest. Observation: steps left, order left, log size, log(last step volume /
    expected), price move since arrival (in daily sigma; 0 if price-blind).
    Reward: minus each step's cost divided by `scale[size]` (default 100, so the return x 100 is minus the shortfall
    in bps). reward="impact" counts only the order's own cost (spread and impact against the real price of the step),
    not the market move since arrival: the move is not caused by the order and its expected value is about 0, but its
    noise (about 50 bps in an hour) hides impact differences of about 1 bp. Evaluation always uses the shortfall."""

    def __init__(self, days: list[Day], profile: dict[str, np.ndarray], sizes=(0.001, 0.01, 0.05),
                 observe_price: bool = True, half_spread: float = 1e-4, eta: float = ETA, seed: int = 0,
                 reward: str = "shortfall", scale: dict[float, float] | None = None):
        self.days, self.profile, self.sizes = days, profile, tuple(sizes)
        self.reward_kind, self.scale = reward, scale or {}
        self.observe_price, self.half_spread, self.eta = observe_price, half_spread, eta
        self.steps = len(days[0].px)
        self.rng = np.random.default_rng(seed)
        self.action_space = spaces.Box(-3.0, 3.0, shape=(1,), dtype=np.float32)
        self.observation_space = spaces.Box(-np.inf, np.inf, shape=(5,), dtype=np.float32)
        self.fixed: tuple[Day, float] | None = None

    def set_episode(self, day: Day, size: float):
        """Evaluate on a given (day, size) at the next reset."""
        self.fixed = (day, size)

    def _obs(self):
        d, k = self.day, self.k
        exp = self.profile.get(d.symbol, np.full(self.steps, 1 / self.steps))
        if k == 0:
            vol_signal = 0.0
        else:
            seen, expected = d.vol[:k].sum(), exp[:k].sum() * max(d.vol.sum(), 1.0)
            vol_signal = float(np.log((seen + 1) / (expected + 1)))
        move = (d.px[k - 1] / d.arrival - 1) / d.sigma if (k > 0 and self.observe_price) else 0.0
        return np.array([(self.steps - k) / self.steps, self.left / self.q, np.log10(self.size), vol_signal,
                         np.clip(move, -50, 50)], np.float32)

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        if self.fixed is not None:
            self.day, self.size = self.fixed
            self.fixed = None
        else:
            self.day = self.days[self.rng.integers(len(self.days))]
            self.size = float(self.rng.choice(self.sizes))
        self.q = self.size * self.day.adv
        self.k, self.left, self.trades = 0, self.q, np.zeros(self.steps)
        return self._obs(), {}

    def step(self, action):
        a = float(np.clip(np.asarray(action, float).reshape(-1)[0], -3.0, 3.0))
        pace = self.left / (self.steps - self.k)
        n = self.left if self.k == self.steps - 1 else min(self.left, pace * np.exp(a))
        self.trades[self.k] = n
        part = (impact_part if self.reward_kind == "impact" else shortfall_part)(
            self.day, self.trades, self.k, self.q, self.half_spread, self.eta)
        self.k += 1
        self.left -= n
        done = self.k == self.steps
        reward = -part / self.scale.get(self.size, 100.0)
        info = {"shortfall_bps": shortfall_bps(self.day, self.trades, self.size, self.half_spread, self.eta)
                if done else None}
        return self._obs() if not done else np.zeros(5, np.float32), float(reward), done, False, info


def shortfall_part(day: Day, trades: np.ndarray, k: int, q: float, half_spread: float, eta: float) -> float:
    """The cost (bps of the order) of step k's fill, given the trades so far; the steps' parts add up to
    `shortfall_bps`."""
    floor = 0.1 * max(np.median(day.vol), 1.0)
    sold_before = trades[:k].sum()
    mid = day.px[k] * (1 - GAMMA * day.sigma * sold_before / day.adv)
    fill = mid * (1 - half_spread - eta * day.sigma * (trades[k] / max(day.vol[k], floor)) ** BETA)
    return float(trades[k] * (day.arrival - fill) / (q * day.arrival) * 1e4)


def impact_part(day: Day, trades: np.ndarray, k: int, q: float, half_spread: float, eta: float) -> float:
    """The order's own cost of step k (bps of the order): the fill against the step's real price, without the market
    move since arrival."""
    floor = 0.1 * max(np.median(day.vol), 1.0)
    sold_before = trades[:k].sum()
    mid = day.px[k] * (1 - GAMMA * day.sigma * sold_before / day.adv)
    fill = mid * (1 - half_spread - eta * day.sigma * (trades[k] / max(day.vol[k], floor)) ** BETA)
    return float(trades[k] * (day.px[k] - fill) / (q * day.arrival) * 1e4)
