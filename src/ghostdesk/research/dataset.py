"""The research panel: session x symbol matrices of adjusted prices, membership, sectors, and the label.

- **Symbols:** every price symbol that is an index member on at least one session of the window.
- **Fields** for the feature engine: open, high, low, close, volume, vwap from the adjusted store (`data.store`).
- **Label** (decision D29): orders are market-on-open, so the prediction made after the close of day t is scored on
  the open(t+1) -> open(t+2) return. The residual removes the market (beta to SPY from the 252 sessions through t,
  no later data) and then the sector mean of the beta-residuals on that day. A label touching a vendor corporate-
  action error (adjusted move > 30% and 20 points larger than the raw move) is NaN.
- **Lock:** a panel that reaches past the validation end needs the test lock open (`research.holdout_lock`).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ghostdesk.data.store import PriceStore, matrices, membership
from ghostdesk.paths import DATA_DIR
from ghostdesk.research.holdout_lock import guard

FIELD_MAP = {"open": "o", "high": "h", "low": "l", "close": "c", "volume": "v", "vwap": "vw"}


@dataclass
class Panel:
    days: pd.DatetimeIndex
    symbols: list[str]
    fields: dict[str, np.ndarray]     # engine field name -> (T, N)
    member: np.ndarray                # (T, N) bool
    sector: np.ndarray                # (N,) str
    spy_open: np.ndarray              # (T,)
    spy_close: np.ndarray             # (T,)
    raw_open: np.ndarray              # (T, N) as traded (order sizes, cost estimates)
    flag: np.ndarray                  # (T, N) bool: vendor error on the close-to-close move into day t
    data_key: str                     # store content hash + window + as-of (the feature cache key)


def load_panel(start, end, asof=None, store: PriceStore | None = None, include_test: bool = False,
               warmup_days: int = 400) -> Panel:
    """Matrices from `start - warmup_days` (feature history) to `end`."""
    store = store or PriceStore()
    guard(pd.DatetimeIndex([pd.Timestamp(end)]), include_test=include_test)
    lo = pd.Timestamp(start) - pd.Timedelta(days=warmup_days)
    ps = pd.read_parquet(DATA_DIR / "price_symbols.parquet")
    adj = store.read("adj", start=lo, end=end, asof=asof)
    raw = store.read("raw", start=lo, end=end, asof=asof)
    days = pd.DatetimeIndex(sorted(adj.loc[adj["symbol"] == "SPY", "day"].unique()))
    window = days[days >= pd.Timestamp(start)]
    syms = sorted(set(ps["price_symbol"].dropna()) & set(adj["symbol"]) - {"SPY"})
    mem = membership(ps, days, syms)
    syms = [s for s in syms if mem.loc[window, s].any()]
    mem = mem[syms]
    m = matrices(adj, list(FIELD_MAP.values()), days, syms + ["SPY"])
    r = matrices(raw, ["o", "c"], days, syms)
    fields = {k: m[v][syms].to_numpy() for k, v in FIELD_MAP.items()}
    sec = pd.read_parquet(DATA_DIR / "sectors.parquet").set_index("cik")["sector"]
    cik = ps.dropna(subset=["price_symbol", "cik"]).drop_duplicates("price_symbol", keep="last").set_index(
        "price_symbol")["cik"]
    sector = np.array([sec.get(int(cik[s]), "unknown") if s in cik else "unknown" for s in syms])
    adj_c, raw_c = np.log(fields["close"]), np.log(r["c"].to_numpy())
    with np.errstate(invalid="ignore"):
        a, b = np.diff(adj_c, axis=0, prepend=np.nan), np.diff(raw_c, axis=0, prepend=np.nan)
        flag = (np.abs(a) > 0.3) & ((np.abs(a) - np.abs(b)) > 0.2)
    key = f"{store.content_hash('adj')[:16]}|{days[0]:%Y%m%d}-{days[-1]:%Y%m%d}|{asof}|{len(syms)}"
    return Panel(days, syms, fields, mem.to_numpy(), sector, m["o"]["SPY"].to_numpy(), m["c"]["SPY"].to_numpy(),
                 r["o"].to_numpy(), flag, key)


def open_to_open(open_: np.ndarray) -> np.ndarray:
    """Row t: log return from open(t+1) to open(t+2); NaN for the last two rows (not known yet)."""
    lo = np.log(open_)
    out = np.full(lo.shape, np.nan)
    out[:-2] = lo[2:] - lo[1:-1]
    return out


def rolling_beta(ret: np.ndarray, mkt: np.ndarray, window: int = 252, min_obs: int = 120) -> np.ndarray:
    """Row t: beta of each stock to the market from the `window` rows ending at t (close-to-close returns known at
    t); 1.0 where fewer than `min_obs` pairs."""
    ok = np.isfinite(ret) & np.isfinite(mkt)[:, None]
    x = np.where(ok, mkt[:, None], 0.0)
    y = np.where(ok, ret, 0.0)

    def wsum(a):
        c = np.cumsum(a, axis=0)
        c[window:] = c[window:] - c[:-window]
        return c

    cnt, sx, sy, sxx, sxy = wsum(ok.astype(float)), wsum(x), wsum(y), wsum(x * x), wsum(x * y)
    with np.errstate(invalid="ignore", divide="ignore"):
        var = sxx - sx * sx / cnt
        b = (sxy - sx * sy / cnt) / var
    return np.where((cnt >= min_obs) & (var > 0), b, 1.0)


def residual_label(p: Panel) -> np.ndarray:
    """(T, N) open(t+1) -> open(t+2) residual return: minus beta x SPY, then minus the sector mean of members.
    NaN for non-members on day t, for vendor-error days inside the label window, and the last two rows."""
    r = open_to_open(p.fields["open"])
    spy = open_to_open(p.spy_open[:, None])[:, 0]
    cc = np.diff(np.log(p.fields["close"]), axis=0, prepend=np.nan)
    mcc = np.diff(np.log(p.spy_close), prepend=np.nan)
    beta = rolling_beta(cc, mcc)
    res = r - beta * spy[:, None]
    bad = np.zeros_like(p.flag)
    bad[:-2] = p.flag[1:-1] | p.flag[2:]
    res[bad | ~p.member] = np.nan
    out = res.copy()
    for s in np.unique(p.sector):
        cols = p.sector == s
        x = res[:, cols]
        n = np.isfinite(x).sum(axis=1, keepdims=True)
        mu = np.where(n > 0, np.nansum(x, axis=1, keepdims=True) / np.maximum(n, 1), 0.0)
        out[:, cols] = x - mu
    return out

