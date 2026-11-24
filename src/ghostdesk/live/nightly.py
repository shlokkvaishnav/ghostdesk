"""The nightly run (decision D30), as a library: every outside dependency is injected, so whole weeks of runs with
crashes, rate-limit storms, partial fills and missed nights are simulated with a fake broker and clock
(`sim.fault_injection`).

One run, for the last closed session s:
1. **Gate** (`decide`): nothing if s is done. Predictions may be written any time after the close; orders only
   inside Alpaca's market-on-open window: from 19:00 New York time after s until 09:28 before the next open
   (OPG orders sent between 09:28 and 19:00 are rejected by Alpaca).
2. **Ledger first:** if the ledger has no file for s, every model predicts every member and the file is written
   (`live.ledger`); a rerun reuses it and never rewrites it. No order is sent for a session without its ledger file.
3. **Kill switch:** with trading off the run ends after the ledger.
4. **Plan:** the target weights of the pre-registered ensemble (`Deps.target`) -> whole shares. The expected book
   is the positions plus this session's open orders, so a rerun after a crash sends only what is missing.
   A change of side is only closed tonight (the new side opens the next night): orders never cross zero.
5. **Orders:** one market-on-open order per (session, symbol), client order id `gd-<YYYYMMDD>-<symbol>`. Alpaca
   accepts an id once, so a retry or a rerun cannot duplicate an order. A permanent rejection is recorded and the
   stock is skipped; a rate limit that outlasts the broker's retries stops the run (the next run continues).
6. **Record:** `night_<YYYYMMDD>.json` with the ledger hash, plan, orders, and `complete` once every planned stock
   has an order or a recorded reason. A complete record makes the session done.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from ghostdesk.live.alpaca_broker import BrokerError
from ghostdesk.live.ledger import Ledger
from ghostdesk.live.order_planning import side_of, target_shares_from_weights

NY = "America/New_York"
OPG_OPEN = (19, 0)     # Alpaca queues OPG orders sent after 19:00 New York time for the next open
OPG_CLOSE = (9, 28)    # and rejects them from 09:28 until 19:00


def trading_enabled(value: str | None) -> bool:
    """The kill switch `TRADING`: orders only when it is exactly "on". Unset, empty or any other value is off."""
    return value == "on"


@dataclass(frozen=True)
class NightConfig:
    min_frac: float = 0.2    # a change below this share of the stock's target value is not traded
    margin_min: int = 3      # stay this many minutes inside the window on both sides


@dataclass(frozen=True)
class Decision:
    session: pd.Timestamp | None
    predict: bool
    trade: bool
    ok: bool
    reason: str


@dataclass
class Deps:
    broker: object
    now: Callable[[], pd.Timestamp]
    predict: Callable[[pd.Timestamp], pd.DataFrame]   # session -> model, symbol, score, pred_return
    target: Callable[[pd.DataFrame], pd.Series]       # the session's ledger rows -> signed weights per symbol
    ledger: Ledger
    store: Path
    trading: bool = False
    log: Callable[[str], None] = print
    notes: dict = field(default_factory=dict)


def _et(day: pd.Timestamp, hm: tuple[int, int]) -> pd.Timestamp:
    return (pd.Timestamp(day) + pd.Timedelta(hours=hm[0], minutes=hm[1])).tz_localize(NY).tz_convert("UTC")


def last_closed(sessions: pd.DataFrame, now: pd.Timestamp) -> pd.Series | None:
    done = sessions[sessions["close_utc"] <= now]
    return None if done.empty else done.iloc[-1]


def window(sessions: pd.DataFrame, s: pd.Timestamp, cfg: NightConfig = NightConfig()):
    """(first, last) UTC times at which this run may send OPG orders for the open after session s."""
    nxt = sessions[sessions["date"] > s]
    if nxt.empty:
        return None, None
    m = pd.Timedelta(minutes=cfg.margin_min)
    return _et(s, OPG_OPEN) + m, _et(nxt["date"].iloc[0], OPG_CLOSE) - m


def state_path(store: Path, s: pd.Timestamp) -> Path:
    return store / f"night_{pd.Timestamp(s):%Y%m%d}.json"


def read_state(store: Path, s) -> dict:
    p = state_path(store, s)
    try:
        return json.loads(p.read_text()) if p.exists() else {}
    except ValueError:
        return {}


def is_done(store: Path, s) -> bool:
    return bool(read_state(store, s).get("complete"))


def decide(sessions: pd.DataFrame, now: pd.Timestamp, done: bool, cfg: NightConfig = NightConfig()) -> Decision:
    row = last_closed(sessions, now)
    if row is None:
        return Decision(None, False, False, True, "no closed session yet")
    s = row["date"]
    if done:
        return Decision(s, False, False, True, f"session {s:%Y-%m-%d} done")
    first, last = window(sessions, s, cfg)
    if first is None:
        return Decision(s, True, False, False, "no next session in the calendar")
    if now < first:
        return Decision(s, True, False, True, f"ledger only; orders wait for {first:%H:%M} UTC (OPG window)")
    if now > last:
        return Decision(s, True, False, False, f"OPG window for {s:%Y-%m-%d} missed (closed {last:%H:%M} UTC)")
    return Decision(s, True, True, True, "trade")


def _write(store: Path, s, state: dict) -> None:
    p = state_path(store, s)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(state, indent=1, default=str))
    tmp.replace(p)


def run_night(d: Deps, sessions: pd.DataFrame, cfg: NightConfig = NightConfig()) -> tuple[bool, str, dict]:
    """One run. Returns (ok, message, extra fields for the health record)."""
    now = d.now()
    row = last_closed(sessions, now)
    s = row["date"] if row is not None else None
    dec = decide(sessions, now, s is not None and is_done(d.store, s), cfg)
    if not dec.predict:
        return dec.ok, dec.reason, {}
    s = dec.session
    ok_chain, why = d.ledger.verify()
    if not ok_chain:
        repaired = d.ledger.repair()
        ok_chain, why = d.ledger.verify()
        if not ok_chain:
            return False, f"ledger check failed: {why}; no order sent", {}
        d.log(f"ledger: added the chain line of {repaired} (crash between the two writes)")
    state = read_state(d.store, s) or {"session": f"{s:%Y-%m-%d}", "runs": [], "orders": [], "rejected": {}}
    state["runs"].append(now.isoformat())
    if not d.ledger.has(s):
        nxt = sessions[sessions["date"] > s]
        if nxt.empty:
            _write(d.store, s, state)
            return False, f"ledger {s:%Y-%m-%d} not written: no next session in the calendar; no order", {}
        if d.now() >= nxt["open_utc"].iloc[0]:
            # the outcome (the next open) already exists: a prediction now is not a forecast (D38). A late trigger
            # is not a pipeline error, so the run is ok; the session stays missing from the ledger.
            state["missed"] = "the next open passed before the ledger was written"
            _write(d.store, s, state)
            return True, f"session {s:%Y-%m-%d} missed: its next open has passed; no ledger, no order", {
                "missed": f"{s:%Y-%m-%d}"}
        preds = d.predict(s)
        made_at = d.now()
        if made_at >= nxt["open_utc"].iloc[0]:
            state["missed"] = "the prediction finished after the next open"
            _write(d.store, s, state)
            return True, f"session {s:%Y-%m-%d} missed: prediction finished after the next open; no ledger", {
                "missed": f"{s:%Y-%m-%d}"}
        rec = d.ledger.append(s, made_at, preds)
        d.log(f"ledger {s:%Y-%m-%d}: {rec['rows']} predictions, {preds['model'].nunique()} models")
    line = next(x for x in d.ledger.lines() if x["session"] == f"{s:%Y-%m-%d}")
    state["ledger"] = {"sha256": line["file_sha256"], "written_at": line["written_at"]}
    if not d.trading:
        state["trading"] = "off"
        _write(d.store, s, state)
        return True, f"ledger {s:%Y-%m-%d} written; trading is off (no order)", {"trading": "off"}
    if not dec.trade:
        _write(d.store, s, state)
        return dec.ok, dec.reason, {}

    b = d.broker
    tag = f"gd-{s:%Y%m%d}-"
    weights = d.target(d.ledger.read(s))
    open_orders = b.open_orders()
    stale = [o for o in open_orders if not str(o.get("client_order_id", "")).startswith(tag)]
    if stale:  # an order of an earlier night still open (should not happen with OPG): cancel all, plan again
        b.cancel_open_orders()
        open_orders = [o for o in b.open_orders() if str(o.get("client_order_id", "")).startswith(tag)]
    positions = b.positions()
    pending: dict[str, float] = {}
    sent = set()
    for o in open_orders:
        if str(o.get("client_order_id", "")).startswith(tag):
            q = float(o.get("qty") or 0) - float(o.get("filled_qty") or 0)
            pending[o["symbol"]] = pending.get(o["symbol"], 0.0) + (q if o["side"] == "buy" else -q)
            sent.add(o["symbol"])
    sent |= {o["symbol"] for o in state["orders"]} | set(state["rejected"])
    syms = sorted(set(weights.index) | set(positions))
    prices = pd.Series(b.latest_prices(syms), dtype=float)
    equity = float(b.account()["equity"])
    target = target_shares_from_weights(weights, prices, equity)
    expected = {k: positions.get(k, 0.0) + pending.get(k, 0.0) for k in set(positions) | set(pending)}
    per_name = max((abs(w) for w in weights), default=0.0) * equity
    plan, deferred, later = {}, [], {}
    for k in sorted(set(target) | set(expected)):
        a, t = expected.get(k, 0.0), target.get(k, 0.0)
        if k in sent:  # one order per (session, symbol): what is still missing waits for the next night
            if abs(t - a) > 1e-9 and k not in state["rejected"]:
                later[k] = "this session already has its order for the stock; the rest next night"
            continue
        if a and t and np.sign(a) != np.sign(t):
            t = 0.0  # close tonight, open the new side next night
            deferred.append(k)
        if abs(t - a) < 1e-9:
            continue
        if t and a and abs(t - a) * float(prices.get(k, 0)) < cfg.min_frac * per_name:
            continue
        plan[k] = (a, t)
    state |= {"equity": equity, "target": target, "deferred_flips": deferred,
              "plan": {k: list(v) for k, v in plan.items()}}
    _write(d.store, s, state)
    stopped = None
    for k, (a, t) in plan.items():
        q = t - a
        if q != round(q):
            q = float(np.trunc(q))  # whole shares only (OPG); a fractional remainder stays
            if not q:
                continue
        try:
            o = b.submit(k, abs(q), side_of(q), tag + k, time_in_force="opg")
            state["orders"].append({"symbol": k, "qty": q, "id": o["id"], "status": o.get("status"),
                                    "at": d.now().isoformat()})
        except BrokerError as e:
            if e.permanent:
                state["rejected"][k] = f"{e.status}: {e.message}"
            else:
                stopped = f"{e.status}: {e.message}"
                break
        finally:
            _write(d.store, s, state)
    unreached = {k: state["rejected"][k] for k in plan if k in state["rejected"]}
    if stopped:
        _write(d.store, s, state)
        return False, f"session {s:%Y-%m-%d}: stopped by {stopped}; {len(state['orders'])} orders so far", {}
    state["complete"] = True
    state["unreached"] = unreached | later | {k: "change of side: closed tonight, opened next night"
                                               for k in deferred}
    _write(d.store, s, state)
    return len(state["rejected"]) == 0, (f"session {s:%Y-%m-%d}: {len(state['orders'])} OPG orders, "
                                        f"{len(state['rejected'])} rejected, {len(deferred)} flips deferred"), {
        "orders": len(state["orders"]), "rejected": len(state["rejected"])}
