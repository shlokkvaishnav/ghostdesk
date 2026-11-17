"""Live trading rules on small made-up tables: no look-ahead in the live signal, the same ranks as the study, whole-
share targets, idempotent trades, and child orders that never cross zero."""
import json

import numpy as np
import pandas as pd
import pytest

from ghostdesk.live.broker import Broker, BrokerError
from ghostdesk.live.portfolio import (
    FIRST_HOUR_PROFILE,
    buckets_left,
    child_orders,
    per_name_value,
    split,
    target_shares,
    too_expensive,
    trades,
    unit_of,
)
from ghostdesk.live.signal import composite, current_members, latest_pairs, one_class_per_company, quintile
from ghostdesk.signal.study import add_signals

SESSIONS = pd.DatetimeIndex(pd.bdate_range("2026-06-01", "2026-12-31"))


def idx(rows):
    df = pd.DataFrame(rows, columns=["cik", "accession", "accepted_utc", "amendment", "prev_accession", "form"])
    df["accepted_utc"] = pd.to_datetime(df["accepted_utc"], utc=True)
    return df


def test_latest_pairs_uses_only_reports_tradeable_by_the_close():
    close = pd.Timestamp("2026-11-02 21:00", tz="UTC")  # Monday 16:00 New York (EST)
    df = idx([
        (1, "a-old", "2026-08-01 12:00", False, "p", "10-Q"),
        (1, "a-new", "2026-11-02 15:00", False, "p", "10-Q"),   # after Monday's open: tradeable Tuesday -> not used
        (2, "b", "2026-11-02 14:00", False, "p", "10-K"),       # 09:00 New York: tradeable at Monday's open
        (3, "c-amend", "2026-10-01 12:00", True, "p", "10-K/A"),  # amendments are never used
        (4, "d", "2026-05-01 12:00", False, "p", "10-K"),       # older than 120 days
        (5, "e", "2026-10-01 12:00", False, None, "10-K"),      # no earlier report
    ])
    out = latest_pairs(df, SESSIONS, close).set_index("cik")["accession"].to_dict()
    assert out == {1: "a-old", 2: "b"}


def test_composite_matches_the_study_ranking():
    rng = np.random.default_rng(0)
    s = pd.DataFrame({"form": ["10-K"] * 6 + ["10-Q"] * 6,
                      **{m: rng.random(12) for m in ("sim_full_cosine", "sim_full_jaccard", "sim_full_edit")}})
    study = add_signals(s.assign(month=pd.Timestamp("2026-10-30"), sic="3571"))["composite"]
    assert np.allclose(composite(s).to_numpy(), study.to_numpy())


def test_quintile_top_is_least_change():
    q = quintile(pd.Series(np.arange(10.0)))
    assert q.iloc[0] == 1 and q.iloc[-1] == 5 and q.value_counts().eq(2).all()
    assert quintile(pd.Series([1.0, np.nan, 2.0])).isna().all()  # fewer than 5 values: no quintiles


def test_members_from_wikipedia_table_and_share_classes():
    html = """<table><tr><th>Symbol</th><th>Security</th><th>GICS Sector</th><th>CIK</th></tr>
    <tr><td>BRK-B</td><td>Berkshire</td><td>Financials</td><td>1067983</td></tr>
    <tr><td>GOOGL</td><td>Alphabet A</td><td>Communication</td><td>1652044</td></tr>
    <tr><td>GOOG</td><td>Alphabet C</td><td>Communication</td><td>1652044</td></tr></table>"""
    m = current_members(html)
    assert m["symbol"].tolist() == ["BRK.B", "GOOGL", "GOOG"]
    one = one_class_per_company(m, pd.Series({"GOOG": 5.0, "GOOGL": 9.0, "BRK.B": 1.0}))
    assert sorted(one["symbol"]) == ["BRK.B", "GOOGL"]


def test_target_shares_equal_value_whole_shares():
    sides = pd.Series({"A": 1, "B": 1, "C": -1, "D": 0})
    t = target_shares(sides, pd.Series({"A": 10.0, "B": 33.0, "C": 50.0, "D": 1.0}), equity=1000, leg=0.5)
    assert t == {"A": 25, "B": 8, "C": -10}
    assert per_name_value(sides, 1000, leg=0.5) == 250


def test_fractional_longs_keep_expensive_stocks_and_shorts_stay_whole():
    sides = pd.Series({"NVR": 1, "A": 1, "AZO": -1, "C": -1})
    prices = pd.Series({"NVR": 7000.0, "A": 33.0, "AZO": 4000.0, "C": 333.0})
    t = target_shares(sides, prices, equity=2000, leg=0.9, fractional={"NVR", "A", "AZO"})
    assert t["NVR"] == pytest.approx(900 / 7000, abs=1e-4) and t["A"] == pytest.approx(27.2727, abs=1e-4)
    assert t["C"] == -3.0 and "AZO" not in t  # a short is whole shares: 900 / 4000 rounds to 0
    assert too_expensive(sides, t, prices) == ["AZO"]
    assert unit_of("NVR", 0, t["NVR"], {"NVR"}) == 0.0001 and unit_of("C", 0, -3, {"C"}) == 1.0


def test_trades_skip_small_changes_but_always_close_and_flip():
    prices = pd.Series({"A": 10.0, "B": 10.0, "C": 10.0, "D": 10.0})
    t = trades(target={"A": 25, "B": -10, "D": 30}, current={"A": 24, "B": 10, "C": 5, "D": 10},
               prices=prices, per_name=250)
    assert t == {"B": (10, -10), "C": (5, 0), "D": (10, 30)}
    assert trades({"A": 25}, {"A": 25}, prices, 250) == {}  # a rerun after the rebalance trades nothing


def test_buckets_left_follow_the_profile():
    b = buckets_left(0)
    assert len(b) == 12 and b[0] == (0, pytest.approx(FIRST_HOUR_PROFILE[0] / sum(FIRST_HOUR_PROFILE)))
    late = buckets_left(12.0)  # started at 09:42: buckets from 09:45
    assert late[0][0] == 15 and sum(w for _, w in late) == pytest.approx(1)
    after = buckets_left(75)
    assert [m for m, _ in after] == [75, 80, 85, 90, 95, 100]


def test_split_is_exact():
    for q in (0, 1, 7, 101):
        parts = split(q, [0.5, 0.3, 0.2])
        assert sum(parts) == q and min(parts) >= 0


@pytest.mark.parametrize("cur,tgt,unit", [(10, 30, 1), (30, 10, 1), (-10, -40, 1), (10, 0, 1), (0, -7, 1),
                                          (12, -9, 1), (-5, 8, 1), (0, 0.1286, 1e-4), (2.5, 0, 1e-4),
                                          (1.75, -3, 1e-4), (-2, 0.3333, 1e-4)])
def test_child_orders_reach_target_and_never_cross_zero(cur, tgt, unit):
    if unit != 1:
        unit = unit_of("X", cur, tgt, {"X"})  # the unit the trade mode uses
    for w in ([1.0], [0.5, 0.5], [0.2] * 5, list(FIRST_HOUR_PROFILE)):
        pos = cur
        for bucket in child_orders(cur, tgt, w, unit):
            for q in bucket:
                new = pos + q
                assert pos == 0 or new == 0 or np.sign(new) == np.sign(pos), (pos, q)
                if q < 0 and new < 0:
                    assert q == round(q), "a sale that opens or adds to a short is whole shares"
                pos = new
        assert pos == pytest.approx(tgt, abs=1e-9)


class FakeResponse:
    def __init__(self, status, body):
        self.status_code, self._body = status, body
        self.content = json.dumps(body).encode()
        self.text = self.content.decode()

    def json(self):
        return self._body


class FakeSession:
    def __init__(self, answers):
        self.answers, self.calls = list(answers), []

    def request(self, method, url, **kw):
        self.calls.append((method, url, kw))
        return self.answers.pop(0)


def test_broker_refuses_a_live_endpoint():
    with pytest.raises(ValueError):
        Broker(headers={}, base="https://api.alpaca.markets/v2")


def test_broker_retries_then_raises_with_message():
    s = FakeSession([FakeResponse(429, {}), FakeResponse(200, [{"symbol": "A", "qty": "-3"}])])
    b = Broker(headers={}, session=s, sleep=lambda _: None)
    assert b.positions() == {"A": -3}
    s = FakeSession([FakeResponse(403, {"message": "insufficient buying power"})])
    with pytest.raises(BrokerError, match="insufficient buying power"):
        Broker(headers={}, session=s, sleep=lambda _: None).submit("A", 1, "buy", "x")


def test_broker_sessions_in_utc():
    s = FakeSession([FakeResponse(200, [{"date": "2026-11-27", "open": "09:30", "close": "13:00"}])])
    d = Broker(headers={}, session=s).sessions("2026-11-27", "2026-11-27")
    assert str(d["open_utc"][0]) == "2026-11-27 14:30:00+00:00" and str(d["close_utc"][0]) == "2026-11-27 18:00:00+00:00"


def test_rebalance_cost_against_arrival():
    from ghostdesk.live.site import rebalance_summary
    log = {"date": "2026-12-01", "arrival": {"A": 100.0, "B": 50.0},
           "orders": [{"symbol": "A", "qty": 10, "price": 100.1, "filled_qty": 10},   # bought 10 bps higher
                      {"symbol": "B", "qty": -20, "price": 49.95, "filled_qty": 20},  # sold 10 bps lower
                      {"symbol": "C", "qty": -5, "error": "not shortable"}]}
    s = rebalance_summary(log)
    assert s["cost_bps"] == pytest.approx(10.0) and s["rejected"] == 1 and s["filled"] == 2


def test_equity_curve_in_percent_from_the_first_day():
    from ghostdesk.live.site import equity_curve
    h = pd.DataFrame({"day": pd.to_datetime(["2026-11-16", "2026-11-17"]), "equity": [100000.0, 101000.0],
                      "profit_loss": [0, 1000]})
    spy = pd.DataFrame({"t": ["2026-11-16T05:00:00Z", "2026-11-17T05:00:00Z"], "c": [500.0, 495.0]})
    c = equity_curve(h, spy)
    assert c[1] == {"day": "2026-11-17", "account": 1.0, "spy": -1.0}


def test_report_scores_rank_latest_pair_per_member():
    from ghostdesk.live.site import report_scores
    at = pd.Timestamp("2026-11-17", tz="UTC")
    rows = [(c, f"a{c}", "10-Q", f"2026-1{1 if c % 2 else 0}-0{c % 9 + 1}", c / 10) for c in range(1, 8)]
    rows.append((1, "old", "10-Q", "2026-06-01", 0.0))  # older than 120 days
    s = pd.DataFrame(rows, columns=["cik", "accession", "form", "accepted_utc", "sim_full_cosine"])
    s["sim_full_jaccard"] = s["sim_full_cosine"]
    s["sim_full_edit"] = s["sim_full_cosine"]
    s["error"] = ""
    m = pd.DataFrame({"cik": range(1, 8), "symbol": list("ABCDEFG"), "name": "x", "sector": "y"})
    r = report_scores(s, m, at)
    assert len(r) == 7 and "old" not in set(r["accession"])
    assert r.set_index("symbol")["q"]["G"] == 5 and r.set_index("symbol")["q"]["A"] == 1


def test_close_all_cancels_orders_and_closes_positions():
    s = FakeSession([FakeResponse(207, [{"symbol": "A", "status": 200}])])
    out = Broker(headers={}, session=s).close_all()
    method, url, kw = s.calls[0]
    assert method == "DELETE" and url.endswith("/positions") and kw["params"] == {"cancel_orders": "true"}
    assert out == [{"symbol": "A", "status": 200}]


def test_learned_profile_from_minute_bars():
    from ghostdesk.live.portfolio import learned_profile
    rows = []
    for day in pd.bdate_range("2026-10-01", periods=5):  # EDT: 09:30 New York = 13:30 UTC
        for sym in ("A", "B"):
            for minute in range(-5, 70):  # pre-market and after the first hour must be ignored
                v = 200.0 if minute < 5 else 100.0
                rows.append((sym, day + pd.Timedelta(hours=13, minutes=30 + minute), v))
    bars = pd.DataFrame(rows, columns=["symbol", "t", "v"])
    bars["t"] = bars["t"].dt.tz_localize("UTC")
    prof, n = learned_profile(bars, min_days=10)
    assert n == 10 and prof[0] == pytest.approx(2 / 13, abs=1e-4) and prof[1] == pytest.approx(1 / 13, abs=1e-4)
    assert sum(prof) == pytest.approx(1, abs=1e-3)
    assert learned_profile(bars, min_days=11) == (FIRST_HOUR_PROFILE, 10)  # too few stock-days: fixed profile
    assert buckets_left(0, profile=prof)[0][1] == pytest.approx(prof[0] / sum(prof))


def test_broker_paces_requests_and_keeps_retrying_rate_limits():
    t = [0.0]
    waits = []

    def sleep(x):
        waits.append(x)
        t[0] += x

    answers = [FakeResponse(429, {})] * 5 + [FakeResponse(200, [])]
    b = Broker(headers={}, session=FakeSession(answers), sleep=sleep, clock=lambda: t[0], per_minute=60)
    assert b.positions() == {}  # five 429 answers in a row are still retried
    assert all(w >= 0 for w in waits) and sum(waits) >= 5 * 1.0


def test_broker_error_permanence_and_exact_paper_host():
    assert BrokerError(422, "x").permanent and BrokerError(403, "x").permanent
    assert not BrokerError(429, "x").permanent and not BrokerError(503, "x").permanent
    with pytest.raises(ValueError):
        Broker(headers={}, base="https://paper-api.alpaca.markets.example.com/v2")


def test_reconcile_target_against_positions():
    from ghostdesk.live.site import reconcile
    target = {"A": 10.0, "B": -5.0, "C": 2.5}
    pos = [{"symbol": "A", "qty": "10", "current_price": "50"},     # on target
           {"symbol": "B", "qty": "-3", "current_price": "100"},    # 200 off of a 500 target: not on target
           {"symbol": "D", "qty": "1", "current_price": "20"}]      # not in the target
    r = reconcile(target, pos, equity=1000)
    assert r["stocks_target"] == 3 and r["on_target"] == 1
    assert r["missing"] == ["C"] and r["extra"] == ["D"]
    assert r["off_pct"] == pytest.approx((200 + 20) / 1000 * 100)  # C has no price: not counted in value
    assert r["gross"]["long"] == {"target": 50.0, "actual": 52.0} and r["gross"]["short"] == {"target": 50.0, "actual": 30.0}
    assert r["worst"][0]["symbol"] == "B"
