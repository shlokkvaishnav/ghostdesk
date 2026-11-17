"""The Alpaca bar client against a fake server: pages, retry after 429, rate limit, no key leaks; coverage."""
import pandas as pd
import pytest

from ghostdesk.data import alpaca_client
from ghostdesk.data.alpaca_client import AlpacaClient, alpaca_symbol, coverage


class Resp:
    def __init__(self, code, body):
        self.status_code, self._body = code, body

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class Fake:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    def get(self, url, params, headers, timeout):
        self.calls.append(dict(params))
        return self.replies.pop(0)


def bar(t, c):
    return {"t": t, "o": c, "h": c + 1, "l": c - 1, "c": c, "v": 100, "n": 5, "vw": c}


def test_pages_and_retry():
    replies = [Resp(429, {}),
               Resp(200, {"bars": {"AAPL": [bar("2024-01-02T05:00:00Z", 1.0)]}, "next_page_token": "p2"}),
               Resp(200, {"bars": {"AAPL": [bar("2024-01-03T05:00:00Z", 2.0)], "MSFT": [bar("2024-01-02T05:00:00Z",
                                                                                          3.0)]}})]
    s, waits, now = Fake(replies), [], [0.0]
    c = AlpacaClient(headers={"k": "v"}, session=s, sleep=lambda x: waits.append(x) or now.__setitem__(0, now[0] + x),
                     clock=lambda: now[0])
    df = c.bars(["AAPL", "MSFT"], "2024-01-01", "2024-01-05")
    assert df[["symbol", "c"]].values.tolist() == [["AAPL", 1.0], ["AAPL", 2.0], ["MSFT", 3.0]]
    assert s.calls[-1]["page_token"] == "p2" and s.calls[0]["feed"] == "sip" and s.calls[0]["adjustment"] == "all"
    assert any(w >= 5 for w in waits)  # waited after the 429
    assert str(df["t"].dt.tz) == "UTC"


def test_missing_keys_message_has_no_values(monkeypatch, tmp_path):
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)
    monkeypatch.setattr(alpaca_client, "REPO_ROOT", tmp_path)
    (tmp_path / ".env").write_text("ALPACA_API_KEY=abc123secret\n")
    with pytest.raises(RuntimeError) as e:
        alpaca_client.keys()
    assert "ALPACA_SECRET_KEY" in str(e.value) and "abc123secret" not in str(e.value)


def test_symbol_and_coverage():
    assert alpaca_symbol("BRK-B") == "BRK.B" and alpaca_symbol("AAPL") == "AAPL"
    t = pd.to_datetime(["2024-01-02T05:00:00Z", "2024-01-03T05:00:00Z", "2024-01-02T05:00:00Z"], utc=True)
    daily = pd.DataFrame({"symbol": ["AAPL", "AAPL", "BRK.B"], "t": t})
    members = pd.DataFrame({"ticker": ["AAPL", "BRK-B"], "start": pd.to_datetime(["2020-01-01", "2020-01-01"]),
                            "end": [pd.NaT, pd.Timestamp("2024-01-03")]})
    c = coverage(daily, members, "2024-01-01", "2024-12-31")
    assert c == {"member_days": 3, "with_bar": 3, "share": 1.0}


def test_symbol_dropped_from_a_batch_is_asked_again():
    replies = [Resp(200, {"bars": {"DOV": [bar("2024-01-02T05:00:00Z", 1.0)]}}),
               Resp(200, {"bars": {"DOW": [bar("2024-01-02T05:00:00Z", 2.0)]}})]
    s = Fake(replies)
    df = AlpacaClient(headers={"k": "v"}, session=s, sleep=lambda x: None).bars(["DOV", "DOW"], "2024-01-01",
                                                                               "2024-01-05")
    assert sorted(df["symbol"]) == ["DOV", "DOW"] and s.calls[1]["symbols"] == "DOW"
