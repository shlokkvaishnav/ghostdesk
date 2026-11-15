"""Categorical tokens per second for the world model (reports/spec_03.md, amendment A1).

Fields, in this order:
- buy, sell: aggressor volume in the second, 16 bins (0 = no trade; 1..15 by train-day quantiles of log1p volume);
- move: mid change in half-ticks, clipped to [-10, 10] (21 classes, class = move + 10);
- spread: spread in ticks 1, 2, >= 3 (3 classes);
- imb1, imb5: level-1 and 5-level depth imbalance, 10 equal-width bins on [-1, 1].
The tick of a day is its modal spread. `VolumeBins` is fitted on train days only.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

FIELDS = ("buy", "sell", "move", "spread", "imb1", "imb5")
SIZES = {"buy": 16, "sell": 16, "move": 21, "spread": 3, "imb1": 10, "imb5": 10}
MAX_MOVE = 10


def day_tick(book: pd.DataFrame) -> tuple[float, float]:
    """(tick, share of seconds whose spread is a whole number of ticks)."""
    sp = (book["ask_px_0"] - book["bid_px_0"]).to_numpy(float)
    vals, counts = np.unique(np.round(sp, 8), return_counts=True)
    tick = float(vals[np.argmax(counts)])
    whole = np.abs(sp / tick - np.round(sp / tick)) < 1e-6
    return tick, float(whole.mean())


@dataclass
class VolumeBins:
    edges: np.ndarray  # 14 inner edges on log1p(volume) for positive volumes
    centers: np.ndarray  # representative volume of each of the 16 bins (bin 0 = 0)

    @classmethod
    def fit(cls, volumes: np.ndarray) -> VolumeBins:
        v = np.asarray(volumes, float)
        v = v[v > 0]
        edges = np.quantile(np.log1p(v), np.arange(1, 15) / 15)
        b = 1 + np.searchsorted(edges, np.log1p(v), side="right")
        centers = np.zeros(16)
        for i in range(1, 16):
            centers[i] = np.median(v[b == i]) if (b == i).any() else np.nan
        return cls(edges, centers)

    def __call__(self, volumes) -> np.ndarray:
        v = np.asarray(volumes, float)
        return np.where(v > 0, 1 + np.searchsorted(self.edges, np.log1p(np.maximum(v, 0)), side="right"), 0).astype(np.int64)


def raw_day(book: pd.DataFrame, trades: pd.DataFrame) -> dict:
    """Per-second raw series of one day: buy, sell volume, mid (price), spread (ticks), imbalances, tick."""
    tick, whole = day_tick(book)
    t = trades.set_index("ts").reindex(book["ts"])
    bp, ap = book["bid_px_0"].to_numpy(float), book["ask_px_0"].to_numpy(float)
    bs, as_ = book["bid_sz_0"].to_numpy(float), book["ask_sz_0"].to_numpy(float)
    bd = book[[f"bid_sz_{i}" for i in range(5)]].sum(axis=1).to_numpy(float)
    ad = book[[f"ask_sz_{i}" for i in range(5)]].sum(axis=1).to_numpy(float)
    return {"buy_vol": t["buy_vol"].fillna(0).to_numpy(float), "sell_vol": t["sell_vol"].fillna(0).to_numpy(float),
            "mid": (bp + ap) / 2, "spread_ticks": (ap - bp) / tick, "imb1": (bs - as_) / (bs + as_),
            "imb5": (bd - ad) / (bd + ad), "tick": tick, "tick_whole_share": whole}


def tokenise(raw: dict, bins: VolumeBins) -> tuple[np.ndarray, float]:
    """(tokens (T, 6) int64 in FIELDS order, share of moves clipped). Row t holds the flow of second t and the book
    at the end of second t; the move of row 0 is 0 (no previous mid)."""
    half = raw["tick"] / 2
    dm = np.concatenate([[0.0], np.diff(raw["mid"])]) / half
    dm = np.round(dm)
    clipped = float(np.mean(np.abs(dm) > MAX_MOVE))
    move = np.clip(dm, -MAX_MOVE, MAX_MOVE).astype(np.int64) + MAX_MOVE
    spread = np.clip(np.round(raw["spread_ticks"]), 1, 3).astype(np.int64) - 1
    imb = [np.clip(np.floor((np.nan_to_num(raw[k]) + 1) / 2 * 10), 0, 9).astype(np.int64) for k in ("imb1", "imb5")]
    tok = np.stack([bins(raw["buy_vol"]), bins(raw["sell_vol"]), move, spread, *imb], 1)
    return tok, clipped
