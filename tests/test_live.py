"""Live helpers on small made-up tables: today's members, whole-share targets, trades that skip small changes,
orders that never cross zero, and the paper-only broker with its retries."""
import json

import numpy as np
import pandas as pd
import pytest

from ghostdesk.live.alpaca_broker import Broker, BrokerError
from ghostdesk.live.members import current_members, one_class_per_company
from ghostdesk.live.order_planning import orders_for, target_shares_from_weights, trades


def test_members_from_wikipedia_table_and_share_classes():
    html = """<table><tr><th>Symbol</th><th>Security</th><th>GICS Sector</th><th>CIK</th></tr>
    <tr><td>BRK-B</td><td>Berkshire</td><td>Financials</td><td>1067983</td></tr>
    <tr><td>GOOGL</td><td>Alphabet A</td><td>Communication</td><td>1652044</td></tr>
    <tr><td>GOOG</td><td>Alphabet C</td><td>Communication</td><td>1652044</td></tr></table>"""
    m = current_members(html)
    assert m["symbol"].tolist() == ["BRK.B", "GOOGL", "GOOG"]
    one = one_class_per_company(m, pd.Series({"GOOG": 5.0, "GOOGL": 9.0, "BRK.B": 1.0}))
    assert sorted(one["symbol"]) == ["BRK.B", "GOOGL"]


def test_target_shares_whole_and_rounded():
    t = target_shares_from_weights(pd.Series({"A": 0.02, "B": -0.02, "C": 0.0001, "D": 0.01}),
                                   pd.Series({"A": 50.0, "B": 30.0, "C": 900.0}), 100_000)
    assert t == {"A": 40.0, "B": -67.0}  # C rounds to 0 shares, D has no price


def test_trades_skip_small_changes_but_always_close_and_flip():
    px = pd.Series({"A": 10.0, "B": 10.0, "C": 10.0, "D": 10.0})
    plan = trades({"A": 101, "B": -50, "D": 30}, {"A": 100, "B": 40, "C": 5}, px, per_name=1000)
    assert set(plan) == {"B", "C", "D"}  # A's change (10 dollars) is below 20% of 1000


@pytest.mark.parametrize("cur,tgt", [(10, 30), (30, 10), (-10, -40), (10, 0), (0, -7), (12, -9), (-5, 8), (3, 3)])
def test_orders_reach_target_and_never_cross_zero(cur, tgt):
    pos = cur
    for q in orders_for(cur, tgt):
        new = pos + q
        assert pos == 0 or new == 0 or np.sign(new) == np.sign(pos)
        pos = new
    assert pos == tgt


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
        a = self.answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return a


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


def test_equity_curve_in_percent_from_the_first_day():
    from ghostdesk.live.dashboard_data import equity_curve
    h = pd.DataFrame({"day": pd.to_datetime(["2026-11-16", "2026-11-17"]), "equity": [100000.0, 101000.0],
                      "profit_loss": [0, 1000]})
    spy = pd.DataFrame({"t": ["2026-11-16T05:00:00Z", "2026-11-17T05:00:00Z"], "c": [500.0, 495.0]})
    c = equity_curve(h, spy)
    assert c[1] == {"day": "2026-11-17", "account": 1.0, "spy": -1.0}


def test_close_all_cancels_orders_and_closes_positions():
    s = FakeSession([FakeResponse(207, [{"symbol": "A", "status": 200}])])
    out = Broker(headers={}, session=s).close_all()
    method, url, kw = s.calls[0]
    assert method == "DELETE" and url.endswith("/positions") and kw["params"] == {"cancel_orders": "true"}
    assert out == [{"symbol": "A", "status": 200}]


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
    from ghostdesk.live.dashboard_data import reconcile
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


def test_broker_retries_a_network_error():
    import requests
    s = FakeSession([requests.ConnectionError("reset"), requests.Timeout("slow"),
                     FakeResponse(200, [{"symbol": "A", "qty": "2"}])])
    assert Broker(headers={}, session=s, sleep=lambda _: None).positions() == {"A": 2}


def test_broker_network_error_that_persists_is_not_permanent():
    import requests
    s = FakeSession([requests.ConnectionError("down")] * 8)
    with pytest.raises(BrokerError) as e:
        Broker(headers={}, session=s, sleep=lambda _: None).positions()
    assert not e.value.permanent  # the rebalance skips the child and the next bucket tries again


def test_a_retried_order_that_alpaca_already_took_is_returned():
    taken = {"id": "o1", "symbol": "A", "side": "buy", "qty": "3", "status": "new"}
    s = FakeSession([FakeResponse(422, {"message": "client_order_id must be unique"}), FakeResponse(200, taken)])
    assert Broker(headers={}, session=s, sleep=lambda _: None).submit("A", 3, "buy", "gd-x") == taken
    assert s.calls[1][1].endswith("/orders:by_client_order_id")


def test_a_reused_order_id_for_a_different_order_is_still_an_error():
    other = {"id": "o1", "symbol": "B", "side": "sell", "qty": "1", "status": "filled"}
    s = FakeSession([FakeResponse(422, {"message": "client_order_id must be unique"}), FakeResponse(200, other)])
    with pytest.raises(BrokerError, match="unique"):
        Broker(headers={}, session=s, sleep=lambda _: None).submit("A", 3, "buy", "gd-x")
