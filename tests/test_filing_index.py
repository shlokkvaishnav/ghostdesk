"""Like-with-like pairing of reports, on a small made-up index."""
import pandas as pd

from ghostdesk.filings.filing_index import frame, no_future_pairs, pair_previous

R = [  # cik, accession, form, base, amendment, filed, period, accepted (UTC), doc
    (1, "k21", "10-K", "10-K", False, "2021-10-29", "2021-09-25", "2021-10-28T22:05:00Z", ""),
    (1, "k22", "10-K", "10-K", False, "2022-10-28", "2022-09-24", "2022-10-27T22:01:00Z", ""),
    (1, "k22a", "10-K/A", "10-K", True, "2023-01-10", "2022-09-24", "2023-01-10T12:00:00Z", ""),
    (1, "q2_21", "10-Q", "10-Q", False, "2021-07-30", "2021-06-26", "2021-07-29T20:00:00Z", ""),
    (1, "q3_21", "10-Q", "10-Q", False, "2021-10-29", "2021-09-25", "2021-10-28T20:00:00Z", ""),
    (1, "q2_22", "10-Q", "10-Q", False, "2022-07-29", "2022-06-25", "2022-07-28T20:00:00Z", ""),
    (2, "x20", "10-K", "10-K", False, "2020-03-01", "2019-12-31", "2020-03-01T12:00:00Z", ""),
    (2, "x21", "10-K", "10-K", False, "2021-09-01", "2021-06-30", "2021-09-01T12:00:00Z", ""),  # new fiscal year
]


def test_like_with_like_pairs():
    p = pair_previous(frame(R)).set_index("accession")["prev_accession"]
    assert p["k22"] == "k21"
    assert p["q2_22"] == "q2_21"  # Q2 with Q2, not with the latest 10-Q (Q3) or a 10-K
    assert pd.isna(p["k22a"])  # amendments are never paired
    assert pd.isna(p["x21"])  # a fiscal-year change gives no pair, not a wrong one
    assert pd.isna(p["k21"]) and pd.isna(p["q3_21"])


def test_pairs_use_only_earlier_reports():
    idx = pair_previous(frame(R))
    assert no_future_pairs(idx)
    idx.loc[idx["accession"] == "k21", "accepted_utc"] = pd.Timestamp("2030-01-01", tz="UTC")
    assert not no_future_pairs(idx)
