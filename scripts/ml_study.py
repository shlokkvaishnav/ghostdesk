"""The ML study (decision D18): point-in-time characteristics -> walk-forward models -> the same evaluation as the
signal study. `--period dev` uses formation months up to 2021 only (predictions 2019-2021; the tree settings are
chosen on 2020-2021). `--period test` needs the committed ML pre-registration (`ml/split.py`), and scores
2022-2025 once with the settings it names.
Writes data/ml_<period>.json and data/ml_predictions_<period>.parquet.
Usage: python -u scripts/ml_study.py --period dev
"""
import argparse
import json

import pandas as pd

from ghostdesk.data.factors import load_factors
from ghostdesk.filings.edgar import DATA_DIR
from ghostdesk.ml import split
from ghostdesk.ml.characteristics import ALL, add_characteristics, rank_features
from ghostdesk.ml.models import GBM_GRID, gbm, ridge, walk_forward
from ghostdesk.signal.study import add_signals, ic, mean_t, summary

ap = argparse.ArgumentParser()
ap.add_argument("--period", choices=["dev", "test"], default="dev")
args = ap.parse_args()

panel = add_signals(pd.read_parquet(DATA_DIR / "panel_pooled.parquet"))
if args.period == "dev":
    panel, sha, first, score_from = split.dev(panel), None, "2019-01-01", "2019-01-01"
else:
    panel, sha = split.everything(panel)
    first = score_from = str(split.TEST_START.date())
members = pd.read_parquet(DATA_DIR / "price_symbols.parquet")
returns = pd.read_parquet(DATA_DIR / "returns_daily.parquet")
raw = pd.read_parquet(DATA_DIR / "prices_daily_raw.parquet", columns=["symbol", "t", "h", "l", "c", "v"])
features = pd.read_parquet(DATA_DIR / "features.parquet")
factors = load_factors(DATA_DIR / "sources" / "ff")

chars = add_characteristics(panel, members, returns, raw, features)
x = rank_features(chars)
models = {"linear": ridge()} | {f"gbm_{k}": gbm(v) for k, v in GBM_GRID.items()}
TESTED = "gbm_large"  # chosen on 2020-2021 IC (decision D18); the only tree setting run in the test
if args.period == "test":
    models = {"linear": models["linear"], TESTED: models[TESTED]}
ics, preds, out = {}, [], {"period": args.period, "prereg_commit": sha, "features": ALL, "models": {}}
for name, fit in models.items():
    pr = walk_forward(x, ALL, fit, first=first)
    preds.append(pr.assign(model=name))
    p = chars.merge(pr[["month", "cik", "pred"]], on=["month", "cik"])
    p = p[p["month"] >= pd.Timestamp(score_from)]
    s = summary(p, "pred", factors)
    ics[name] = ic(p, "pred")
    by = {}
    for label, sub in (("2019", p[p["month"].dt.year == 2019]), ("2020-2021", p[p["month"].dt.year >= 2020])):
        if len(sub):
            ss = summary(sub, "pred", factors)
            by[label] = {"ls_net_5bps": ss["long_short_net"]["5bps"], "ic": ss["ic"]}
    out["models"][name] = s | {"by_period": by}
    print(f"{name:12s} LS net 5bps {s['long_short_net']['5bps']['mean']*100:+.2f}%/m (t {s['long_short_net']['5bps']['t']:.2f})"
          f"  IC {s['ic']['mean']:+.3f} (t {s['ic']['t']:.2f})  traded {s['traded_monthly']:.2f}", flush=True)
out["ic_gbm_minus_linear"] = mean_t((ics[TESTED] - ics["linear"]).dropna(), 3)
for single in ("composite", "mom_12_1", "rev_1", "vol_63"):  # one characteristic each, the same harness
    p = chars[chars["month"] >= pd.Timestamp(score_from)]
    s = summary(p, single, factors)
    out["models"][f"single_{single}"] = s
    print(f"{single:12s} LS gross {s['long_short_gross']['mean']*100:+.2f}%/m  IC {s['ic']['mean']:+.3f}", flush=True)
pd.concat(preds).to_parquet(DATA_DIR / f"ml_predictions_{args.period}.parquet", index=False)
(DATA_DIR / f"ml_{args.period}.json").write_text(json.dumps(out, indent=1, default=float))
