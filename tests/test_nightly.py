"""The nightly run: the OPG window gate (both time zones), the append-only ledger, scoring by the owner's rule, and
the fault-injection harness (no violations; a deliberate bug is caught)."""
import numpy as np
import pandas as pd
import pytest

from ghostdesk.live.ledger import Ledger, LedgerError, model_summary, score
from ghostdesk.live.nightly import decide, window
from ghostdesk.sim.fault_injection import run_many, sessions_between


def ts(s):
    return pd.Timestamp(s, tz="UTC")


def test_window_follows_new_york_time_in_winter_and_summer():
    for start, utc_open in (("2026-12-07", "00:03"), ("2026-07-06", "23:03")):  # EST: 19:00 = 00:00 UTC
        cal = sessions_between(start, 3)
        first, last = window(cal, cal["date"].iloc[0])
        assert f"{first:%H:%M}" == utc_open
        assert last == (cal["date"].iloc[1] + pd.Timedelta(hours=9, minutes=25)).tz_localize(
            "America/New_York").tz_convert("UTC")


def test_decide_ledger_after_close_orders_only_in_window():
    cal = sessions_between("2026-12-07", 3)  # Mon Tue Wed, EST
    assert not decide(cal, ts("2026-12-07 18:00"), False).predict  # the session is open
    d = decide(cal, ts("2026-12-07 21:40"), False)
    assert d.predict and not d.trade and d.ok  # after the close, before 19:00 ET: ledger only
    d = decide(cal, ts("2026-12-08 01:30"), False)
    assert d.trade and d.session == pd.Timestamp("2026-12-07")
    assert decide(cal, ts("2026-12-08 11:00"), False).trade  # 06:00 ET: still inside
    d = decide(cal, ts("2026-12-08 14:29"), False)  # 09:29 ET: window closed, the session is not over
    assert not d.trade and not d.ok and "missed" in d.reason
    assert not decide(cal, ts("2026-12-08 01:30"), True).predict  # done: nothing


def test_ledger_is_append_only_and_verifiable(tmp_path):
    led = Ledger(tmp_path)
    preds = pd.DataFrame({"model": ["a"] * 20, "symbol": [f"S{i}" for i in range(20)], "score": np.arange(20.0)})
    led.append("2026-12-07", ts("2026-12-07 21:40"), preds)
    with pytest.raises(LedgerError):
        led.append("2026-12-07", ts("2026-12-07 22:00"), preds)
    rows = led.read("2026-12-07")
    assert rows["side"].tolist().count(1) == 2 and rows["side"].tolist().count(-1) == 2
    led.append("2026-12-08", ts("2026-12-08 21:40"), preds)
    assert led.verify()[0]
    df = pd.read_parquet(led.path("2026-12-07"))
    df.loc[0, "score"] = 99.0  # someone edits an old prediction
    df.to_parquet(led.path("2026-12-07"), index=False)
    ok, why = led.verify()
    assert not ok and "changed" in why


def test_ledger_repair_after_a_crash_between_file_and_chain(tmp_path):
    led = Ledger(tmp_path)
    preds = pd.DataFrame({"model": ["a"] * 3, "symbol": ["A", "B", "C"], "score": [1.0, 2.0, 3.0]})
    led.append("2026-12-07", ts("2026-12-07 21:40"), preds)
    led.chain.write_text("")  # the process died after the file and before its chain line
    assert not led.verify()[0]
    assert led.repair() == ["2026-12-07"] and led.verify()[0]


def test_score_uses_the_next_two_opens_and_costs():
    rows = pd.DataFrame({"session": pd.Timestamp("2026-12-07"), "model": "a", "symbol": ["A", "B"],
                         "score": [1.0, -1.0], "rank": [1.0, 0.5], "side": [1, -1], "pred_return": [0.01, np.nan]})
    opens = pd.DataFrame({"A": [100.0, 100.0, 102.0], "B": [50.0, 50.0, 49.0]},
                         index=pd.to_datetime(["2026-12-07", "2026-12-08", "2026-12-09"]))
    s = score(rows, opens, fixed_bps=2.0).set_index("symbol")
    assert s.loc["A", "realized"] == pytest.approx(0.02) and s.loc["B", "realized"] == pytest.approx(-0.02)
    assert s.loc["A", "pnl"] == pytest.approx(0.02 - 0.0004) and bool(s.loc["B", "profitable"])
    assert s.loc["A", "abs_error"] == pytest.approx(0.01)
    m = model_summary(s.reset_index())
    assert m.loc[0, "profitable_share"] == 1.0 and m.loc[0, "sessions"] == 1
    assert score(rows.assign(session=pd.Timestamp("2026-12-08")), opens).empty  # the second open is not known yet


def test_fault_injection_finds_no_violation():
    r = run_many(30)
    assert r["violations"] == 0, r["examples"]
    assert r["crashes"] > 0 and r["failed_runs"] > 0 and r["nights_done"] > 0


def test_fault_injection_catches_deliberate_bugs():
    assert run_many(10, mutate="no_window")["violations"] > 0
    assert run_many(40, mutate="dup_ids", p_crash=0.7)["violations"] > 0
