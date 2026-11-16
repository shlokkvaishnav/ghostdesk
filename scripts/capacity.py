"""Capacity of the signal strategy (2016-2025 trades of the primary signal): monthly trading cost against fund size,
and the break-even size for three gross-return levels (the pooled estimate, the build-period estimate, and the upper
end of the pooled 95% interval). Needs data/panel_pooled.parquet and data/results_pooled.json (from
scripts/signal_study.py --period pooled). Writes data/capacity.json.
Usage: python -u scripts/capacity.py
"""
import json

import numpy as np
import pandas as pd

from ghostdesk.execution.capacity import break_even, capacity_curve, monthly_trades
from ghostdesk.filings.edgar import DATA_DIR
from ghostdesk.signal.study import PRIMARY

panel = pd.read_parquet(DATA_DIR / "panel_pooled.parquet")
returns = pd.read_parquet(DATA_DIR / "returns_daily.parquet", columns=["symbol", "day", "ret"])
vol = returns.pivot(index="day", columns="symbol", values="ret").rolling(63, min_periods=40).std()
panel["sigma"] = [vol.at[m, s] if (m in vol.index and s in vol.columns) else np.nan
                  for m, s in zip(panel["month"], panel["price_symbol"], strict=True)]
panel["sigma"] = panel["sigma"].fillna(panel["sigma"].median())
trades = monthly_trades(panel, PRIMARY)
aums = [1e6 * 10 ** (k / 4) for k in range(21)]  # $1M to $100B (past about $10B one-day trades exceed ADV)
curve = capacity_curve(trades, aums)

pooled = json.loads((DATA_DIR / "results_pooled.json").read_text())["measures"][PRIMARY]
build = json.loads((DATA_DIR / "results_build.json").read_text())["measures"][PRIMARY]
levels = {"pooled estimate": pooled["long_short_gross"]["mean"], "build estimate": build["long_short_gross"]["mean"],
          "pooled 95% upper": pooled["long_short_gross"]["ci95"][1]}
out = {"months": int(trades["month"].nunique()), "traded_weight_monthly": float(trades.groupby("month")["dw"].sum()
                                                                               .iloc[1:].mean()),
       "cost_curve": {f"{a:.0f}": float(c) for a, c in curve.items()},
       "gross_levels": levels, "break_even_aum": {k: break_even(curve, v) for k, v in levels.items()}}
(DATA_DIR / "capacity.json").write_text(json.dumps(out, indent=1))
print(f"traded weight per month: {out['traded_weight_monthly']:.2f}")
for a in (1e6, 1e7, 1e8, 1e9, 1e10):
    print(f"fund ${a:>14,.0f}: cost {curve[min(curve.index, key=lambda x: abs(x - a))] * 1e4:6.2f} bps per month")
for k, v in out["break_even_aum"].items():
    print(f"break-even at {k} ({levels[k] * 100:.2f}%/month gross): " + ("none on the curve" if np.isnan(v)
                                                                          else f"${v:,.0f}"))
