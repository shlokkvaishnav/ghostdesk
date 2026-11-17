"""Parametric impact simulator: arithmetic Brownian price with linear permanent impact and power-law temporary impact.

With beta = 1 it is exactly the Almgren-Chriss model of `schedules.py` (tested against its closed form). With
beta = 0.5 the temporary impact follows the square-root law, eta |v|^0.5, and the Almgren-Chriss schedule is no longer
optimal: that gap is what an RL agent can try to close.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ghostdesk.execution.schedules import ACParams


@dataclass
class ImpactSimulator:
    params: ACParams
    S0: float = 100.0
    beta: float = 1.0
    rng: np.random.Generator = field(default_factory=np.random.default_rng)

    def reset(self, seed: int | None = None) -> float:
        if seed is not None:
            self.rng = np.random.default_rng(seed)
        self.S = self.S0
        return self.S

    def step(self, n: float) -> tuple[float, float]:
        """Sell n >= 0 shares in this interval. Returns (execution price, new mid price)."""
        p = self.params
        v = n / p.tau
        exec_price = self.S - p.eps * np.sign(n) - p.eta * np.sign(v) * abs(v) ** self.beta
        self.S = self.S + p.sigma * np.sqrt(p.tau) * self.rng.standard_normal() - p.gamma * n
        return float(exec_price), float(self.S)
