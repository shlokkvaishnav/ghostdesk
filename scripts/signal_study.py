"""The signal study for one period. Builds the stock-month panel for that period only and writes the results.

    python -u scripts/signal_study.py --period build            # formation months 2016-01 .. 2019-12
    python -u scripts/signal_study.py --period check            # 2020-01 .. 2021-12
    python -u scripts/signal_study.py --period test --prereg <commit of docs/preregistration.md>
    python -u scripts/signal_study.py --period pooled --prereg <commit>      # 2016-01 .. 2025-11

The test and pooled periods (they contain 2022-2025 returns) run only if docs/preregistration.md is committed, has
no uncommitted change, and `--prereg` is the commit that last changed it. It writes data/results_<period>.json and
data/panel_<period>.parquet (not in git).
"""
import argparse
import json
import subprocess

import pandas as pd

from ghostdesk.data.factors import load_factors
from ghostdesk.filings.edgar import DATA_DIR, REPO_ROOT, SUBMISSIONS, EdgarClient
from ghostdesk.signal.panel import MEASURES, build_panel
from ghostdesk.signal.study import NEUTRAL, PRIMARY, add_signals, summary

PERIODS = {"build": ("2016-01-01", "2019-12-31"), "check": ("2020-01-01", "2021-12-31"),
           "test": ("2022-01-01", "2025-11-30"), "pooled": ("2016-01-01", "2025-11-30")}
GUARDED = ("test", "pooled")  # periods that contain test-period returns

ap = argparse.ArgumentParser()
ap.add_argument("--period", choices=PERIODS, required=True)
ap.add_argument("--prereg", default="")
args = ap.parse_args()


def git(*a) -> str:
    return subprocess.run(["git", *a], cwd=REPO_ROOT, capture_output=True, text=True, check=False).stdout.strip()


if args.period in GUARDED:
    last = git("log", "-1", "--format=%H", "--", "docs/preregistration.md")
    if not last or git("status", "--porcelain", "--", "docs/preregistration.md"):
        raise SystemExit("docs/preregistration.md must be committed and unchanged before the test period runs")
    if not args.prereg or not last.startswith(args.prereg):
        raise SystemExit(f"--prereg must be the commit that last changed docs/preregistration.md ({last[:12]})")

start, end = PERIODS[args.period]
features = pd.read_parquet(DATA_DIR / "features.parquet")
members = pd.read_parquet(DATA_DIR / "price_symbols.parquet").merge(
    pd.read_parquet(DATA_DIR / "universe.parquet")[["ticker", "start", "valid_from"]], on=["ticker", "start"],
    how="left")
returns = pd.read_parquet(DATA_DIR / "returns_daily.parquet")
raw = pd.read_parquet(DATA_DIR / "prices_daily_raw.parquet", columns=["symbol", "t", "h", "l", "c", "v"])
sec = EdgarClient()
sic = {int(k): str(sec.get_json(SUBMISSIONS.format(cik=int(k))).get("sic", "")) for k in members["cik"].dropna().unique()}

panel = add_signals(build_panel(features, members, returns, raw, sic, start, end))
panel.to_parquet(DATA_DIR / f"panel_{args.period}.parquet", index=False)
factors = load_factors(DATA_DIR / "sources" / "ff")
results = {"period": args.period, "formation": [start, end], "primary": PRIMARY,
           "prereg_commit": git("log", "-1", "--format=%H", "--", "docs/preregistration.md") or None,
           "code_commit": git("rev-parse", "HEAD"),
           "panel": {"rows": len(panel), "months": int(panel["month"].nunique()),
                     "with_signal": float(panel[PRIMARY].notna().mean())},
           "measures": {m: summary(panel, m, factors) for m in [PRIMARY, NEUTRAL, *(f"{x}_r" for x in MEASURES)]
                        if panel[m].notna().sum() > 1000}}
(DATA_DIR / f"results_{args.period}.json").write_text(json.dumps(results, indent=1, default=str))
p = results["measures"][PRIMARY]
print(json.dumps({"period": args.period, "panel": results["panel"], "primary": PRIMARY,
                  "neutral_ls_net_5bps": results["measures"][NEUTRAL]["long_short_net"]["5bps"],
                  "ls_gross": p["long_short_gross"], "ls_net_5bps": p["long_short_net"]["5bps"], "ic": p["ic"],
                  "fm_signal": p["fama_macbeth"]["signal"], "alpha_net_5bps": {k: p["alpha_net_5bps"][k] for k in
                                                                               ("alpha_monthly", "t")},
                  "mde_monthly": p["mde_monthly_80pct_power"], "break_even_bps": p["break_even_bps"]}, indent=1))
