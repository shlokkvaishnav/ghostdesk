"""The data of the web page (site-data/live.json). Pure function of what the job read, so it is tested offline.

Only what the page shows: the account's equity curve and SPY on the same scale (returns, not raw prices), the
positions with their signal, the newest scored reports, a summary of each rebalance (orders, rejects, cost against
the arrival price), and the health of the three job modes.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ghostdesk.evaluation.portfolio_stats import FULL
from ghostdesk.live.live_signal import composite, quintile
from ghostdesk.live.order_planning import FIRST_HOUR_PROFILE

# What the backtest leads us to expect for the account (2016-2025 pooled, `composite` long-short after 5 bps, one leg
# = 0.9 of equity as in D15): mean and standard deviation of the monthly return. Shown as a band behind the live
# curve; with a mean near 0 the band says "expect noise", which is the honest prior for a signal not detected.
EXPECTED_MONTH = {"mean": 0.9 * 0.001338, "sd": 0.9 * 0.01797, "source": "pooled 2016-2025 backtest, after 5 bps"}


def reconcile(target: dict[str, float], positions: list[dict], equity: float) -> dict:
    """Target (latest rebalance log) against the positions now, at today's prices. A stock is on target when the
    value off target is at most 20% of its target value. `off_pct`: sum of |value off target| in % of equity."""
    held = {p["symbol"]: (float(p["qty"]), float(p.get("current_price") or 0)) for p in positions}
    rows = []
    for s in sorted(set(target) | set(held)):
        t = float(target.get(s, 0.0))
        q, px = held.get(s, (0.0, 0.0))
        rows.append({"symbol": s, "target": t, "actual": q, "price": px, "off_value": round((q - t) * px, 2)})
    priced = [r for r in rows if r["price"] > 0]

    def gross(sign: int, key: str) -> float:
        return round(sum(abs(r[key]) * r["price"] for r in priced if sign * r[key] > 0) / equity * 100, 2)

    return {"stocks_target": sum(1 for r in rows if r["target"]),
            "on_target": sum(1 for r in priced if r["target"]
                             and abs(r["off_value"]) <= 0.2 * abs(r["target"]) * r["price"]),
            "missing": sorted(r["symbol"] for r in rows if r["target"] and not r["actual"]),
            "extra": sorted(r["symbol"] for r in rows if r["actual"] and not r["target"]),
            "off_pct": round(sum(abs(r["off_value"]) for r in priced) / equity * 100, 2),
            "gross": {side: {"target": gross(sign, "target"), "actual": gross(sign, "actual")}
                      for side, sign in (("long", 1), ("short", -1))},
            "worst": [{k: r[k] for k in ("symbol", "target", "actual", "off_value")}
                      for r in sorted(priced, key=lambda r: -abs(r["off_value"]))[:5]]}


def equity_curve(history: pd.DataFrame, spy: pd.DataFrame) -> list[dict]:
    """day, account return and SPY return (both from the first day with equity), in %."""
    h = history[history["equity"] > 0].sort_values("day")
    if h.empty:
        return []
    s = spy.assign(day=pd.to_datetime(spy["t"], utc=True).dt.tz_convert("America/New_York").dt.normalize()
                   .dt.tz_localize(None)).set_index("day")["c"] if len(spy) else pd.Series(dtype=float)
    s = s.reindex(h["day"]).ffill()
    e0, s0 = float(h["equity"].iloc[0]), (s.dropna().iloc[0] if s.notna().any() else np.nan)
    return [{"day": f"{d:%Y-%m-%d}", "account": round((e / e0 - 1) * 100, 3),
             "spy": None if pd.isna(v) else round((v / s0 - 1) * 100, 3)}
            for d, e, v in zip(h["day"], h["equity"], s.to_numpy(), strict=True)]


def report_scores(scores: pd.DataFrame, members: pd.DataFrame, at: pd.Timestamp, days: int = 120) -> pd.DataFrame:
    """The latest scored pair of each member (accepted in the last `days`), with `composite` and `q` across them."""
    s = scores[(scores["error"].fillna("") == "") & scores[FULL].notna().all(axis=1)].copy()
    s["accepted_utc"] = pd.to_datetime(s["accepted_utc"], utc=True)
    s = s[s["accepted_utc"] > at - pd.Timedelta(days=days)]
    s = s.sort_values("accepted_utc").drop_duplicates("cik", keep="last")
    s = s.merge(members.drop_duplicates("cik")[["cik", "symbol", "name", "sector"]], on="cik", how="inner")
    if s.empty:
        return s.assign(composite=[], q=[])
    s["composite"] = composite(s).to_numpy()
    s["q"] = quintile(s["composite"]).to_numpy()
    return s


def rebalance_summary(log: dict) -> dict:
    """Orders, fills, rejects, and the cost of the fills against the arrival price, in bps of traded value
    (positive = paid more than the arrival price). Paper fills are simulated by Alpaca."""
    orders = log.get("orders", [])
    filled = [o for o in orders if o.get("price") and o.get("filled_qty")]
    arrival = log.get("arrival", {})
    num = den = 0.0
    for o in filled:
        a = arrival.get(o["symbol"])
        if a:
            v = o["filled_qty"] * a
            num += np.sign(o["qty"]) * (o["price"] - a) / a * 1e4 * v
            den += v
    return {"date": log.get("date"), "orders": len(orders), "filled": len(filled),
            "rejected": sum(1 for o in orders if "error" in o), "stocks": len({o["symbol"] for o in orders}),
            "traded_value": round(den, 2), "cost_bps": round(num / den, 2) if den else None,
            "long": log.get("long"), "short": log.get("short"), "first_run": log.get("first_run", False),
            "start_minute": log.get("start_minute")}


def build(account: dict, positions: list[dict], history: pd.DataFrame, spy: pd.DataFrame, rebalances: list[dict],
          scores: pd.DataFrame | None, members: pd.DataFrame | None, health: dict, at: pd.Timestamp,
          next_rebalance: str | None = None) -> dict:
    names = {} if members is None else members.drop_duplicates("symbol").set_index("symbol")[["name", "sector"]]
    sig = {}
    if rebalances:
        sig = {r["symbol"]: r for r in rebalances[-1].get("signal", [])}
    pos = []
    for p in positions:
        s = p["symbol"]
        info = names.loc[s] if len(names) and s in names.index else None
        pos.append({"symbol": s, "name": None if info is None else info["name"],
                    "sector": None if info is None else info["sector"], "qty": round(float(p["qty"]), 4),
                    "value": round(float(p["market_value"]), 2), "pl_pct": round(float(p["unrealized_plpc"]) * 100, 2),
                    "q": sig.get(s, {}).get("q"), "form": sig.get(s, {}).get("form")})
    reports, universe = [], []
    if scores is not None and members is not None and len(scores):
        r = report_scores(scores, members, at)
        universe = [{"symbol": x.symbol, "rank": round(float(x.composite), 4), "q": None if pd.isna(x.q) else int(x.q),
                     "form": x.form, "accepted": f"{x.accepted_utc:%Y-%m-%d}"} for x in r.itertuples()]
        r = r[r["accepted_utc"] > at - pd.Timedelta(days=45)].sort_values("accepted_utc", ascending=False)
        reports = [{"symbol": x.symbol, "name": x.name, "form": x.form, "accepted": f"{x.accepted_utc:%Y-%m-%d}",
                    "similarity": round(float(x.sim_full_cosine), 4), "rank": round(float(x.composite), 3),
                    "q": None if pd.isna(x.q) else int(x.q)} for x in r.head(80).itertuples()]
    sectors: dict[str, dict] = {}
    for p in pos:
        k = p["sector"] or "Other"
        sectors.setdefault(k, {"long": 0.0, "short": 0.0})["long" if p["value"] > 0 else "short"] += abs(p["value"])
    eq = float(account.get("equity") or 0)
    return {"updated": at.isoformat(timespec="minutes"), "next_rebalance": next_rebalance,
            "account": {"equity": eq, "cash": float(account.get("cash") or 0),
                        "long": float(account.get("long_market_value") or 0),
                        "short": float(account.get("short_market_value") or 0)},
            "curve": equity_curve(history, spy), "positions": sorted(pos, key=lambda p: -abs(p["value"])),
            "sectors": [{"sector": k, **{x: round(v / eq * 100, 2) if eq else 0 for x, v in d.items()}}
                        for k, d in sorted(sectors.items())],
            "reports": reports, "universe": universe, "profile": list(rebalances[-1].get("profile", FIRST_HOUR_PROFILE)) if rebalances
            else list(FIRST_HOUR_PROFILE),
            "buckets": bucket_shares(rebalances[-1]) if rebalances else [],
            "rebalances": [rebalance_summary(r) for r in rebalances], "health": health,
            "expected_month": EXPECTED_MONTH,
            "recon": reconcile(_latest_target(rebalances), positions, eq) if rebalances and eq else None}


def _latest_target(rebalances: list[dict]) -> dict[str, float]:
    """The target of the latest rebalance day (a same-day rerun log carries the same target)."""
    return {s: float(q) for s, q in rebalances[-1].get("target", {}).items()}


def bucket_shares(log: dict) -> list[dict]:
    """Share of the rebalance's traded shares sent in each bucket (minute after the open, share)."""
    starts = log.get("buckets", [])
    q = [0.0] * len(starts)
    for o in log.get("orders", []):
        if "error" not in o and o.get("bucket", -1) < len(q):
            q[o["bucket"]] += abs(o["qty"])
    tot = sum(q) or 1.0
    return [{"minute": m, "share": round(v / tot, 4)} for m, v in zip(starts, q, strict=True)]
