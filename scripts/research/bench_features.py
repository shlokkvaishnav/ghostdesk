"""Speed of the feature engine against plain pandas on the real panel (2016 to the validation end).

Times, for the 158 Alpha158 factors: the engine on all symbols (cold, no cache), the engine again (warm cache), and
the engine and the pandas reference on the same `--pandas-symbols` symbols (pandas on all ~650 symbols takes too long
for a laptop: its regression factors call numpy.polyfit once per window). Checks that both have the same missing
cells, and records the factors whose values differ (by |a - b| / (|b| + 1e-6) > 1e-6) with the share of cells: these
are near-constant windows where pandas' running rolling variance leaves a residue (about 1e-9) instead of 0.
Writes data/results/bench_features.json.
Usage: python -u scripts/research/bench_features.py [--pandas-symbols 50]
"""
import argparse
import json
import shutil
import tempfile
import time
from pathlib import Path

import numpy as np
import pandas as pd

from ghostdesk.features.alpha158 import alpha158
from ghostdesk.features.engine import FeatureEngine
from ghostdesk.features.pandas_reference import alpha158_pandas
from ghostdesk.paths import DATA_DIR
from ghostdesk.research.dataset import load_panel
from ghostdesk.research.holdout_lock import TRAIN_START, VAL_END

ap = argparse.ArgumentParser()
ap.add_argument("--pandas-symbols", type=int, default=50)
args = ap.parse_args()

p = load_panel(TRAIN_START, VAL_END)
exprs = alpha158()
t, n = p.fields["close"].shape
print(f"panel {t} sessions x {n} symbols", flush=True)
cache = Path(tempfile.mkdtemp())
try:
    t0 = time.perf_counter()
    eng = FeatureEngine(p.fields, cache_dir=cache, data_key=p.data_key)
    full = eng.compute(exprs)
    cold = time.perf_counter() - t0
    stats_cold = dict(eng.stats)
    t0 = time.perf_counter()
    warm_eng = FeatureEngine(p.fields, cache_dir=cache, data_key=p.data_key)
    warm_eng.compute(exprs)
    warm = time.perf_counter() - t0
    cache_mb = sum(f.stat().st_size for f in cache.rglob("*.npy")) / 1e6
finally:
    shutil.rmtree(cache, ignore_errors=True)
print(f"engine cold {cold:.2f} s, warm {warm:.2f} s; {stats_cold}", flush=True)

k = min(args.pandas_symbols, n)
sub = {f: m[:, :k] for f, m in p.fields.items()}
t0 = time.perf_counter()
FeatureEngine(sub).compute(exprs)
eng_sub = time.perf_counter() - t0
long = pd.DataFrame({"symbol": np.repeat(p.symbols[:k], t), "day": np.tile(p.days, k),
                     **{f: sub[f].T.reshape(-1) for f in sub}})
t0 = time.perf_counter()
ref = alpha158_pandas(long)
pd_sub = time.perf_counter() - t0
worst, by_factor = 0.0, {}
for name in exprs:
    a, b = full[name][:, :k], ref[name].to_numpy().reshape(k, t).T
    both = np.isfinite(a) & np.isfinite(b)
    if not (np.isnan(a) == np.isnan(b)).all():
        i, j = np.argwhere(np.isnan(a) != np.isnan(b))[0]
        raise AssertionError(f"{name} {p.days[i]} {p.symbols[j]}: engine {a[i, j]}, pandas {b[i, j]}, "
                             f"closes {p.fields['close'][i - 11:i + 1, j]}")
    if both.any():
        d = np.abs(a[both] - b[both]) / (np.abs(b[both]) + 1e-6)
        by_factor[name] = (float(d.max()), float((d > 1e-6).mean()))
        worst = max(worst, float(d.max()))
print("factors with any difference > 1e-6 (max, share of cells):",
      {k: v for k, v in by_factor.items() if v[0] > 1e-6}, flush=True)
out = {"sessions": t, "symbols": n, "factors": len(exprs), "engine_cold_s": round(cold, 3),
       "engine_warm_s": round(warm, 3), "cache_mb": round(cache_mb, 1), "engine_stats": stats_cold,
       "subset_symbols": k, "engine_subset_s": round(eng_sub, 3), "pandas_subset_s": round(pd_sub, 3),
       "speedup_subset": round(pd_sub / eng_sub, 1), "max_diff_rel_to_abs_plus_1e-6": worst,
       "differing_factors": {k: v for k, v in by_factor.items() if v[0] > 1e-6},
       "at": pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds")}
print(json.dumps(out), flush=True)
res = DATA_DIR / "results"
res.mkdir(exist_ok=True)
(res / "bench_features.json").write_text(json.dumps(out, indent=1))
