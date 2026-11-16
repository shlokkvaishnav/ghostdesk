"""Point-in-time rule: information is usable at the first market open after it is public."""
import pandas as pd

from ghostdesk.data.calendar import first_open_after, opens

SESSIONS = ["2024-03-08", "2024-03-11", "2024-11-01", "2024-11-04", "2023-11-02", "2023-11-03"]


def test_open_is_0930_new_york_across_daylight_saving():
    o = opens(["2024-03-08", "2024-03-11"])  # US clocks change on 2024-03-10
    assert [t.strftime("%H:%M") for t in o] == ["14:30", "13:30"]


def test_apple_10k_examples():
    # 2024 10-K accepted 06:01 New York time, before the open: usable the same morning
    assert first_open_after("2024-11-01T10:01:36Z", SESSIONS) == pd.Timestamp("2024-11-01 13:30", tz="UTC")
    # 2023 10-K accepted 18:08 New York time, after the close: usable at the next open
    assert first_open_after("2023-11-02T22:08:27Z", SESSIONS) == pd.Timestamp("2023-11-03 13:30", tz="UTC")


def test_the_open_itself_is_too_late_and_weekends_skip():
    assert first_open_after("2024-03-08T14:30:00Z", SESSIONS) == opens(["2024-03-11"])[0]
    assert first_open_after("2024-03-08T14:29:59Z", SESSIONS) == opens(["2024-03-08"])[0]
    assert first_open_after("2030-01-01T00:00:00Z", SESSIONS) is None
