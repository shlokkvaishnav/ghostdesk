"""Pieces of the site data that are pure functions of broker answers: the book against its target, and the
account's equity against SPY.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def reconcile(target: dict[str, float], positions: list[dict], equity: float) -> dict:
    """Target (the night's plan) against the positions now, at today's prices. A stock is on target when the
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
