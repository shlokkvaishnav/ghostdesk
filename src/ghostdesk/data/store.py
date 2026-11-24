"""Point-in-time price store: Parquet batches read through DuckDB, with as-of reads (decision D26).

Layout under `root` (default data/store/, not in git):
  bars/<kind>/<batch>.parquet   kind = "adj" (split- and dividend-adjusted) or "raw"; one file per ingestion batch,
                                columns symbol, day, o, h, l, c, v, n, vw, ingested_at (UTC). Files are never
                                changed after they are written.
A read keeps, for each (symbol, day), the row of the newest batch with `ingested_at <= asof`, so `asof` gives the
data as the desk knew it on that date. This matters for the adjusted series: a dividend or split after day d changes
every earlier adjusted price, and the store keeps both versions. A read without `asof` sees the newest version.

Daily ingestion (`ingest_daily`) appends the new sessions. For the adjusted series it also compares the overlap
sessions with the stored values: a change means a new corporate action, and that symbol's whole adjusted history is
fetched again into the new batch. Membership comes from the point-in-time index intervals
(`data/price_symbols.parquet`, `data.sp500_universe`).
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from ghostdesk.paths import DATA_DIR

FIELDS = ["o", "h", "l", "c", "v", "n", "vw"]
NY = "America/New_York"


def session_day(t: pd.Series) -> pd.Series:
    """Bar timestamps (UTC) -> the New York session date (naive)."""
    return pd.to_datetime(t, utc=True).dt.tz_convert(NY).dt.normalize().dt.tz_localize(None)


def bars_to_rows(bars: pd.DataFrame, ingested_at: pd.Timestamp) -> pd.DataFrame:
    """Alpaca bars (symbol, t, o, h, l, c, v, n, vw) -> store rows (symbol, day, fields, ingested_at)."""
    out = bars.assign(day=session_day(bars["t"]))[["symbol", "day", *FIELDS]].copy()
    for f in FIELDS:
        out[f] = out[f].astype(float)
    out["ingested_at"] = pd.Timestamp(ingested_at).tz_convert("UTC") if pd.Timestamp(ingested_at).tzinfo \
        else pd.Timestamp(ingested_at, tz="UTC")
    return out.sort_values(["symbol", "day"]).reset_index(drop=True)


class PriceStore:
    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root else DATA_DIR / "store"

    def _dir(self, kind: str) -> Path:
        if kind not in ("adj", "raw"):
            raise ValueError(kind)
        return self.root / "bars" / kind

    def batches(self, kind: str) -> list[Path]:
        return sorted(self._dir(kind).glob("*.parquet"))

    def write_batch(self, kind: str, rows: pd.DataFrame, name: str) -> Path:
        """Write one immutable batch. Refuses to overwrite: a batch name is used once."""
        d = self._dir(kind)
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"{name}.parquet"
        if p.exists():
            raise FileExistsError(p)
        rows.to_parquet(p, index=False)
        return p

    def read(self, kind: str = "adj", start=None, end=None, asof=None, symbols: list[str] | None = None) -> pd.DataFrame:
        """Long rows (symbol, day, fields), newest version known at `asof` (UTC time or date; None = newest)."""
        files = self.batches(kind)
        if not files:
            return pd.DataFrame(columns=["symbol", "day", *FIELDS])
        where = ["1=1"]
        params: list = [[str(f) for f in files]]
        if asof is not None:
            a = pd.Timestamp(asof)
            a = a.tz_localize("UTC") if a.tzinfo is None else a.tz_convert("UTC")
            where.append("ingested_at <= ?")
            params.append(a.to_pydatetime())
        if start is not None:
            where.append("day >= ?")
            params.append(pd.Timestamp(start).to_pydatetime())
        if end is not None:
            where.append("day <= ?")
            params.append(pd.Timestamp(end).to_pydatetime())
        if symbols is not None:
            where.append("list_contains(?, symbol)")
            params.append(list(symbols))
        q = f"""SELECT symbol, day, {', '.join(FIELDS)} FROM read_parquet(?) WHERE {' AND '.join(where)}
                QUALIFY row_number() OVER (PARTITION BY symbol, day ORDER BY ingested_at DESC) = 1
                ORDER BY symbol, day"""
        with duckdb.connect() as con:
            df = con.execute(q, params).df()
        df["day"] = pd.to_datetime(df["day"])
        return df

    def last_day(self, kind: str = "adj") -> pd.Timestamp | None:
        files = self.batches(kind)
        if not files:
            return None
        with duckdb.connect() as con:
            d = con.execute("SELECT max(day) FROM read_parquet(?)", [[str(f) for f in files]]).fetchone()[0]
        return pd.Timestamp(d)

    def content_hash(self, kind: str = "adj") -> str:
        """SHA-256 over the batch file names and bytes: changes when any batch is added."""
        h = hashlib.sha256()
        for f in self.batches(kind):
            h.update(f.name.encode())
            h.update(f.read_bytes())
        return h.hexdigest()


def matrices(rows: pd.DataFrame, fields=FIELDS, days: pd.DatetimeIndex | None = None,
             symbols: list[str] | None = None) -> dict[str, pd.DataFrame]:
    """Long rows -> one (session x symbol) float matrix per field, on a shared index (NaN where no bar)."""
    days = days if days is not None else pd.DatetimeIndex(sorted(rows["day"].unique()))
    symbols = symbols if symbols is not None else sorted(rows["symbol"].unique())
    out = {}
    for f in fields:
        m = rows.pivot(index="day", columns="symbol", values=f)
        out[f] = m.reindex(index=days, columns=symbols).astype(float)
    return out


def membership(intervals: pd.DataFrame, days: pd.DatetimeIndex, symbols: list[str]) -> pd.DataFrame:
    """(session x symbol) bool: the symbol's company is in the S&P 500 on that session. `intervals` has
    price_symbol, start, end (end NaT = still a member; a member while start <= day < end)."""
    out = pd.DataFrame(False, index=days, columns=symbols)
    d = days.to_numpy()
    for sym, s, e in zip(intervals["price_symbol"], intervals["start"], intervals["end"], strict=True):
        if sym is None or (isinstance(sym, float) and np.isnan(sym)) or sym not in out.columns:
            continue
        m = (d >= np.datetime64(s)) & ((d < np.datetime64(e)) if pd.notna(e) else True)
        out.loc[m, sym] = True
    return out


def ingest_daily(store: PriceStore, fetch, symbols: list[str], today: pd.Timestamp, now: pd.Timestamp,
                 overlap_days: int = 10, tol: float = 1e-6, first_day: str = "2016-01-01") -> dict:
    """Append the sessions after the stored last day up to `today` (both kinds), as batch `<YYYYMMDDHHMM>`.
    `fetch(symbols, start, end, adjustment)` returns Alpaca bars. The adjusted fetch starts `overlap_days` before the
    last stored day; a symbol whose overlap closes changed (a new dividend or split) is fetched again from the start
    of its history (`first_day`; the live store starts about 600 days back). Returns counts for the health record.
A symbol new to the store (an index addition) gets its history from `add_symbols`."""
    name = f"{pd.Timestamp(now).tz_convert('UTC'):%Y%m%d%H%M}"
    last = store.last_day("raw")
    start = (last + pd.Timedelta(days=1)) if last is not None else pd.Timestamp(first_day)
    if start > today:
        return {"new_rows": 0, "refetched": 0, "batch": None}
    # A bare end date is refused by the free plan as "recent SIP data"; an explicit time at least 16 minutes old is not.
    end = min(pd.Timestamp(today).tz_localize("UTC") + pd.Timedelta(hours=23, minutes=59),
              pd.Timestamp(now).tz_convert("UTC") - pd.Timedelta(minutes=16)).isoformat().replace("+00:00", "Z")
    raw = fetch(symbols, f"{start:%Y-%m-%d}", end, "raw")
    ov_start = (last - pd.Timedelta(days=overlap_days)) if last is not None else start
    adj = fetch(symbols, f"{ov_start:%Y-%m-%d}", end, "all")
    new_adj = bars_to_rows(adj, now) if len(adj) else pd.DataFrame(columns=["symbol", "day", *FIELDS, "ingested_at"])
    refetch: list[str] = []
    if last is not None and len(new_adj):
        old = store.read("adj", start=ov_start, end=last, symbols=sorted(set(new_adj["symbol"])))
        m = new_adj.merge(old[["symbol", "day", "c"]], on=["symbol", "day"], suffixes=("", "_old"))
        changed = m[(m["c"] / m["c_old"] - 1).abs() > tol]
        refetch = sorted(set(changed["symbol"]))
    if refetch:
        full = fetch(refetch, first_day, end, "all")
        new_adj = pd.concat([new_adj[~new_adj["symbol"].isin(refetch)], bars_to_rows(full, now)], ignore_index=True)
    if last is not None:  # unchanged overlap rows add nothing; keep only new sessions and refetched symbols
        new_adj = new_adj[(new_adj["day"] > last) | new_adj["symbol"].isin(refetch)]
    if len(raw):
        store.write_batch("raw", bars_to_rows(raw, now), name)
    if len(new_adj):
        store.write_batch("adj", new_adj.reset_index(drop=True), name)
    return {"new_rows": len(raw), "refetched": len(refetch), "batch": name}


def add_symbols(store: PriceStore, fetch, symbols: list[str], first_day: str, end: str, now: pd.Timestamp) -> int:
    """Fetch the whole history (raw and adjusted) of symbols that the store does not have yet, as one batch."""
    have = set(store.read("raw", start=pd.Timestamp(end) - pd.Timedelta(days=10), end=end)["symbol"]) \
        if store.batches("raw") else set()
    new = sorted(set(symbols) - have)
    if not new or not store.batches("raw"):
        return 0
    name = f"add-{pd.Timestamp(now).tz_convert('UTC'):%Y%m%d%H%M}"
    for kind, adj in (("raw", "raw"), ("adj", "all")):
        b = fetch(new, first_day, end, adj)
        if len(b):
            store.write_batch(kind, bars_to_rows(b, now), name)
    return len(new)
