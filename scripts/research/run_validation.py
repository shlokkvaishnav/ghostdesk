"""The validation study (2021-2022) of every model, and the walk-forward runtime on 2016-2022.

1. Panel 2016 .. validation end from the store; the 158 Alpha158 factors (feature cache in data/cache/features).
2. Walk-forward: yearly folds predicting 2018 .. 2022, each trained on all earlier sessions minus a 2-session purge.
3. Each model's scores go to the experiment registry (run key = data + code + config); metrics on the validation
   years, and on 2018-2020 as a walk-forward check inside the train split.
4. Kaggle scores (data/kaggle/out/<model>_val.npz) are scored the same way if present.
5. Optimizer against the equal-weight top/bottom 10% book on the validation years, for the `--opt-model` scores.
6. `--verify`: run LightGBM again and check that its scores are bit-identical to the registered run.
Writes data/results/validation.json. The test period is never read (`research.holdout_lock`).
Usage: python -u scripts/research/run_validation.py [--verify] [--opt-model lightgbm] [--skip-opt]
"""
import argparse
import json
import time

import numpy as np
import pandas as pd

from ghostdesk.features.alpha158 import alpha158
from ghostdesk.features.engine import FeatureEngine
from ghostdesk.paths import DATA_DIR
from ghostdesk.research.backtest import decile_weights, evaluate, half_spread, walk_forward
from ghostdesk.research.dataset import load_panel, residual_label, rolling_beta
from ghostdesk.research.holdout_lock import TRAIN_START, VAL_END, VAL_START
from ghostdesk.research.models import Design, ExternalScores, rank_features, zoo
from ghostdesk.research.optimizer import OptConfig, optimize_path
from ghostdesk.research.registry import Registry, array_sha256

ap = argparse.ArgumentParser()
ap.add_argument("--verify", action="store_true")
ap.add_argument("--opt-model", default="lightgbm")
ap.add_argument("--skip-opt", action="store_true")
args = ap.parse_args()
T0 = time.perf_counter()
timing = {}


def lap(name, t):
    timing[name] = round(time.perf_counter() - t, 2)
    print(f"{name}: {timing[name]} s", flush=True)


t = time.perf_counter()
p = load_panel(TRAIN_START, VAL_END, warmup_days=0)
lap("load_panel", t)
t = time.perf_counter()
eng = FeatureEngine(p.fields, cache_dir=DATA_DIR / "cache" / "features", data_key=p.data_key)
feats = eng.compute(alpha158())
lap("features", t)
hist = np.lib.stride_tricks.sliding_window_view(np.isfinite(p.fields["close"]), 61, axis=0).all(-1)
mask = np.zeros_like(p.member)
mask[60:] = hist
mask &= p.member
t = time.perf_counter()
X, names = rank_features(feats, mask)
del feats
y = residual_label(p)
d = Design(X, y, mask, names, p.fields["close"])
lap("design", t)
ret = np.exp(np.log(p.raw_open[2:]) - np.log(p.raw_open[1:-1])) - 1
ret = np.vstack([ret, np.full((2, ret.shape[1]), np.nan)])  # row t: open(t+1) -> open(t+2), raw (as traded)
t = time.perf_counter()
hs = half_spread(p.fields["high"], p.fields["low"], p.fields["close"])
lap("spread", t)
years = list(range(2018, VAL_END.year + 1))
val_rows = np.where((p.days >= VAL_START) & (p.days <= VAL_END))[0]
chk_rows = np.where((p.days.year >= 2018) & (p.days.year <= 2020))[0]
reg = Registry()
results, keys, all_scores = {}, {}, {}
data_hash = p.data_key
for m in zoo():
    t = time.perf_counter()
    s = walk_forward(m, d, p.days, years)
    secs = time.perf_counter() - t
    lap(f"walk_forward_{m.name}", t)
    w = decile_weights(s, mask)
    res = {"validation": evaluate(w, s, y, ret, hs, mask, val_rows)["summary"],
           "train_walk_forward_2018_2020": evaluate(w, s, y, ret, hs, mask, chk_rows)["summary"]}
    cfg = {"model": m.config(), "features": "alpha158", "years": years, "purge": 2, "label": "open-open residual"}
    keys[m.name] = reg.record(m.name, data_hash, cfg, s, res, secs, allow_dirty=False)
    results[m.name] = res
    all_scores[m.name] = s
    print(m.name, json.dumps(res["validation"]), flush=True)

for f in sorted((DATA_DIR / "kaggle" / "out").glob("*_val.npz")) if (DATA_DIR / "kaggle" / "out").exists() else []:
    z = np.load(f)
    name = f.name.replace("_val.npz", "")
    s = ExternalScores(name, z["days"], z["scores"], p.days).predict(d, np.arange(len(p.days)))
    w = decile_weights(s, mask)
    results[name] = {"validation": evaluate(w, s, y, ret, hs, mask, val_rows)["summary"], "source": f.name}
    all_scores[name] = s
    keys[name] = reg.record(name, data_hash, {"model": {"name": name}, "source": f.name,
                                              "file_sha256": array_sha256(z["scores"])}, s,
                            results[name], 0.0)
    print(name, json.dumps(results[name]["validation"]), flush=True)
timing["walk_forward_total_classic"] = round(sum(v for k, v in timing.items() if k.startswith("walk_forward_")), 2)

opt = None
if not args.skip_opt and args.opt_model in all_scores:
    s = all_scores[args.opt_model]
    cc = np.diff(np.log(p.fields["close"]), axis=0, prepend=np.nan)
    beta = rolling_beta(cc, np.diff(np.log(p.spy_close), prepend=np.nan))
    groups = sorted(set(p.sector))
    S = np.array([[sec == g for g in groups] for sec in p.sector], dtype=float)
    t = time.perf_counter()
    W, info = optimize_path(s, cc, beta, mask, S, hs, val_rows, OptConfig(), log=lambda x: print(x, flush=True))
    lap("optimizer_path", t)
    solve = np.array([i["solve_s"] for i in info])
    simple = decile_weights(s, mask)
    opt = {"model": args.opt_model, "config": OptConfig().__dict__,
           "solve_ms_median": round(float(np.median(solve) * 1e3), 1),
           "solve_ms_p95": round(float(np.percentile(solve, 95) * 1e3), 1),
           "status": pd.Series([i["status"] for i in info]).value_counts().to_dict(),
           "optimizer": evaluate(W, s, y, ret, hs, mask, val_rows)["summary"],
           "decile_book": evaluate(simple, s, y, ret, hs, mask, val_rows)["summary"],
           "max_abs_weight": round(float(np.abs(W[val_rows]).max()), 4),
           "mean_gross": round(float(np.abs(W[val_rows]).sum(axis=1).mean()), 3)}
    print(json.dumps({k: v for k, v in opt.items() if k != "config"}), flush=True)

verify = None
if args.verify:
    from ghostdesk.research.models import LightGBM

    t = time.perf_counter()
    same = reg.verify(keys["lightgbm"], lambda cfg: walk_forward(LightGBM(), d, p.days, years))
    lap("verify_lightgbm", t)
    verify = {"model": "lightgbm", "run_key": keys["lightgbm"], "bit_identical": bool(same)}
    print(verify, flush=True)

timing["total"] = round(time.perf_counter() - T0, 1)
out = {"panel": {"sessions": len(p.days), "symbols": len(p.symbols), "from": f"{p.days[0]:%Y-%m-%d}",
                 "to": f"{p.days[-1]:%Y-%m-%d}", "features": len(names), "feature_stats": eng.stats},
       "folds_years": years, "validation": [f"{VAL_START:%Y-%m-%d}", f"{VAL_END:%Y-%m-%d}"], "models": results,
       "run_keys": keys, "optimizer": opt, "verify": verify, "timing_s": timing,
       "at": pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds")}
(DATA_DIR / "results").mkdir(exist_ok=True)
(DATA_DIR / "results" / "validation.json").write_text(json.dumps(out, indent=1, default=str))
print("total", timing["total"], "s", flush=True)
