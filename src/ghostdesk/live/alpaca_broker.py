"""Alpaca paper-trading API: clock, calendar, account, positions, orders, portfolio history.

Only the paper endpoint is allowed (`PAPER`); the class refuses any other base URL, so a live (real money) account
cannot be used by mistake. Keys come from `data.alpaca_client.keys` and are sent only as request headers.
`session` and `sleep` are injectable so tests never touch the network.
"""
from __future__ import annotations

import time
from urllib.parse import urlparse

import pandas as pd
import requests

PAPER = "https://paper-api.alpaca.markets/v2"
SNAPSHOTS = "https://data.alpaca.markets/v2/stocks/snapshots"


class Broker:
    def __init__(self, headers: dict | None = None, base: str = PAPER, session=None, sleep=time.sleep,
                 clock=time.monotonic, per_minute: int = 170):
        if urlparse(base).hostname != "paper-api.alpaca.markets":
            raise ValueError("only the Alpaca paper endpoint is allowed")
        self.base, self._headers = base, headers
        self.session = session or requests.Session()
        self._sleep, self._clock, self._last = sleep, clock, -1e9
        self.gap = 60.0 / per_minute  # client-side limit under Alpaca's 200 requests per minute

    def _h(self) -> dict:
        if self._headers is None:
            from ghostdesk.data.alpaca_client import keys
            self._headers = keys()
        return self._headers

    def _pace(self) -> None:
        wait = self.gap - (self._clock() - self._last)
        if wait > 0:
            self._sleep(wait)
        self._last = self._clock()

    def _req(self, method: str, path: str, **kw):
        """Paced request. 429 and 5xx are retried for about 2 minutes; other 4xx raise at once."""
        for attempt in range(8):
            self._pace()
            r = self.session.request(method, self.base + path, headers=self._h(), timeout=30, **kw)
            if r.status_code == 429 or r.status_code >= 500:
                self._sleep(min(30.0, 5.0 * (attempt + 1)))
                continue
            if r.status_code >= 400:
                raise BrokerError(r.status_code, _message(r))
            return r.json() if r.content else None
        raise BrokerError(r.status_code, _message(r))

    def clock(self) -> dict:
        """`is_open`, `next_open`, `next_close`, `timestamp` (ISO strings with offset)."""
        return self._req("GET", "/clock")

    def sessions(self, start: str, end: str) -> pd.DataFrame:
        """Trading sessions: `date` (naive), `open_utc`, `close_utc` (early closes included)."""
        cal = self._req("GET", "/calendar", params={"start": start, "end": end})
        df = pd.DataFrame(cal, columns=["date", "open", "close"])
        d = pd.to_datetime(df["date"])
        ny = "America/New_York"
        return pd.DataFrame({
            "date": d,
            "open_utc": (d + pd.to_timedelta(df["open"] + ":00")).dt.tz_localize(ny).dt.tz_convert("UTC"),
            "close_utc": (d + pd.to_timedelta(df["close"] + ":00")).dt.tz_localize(ny).dt.tz_convert("UTC")})

    def account(self) -> dict:
        return self._req("GET", "/account")

    def positions(self) -> dict[str, float]:
        """Symbol -> signed share count (negative = short; fractional for fractional longs)."""
        return {p["symbol"]: float(p["qty"]) for p in self._req("GET", "/positions")}

    def position_rows(self) -> list[dict]:
        return self._req("GET", "/positions")

    def orders(self, after: str | None = None, status: str = "all", limit: int = 0) -> list[dict]:
        """Orders (newest first) submitted after `after` (ISO time): all pages, or only the first `limit`."""
        out: list[dict] = []
        until = None
        while True:
            params = {"status": status, "limit": limit or 500, "direction": "desc"}
            if after:
                params["after"] = after
            if until:
                params["until"] = until
            page = self._req("GET", "/orders", params=params)
            out += page
            if limit or len(page) < 500:
                return out
            until = page[-1]["submitted_at"]

    def submit(self, symbol: str, qty: float, side: str, client_order_id: str) -> dict:
        """A day market order; `qty` in whole shares or with up to 4 decimals (fractional, long side only)."""
        if qty <= 0 or side not in ("buy", "sell"):
            raise ValueError(f"bad order {symbol} {side} {qty}")
        q = f"{qty:.4f}".rstrip("0").rstrip(".")
        return self._req("POST", "/orders", json={"symbol": symbol, "qty": q, "side": side,
                                                  "type": "market", "time_in_force": "day",
                                                  "client_order_id": client_order_id})

    def close_all(self) -> list:
        """Cancel open orders and close every position at market (Alpaca DELETE /positions)."""
        return self._req("DELETE", "/positions", params={"cancel_orders": "true"}) or []

    def order(self, order_id: str) -> dict:
        return self._req("GET", f"/orders/{order_id}")

    def asset(self, symbol: str) -> dict:
        return self._req("GET", f"/assets/{symbol}")

    def latest_prices(self, symbols: list[str]) -> dict[str, float]:
        """Last trade price per symbol (IEX snapshots: the free plan has no recent SIP data), in batches of 200.
        Used only to size orders."""
        out: dict[str, float] = {}
        for i in range(0, len(symbols), 200):
            self._pace()
            r = self.session.get(SNAPSHOTS, params={"symbols": ",".join(symbols[i:i + 200]), "feed": "iex"},
                                 headers=self._h(), timeout=30)
            if r.status_code >= 400:
                raise BrokerError(r.status_code, _message(r))
            for s, snap in (r.json() or {}).items():
                p = ((snap or {}).get("latestTrade") or {}).get("p")
                if p:
                    out[s] = float(p)
        return out

    def history(self) -> pd.DataFrame:
        """Daily account equity over the last year: `day`, `equity`, `profit_loss`; days before the account had
        money (equity 0) are dropped. A `start` parameter returned one wrong row on the paper API (2026-11-17)."""
        h = self._req("GET", "/account/portfolio/history", params={"period": "1A", "timeframe": "1D"})
        df = pd.DataFrame({"t": h.get("timestamp") or [], "equity": h.get("equity") or [],
                           "profit_loss": h.get("profit_loss") or []})
        df["day"] = pd.to_datetime(df["t"], unit="s", utc=True).dt.tz_convert("America/New_York").dt.normalize()
        df["day"] = df["day"].dt.tz_localize(None)
        df = df.dropna(subset=["equity"])
        return df[df["equity"] > 0][["day", "equity", "profit_loss"]]


class BrokerError(RuntimeError):
    def __init__(self, status: int, message: str):
        super().__init__(f"Alpaca {status}: {message}")
        self.status, self.message = status, message

    @property
    def permanent(self) -> bool:
        """A rejection of the request itself (4xx other than 429): the same order would fail again."""
        return 400 <= self.status < 500 and self.status != 429


def _message(r) -> str:
    try:
        return str(r.json().get("message", ""))[:200]
    except ValueError:
        return r.text[:200]
