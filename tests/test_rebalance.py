"""End-to-end trade runs with a fake broker and a fake clock: a month-start day, a rerun the same day, a missed
window and its catch-up, a run that dies half way and its completion, and the gate for other days."""
import json

import numpy as np
import pandas as pd
import pytest

from ghostdesk.live.alpaca_broker import BrokerError
from ghostdesk.live.rebalance import Config, Deps, decide, month_done, run_trade

SYMS = [f"S{i}" for i in range(10)]
PRICES = {s: 20.0 + 15 * i for i, s in enumerate(SYMS)}


def sessions() -> pd.DataFrame:
    d = pd.bdate_range("2026-11-02", "2026-12-31")
    return pd.DataFrame({"date": d, "open_utc": (d + pd.Timedelta(hours=14, minutes=30)).tz_localize("UTC"),
                         "close_utc": (d + pd.Timedelta(hours=21)).tz_localize("UTC")})


class Clock:
    def __init__(self, t):
        self.t = pd.Timestamp(t, tz="UTC")

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += pd.Timedelta(seconds=s)


class FakeBroker:
    """Fills at once at the fixed price; rejects what Alpaca rejects: a reused client order ID, an order that
    crosses zero, and a fractional short sale."""

    def __init__(self, clock, fail_after=None):
        self.c, self.pos, self.done, self.fail_after = clock, {}, [], fail_after

    def clock(self):
        cal = sessions()
        row = cal[cal["date"] == self.c.t.tz_convert("America/New_York").normalize().tz_localize(None)]
        return {"is_open": bool(len(row)) and row["open_utc"].iloc[0] <= self.c.t < row["close_utc"].iloc[0]}

    def positions(self):
        return {s: q for s, q in self.pos.items() if q}

    def position_rows(self):
        return [{"symbol": s, "qty": str(q), "current_price": str(PRICES[s])} for s, q in self.positions().items()]

    def orders(self, after=None, status="all", limit=0):
        return self.done[:limit] if limit else list(self.done)

    def asset(self, s):
        return {"shortable": True, "easy_to_borrow": True, "fractionable": True}

    def latest_prices(self, syms):
        return {s: PRICES[s] for s in syms}

    def account(self):
        return {"equity": "100000"}

    def submit(self, s, qty, side, cid):
        if self.fail_after is not None and len(self.done) >= self.fail_after:
            raise SystemExit("runner killed")
        if any(o["id"] == cid for o in self.done):
            raise BrokerError(422, "client_order_id must be unique")
        a = self.pos.get(s, 0.0)
        new = round(a + (qty if side == "buy" else -qty), 4)
        if a and new and np.sign(a) != np.sign(new):
            raise BrokerError(403, "order crosses zero")
        if new < 0 and qty != round(qty):
            raise BrokerError(422, "fractional orders cannot be sold short")
        self.pos[s] = new
        self.done.append({"id": cid, "symbol": s, "qty": qty, "side": side})
        return {"id": cid, "status": "filled"}

    def order(self, oid):
        o = next(o for o in self.done if o["id"] == oid)
        return {"status": "filled", "filled_qty": str(o["qty"]), "filled_avg_price": str(PRICES[o["symbol"]])}


@pytest.fixture
def store(tmp_path):
    rng = np.random.default_rng(1)
    pd.DataFrame({"symbol": SYMS, "cik": range(1, 11), "name": SYMS, "sector": "x"}).to_parquet(
        tmp_path / "members.parquet")
    idx = pd.DataFrame({"cik": range(1, 11), "accession": [f"a{i}" for i in range(1, 11)],
                        "accepted_utc": pd.Timestamp("2026-11-05 12:00", tz="UTC"), "amendment": False,
                        "prev_accession": "p", "form": "10-Q"})
    idx.to_parquet(tmp_path / "index.parquet")
    sc = idx[["cik", "accession"]].copy()
    for m in ("sim_full_cosine", "sim_full_jaccard", "sim_full_edit"):
        sc[m] = rng.random(10)
    sc.to_parquet(tmp_path / "scores.parquet")
    return tmp_path


def deps(broker, clock, store):
    return Deps(broker=broker, now=clock.now, sleep=clock.sleep, dollar_volume=lambda s: pd.Series(1.0, index=s),
                minute_bars=lambda *a: pd.DataFrame(), store=store, log=lambda m: None)


def on_target(broker, store, day):
    target = json.loads((store / f"rebalance_{day}.json").read_text())["target"]
    return all(abs(broker.positions().get(s, 0) - q) < 1e-6 for s, q in target.items())


def test_month_start_rebalance_then_rerun_does_nothing(store):
    clock = Clock("2026-12-01 14:40")
    b = FakeBroker(clock)
    b.pos = {"S0": 5.0}  # not an empty account: only the month start makes the run trade
    ok, msg, extra = run_trade(deps(b, clock, store), sessions())
    assert ok and msg.startswith("rebalance 2026-12-01") and extra["rejected"] == 0
    assert on_target(b, store, "20261201") and month_done(store, pd.Timestamp("2026-12-01"))
    pos = b.positions()
    assert sum(q > 0 for q in pos.values()) == 2 and sum(q < 0 for q in pos.values()) == 2
    assert all(q == round(q) for q in pos.values() if q < 0)  # shorts in whole shares
    log = json.loads((store / "rebalance_20261201.json").read_text())
    assert log["recon"]["on_target"] == log["recon"]["stocks_target"] == 4 and log["orders"]
    before = (store / "rebalance_20261201.json").read_text()
    clock.t = pd.Timestamp("2026-12-01 15:40", tz="UTC")
    n = len(b.done)
    ok, msg, _ = run_trade(deps(b, clock, store), sessions())
    assert ok and "no rebalance due" in msg and len(b.done) == n
    assert (store / "rebalance_20261201.json").read_text() == before  # the record is never overwritten


def test_missed_window_is_an_error_and_the_next_session_catches_up(store):
    clock = Clock("2026-12-01 17:30")  # 180 minutes after the open
    b = FakeBroker(clock)
    b.pos = {"S0": 5.0}
    ok, msg, _ = run_trade(deps(b, clock, store), sessions())
    assert not ok and "missed" in msg and "next session catches up" in msg and len(b.done) == 0
    clock.t = pd.Timestamp("2026-12-02 14:45", tz="UTC")
    ok, msg, _ = run_trade(deps(b, clock, store), sessions())
    assert ok and on_target(b, store, "20261202")
    assert json.loads((store / "rebalance_20261202.json").read_text())["catch_up"] is True


def test_a_run_that_dies_half_way_is_finished_by_the_next_run(store):
    clock = Clock("2026-12-01 14:40")
    b = FakeBroker(clock, fail_after=6)
    b.pos = {"S0": 5.0}
    with pytest.raises(SystemExit):
        run_trade(deps(b, clock, store), sessions())
    assert not month_done(store, pd.Timestamp("2026-12-01"))  # no final reconciliation: not done
    b.fail_after = None
    clock.t = pd.Timestamp("2026-12-01 15:40", tz="UTC")
    ok, _, extra = run_trade(deps(b, clock, store), sessions())
    assert ok and extra["rejected"] == 0  # new order IDs: no clash with the first run's IDs
    reruns = list(store.glob("rebalance_20261201_*.json"))
    assert len(reruns) == 1 and json.loads(reruns[0].read_text())["rerun_of"] == "rebalance_20261201.json"
    target = json.loads(reruns[0].read_text())["target"]
    assert all(abs(b.positions().get(s, 0) - q) < 1e-6 for s, q in target.items())


def test_empty_account_trades_at_once_mid_month(store):
    clock = Clock("2026-11-17 14:45")
    b = FakeBroker(clock)
    ok, msg, _ = run_trade(deps(b, clock, store), sessions())
    assert ok and on_target(b, store, "20261117")
    clock.t = pd.Timestamp("2026-11-18 14:45", tz="UTC")
    ok, msg, _ = run_trade(deps(b, clock, store), sessions())
    assert ok and "no rebalance due" in msg


@pytest.mark.parametrize("t,empty,done,trade,ok,word", [
    ("2026-12-05 15:00", False, False, False, True, "not a trading day"),       # Saturday
    ("2026-12-01 14:00", False, False, False, True, "before the open"),
    ("2026-12-01 14:40", False, True, False, True, "no rebalance due"),
    ("2026-12-03 18:00", False, False, False, False, "no session left"),       # 3rd session, window passed
    ("2026-12-04 14:40", False, False, False, True, "no rebalance due"),       # past the catch-up sessions
    ("2026-12-10 14:40", True, False, True, True, "rebalance"),                # empty account: any day
])
def test_decide_gate(t, empty, done, trade, ok, word):
    ts = pd.Timestamp(t, tz="UTC")
    cal = sessions()
    row = cal[cal["date"] == ts.normalize().tz_localize(None)]
    is_open = bool(len(row)) and row["open_utc"].iloc[0] <= ts < row["close_utc"].iloc[0]
    d = decide(cal, ts, is_open, empty, done, Config())
    assert (d.trade, d.ok) == (trade, ok) and word in d.reason
