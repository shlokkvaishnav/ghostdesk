"""Fault-injection harness for the nightly run (decision D35).

The real `live.alpaca_broker.Broker` talks to `FakeAlpaca`, an in-memory imitation of the Alpaca paper API at the
HTTP level (clock, account, positions, orders, client-order-id lookup, cancel, snapshots), so the broker's own
pacing, retries and duplicate-order handling are exercised too. The fake follows Alpaca's rules that matter here:
a client order id is accepted once; OPG orders sent between 09:28 and 19:00 New York time are rejected; an order may
not take a position across zero; OPG orders fill at the next open, fully or partly, and the rest is cancelled.

A scenario is a random run of nights: each night a primary and a backup trigger fire at random times (either may be
missed, or fire twice), and faults are injected: a crash after a random number of requests (the process dies;
the next trigger runs again), 429 storms longer than the broker's retries, permanent rejections of some stocks,
partial fills, and crashes inside prediction. After every run the invariants are checked:

  I1 no duplicate orders: every client order id once; at most one order per (session, symbol)
  I2 never across zero: no order or fill takes a position across zero
  I3 reaches target or reports: a complete night's expected book equals its target, or the stock is listed with a
     reason (rejected, or a change of side deferred to the next night)
  I4 a session is never done twice: no order for a session after its record became complete
  I5 ledger first and append-only: the chain verifies, no ledger file ever changes, and every order of a session
     was sent after that session's ledger file was written
  I6 every OPG order inside Alpaca's window (the fake would reject it otherwise)
A crash between the ledger file and its chain line is also injected (`CrashyLedger`); the next run repairs it.
"""
from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

import numpy as np
import pandas as pd

from ghostdesk.live.alpaca_broker import Broker, BrokerError
from ghostdesk.live.ledger import Ledger
from ghostdesk.live.nightly import OPG_CLOSE, OPG_OPEN, Deps, NightConfig, read_state, run_night

NY = "America/New_York"


class Crash(BaseException):
    """The runner dies (BaseException, so no `except Exception` in the code under test can swallow it)."""


class Resp:
    def __init__(self, status, body):
        self.status_code, self._body = status, body
        self.content = json.dumps(body).encode() if body is not None else b""
        self.text = self.content.decode()

    def json(self):
        return self._body


@dataclass
class FakeAlpaca:
    clock: object
    prices: dict
    rng: np.random.Generator
    reject: set = field(default_factory=set)       # symbols rejected permanently (e.g. not shortable)
    partial: float = 0.0                           # probability that an order fills only partly
    equity: float = 100_000.0
    positions: dict = field(default_factory=dict)
    orders: list = field(default_factory=list)
    storm: int = 0                                 # the next `storm` requests answer 429
    crash_after: int | None = None                 # raise Crash after this many more requests
    fills: list = field(default_factory=list)
    violations: list = field(default_factory=list)

    # ------------------------------------------------------------------ HTTP surface used by Broker
    def request(self, method, url, params=None, json=None, **kw):
        return self._handle(method, urlparse(url).path, params or {}, json)

    def get(self, url, params=None, **kw):
        return self._handle("GET", urlparse(url).path, params or {}, None)

    def _handle(self, method, path, params, body):
        if self.crash_after is not None:
            if self.crash_after <= 0:
                self.crash_after = None
                if self.rng.random() < 0.5:  # half the crashes happen after Alpaca acted: the answer is lost
                    self._route(method, path, params, body)
                raise Crash("runner killed")
            self.crash_after -= 1
        return self._route(method, path, params, body)

    def _route(self, method, path, params, body):
        if self.storm > 0:
            self.storm -= 1
            return Resp(429, {"message": "too many requests"})
        path = path.replace("/v2", "", 1)
        if path.endswith("/stocks/snapshots"):
            syms = params["symbols"].split(",")
            return Resp(200, {s: {"latestTrade": {"p": self.prices[s]}} for s in syms if s in self.prices})
        if path == "/account":
            return Resp(200, {"equity": str(self.equity)})
        if path == "/positions" and method == "GET":
            return Resp(200, [{"symbol": s, "qty": str(q)} for s, q in self.positions.items() if q])
        if path == "/orders" and method == "GET":
            st = params.get("status", "all")
            rows = [o for o in self.orders if st == "all" or (st == "open" and o["status"] in ("new", "accepted"))]
            return Resp(200, list(reversed(rows)))
        if path == "/orders" and method == "DELETE":
            for o in self.orders:
                if o["status"] in ("new", "accepted"):
                    o["status"] = "canceled"
            return Resp(207, [])
        if path == "/orders:by_client_order_id":
            o = next((o for o in self.orders if o["client_order_id"] == params["client_order_id"]), None)
            return Resp(200, o) if o else Resp(404, {"message": "not found"})
        if path == "/orders" and method == "POST":
            return self._submit(body)
        return Resp(404, {"message": f"no fake for {method} {path}"})

    def _submit(self, body):
        cid, sym, side, qty = body["client_order_id"], body["symbol"], body["side"], float(body["qty"])
        if any(o["client_order_id"] == cid for o in self.orders):
            return Resp(422, {"message": "client_order_id must be unique"})
        if sym in self.reject:
            return Resp(403, {"message": "asset not shortable"})
        if body.get("time_in_force") == "opg":
            et = self.clock.t.tz_convert(NY)
            hm = (et.hour, et.minute)
            if OPG_CLOSE <= hm < OPG_OPEN:
                self.violations.append(f"I6 OPG order at {et:%H:%M} ET")
                return Resp(422, {"message": "opg orders are accepted only from 19:00 to 09:28 ET"})
            if qty != round(qty):
                return Resp(422, {"message": "fractional orders must be day orders"})
        signed = qty if side == "buy" else -qty
        cur = self.positions.get(sym, 0.0) + sum(
            (float(o["qty"]) if o["side"] == "buy" else -float(o["qty"]))
            for o in self.orders if o["symbol"] == sym and o["status"] in ("new", "accepted"))
        if cur and cur + signed and np.sign(cur + signed) != np.sign(cur):
            self.violations.append(f"I2 order for {sym} would cross zero ({cur} {signed:+})")
            return Resp(403, {"message": "order would cross zero"})
        o = {"id": f"o{len(self.orders)}", "client_order_id": cid, "symbol": sym, "side": side, "qty": body["qty"],
             "status": "accepted", "filled_qty": "0", "time_in_force": body.get("time_in_force"),
             "submitted_at": self.clock.t.isoformat()}
        self.orders.append(o)
        return Resp(200, o)

    # ------------------------------------------------------------------ the market
    def open_auction(self):
        """Fill every accepted OPG order at the open: fully, or partly with probability `partial`."""
        for o in self.orders:
            if o["status"] != "accepted":
                continue
            q = float(o["qty"])
            f = q if self.rng.random() >= self.partial else float(np.floor(q * self.rng.uniform(0, 1)))
            s = f if o["side"] == "buy" else -f
            before = self.positions.get(o["symbol"], 0.0)
            after = before + s
            if before and after and np.sign(after) != np.sign(before):
                self.violations.append(f"I2 fill of {o['symbol']} crossed zero")
            self.positions[o["symbol"]] = after
            o["filled_qty"] = str(f)
            o["status"] = "filled" if f == q else "canceled"
            self.fills.append((o["symbol"], s))
        for k in list(self.prices):
            self.prices[k] *= float(np.exp(self.rng.normal(0, 0.02)))


class CrashyLedger(Ledger):
    """A ledger whose process may die between writing the file and writing its chain line."""

    def __init__(self, root, rng, p):
        super().__init__(root)
        self.rng, self.p = rng, p

    def append(self, session, made_at, preds):
        rec = super().append(session, made_at, preds)
        if self.rng.random() < self.p:
            lines = self.chain.read_text().splitlines()
            self.chain.write_text("".join(x + "\n" for x in lines[:-1]))
            raise Crash("crash between the ledger file and its chain line")
        return rec


class SimClock:
    def __init__(self, t):
        self.t = pd.Timestamp(t)

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += pd.Timedelta(seconds=float(s))


def sessions_between(start, n) -> pd.DataFrame:
    d = pd.bdate_range(start, periods=n)
    o = pd.DatetimeIndex([(x + pd.Timedelta(hours=9, minutes=30)).tz_localize(NY).tz_convert("UTC") for x in d])
    c = pd.DatetimeIndex([(x + pd.Timedelta(hours=16)).tz_localize(NY).tz_convert("UTC") for x in d])
    return pd.DataFrame({"date": d, "open_utc": o, "close_utc": c})


@dataclass
class Scenario:
    seed: int
    nights: int = 10
    symbols: int = 30
    p_miss: float = 0.2
    p_twice: float = 0.2
    p_crash: float = 0.3
    p_storm: float = 0.2
    p_predict_crash: float = 0.1
    p_ledger_crash: float = 0.1
    partial: float = 0.2
    rejects: int = 2
    mutate: str | None = None   # a deliberate bug, to show the checks catch it: "dup_ids" or "no_window"


def check(fake: FakeAlpaca, ledger: Ledger, store: Path, sessions: pd.DataFrame, seen_hashes: dict,
          done_at: dict) -> list[str]:
    v = list(fake.violations)
    fake.violations.clear()
    cids = [o["client_order_id"] for o in fake.orders]
    if len(cids) != len(set(cids)):
        v.append("I1 duplicate client order id")
    per = pd.Series([c.split("-")[1] + "|" + o["symbol"] for c, o in zip(cids, fake.orders, strict=True)])
    if per.duplicated().any():
        v.append(f"I1 two orders for one (session, symbol): {per[per.duplicated()].tolist()[:3]}")
    ok, why = ledger.verify()
    lines = {x["session"]: x for x in ledger.lines()}
    if not ok and "without a chain line" not in why:  # a file without its line is a crash point, repaired next run
        v.append(f"I5 ledger: {why}")
    for sname, h in list(seen_hashes.items()):
        if sname in lines and lines[sname]["file_sha256"] != h:
            v.append(f"I5 ledger file of {sname} changed")
    for sname, rec in lines.items():
        seen_hashes.setdefault(sname, rec["file_sha256"])
    for o in fake.orders:
        day = pd.Timestamp(o["client_order_id"].split("-")[1])
        sname = f"{day:%Y-%m-%d}"
        if sname not in lines or pd.Timestamp(lines[sname]["written_at"]) > pd.Timestamp(o["submitted_at"]):
            v.append(f"I5 order {o['client_order_id']} before its ledger")
        if sname in done_at and pd.Timestamp(o["submitted_at"]) > done_at[sname]:
            v.append(f"I4 order {o['client_order_id']} after session {sname} was done")
    for s in sessions["date"]:
        st = read_state(store, s)
        sname = f"{s:%Y-%m-%d}"
        if st.get("complete") and sname not in done_at:
            done_at[sname] = fake.clock.t
            exp = dict(fake.positions)
            for o in fake.orders:
                if o["status"] == "accepted" and o["client_order_id"].startswith(f"gd-{s:%Y%m%d}-"):
                    q = float(o["qty"])
                    exp[o["symbol"]] = exp.get(o["symbol"], 0.0) + (q if o["side"] == "buy" else -q)
            for k, (_, t) in (st.get("plan") or {}).items():
                if abs(exp.get(k, 0.0) - float(t)) > 1e-9 and k not in st.get("unreached", {}):
                    v.append(f"I3 {sname} {k}: expected {exp.get(k, 0.0)}, planned {t}, no reason given")
    return v


def run_scenario(sc: Scenario) -> dict:
    rng = np.random.default_rng(sc.seed)
    syms = [f"S{i:02d}" for i in range(sc.symbols)]
    cal = sessions_between("2026-12-01", sc.nights + 2)
    clock = SimClock(cal["close_utc"].iloc[0] + pd.Timedelta(minutes=30))
    fake = FakeAlpaca(clock, {s: float(rng.uniform(20, 400)) for s in syms}, rng,
                      reject=set(rng.choice(syms, sc.rejects, replace=False)), partial=sc.partial)
    broker = Broker(headers={}, session=fake, sleep=clock.sleep, clock=lambda: clock.t.value / 1e9, per_minute=6000)
    root = Path(tempfile.mkdtemp())
    ledger, store = CrashyLedger(root / "ledger", rng, sc.p_ledger_crash), root / "live"
    store.mkdir()

    def predict(s):
        if rng.random() < sc.p_predict_crash:
            raise Crash("crash while predicting")
        r = np.random.default_rng(int(f"{s:%Y%m%d}"))
        return pd.DataFrame([{"model": m, "symbol": x, "score": r.normal(), "pred_return": r.normal(0, 0.01)}
                             for m in ("a", "b") for x in syms])

    def target(rows):
        e = rows.groupby("symbol")["rank"].mean().sort_values()
        k = max(len(e) // 10, 1)
        w = pd.Series(0.0, index=e.index)
        w[e.index[-k:]], w[e.index[:k]] = 0.5 / k, -0.5 / k
        return w

    cfg = NightConfig(margin_min=-600) if sc.mutate == "no_window" else NightConfig()
    if sc.mutate == "dup_ids":  # ids that change on every run, and a planner blind to open orders and its record
        submit = broker.submit
        broker.submit = lambda sym, q, side, cid, **kw: submit(sym, q, side, f"{cid}-{runs}", **kw)
        broker.open_orders = list
    deps = Deps(broker=broker, now=clock.now, predict=predict, target=target, ledger=ledger, store=store,
                trading=True, log=lambda m: None)
    seen, done_at, viol, runs, crashes, failed = {}, {}, [], 0, 0, 0
    for i in range(sc.nights):
        s, n = cal.iloc[i], cal.iloc[i + 1]
        times = []
        for base, spread in ((_ny(s["date"], 20, 30), 60), (_ny(n["date"], 6, 0), 120)):  # primary, backup
            if rng.random() >= sc.p_miss:
                t = base + pd.Timedelta(minutes=float(rng.uniform(-spread, spread)))
                times += [t] * (2 if rng.random() < sc.p_twice else 1)
        if rng.random() < 0.1:
            times.append(s["close_utc"] + pd.Timedelta(minutes=40))  # an early run: ledger only
        for t in sorted(times):
            clock.t = max(clock.t, t)
            fake.crash_after = int(rng.integers(0, 40)) if rng.random() < sc.p_crash else None
            fake.storm = int(rng.integers(9, 20)) if rng.random() < sc.p_storm else 0
            runs += 1
            try:
                run_night(deps, cal, cfg)
            except Crash:
                crashes += 1
            except BrokerError:
                failed += 1  # a storm longer than the broker's retries: the run stops; the script records it
            fake.crash_after, fake.storm = None, 0
            viol += [f"night {i} run {runs}: {x}" for x in check(fake, ledger, store, cal, seen, done_at)]
        clock.t = max(clock.t, n["open_utc"])
        fake.open_auction()
        viol += [f"night {i} open: {x}" for x in check(fake, ledger, store, cal, seen, done_at)]
    done = sum(1 for s in cal["date"] if read_state(store, s).get("complete"))
    return {"seed": sc.seed, "runs": runs, "crashes": crashes, "failed": failed, "orders": len(fake.orders), "fills": len(fake.fills),
            "nights_done": done, "nights": sc.nights, "violations": viol}


def _ny(day, h, m):
    return (pd.Timestamp(day) + pd.Timedelta(hours=h, minutes=m)).tz_localize(NY).tz_convert("UTC")


def run_many(n: int, start_seed: int = 0, **kw) -> dict:
    res = [run_scenario(Scenario(seed=start_seed + i, **kw)) for i in range(n)]
    v = [x for r in res for x in r["violations"]]
    return {"scenarios": n, "runs": sum(r["runs"] for r in res), "crashes": sum(r["crashes"] for r in res), "failed_runs": sum(r["failed"] for r in res),
            "orders": sum(r["orders"] for r in res), "nights": sum(r["nights"] for r in res),
            "nights_done": sum(r["nights_done"] for r in res), "violations": len(v), "examples": v[:10]}
