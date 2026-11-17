"""When does information become tradeable? The first US market open after it is public.

NYSE regular sessions open at 09:30 New York time. `sessions` is the list of trading dates (from the price data, so
holidays and early closes need no separate table). A filing accepted at 09:29:59 on a trading day is usable at that
day's open; one accepted at 09:30:00 or later waits for the next session.
"""
from __future__ import annotations

import pandas as pd

NY = "America/New_York"


def opens(sessions) -> pd.DatetimeIndex:
    """Session dates -> their 09:30 New York open, in UTC."""
    d = pd.DatetimeIndex(pd.to_datetime(sessions)).normalize().tz_localize(None).unique().sort_values()
    return (d + pd.Timedelta(hours=9, minutes=30)).tz_localize(NY).tz_convert("UTC")


def first_open_after(accepted_utc, sessions) -> pd.Timestamp | None:
    """The first session open strictly after the acceptance time (UTC), or None if there is none in `sessions`."""
    t = pd.Timestamp(accepted_utc)
    t = t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")
    o = opens(sessions)
    i = o.searchsorted(t, side="right")
    return o[i] if i < len(o) else None
