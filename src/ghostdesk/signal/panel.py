"""The stock-month panel: one row per (formation month-end, company) with the signal that was tradeable then, the
next month's return, and the controls. Every rule here protects against look-ahead or survivorship bias.

- **Formation** is at the close (16:00 New York) of the last session of each month.
- **Who is in it:** companies in the index at that session (`start <= day < end`, `valid_from <= day`) with a price
  symbol. One row per CIK: for share classes (GOOG, GOOGL) the class with the larger dollar volume is kept.
- **Signal:** the latest paired report whose tradeable time (first open after SEC acceptance) is at or before the
  formation close and less than `window_days` (120) before it. Older signals are not used. 120 days covers the
  usual gap between a Q3 10-Q and the next 10-K (about 100-115 days); `signal_age` (days) is kept.
- **Forward return:** the next month (sessions after the formation day up to the next formation day), from the
  clean daily log returns. A day without a bar or with a flagged vendor error counts as 0 (as cash): a stock that
  leaves the market mid-month earns nothing after its last bar (its delisting return is not known, a stated limit).
  A stock that leaves the index mid-month is held to the month-end, as a real portfolio would hold it.
- **Momentum** (12-1 months): log return from 252 to 21 sessions before formation, only if the stock was in its
  current interval for the whole 252 sessions (so a first-day jump between two companies, data-quality P5, never
  enters it).
- **Size:** log of the 63-session mean dollar volume (raw close x volume); log total assets from the latest
  first-reported XBRL value accepted before formation.
- **Spread:** Corwin-Schultz monthly estimate of the formation month (a cost input, not a control).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..data.calendar import NY, opens
from ..data.spread import corwin_schultz

MEASURES = [f"sim_{p}_{m}" for p in ("full", "risk", "mdna") for m in ("cosine", "jaccard", "edit")]


def month_ends(sessions: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """The last session of each month."""
    s = pd.Series(sessions, index=sessions)
    return pd.DatetimeIndex(s.groupby(s.dt.to_period("M")).max().to_numpy())


def tradeable_times(accepted_utc: pd.Series, sessions: pd.DatetimeIndex) -> pd.Series:
    """First session open strictly after each acceptance time (UTC); NaT when after the last session."""
    o = opens(sessions)
    t = pd.to_datetime(accepted_utc, utc=True)
    i = o.searchsorted(t.to_numpy(), side="right")
    out = pd.Series(pd.NaT, index=accepted_utc.index, dtype="datetime64[ns, UTC]")
    ok = i < len(o)
    out[ok] = o[i[ok]]
    return out


def close_utc(days: pd.DatetimeIndex) -> pd.DatetimeIndex:
    return (pd.DatetimeIndex(days) + pd.Timedelta(hours=16)).tz_localize(NY).tz_convert("UTC")


def build_panel(features: pd.DataFrame, members: pd.DataFrame, returns: pd.DataFrame, raw: pd.DataFrame,
                sic: dict[int, str], start: str, end: str, window_days: int = 120) -> pd.DataFrame:
    """features: data/features.parquet; members: ticker, start, end, cik, price_symbol, valid_from; returns:
    data/returns_daily.parquet; raw: raw daily bars (symbol, t, h, l, c, v); sic: CIK -> SIC code.
    Formation months from `start` to `end` (the last month needs one more month of returns)."""
    sessions = pd.DatetimeIndex(sorted(returns["day"].unique()))
    all_ends = month_ends(sessions)
    ends = all_ends[(all_ends >= pd.Timestamp(start)) & (all_ends <= pd.Timestamp(end))]
    pos = pd.Series(np.arange(len(sessions)), index=sessions)

    # daily matrices (session x symbol)
    r = returns.pivot(index="day", columns="symbol", values="ret").reindex(sessions)
    have = returns.pivot(index="day", columns="symbol", values="close").reindex(sessions).notna()
    cum = r.fillna(0.0).cumsum()
    nbar = have.cumsum()
    rb = raw.assign(day=raw["t"].dt.tz_convert(NY).dt.normalize().dt.tz_localize(None))
    dv = rb.assign(dv=rb["c"] * rb["v"]).pivot(index="day", columns="symbol", values="dv").reindex(sessions)
    dv63 = dv.rolling(63, min_periods=40).mean()

    # signals with their tradeable time
    f = features[features["error"] == ""].copy()
    f["tradeable"] = tradeable_times(f["accepted_utc"], sessions)
    f = f.dropna(subset=["tradeable"]).sort_values("tradeable")
    assets = (f.dropna(subset=["xbrl_Assets"]).sort_values("accepted_utc")
              .drop_duplicates(["cik", "report_date"], keep="first")[["cik", "accepted_utc", "xbrl_Assets"]]
              .sort_values("accepted_utc"))

    # Corwin-Schultz spread per symbol and month
    rb = rb.sort_values(["symbol", "day"])
    rb["cs"] = pd.concat([corwin_schultz(g["h"], g["l"], g["c"], floor=False).set_axis(g.index)
                          for _, g in rb.groupby("symbol")])
    spread = rb.groupby(["symbol", rb["day"].dt.to_period("M")])["cs"].mean().clip(lower=0)

    rows = []
    for d in ends:
        later = all_ends[all_ends > d]
        if len(later) == 0:  # no next month of returns
            break
        d_next = later[0]
        m = members[(members["start"] <= d) & (members["end"].isna() | (d < members["end"]))
                    & (members["valid_from"].fillna(members["start"]) <= d) & members["price_symbol"].notna()
                    & members["cik"].notna()].copy()
        m = m[m["price_symbol"].isin(r.columns)]
        if m.empty:
            continue
        m["logdv"] = np.log(dv63.loc[d].reindex(m["price_symbol"]).to_numpy())
        m = m.sort_values("logdv", ascending=False).drop_duplicates("cik")
        i0, i1 = pos[d], pos[d_next]
        sym = m["price_symbol"]
        m["fwd_logret"] = (cum.iloc[i1] - cum.iloc[i0]).reindex(sym).to_numpy()
        m["fwd_days"] = (nbar.iloc[i1] - nbar.iloc[i0]).reindex(sym).to_numpy()
        m["fwd_ret"] = np.where(m["fwd_days"] > 0, np.expm1(m["fwd_logret"]), np.nan)
        if i0 >= 252:
            a, b = sessions[i0 - 252], sessions[i0 - 21]
            mom = (cum.loc[b] - cum.loc[a]).reindex(sym).to_numpy()
            m["mom"] = np.where(m["start"] <= a, mom, np.nan)
        else:
            m["mom"] = np.nan
        t_close = close_utc(pd.DatetimeIndex([d]))[0]
        last = f[(f["tradeable"] <= t_close) & (f["tradeable"] > t_close - pd.Timedelta(days=window_days))]
        last = last.drop_duplicates("cik", keep="last")
        m = m.merge(last[["cik", "accession", "form", "tradeable", *MEASURES]], on="cik", how="left")
        a_ = assets[assets["accepted_utc"] < t_close].drop_duplicates("cik", keep="last")
        m["log_assets"] = np.log(m["cik"].map(a_.set_index("cik")["xbrl_Assets"]).astype(float))
        m["sic"] = m["cik"].map(lambda c: sic.get(int(c), ""))
        per = d.to_period("M")
        m["spread"] = [spread.get((s, per), np.nan) for s in m["price_symbol"]]
        m["signal_age"] = (t_close - m["tradeable"]).dt.total_seconds() / 86400
        m["month"] = d
        rows.append(m)
    cols = ["month", "cik", "ticker", "price_symbol", "accession", "form", "tradeable", *MEASURES, "fwd_ret",
            "fwd_days", "mom", "logdv", "log_assets", "sic", "spread", "signal_age"]
    return pd.concat(rows, ignore_index=True)[cols]
