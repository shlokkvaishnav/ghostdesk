"""Fit the frozen live models once: ridge and LightGBM on every session from 2016 to the validation end (minus the
2-session purge), the same settings as the validation study. Writes data/live/models/ (ridge.npy, lightgbm.txt,
sectors.json = price symbol -> SIC group, meta.json with the ensemble weights, the code commit and the data hash).
These files go to the encrypted release with the rest of the live state; the nightly run only loads them.
Usage: python -u scripts/research/fit_live_models.py
"""
import json

import numpy as np
import pandas as pd

from ghostdesk.features.alpha158 import alpha158
from ghostdesk.features.engine import FeatureEngine
from ghostdesk.live.predict import LIVE_MODELS, ensemble_weights, save_models
from ghostdesk.paths import DATA_DIR
from ghostdesk.research.dataset import load_panel, residual_label
from ghostdesk.research.holdout_lock import TRAIN_START, VAL_END
from ghostdesk.research.models import Design, LightGBM, Ridge, rank_features
from ghostdesk.research.registry import code_commit

p = load_panel(TRAIN_START, VAL_END, warmup_days=0)
feats = FeatureEngine(p.fields, cache_dir=DATA_DIR / "cache" / "features", data_key=p.data_key).compute(alpha158())
hist = np.lib.stride_tricks.sliding_window_view(np.isfinite(p.fields["close"]), 61, axis=0).all(-1)
mask = np.zeros_like(p.member)
mask[60:] = hist
mask &= p.member
X, names = rank_features(feats, mask)
d = Design(X, residual_label(p), mask, names, p.fields["close"])
rows = np.arange(0, len(p.days) - 2)  # the last 2 sessions have no label
models = {"ridge": Ridge().fit(d, rows), "lightgbm": LightGBM().fit(d, rows)}
val = json.loads((DATA_DIR / "results" / "validation.json").read_text())
weights = ensemble_weights(val, LIVE_MODELS)
out = DATA_DIR / "live" / "models"
meta = {"fitted_on": [f"{p.days[0]:%Y-%m-%d}", f"{p.days[rows[-1]]:%Y-%m-%d}"], "models": list(LIVE_MODELS),
        "ensemble_weights": weights, "features": names, "code_commit": code_commit(), "data_hash": p.data_key,
        "validation_run_keys": val["run_keys"], "at": pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds")}
save_models(models, out, meta)
(out / "sectors.json").write_text(json.dumps(dict(zip(p.symbols, p.sector.tolist(), strict=True))))
print(json.dumps({k: v for k, v in meta.items() if k != "features"}, indent=1))
