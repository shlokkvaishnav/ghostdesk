"""Archive the paper account of the monthly desk before it is closed (decision D38).

Read-only: only GET requests to the Alpaca paper API. Writes positions, open orders, account values, every order,
every fill and the portfolio history to `docs/archive/monthly-desk-2026-11/` (or the folder given). Account number,
account id and any key are left out. Run with `--final` after the account is closed to write only `final_state.json`.

    PYTHONPATH=src .venv/bin/python -u scripts/ops/archive_account.py [--out DIR] [--final]
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from ghostdesk.live.alpaca_broker import Broker

OUT = Path("docs/archive/monthly-desk-2026-11")
ACCOUNT_FIELDS = ("status", "currency", "equity", "last_equity", "cash", "long_market_value", "short_market_value",
                  "buying_power", "initial_margin", "maintenance_margin", "multiplier", "created_at")
DROP = {"account_id", "account_number"}


def _clean(rows: list[dict]) -> list[dict]:
    return [{k: v for k, v in r.items() if k not in DROP} for r in rows]


def all_orders(b: Broker) -> list[dict]:
    """Every order, newest first, paged by `until` (500 per page)."""
    out, until, seen = [], None, set()
    while True:
        p = {"status": "all", "limit": 500, "direction": "desc", "nested": "false"}
        if until:
            p["until"] = until
        page = [o for o in b._req("GET", "/orders", params=p) if o["id"] not in seen]
        if not page:
            return out
        out += page
        seen.update(o["id"] for o in page)
        until = page[-1]["submitted_at"]


def all_fills(b: Broker) -> list[dict]:
    out, token = [], None
    while True:
        p = {"activity_types": "FILL", "page_size": 100, "direction": "desc"}
        if token:
            p["page_token"] = token
        page = b._req("GET", "/account/activities", params=p)
        if not page:
            return out
        out += page
        token = page[-1]["id"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--final", action="store_true")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    b = Broker()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    acct = b.account()
    account = {"at": now, "paper": b.base.startswith("https://paper-api."),
               **{k: acct.get(k) for k in ACCOUNT_FIELDS}}
    positions = _clean(b._req("GET", "/positions"))
    opens = _clean(b._req("GET", "/orders", params={"status": "open", "limit": 500}))
    if a.final:
        (a.out / "final_state.json").write_text(json.dumps(
            {"account": account, "positions": len(positions), "open_orders": len(opens),
             "position_rows": positions, "open_order_rows": opens}, indent=1) + "\n")
        print(f"final: {len(positions)} positions, {len(opens)} open orders, equity {account['equity']}")
        return
    orders, fills = _clean(all_orders(b)), _clean(all_fills(b))
    hist = b._req("GET", "/account/portfolio/history", params={"period": "all", "timeframe": "1D"})
    files = {"account.json": account, "positions.json": positions, "open_orders.json": opens,
             "orders_all.json": orders, "fills.json": fills, "portfolio_history.json": hist}
    for name, obj in files.items():
        (a.out / name).write_text(json.dumps(obj, indent=1) + "\n")
    filled = sum(o["status"] == "filled" for o in orders)
    print(f"archived at {now}: {len(positions)} positions, {len(opens)} open orders, {len(orders)} orders "
          f"({filled} filled), {len(fills)} fills, {len(hist.get('equity') or [])} history points")


if __name__ == "__main__":
    main()
