"""Daily and minute stock bars from the Alpaca market-data API (free plan).

- Keys: ALPACA_API_KEY and ALPACA_SECRET_KEY from the environment, else from the gitignored `.env` file. They are sent
  only as request headers to Alpaca, never printed or logged.
- Feed: "sip" (all US exchanges). The free plan allows SIP history except the last 15 minutes. "iex" has only the
  volume of one exchange (about 2-3% of the market), so it is not used for volume-based work.
- Prices are adjusted for splits and dividends (adjustment="all") for returns; raw prices are kept for orders.
- History starts in 2016. Coverage of companies that later left the market is checked with `coverage`, not assumed.
- Requests stay under the free limit (200 per minute) and wait after a 429 answer.
"""
from __future__ import annotations

import os
import time

import pandas as pd
import requests

from ghostdesk.paths import REPO_ROOT

BARS = "https://data.alpaca.markets/v2/stocks/bars"


def keys() -> dict[str, str]:
    """The request headers with the keys. Raises if a key is missing (never shows a value)."""
    vals = {k: os.environ.get(k, "") for k in ("ALPACA_API_KEY", "ALPACA_SECRET_KEY")}
    env = REPO_ROOT / ".env"
    if not all(vals.values()) and env.exists():
        for line in env.read_text().splitlines():
            k, _, v = line.partition("=")
            if k in vals and not vals[k]:
                vals[k] = v.strip().strip('"').strip("'")
    missing = [k for k, v in vals.items() if not v]
    if missing:
        raise RuntimeError(f"Set {', '.join(missing)} in the environment or in .env")
    return {"APCA-API-KEY-ID": vals["ALPACA_API_KEY"], "APCA-API-SECRET-KEY": vals["ALPACA_SECRET_KEY"]}


class AlpacaClient:
    """Rate-limited bar client. `session`, `sleep` and `clock` are injectable so tests never touch the network."""

    def __init__(self, headers: dict | None = None, per_minute: int = 180, session=None, sleep=time.sleep,
                 clock=time.monotonic):
        self._headers = headers
        self.gap = 60.0 / per_minute
        self.session = session or requests.Session()
        self._sleep, self._clock, self._last = sleep, clock, -1e9

    def _get(self, params: dict) -> dict:
        for attempt in range(5):
            wait = self.gap - (self._clock() - self._last)
            if wait > 0:
                self._sleep(wait)
            self._last = self._clock()
            r = self.session.get(BARS, params=params, headers=self._headers or keys(), timeout=60)
            if r.status_code == 429 or r.status_code >= 500:
                self._sleep(min(60.0, 5.0 * (attempt + 1)))
                continue
            r.raise_for_status()
            return r.json()
        r.raise_for_status()
        return r.json()

    def bars(self, symbols: list[str], start: str, end: str, timeframe: str = "1Day", adjustment: str = "all",
             feed: str = "sip") -> pd.DataFrame:
        """symbol, t (UTC), o, h, l, c, v, n (trades), vw (VWAP), for all pages. Symbols with no data are absent."""
        params = {"symbols": ",".join(symbols), "timeframe": timeframe, "start": start, "end": end,
                  "adjustment": adjustment, "feed": feed, "limit": 10000}
        rows = []
        while True:
            j = self._get(params)
            for sym, bs in (j.get("bars") or {}).items():
                rows += [dict(b, symbol=sym) for b in bs]
            token = j.get("next_page_token")
            if not token:
                break
            params = dict(params, page_token=token)
        df = pd.DataFrame(rows, columns=["symbol", "t", "o", "h", "l", "c", "v", "n", "vw"])
        gone = [s for s in symbols if s not in set(df["symbol"])]
        if len(symbols) > 1 and gone:  # a multi-symbol answer can drop a symbol (seen: DOW); ask for each alone
            df = pd.concat([df] + [self.bars([s], start, end, timeframe, adjustment, feed) for s in gone],
                           ignore_index=True)
        df["t"] = pd.to_datetime(df["t"], utc=True)
        return df.sort_values(["symbol", "t"]).reset_index(drop=True)


def alpaca_symbol(ticker: str) -> str:
    """Index ticker -> Alpaca symbol: share classes use a dot (BRK.B); the index lists use a dot or a dash."""
    return ticker.replace("-", ".")


def coverage(daily: pd.DataFrame, members: pd.DataFrame, start: str = "2016-01-01", end: str = "2025-12-31") -> dict:
    """Share of member-days (from the universe intervals, `ticker` or `price_symbol`, `start`, `end`) on which the
    stock has a daily bar, from `start` (Alpaca history begins in 2016). Days are NYSE sessions found in the data."""
    days = pd.DatetimeIndex(sorted(daily["t"].dt.tz_convert("America/New_York").dt.normalize().dt.tz_localize(None)
                                   .unique()))
    days = days[(days >= start) & (days <= end)]
    have = set(zip(daily["symbol"], daily["t"].dt.tz_convert("America/New_York").dt.normalize().dt.tz_localize(None),
                   strict=True))
    need = got = 0
    syms = members["price_symbol"] if "price_symbol" in members else members["ticker"].map(alpaca_symbol)
    for sym, s, e in zip(syms, members["start"], members["end"], strict=True):  # sym None: no prices
        d = days[(days >= s) & ((days < e) if pd.notna(e) else True)]
        need += len(d)
        got += sum((sym, x) in have for x in d)
    return {"member_days": need, "with_bar": got, "share": got / need if need else float("nan")}
