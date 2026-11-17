"""The trade run (decision D15), as a library: every outside dependency is injected, so a whole month-start day,
a rerun and a missed window are tested with a fake broker and a fake clock (`tests/test_rebalance.py`).

`decide` is the gate (pure). `run_trade` does one run: formation at the last close, targets, VWAP child orders,
fills, and a reconciliation of the book against the target at the end. Records go to `Deps.store` (data/live/):
the first run of a day writes `rebalance_<date>.json`; a later run that finishes leftover trades writes
`rebalance_<date>_<HHMM>.json` and never overwrites the first record.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from ghostdesk.evaluation.portfolio_stats import FULL
from ghostdesk.live.alpaca_broker import BrokerError
from ghostdesk.live.dashboard_data import reconcile
from ghostdesk.live.live_signal import composite, latest_pairs, one_class_per_company, quintile
from ghostdesk.live.order_planning import (
    buckets_left,
    child_orders,
    learned_profile,
    per_name_value,
    side_of,
    target_shares,
    too_expensive,
    trades,
    unit_of,
)


@dataclass(frozen=True)
class Config:
    leg: float = 0.9            # each leg's share of equity: gross 1.8x inside the 2x margin
    window_min: float = 150     # trade only from the open to this many minutes after it
    catchup_sessions: int = 3   # a month with no rebalance yet is caught up in its first N sessions (H1)
    start: str = "2026-11-16"   # the paper account was opened on this day
    min_frac: float = 0.2       # a change below this share of a stock's target value is not traded
    profile_symbols: int = 30   # stocks used to learn the volume profile (D16)


@dataclass(frozen=True)
class Decision:
    trade: bool
    ok: bool
    reason: str
    catch_up: bool = False


def decide(sessions: pd.DataFrame, now: pd.Timestamp, is_open: bool, empty_account: bool,
           month_done: bool, cfg: Config = Config()) -> Decision:
    """Should this run trade? `month_done`: a rebalance record exists for this month. A due rebalance whose
    window has passed is an error (ok=False), so the page shows it; the next session catches it up."""
    today = now.tz_convert("America/New_York").normalize().tz_localize(None)
    row = sessions[sessions["date"] == today]
    if row.empty:
        return Decision(False, True, "not a trading day")
    month = sessions[sessions["date"].dt.to_period("M") == today.to_period("M")]["date"].reset_index(drop=True)
    k = int((month < today).sum())  # 0 = first session of the month
    due = empty_account or (not month_done and k < cfg.catchup_sessions)
    if not due:
        return Decision(False, True, f"no rebalance due ({today:%Y-%m-%d})")
    minutes = (now - row["open_utc"].iloc[0]).total_seconds() / 60
    if minutes < 0:
        return Decision(False, True, f"rebalance due; {-minutes:.0f} min before the open")
    if minutes > cfg.window_min or not is_open:
        last = k + 1 >= cfg.catchup_sessions and not empty_account
        return Decision(False, False, f"rebalance due but missed: {minutes:.0f} min after the open (window 0-"
                        f"{cfg.window_min:.0f}); " + ("no session left to catch up this month" if last
                                                     else "the next session catches up"))
    return Decision(True, True, "rebalance", catch_up=k > 0 and not empty_account)


def formation(sessions: pd.DataFrame, today: pd.Timestamp, members: pd.DataFrame, index: pd.DataFrame,
              scores: pd.DataFrame) -> tuple[pd.DataFrame, int, pd.Timestamp]:
    """Members with the features of their latest pair at the last close before `today`, the count of pairs
    without features, and that close."""
    prev_close = sessions.loc[sessions["date"] < today, "close_utc"].iloc[-1]
    lp = latest_pairs(index, pd.DatetimeIndex(sessions["date"]), prev_close)
    lp = lp.merge(scores[["cik", "accession", *FULL]], on=["cik", "accession"], how="left")
    missing = int(lp[FULL[0]].isna().sum())
    f = members.merge(lp[["cik", "accession", "form", "tradeable", *FULL]], on="cik", how="left")
    return f, missing, prev_close


def select(f: pd.DataFrame, dollar_volume: pd.Series) -> tuple[pd.DataFrame, pd.Series]:
    """One class per company, `composite` and quintile; sides: +1 long (Q5), -1 short (Q1), 0. Rows are in
    dollar-volume order (high first) before the quintiles, because the study's panel is in that order and
    `quintile` breaks ties by order (found by tests/test_parity.py: 78 tied values in one month)."""
    one = one_class_per_company(f, dollar_volume).dropna(subset=[FULL[0]]).copy()
    one = one.iloc[np.argsort(-one["symbol"].map(dollar_volume).fillna(-1.0).to_numpy(), kind="stable")]
    one["composite"] = composite(one).to_numpy()
    one["q"] = quintile(one["composite"]).to_numpy()
    sides = pd.Series(np.where(one["q"] == 5, 1, np.where(one["q"] == 1, -1, 0)), index=one["symbol"])
    return one, sides


@dataclass
class Deps:
    """What a run needs from outside. Real ones are built in scripts/live_desk.py; tests pass fakes."""
    broker: object
    now: Callable[[], pd.Timestamp]
    sleep: Callable[[float], None]
    dollar_volume: Callable[[list[str]], pd.Series]
    minute_bars: Callable[[list[str], pd.Timestamp, pd.Timestamp], pd.DataFrame]
    store: Path
    log: Callable[[str], None] = print
    notes: dict = field(default_factory=dict)


def month_done(store: Path, today: pd.Timestamp) -> bool:
    """A rebalance of this month ran to its end (its record has the final reconciliation). A run that died
    half way leaves a record without one, so the next run in the window finishes the trades."""
    for p in store.glob(f"rebalance_{today:%Y%m}*.json"):
        try:
            if "recon" in json.loads(p.read_text()):
                return True
        except ValueError:
            continue
    return False


def run_trade(d: Deps, sessions: pd.DataFrame, cfg: Config = Config(), dry_run: bool = False) -> tuple[bool, str, dict]:
    """One trade run. Returns (ok, message, extra fields for the health record)."""
    b, t = d.broker, d.now()
    today = t.tz_convert("America/New_York").normalize().tz_localize(None)
    empty = not b.positions() and not b.orders(after=f"{cfg.start}T00:00:00Z", limit=1)
    dec = decide(sessions, t, bool(b.clock()["is_open"]), empty, month_done(d.store, today), cfg)
    if not dec.trade and not dry_run:
        return dec.ok, dec.reason, {}
    row = sessions[sessions["date"] == today]
    if row.empty:  # a dry run on a weekend or holiday: plan for the next session
        row = sessions[sessions["date"] > today].head(1)
        today = row["date"].iloc[0]
    open_utc = row["open_utc"].iloc[0]
    minutes = min(max((t - open_utc).total_seconds() / 60, 0.0), cfg.window_min)

    f, missing, prev_close = formation(sessions, today, pd.read_parquet(d.store / "members.parquet"),
                                       pd.read_parquet(d.store / "index.parquet"),
                                       pd.read_parquet(d.store / "scores.parquet"))
    one, sides = select(f, d.dollar_volume(f["symbol"].tolist()))
    current = b.positions()
    assets = {s: _asset(b, s) for s in sorted(set(sides[sides != 0].index) | set(current))}
    shortable = {s: bool(assets[s].get("shortable") and assets[s].get("easy_to_borrow"))
                 for s in sides[sides == -1].index}
    sides[[s for s, ok in shortable.items() if not ok]] = 0
    fractional = {s for s, a in assets.items() if a.get("fractionable")}
    prices = pd.Series(b.latest_prices(sorted(assets)), dtype=float)
    equity = float(b.account()["equity"])
    target = target_shares(sides, prices, equity, leg=cfg.leg, fractional=fractional)
    plan = trades(target, current, prices, per_name_value(sides, equity, leg=cfg.leg), cfg.min_frac)
    gross = {k: sum(abs(q) * float(prices.get(s, 0)) for s, q in target.items() if np.sign(q) == sign) / equity
             for k, sign in (("long", 1), ("short", -1))}
    biggest = sorted(plan, key=lambda x: -abs(plan[x][1] - plan[x][0]) * prices.get(x, 0))[:cfg.profile_symbols]
    profile, profile_days = _profile(d, biggest, sessions, today)
    weights = buckets_left(minutes, profile=profile)
    log = {"date": f"{today:%Y-%m-%d}", "formation_close": prev_close.isoformat(), "equity": equity,
           "config": asdict(cfg), "first_run": empty, "catch_up": dec.catch_up,
           "stocks_with_signal": len(one), "missing_scores": missing,
           "long": int((sides == 1).sum()), "short": int((sides == -1).sum()),
           "not_shortable": sorted(s for s, ok in shortable.items() if not ok),
           "asset_lookup_failed": sorted(s for s, a in assets.items() if not a),
           "start_minute": round(minutes, 1), "buckets": [m for m, _ in weights], "profile": list(profile),
           "profile_stock_days": profile_days, "arrival": {s: float(prices[s]) for s in plan if s in prices},
           "target": {s: float(q) for s, q in target.items()}, "leg": cfg.leg,
           "target_gross": {k: round(v, 4) for k, v in gross.items()},
           "too_expensive": too_expensive(sides, target, prices),
           "signal": one[["symbol", "form", "composite", "q"]].to_dict("records"), "orders": []}
    d.log(f"rebalance {today:%Y-%m-%d}: {len(plan)} stocks to trade, {len(weights)} buckets from minute "
          f"{weights[0][0]}; long {log['long']}, short {log['short']}, equity {equity:,.0f}; target gross long "
          f"{gross['long']:.3f}, short {gross['short']:.3f}; too expensive {log['too_expensive']}")
    if dry_run:
        for s, (a, q) in list(plan.items())[:15]:
            d.log(f"  {s:6} {a:>8} -> {q:>8}")
        d.notes["plan"] = plan
        return True, f"dry run: {len(plan)} stocks would trade", {"dry_run": True}

    first = d.store / f"rebalance_{today:%Y%m%d}.json"
    tag = f"{d.now():%H%M}"
    if first.exists():
        if not plan:
            return True, f"rebalance {today:%Y-%m-%d} done earlier; nothing left to trade", {}
        log["rerun_of"] = first.name
    path = d.store / f"rebalance_{today:%Y%m%d}_{tag}.json" if first.exists() else first
    w = [x for _, x in weights]
    kids = {s: child_orders(a, q, w, unit_of(s, a, q, fractional)) for s, (a, q) in plan.items()}
    stopped: set[str] = set()
    for k, (start_min, _) in enumerate(weights):
        wait = (open_utc + pd.Timedelta(minutes=start_min) - d.now()).total_seconds()
        if wait > 0:
            d.sleep(wait)
        for s, per_bucket in kids.items():
            for j, q in enumerate(per_bucket[k]):
                if s in stopped:
                    break
                try:
                    o = b.submit(s, abs(q), side_of(q), f"gd-{today:%Y%m%d}-{tag}-{k:02d}{j}-{s}")
                    log["orders"].append({"symbol": s, "bucket": k, "qty": q, "id": o["id"], "status": o["status"]})
                    if j == 0 and len(per_bucket[k]) > 1:
                        _wait_filled(d, o["id"])  # a flip: the close must fill before the open
                except BrokerError as e:
                    if e.permanent:
                        stopped.add(s)  # a rejected order: this stock's later children would fail the same way
                    log["orders"].append({"symbol": s, "bucket": k, "qty": q, "error": e.message,
                                          "status_code": e.status})
                    if not e.permanent:
                        break  # a rate limit or server error: skip this child; the next bucket tries again
        path.write_text(json.dumps(log, indent=1, default=str))
    _final_fills(d, log)
    log["recon"] = reconcile(log["target"], b.position_rows(), float(b.account()["equity"]))
    path.write_text(json.dumps(log, indent=1, default=str))
    errs = sum(1 for o in log["orders"] if "error" in o)
    r = log["recon"]
    ok = errs == 0 and r["on_target"] >= 0.9 * r["stocks_target"]
    return ok, (f"rebalance {today:%Y-%m-%d}: {len(log['orders'])} orders, {errs} rejected; on target "
                f"{r['on_target']}/{r['stocks_target']}, off {r['off_pct']}%"), {
        "orders": len(log["orders"]), "rejected": errs, "on_target": r["on_target"], "off_pct": r["off_pct"]}


def _profile(d: Deps, symbols: list[str], sessions: pd.DataFrame, today: pd.Timestamp):
    """D16: the volume profile of the last 20 sessions' first hour; the Step 4 profile if bars cannot be read."""
    past = sessions[sessions["date"] < today]
    if not symbols or len(past) < 20:
        return learned_profile(pd.DataFrame())
    try:
        bars = d.minute_bars(symbols, past["open_utc"].iloc[-20], past["close_utc"].iloc[-1])
    except Exception as e:  # noqa: BLE001 - execution falls back to the fixed profile
        d.log(f"profile: minute bars failed ({type(e).__name__}); fixed profile")
        return learned_profile(pd.DataFrame())
    return learned_profile(bars)


def _asset(b, symbol: str) -> dict:
    try:
        return b.asset(symbol)
    except BrokerError:
        return {}


def _wait_filled(d: Deps, order_id: str, timeout_s: float = 120) -> None:
    t0 = d.now()
    while (d.now() - t0).total_seconds() < timeout_s:
        if d.broker.order(order_id)["status"] in ("filled", "canceled", "rejected", "expired"):
            return
        d.sleep(2)


def _final_fills(d: Deps, log: dict) -> None:
    d.sleep(20)
    for o in log["orders"]:
        if "id" in o:
            try:
                r = d.broker.order(o["id"])
                o.update(status=r["status"], filled_qty=float(r.get("filled_qty") or 0),
                         price=float(r["filled_avg_price"]) if r.get("filled_avg_price") else None,
                         filled_at=r.get("filled_at"))
            except BrokerError as e:
                o["fill_error"] = e.message
