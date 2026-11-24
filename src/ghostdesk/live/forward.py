"""The whole forward evaluation as one pure function of its inputs (decision D37).

`build_report` takes the ledger rows, the nightly books, raw bars and the validation results and returns the
JSON-ready dict that the page and `data/live/forward_eval.json` use. `read_books` loads `night_*.json`. Nothing here
touches the network or places an order; with no ledger the report says `forward_days: 0`.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from ghostdesk.live.compare import compare
from ghostdesk.live.evaluate import daily_metrics, summarize
from ghostdesk.live.ledger import score
from ghostdesk.live.portfolio import book_days, book_summary, curve
from ghostdesk.research.backtest import half_spread


def read_books(live_dir: Path) -> dict[pd.Timestamp, dict]:
    """`night_<YYYYMMDD>.json` files -> session -> {"target": shares, "equity": equity}. Unreadable files and nights
    without a plan (no `target`) are left out."""
    out = {}
    for p in sorted(Path(live_dir).glob("night_*.json")):
        try:
            d = json.loads(p.read_text())
            out[pd.Timestamp(p.stem.split("_")[1])] = {"target": d["target"], "equity": d["equity"]}
        except (OSError, ValueError, KeyError, IndexError):
            continue
    return out


def _wide(raw: pd.DataFrame, col: str) -> pd.DataFrame:
    return raw.pivot(index="day", columns="symbol", values=col).sort_index()


def build_report(ledger_rows: pd.DataFrame, books: dict[pd.Timestamp, dict], raw: pd.DataFrame,
                 sectors: dict[str, str] | None, validation: dict) -> dict:
    """`raw`: raw daily bars (day, symbol, o, h, l, c). Returns forward summary, daily rows, book metrics and curve,
    and the validation-versus-forward table."""
    if raw.empty or ledger_rows.empty:
        opens = pd.DataFrame()
        hs = None
        scored = score(ledger_rows, opens, None, None)
    else:
        opens = _wide(raw, "o")
        hi, lo, cl = (_wide(raw, c).reindex_like(opens) for c in ("h", "l", "c"))
        hs = pd.DataFrame(half_spread(hi.to_numpy(), lo.to_numpy(), cl.to_numpy()), index=opens.index,
                          columns=opens.columns)
        scored = score(ledger_rows, opens, hs, pd.Series(sectors) if sectors else None)
    daily = daily_metrics(scored)
    fwd = summarize(daily)
    bdays = book_days(books, opens, hs) if len(opens) else book_days({}, opens)
    book = book_summary(bdays)
    return {"forward": fwd,
            "daily": [{"session": f"{r.session:%Y-%m-%d}", "model": r.model,
                       **{k: (None if pd.isna(v) else float(v)) for k, v in
                          (("ic", r.ic), ("hit", r.hit), ("pnl", r.pnl))}} for r in daily.itertuples()],
            "book": {**book, "curve": curve(bdays)},
            "compare": compare(validation, fwd, book)}
