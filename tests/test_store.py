"""The point-in-time price store: immutable batches, as-of reads that see the data as known then, the overlap
check that refetches a symbol after a dividend, and membership from the index intervals."""
import pandas as pd
import pytest

from ghostdesk.data.store import PriceStore, bars_to_rows, ingest_daily, matrices, membership


def bars(sym, days, close, adj=1.0):
    d = pd.DatetimeIndex(days)
    return pd.DataFrame({"symbol": sym, "t": (d + pd.Timedelta(hours=5)).tz_localize("UTC"), "o": close, "h": close,
                         "l": close, "c": [c * adj for c in close], "v": 100.0, "n": 1.0, "vw": close})


def test_as_of_read_sees_the_old_adjusted_history(tmp_path):
    s = PriceStore(tmp_path)
    s.write_batch("adj", bars_to_rows(bars("A", ["2026-01-02", "2026-01-05"], [10.0, 11.0]),
                                      pd.Timestamp("2026-01-06", tz="UTC")), "b1")
    s.write_batch("adj", bars_to_rows(bars("A", ["2026-01-02", "2026-01-05"], [10.0, 11.0], adj=0.5),
                                      pd.Timestamp("2026-02-01", tz="UTC")), "b2")  # a later 2-for-1 split
    assert s.read("adj", asof="2026-01-10")["c"].tolist() == [10.0, 11.0]
    assert s.read("adj")["c"].tolist() == [5.0, 5.5]
    assert s.read("adj", asof="2026-01-01").empty
    with pytest.raises(FileExistsError):
        s.write_batch("adj", bars_to_rows(bars("A", ["2026-01-02"], [1.0]), pd.Timestamp.now(tz="UTC")), "b1")


def test_daily_ingestion_appends_and_refetches_after_a_dividend(tmp_path):
    s = PriceStore(tmp_path)
    days = pd.bdate_range("2026-01-01", "2026-01-30")
    first = pd.Timestamp("2026-01-30 23:00", tz="UTC")
    for kind in ("raw", "adj"):
        s.write_batch(kind, bars_to_rows(pd.concat([bars("A", days, [10.0] * len(days)),
                                                    bars("B", days, [20.0] * len(days))]), first), "seed")
    calls = []

    def fetch(symbols, start, end, adjustment):
        calls.append((tuple(symbols), start, adjustment))
        d = pd.bdate_range(pd.Timestamp(start).tz_localize(None), "2026-02-03")
        d = d[d >= pd.Timestamp(start[:10])]
        return pd.concat([bars(x, d, [10.0 if x == "A" else 20.0] * len(d),
                               adj=0.98 if (x == "B" and adjustment == "all") else 1.0) for x in symbols])

    out = ingest_daily(s, fetch, ["A", "B"], pd.Timestamp("2026-02-03"), pd.Timestamp("2026-02-04 01:00", tz="UTC"))
    assert out["refetched"] == 1 and calls[-1][0] == ("B",) and calls[-1][1] == "2016-01-01"
    new = s.read("adj")
    assert new["day"].max() == pd.Timestamp("2026-02-03")
    assert new.loc[new["symbol"] == "B", "c"].eq(20.0 * 0.98).all()  # the whole history of B in the new version
    assert s.read("adj", asof=first).loc[lambda x: x["symbol"] == "B", "c"].eq(20.0).all()
    again = ingest_daily(s, fetch, ["A", "B"], pd.Timestamp("2026-02-03"), pd.Timestamp("2026-02-04 02:00", tz="UTC"))
    assert again["new_rows"] == 0  # nothing after the stored last day


def test_membership_and_matrices():
    days = pd.bdate_range("2026-01-01", "2026-01-09")
    iv = pd.DataFrame({"price_symbol": ["A", "B", None], "start": pd.to_datetime(["2026-01-05", "2025-01-01", "2020-01-01"]),
                       "end": pd.to_datetime(["NaT", "2026-01-07", "NaT"])})
    m = membership(iv, days, ["A", "B"])
    assert m["A"].tolist() == [False, False, True, True, True, True, True]
    assert m["B"].tolist() == [True, True, True, True, False, False, False]
    rows = bars_to_rows(bars("A", days[:2], [1.0, 2.0]), pd.Timestamp.now(tz="UTC"))
    mx = matrices(rows, ["c"], days, ["A", "B"])
    assert mx["c"].shape == (7, 2) and mx["c"]["B"].isna().all() and mx["c"]["A"].iloc[1] == 2.0
