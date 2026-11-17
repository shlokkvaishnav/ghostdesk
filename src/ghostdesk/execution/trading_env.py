"""Optimal-execution environment: sell X shares over N steps; reward = minus the implementation shortfall.

Action: the fraction of the remaining inventory to sell this step, in [0, 1]; the last step sells what is left.
Observation: (time left / N, inventory left / X, (S - S0) / (sigma sqrt T)), all float32. With observe_price=False the
third entry is always 0 (the price-blind ablation of reports/spec_02.md).
Reward per step: (n_k * exec_price_k - n_k * S0) / (X * sigma * sqrt(T)) minus an optional risk term
lam * sigma^2 * tau * x_k^2 on the same scale, so the undiscounted return times the scale equals minus the
shortfall (minus lam times the variance proxy). `info` carries the unscaled shortfall.
"""
from __future__ import annotations

from typing import ClassVar

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from ghostdesk.execution.impact_simulator import ImpactSimulator


class ExecutionEnv(gym.Env):
    metadata: ClassVar[dict] = {"render_modes": []}

    def __init__(self, sim: ImpactSimulator, X: float = 1e5, lam: float = 0.0, observe_price: bool = True):
        self.sim, self.X, self.lam, self.observe_price = sim, float(X), float(lam), observe_price
        p = sim.params
        self.N, self.scale = p.N, self.X * p.sigma * np.sqrt(p.T)
        self.action_space = spaces.Box(0.0, 1.0, shape=(1,), dtype=np.float32)
        self.observation_space = spaces.Box(np.array([0, 0, -np.inf], np.float32), np.array([1, 1, np.inf], np.float32))

    def _obs(self):
        p = self.sim.params
        price = (self.sim.S - self.sim.S0) / (p.sigma * np.sqrt(p.T)) if self.observe_price else 0.0
        return np.array([(self.N - self.k) / self.N, self.x / self.X, price], dtype=np.float32)

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        self.sim.reset(int(self.np_random.integers(2**31)))
        self.k, self.x, self.shortfall, self.risk = 0, self.X, 0.0, 0.0
        return self._obs(), {}

    def step(self, action):
        frac = float(np.clip(np.asarray(action, float).reshape(-1)[0], 0.0, 1.0))
        n = self.x if self.k == self.N - 1 else frac * self.x
        price, _ = self.sim.step(n)
        self.k += 1
        self.x -= n
        if self.k == self.N:
            self.x = 0.0  # exact zero, not a rounding residue
        p = self.sim.params
        step_shortfall = n * (self.sim.S0 - price)
        step_risk = self.lam * p.sigma**2 * p.tau * self.x**2
        self.shortfall += step_shortfall
        self.risk += step_risk
        reward = -(step_shortfall + step_risk) / self.scale
        done = self.k == self.N
        info = {"shortfall": self.shortfall, "risk": self.risk, "inventory": self.x, "sold": n}
        return self._obs(), float(reward), done, False, info


def run_schedule(env: ExecutionEnv, holdings: np.ndarray, seed: int) -> float:
    """Follow fixed holdings x_0..x_N in the environment; returns the implementation shortfall."""
    env.reset(seed=seed)
    info = {}
    for k in range(env.N):
        x_now, x_next = holdings[k], holdings[k + 1]
        frac = 1.0 if x_now <= 0 else (x_now - x_next) / x_now
        *_, info = env.step(np.array([frac], np.float32))
    return info["shortfall"]
