"""Point-in-time stock characteristics for each row of the stock-month panel (`text_signal/stock_month_panel.py`).

Every value uses only data known at the formation close (16:00 New York on the last session of the month):
- **Price** characteristics use daily bars up to and including the formation day. A window characteristic needs the
  stock to be in its current index interval for the whole window (the same rule as `mom` in the panel), so a ticker
  that was reused by another company never mixes two companies.
- **Accounting** characteristics use the latest report accepted by the SEC strictly before the formation close and
  not more than `MAX_REPORT_AGE` days before it, with its first-reported XBRL values. A 10-Q flow (3 months) is
  multiplied by 4 to compare with a 10-K flow (12 months). Growth compares a report with the report of the same kind
  about one year earlier (365 +- 20 days), which was public earlier.
- **Size and text** come from the panel: `logdv` (63-session dollar volume) and `composite` (the signal study's
  text-change rank within form).

`tests/test_return_models.py` checks the rule by changing every input after the formation time and asserting that no
characteristic changes. Market value (and so book-to-market) is not available: the data has no share counts.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ghostdesk.data.market_calendar import NY
from ghostdesk.text_signal.stock_month_panel import close_utc

# name -> lookback in sessions (the window must lie inside the stock's current index interval)
PRICE = {"mom_12_1": 252, "mom_6_1": 126, "rev_1": 21, "vol_21": 21, "vol_63": 63, "beta_252": 252,
         "maxret_21": 21, "amihud_63": 63, "high_52w": 252, "log_price": 0}
ACCOUNTING = ["log_assets", "roa", "turnover", "equity_assets", "sales_growth", "asset_growth"]
TEXT = ["composite"]
ALL = [*PRICE, "logdv", *ACCOUNTING, *TEXT]  # logdv: from the panel (63-session dollar volume)
MAX_REPORT_AGE = 200  # days


def _mat(df: pd.DataFrame, value: str, sessions: pd.DatetimeIndex) -> pd.DataFrame:
    return df.pivot(index="day", columns="symbol", values=value).reindex(sessions)


def price_matrices(returns: pd.DataFrame, raw: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Session x symbol matrices of each price characteristic, as known at each session's close."""
    sessions = pd.DatetimeIndex(sorted(returns["day"].unique()))
    r = _mat(returns.assign(ret=returns["ret"].where(~returns["flag"])), "ret", sessions)  # daily log returns
    adj = _mat(returns, "close_adj", sessions)
    rb = raw.assign(day=raw["t"].dt.tz_convert(NY).dt.normalize().dt.tz_localize(None))
    close = _mat(rb, "c", sessions).reindex(columns=r.columns)
    dv = _mat(rb.assign(dv=rb["c"] * rb["v"]), "dv", sessions).reindex(columns=r.columns)
    cum = r.fillna(0.0).cumsum()
    mkt = r.mean(axis=1)
    simple = np.expm1(r)
    out = {
        "mom_12_1": cum.shift(21) - cum.shift(252),
        "mom_6_1": cum.shift(21) - cum.shift(126),
        "rev_1": cum - cum.shift(21),
        "vol_21": r.rolling(21, min_periods=15).std(),
        "vol_63": r.rolling(63, min_periods=40).std(),
        "beta_252": r.rolling(252, min_periods=150).cov(mkt).div(mkt.rolling(252, min_periods=150).var(), axis=0),
        "maxret_21": simple.rolling(21, min_periods=15).max(),
        "amihud_63": np.log((simple.abs() / dv.where(dv > 0)).rolling(63, min_periods=40).mean() * 1e9),
        "high_52w": adj / adj.rolling(252, min_periods=150).max(),
        "log_price": np.log(close.where(close > 0)),
    }
    return out


def report_values(features: pd.DataFrame) -> pd.DataFrame:
    """One row per report with its first-reported values and the accounting characteristics it gives."""
    f = features[features["error"].fillna("") == ""].copy()
    f = (f.sort_values("accepted_utc").drop_duplicates(["cik", "report_date"], keep="first")
         .sort_values(["cik", "report_date"]).reset_index(drop=True))
    f["report_date"] = pd.to_datetime(f["report_date"])
    k = np.where(f["form"].str.startswith("10-K"), 1.0, 4.0)
    a = f["xbrl_Assets"].where(f["xbrl_Assets"] > 0)
    f["log_assets"] = np.log(a)
    f["roa"] = f["xbrl_NetIncomeLoss"] * k / a
    f["turnover"] = f["xbrl_Revenues"] * k / a
    f["equity_assets"] = f["xbrl_StockholdersEquity"] / a
    f["kind"] = np.where(f["form"].str.startswith("10-K"), "K", "Q")
    # the same kind of report about one year earlier
    prev = f[["cik", "kind", "report_date", "xbrl_Revenues", "xbrl_Assets"]].rename(
        columns={"report_date": "prev_date", "xbrl_Revenues": "rev_prev", "xbrl_Assets": "assets_prev"})
    prev["target"] = prev["prev_date"] + pd.Timedelta(days=365)
    g = pd.merge_asof(f.sort_values("report_date"), prev.sort_values("target"), left_on="report_date",
                      right_on="target", by=["cik", "kind"], direction="nearest", tolerance=pd.Timedelta(days=20))
    pos = lambda x: x.where(x > 0)
    g["sales_growth"] = np.log(pos(g["xbrl_Revenues"]) / pos(g["rev_prev"]))
    g["asset_growth"] = np.log(pos(g["xbrl_Assets"]) / pos(g["assets_prev"]))
    return g[["cik", "accepted_utc", *ACCOUNTING]]


def add_characteristics(panel: pd.DataFrame, members: pd.DataFrame, returns: pd.DataFrame, raw: pd.DataFrame,
                        features: pd.DataFrame) -> pd.DataFrame:
    """panel: month, cik, ticker, price_symbol, composite (from `evaluation.portfolio_stats.add_signals`); members: ticker, start,
    end; returns, raw, features: as for `text_signal.stock_month_panel.build_panel`. Returns the panel with the columns of `ALL`
    (raw values; `rank_features` makes the model inputs)."""
    p = panel.drop(columns=[c for c in [*PRICE, *ACCOUNTING] if c in panel.columns]).copy()
    sessions = pd.DatetimeIndex(sorted(returns["day"].unique()))
    pos = pd.Series(np.arange(len(sessions)), index=sessions)
    mats = price_matrices(returns, raw)
    # the start of each row's current index interval, as a session position
    iv = p[["month", "ticker"]].merge(members[["ticker", "start", "end"]], on="ticker", how="left")
    iv = iv[(iv["start"] <= iv["month"]) & (iv["end"].isna() | (iv["month"] < iv["end"]))]
    start = iv.drop_duplicates(["month", "ticker"]).set_index(["month", "ticker"])["start"]
    s = start.reindex(pd.MultiIndex.from_frame(p[["month", "ticker"]])).to_numpy()
    start_pos = sessions.searchsorted(pd.DatetimeIndex(s))
    i0 = pos.reindex(p["month"]).to_numpy()
    for name, look in PRICE.items():
        m = mats[name]
        col = m.columns.get_indexer(p["price_symbol"])
        v = np.where(col >= 0, m.to_numpy()[i0, np.maximum(col, 0)], np.nan)
        ok = pd.notna(s) & (i0 - look >= start_pos)
        p[name] = np.where(ok, v, np.nan)
    # accounting: the latest report accepted strictly before the formation close
    rv = report_values(features)
    rv = rv.assign(cik=rv["cik"].astype("int64"),
                   accepted_utc=pd.to_datetime(rv["accepted_utc"], utc=True).astype("datetime64[ns, UTC]"))
    rv = rv.sort_values("accepted_utc")
    p["_t"] = close_utc(pd.DatetimeIndex(p["month"])).astype("datetime64[ns, UTC]")
    p["_i"] = np.arange(len(p))
    left = p[["_i", "cik", "_t"]].assign(cik=p["cik"].astype("int64")).sort_values("_t")
    j = pd.merge_asof(left, rv.rename(columns={"accepted_utc": "_acc"}),
                      left_on="_t", right_on="_acc", by="cik", allow_exact_matches=False, direction="backward")
    j = j.set_index("_i").reindex(p["_i"])
    fresh = (j["_t"] - j["_acc"]) <= pd.Timedelta(days=MAX_REPORT_AGE)
    for c in ACCOUNTING:
        p[c] = j[c].where(fresh).to_numpy()
    return p.drop(columns=["_t", "_i"])


def rank_features(panel: pd.DataFrame, cols: list[str] | None = None) -> pd.DataFrame:
    """Each characteristic as its cross-sectional rank in the month, mapped to [-0.5, 0.5]; a missing value is 0
    (the middle), as in Gu, Kelly and Xiu (2020). Ranks use only the month's own stocks."""
    cols = cols or ALL
    out = panel.copy()
    for c in cols:
        r = panel.groupby("month")[c].rank(pct=True)
        n = panel.groupby("month")[c].transform("count")
        out[c] = ((r * n - 0.5) / n - 0.5).fillna(0.0)
    return out
