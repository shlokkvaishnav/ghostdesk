"""Price-chart images for the CNN (Jiang, Kelly and Xiu 2023, "I20" images): the last 20 sessions of a stock as a
64 x 60 black-and-white picture.

- Each session is 3 pixels wide: the open as a tick on the left, the high-low range as a bar in the middle, the
  close as a tick on the right. The 20-session moving average of the close is one pixel per session in the middle
  column.
- Rows 0-50 are prices, scaled so the window's lowest low (or moving average) is row 50 and the highest high row 0.
  Row 51 is empty. Rows 52-63 are volume bars, scaled by the window's largest volume.
- Prices are split- and dividend-adjusted, so the picture does not jump at a split. A window with a missing bar,
  a flagged vendor-error day, or a day before the stock's current index interval gives no image.

`windows` returns the arrays for many (symbol, end session) pairs at once; `draw` turns them into images. An
image ending on session t uses only bars up to and including t (`tests/test_cnn.py`).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..data.calendar import NY

DAYS = 20
HEIGHT, WIDTH = 64, 3 * DAYS
PRICE_ROWS, VOLUME_ROWS = 51, 12


def matrices(prices: pd.DataFrame, returns: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Session x symbol matrices: adjusted o, h, l, c, v, the 20-session moving average of c, and `bad` (a flagged
    vendor-error day or a missing bar)."""
    p = prices.assign(day=prices["t"].dt.tz_convert(NY).dt.normalize().dt.tz_localize(None))
    sessions = pd.DatetimeIndex(sorted(returns["day"].unique()))
    out = {k: p.pivot(index="day", columns="symbol", values=k).reindex(sessions) for k in ("o", "h", "l", "c", "v")}
    out["ma"] = out["c"].rolling(DAYS, min_periods=DAYS).mean()
    flag = returns.pivot(index="day", columns="symbol", values="flag").reindex(sessions)
    flag = flag.reindex(columns=out["c"].columns).fillna(False).astype(bool)
    out["bad"] = flag | out["c"].isna() | out["h"].isna() | out["l"].isna() | out["o"].isna()
    return out


def windows(mats: dict[str, pd.DataFrame], symbols, end_pos, start_pos=None) -> tuple[dict[str, np.ndarray], np.ndarray]:
    """For each (symbol, end session position): arrays (n, 20) of o, h, l, c, ma, v for the sessions end-19..end,
    and a mask of the pairs that give a valid image. `start_pos`: position of the stock's current index-interval
    start; a window must begin at or after it."""
    cols = mats["c"].columns.get_indexer(pd.Index(symbols))
    end_pos = np.asarray(end_pos)
    idx = end_pos[:, None] + np.arange(-DAYS + 1, 1)[None, :]
    ok = (cols >= 0) & (end_pos >= DAYS - 1)
    if start_pos is not None:
        ok &= end_pos - DAYS + 1 >= np.asarray(start_pos)
    idx = np.clip(idx, 0, len(mats["c"]) - 1)
    c = np.maximum(cols, 0)[:, None]
    arr = {k: mats[k].to_numpy(dtype=float)[idx, c] for k in ("o", "h", "l", "c", "ma", "v")}
    bad = mats["bad"].to_numpy()[idx, c].any(axis=1) | np.isnan(arr["ma"]).any(axis=1) | np.isnan(arr["v"]).any(axis=1)
    hi = np.maximum(arr["h"].max(axis=1), arr["ma"].max(axis=1))
    lo = np.minimum(arr["l"].min(axis=1), arr["ma"].min(axis=1))
    ok &= ~bad & (hi > lo)
    return arr, ok


def draw(arr: dict[str, np.ndarray]) -> np.ndarray:
    """Images (n, 64, 60), uint8 0/255, from the arrays of `windows` (valid rows only)."""
    n = len(arr["c"])
    hi = np.maximum(arr["h"].max(axis=1), arr["ma"].max(axis=1))[:, None]
    lo = np.minimum(arr["l"].min(axis=1), arr["ma"].min(axis=1))[:, None]

    def row(x):
        return np.rint((hi - x) / (hi - lo) * (PRICE_ROWS - 1)).astype(int).clip(0, PRICE_ROWS - 1)

    img = np.zeros((n, HEIGHT, WIDTH), dtype=np.uint8)
    rows = np.arange(HEIGHT)[None, :, None]  # (1, 64, 1)
    r_o, r_h, r_l, r_c, r_ma = row(arr["o"]), row(arr["h"]), row(arr["l"]), row(arr["c"]), row(arr["ma"])
    i = np.arange(n)[:, None]
    d = np.arange(DAYS)[None, :]
    img[i, r_o, 3 * d] = 255
    img[i, r_c, 3 * d + 2] = 255
    bar = (rows >= r_h[:, None, :]) & (rows <= r_l[:, None, :])  # (n, 64, 20)
    vmax = arr["v"].max(axis=1, keepdims=True)
    vh = np.rint(np.where(vmax > 0, arr["v"] / np.where(vmax > 0, vmax, 1), 0) * VOLUME_ROWS).astype(int)
    vol = (rows > HEIGHT - 1 - vh[:, None, :]) & (rows >= HEIGHT - VOLUME_ROWS)
    img[:, :, 1::3] = np.where(bar | vol, 255, 0).astype(np.uint8)
    img[i, r_ma, 3 * d + 1] = 255
    return img
