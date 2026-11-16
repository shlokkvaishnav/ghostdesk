"""The stock-month panel: tradeable time, signal window, membership, flagged days, momentum age, share classes."""
import numpy as np
import pandas as pd
import pytest

from ghostdesk.signal.panel import MEASURES, build_panel, month_ends

DAYS = pd.bdate_range("2019-01-01", "2020-04-30")


def daily(sym, ret=0.001, flag_day=None):
    r = pd.Series(ret, index=DAYS)
    r.iloc[0] = np.nan
    flag = pd.Series(False, index=DAYS)
    if flag_day is not None:
        r[pd.Timestamp(flag_day)], flag[pd.Timestamp(flag_day)] = np.nan, True
    close = 100 * np.exp(r.fillna(0).cumsum())
    return pd.DataFrame({"symbol": sym, "day": DAYS, "ret": r.to_numpy(), "flag": flag.to_numpy(),
                         "close": close.to_numpy(), "close_adj": close.to_numpy()})


def raw_bars(sym, vol=1000):
    c = 100 * np.exp(np.cumsum(np.full(len(DAYS), 0.001)))
    return pd.DataFrame({"symbol": sym, "t": (DAYS + pd.Timedelta(hours=5)).tz_localize("UTC"), "h": c * 1.01,
                         "l": c * 0.99, "c": c, "v": vol})


def feature(cik, accepted, sim):
    row = {"cik": cik, "accession": f"{cik}-{accepted}", "prev_accession": "p", "form": "10-Q", "error": "",
           "accepted_utc": pd.Timestamp(accepted, tz="UTC"), "report_date": pd.Timestamp("2019-12-31"),
           "xbrl_Assets": 1e9}
    return row | {m: sim for m in MEASURES}


@pytest.fixture(scope="module")
def panel():
    members = pd.DataFrame({
        "ticker": ["AAA", "BBB", "GOOG", "GOOGL", "NEW", "OUT"],
        "start": pd.to_datetime(["2010-01-01", "2010-01-01", "2010-01-01", "2010-01-01", "2019-11-01", "2010-01-01"]),
        "end": pd.to_datetime([None, None, None, None, None, "2019-12-15"]),
        "cik": pd.array([1, 2, 3, 3, 4, 5], dtype="Int64"),
        "price_symbol": ["AAA", "BBB", "GOOG", "GOOGL", "NEW", "OUT"],
        "valid_from": pd.NaT})
    returns = pd.concat([daily("AAA"), daily("BBB", flag_day="2020-01-15"), daily("GOOG"), daily("GOOGL"),
                         daily("NEW"), daily("OUT")])
    raw = pd.concat([raw_bars(s, v) for s, v in
                     [("AAA", 1000), ("BBB", 0), ("GOOG", 10), ("GOOGL", 5000), ("NEW", 1000), ("OUT", 1000)]])
    feats = pd.DataFrame([
        feature(1, "2019-12-31T21:30:00", 0.9),  # 16:30 New York on the month-end: after the close -> not for Dec
        feature(1, "2019-12-20T12:00:00", 0.5),  # tradeable 2019-12-20 09:30 -> the Dec signal
        feature(2, "2019-08-01T12:00:00", 0.7),  # older than 120 days at the end of Dec -> not used
        feature(3, "2019-12-02T12:00:00", 0.6),
    ])
    return build_panel(feats, members, returns, raw, {1: "3571", 2: "6022", 3: "7372"}, "2019-12-01", "2020-02-28")


def test_tradeable_time_and_window(panel):
    dec = panel[panel["month"] == pd.Timestamp("2019-12-31")].set_index("ticker")
    assert dec.loc["AAA", "sim_full_edit"] == 0.5  # the report accepted after the close waits for January
    assert 11 < dec.loc["AAA", "signal_age"] < 12
    assert np.isnan(dec.loc["BBB", "sim_full_edit"])  # too old
    jan = panel[panel["month"] == pd.Timestamp("2020-01-31")].set_index("ticker")
    assert jan.loc["AAA", "sim_full_edit"] == 0.9


def test_membership_and_share_classes(panel):
    dec = panel[panel["month"] == pd.Timestamp("2019-12-31")]
    assert "OUT" not in set(dec["ticker"])  # left the index on 2019-12-15
    assert dec[dec["cik"] == 3]["ticker"].tolist() == ["GOOGL"]  # the larger dollar volume class


def test_flagged_day_counts_as_zero_and_momentum_age(panel):
    dec = panel[panel["month"] == pd.Timestamp("2019-12-31")].set_index("ticker")
    n = ((DAYS > pd.Timestamp("2019-12-31")) & (DAYS <= pd.Timestamp("2020-01-31"))).sum()
    assert abs(dec.loc["AAA", "fwd_ret"] - np.expm1(0.001 * n)) < 1e-12
    assert abs(dec.loc["BBB", "fwd_ret"] - np.expm1(0.001 * (n - 1))) < 1e-12  # 2020-01-15 flagged -> 0
    assert np.isnan(dec.loc["NEW", "mom"]) and not np.isnan(dec.loc["AAA", "mom"])
    assert np.isnan(dec.loc["BBB", "logdv"])  # zero volume: NaN, not -inf


def test_month_ends():
    assert month_ends(DAYS)[:2].tolist() == [pd.Timestamp("2019-01-31"), pd.Timestamp("2019-02-28")]
