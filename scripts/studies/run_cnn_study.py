"""The chart-CNN study (decision D19): 20-session price images -> CNN probability of an up month -> the same
evaluation as the signal and ML studies.
- `--period dev`: train on images of 2016-2019 (labels end by 2019-12-31), predict month-ends 2020-2021.
- `--period test`: needs the committed `docs/preregistration-cnn.md` (`return_models/holdout_lock.py`); train on 2016-2021 (labels
  end by 2021-12-31), predict month-ends 2022-01 to 2025-11, once.
Each run trains the given seeds (about 6 min each on an Apple GPU), saves their predictions, and evaluates the mean
of all seeds saved so far: data/cnn_<period>.json, data/cnn_predictions_<period>[_seed<n>].parquet.
Usage: python -u scripts/studies/run_cnn_study.py --period dev --seeds 0   (then --seeds 1, --seeds 2)
"""
import argparse
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from ghostdesk.data.fama_french import load_factors
from ghostdesk.evaluation.portfolio_stats import add_signals, ic, summary
from ghostdesk.filings.edgar_client import DATA_DIR
from ghostdesk.return_models import chart_cnn, holdout_lock
from ghostdesk.return_models.chart_images import matrices

PREREG = Path(__file__).resolve().parents[2] / "docs" / "preregistration-cnn.md"
ap = argparse.ArgumentParser()
ap.add_argument("--period", choices=["dev", "test"], default="dev")
ap.add_argument("--seeds", type=int, nargs="*", default=[0], help="seeds to train in this run (none: evaluate only)")
args = ap.parse_args()

panel = add_signals(pd.read_parquet(DATA_DIR / "panel_pooled.parquet"))
if args.period == "dev":
    sha, train_end, pred_from = None, "2019-12-31", "2020-01-01"
    panel = holdout_lock.dev(panel)
else:
    panel, sha = holdout_lock.everything(panel, PREREG)
    train_end, pred_from = "2021-12-31", "2022-01-01"
t0 = time.time()
prices = pd.read_parquet(DATA_DIR / "prices_daily.parquet", columns=["symbol", "t", "o", "h", "l", "c", "v"])
returns = pd.read_parquet(DATA_DIR / "returns_daily.parquet", columns=["symbol", "day", "flag"])
members = pd.read_parquet(DATA_DIR / "price_symbols.parquet")
factors = load_factors(DATA_DIR / "sources" / "ff")
mats = matrices(prices, returns)
x, y, keys = chart_cnn.training_images(mats, members, "2016-01-01", train_end, train_end)
print(f"training images {len(x)} (up share {y.mean():.3f}), {time.time() - t0:.0f}s", flush=True)
p = panel[panel["month"] >= pd.Timestamp(pred_from)].reset_index(drop=True)
img, ok = chart_cnn.prediction_images(mats, p, members)
for s in args.seeds:  # each seed: train, predict, save (one seed per run keeps a run under 10 minutes)
    m, h = chart_cnn.fit(x, y, s)
    p_s = p[["month", "cik"]].assign(pred=np.nan, seed=s)
    p_s.loc[ok, "pred"] = chart_cnn.predict([m], img)
    p_s.to_parquet(DATA_DIR / f"cnn_predictions_{args.period}_seed{s}.parquet", index=False)
    (DATA_DIR / f"cnn_{args.period}_seed{s}.json").write_text(json.dumps({"val_loss": h, "prereg_commit": sha}))
    print(f"seed {s} done, {time.time() - t0:.0f}s", flush=True)

# evaluate the mean of all seeds trained so far
files = sorted(DATA_DIR.glob(f"cnn_predictions_{args.period}_seed*.parquet"))
allp = pd.concat([pd.read_parquet(f) for f in files])
mean = allp.groupby(["month", "cik"])["pred"].mean().rename("pred").reset_index()
p = p.merge(mean, on=["month", "cik"], how="left")
s = summary(p, "pred", factors)
seeds = sorted(allp["seed"].unique().tolist())
out = {"period": args.period, "prereg_commit": sha, "train_images": len(x), "train_up_share": float(y.mean()),
       "seeds": seeds, "rows_with_image": float(ok.mean()), "cnn": s,
       "val_loss": {int(k): json.loads((DATA_DIR / f"cnn_{args.period}_seed{k}.json").read_text())["val_loss"]
                    for k in seeds},
       "ic_by_month": {str(k.date()): float(v) for k, v in ic(p, "pred").items()}}
print(f"CNN ({len(seeds)} seeds) LS net 5bps {s['long_short_net']['5bps']['mean']*100:+.2f}%/m "
      f"(t {s['long_short_net']['5bps']['t']:.2f})  IC {s['ic']['mean']:+.3f} (t {s['ic']['t']:.2f})  "
      f"traded {s['traded_monthly']:.2f}  {time.time() - t0:.0f}s")
p[["month", "cik", "pred"]].to_parquet(DATA_DIR / f"cnn_predictions_{args.period}.parquet", index=False)
(DATA_DIR / f"cnn_{args.period}.json").write_text(json.dumps(out, indent=1, default=float))
