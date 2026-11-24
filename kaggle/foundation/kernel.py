"""Kaggle GPU kernel: zero-shot forecasts of three time-series foundation models (decision D31). No fine-tuning.

For every validation session t (2021-2022) and every index member with 512 finite sessions of history through t:
- Chronos-2 (amazon/chronos-2) and TimesFM-2.5 (google/timesfm-2.5-200m-pytorch): the adjusted close series through
  the close of t; forecast 2 steps; score = log(median close(t+2) / median close(t+1)).
- Kronos-small (NeoQuasar/Kronos-small, Kronos-Tokenizer-base): the OHLCV candles through t; forecast 2 candles;
  score = log(open(t+2) / open(t+1)), the label's own window; mean of 3 samples (seeded).
Each model runs inside its own try block, so one failure does not lose the others; errors go to meta.json.
Output: /kaggle/working/<model>_val.npz (days, scores session x symbol) and meta.json.
"""
import json
import os
import subprocess
import sys
import time
import traceback

import numpy as np

OUT = os.environ.get("OUT", "/kaggle/working")
SMOKE = os.environ.get("SMOKE")
CTX = 512
t0 = time.time()
meta = {"errors": {}, "minutes": {}, "series": {}}


def sh(cmd):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return r.returncode, (r.stdout + r.stderr)[-2000:]


if not SMOKE:
    meta["install"] = {
        "chronos": sh("pip install -q 'chronos-forecasting>=2.1'"),
        "timesfm": sh("pip install -q 'timesfm[torch] @ git+https://github.com/google-research/timesfm.git'"),
        "kronos": sh("git clone -q https://github.com/shiyu-coder/Kronos /kaggle/working/Kronos && "
                     "pip install -q einops safetensors huggingface_hub"),
    }
import torch

path = os.environ.get("PANEL") or next(
    os.path.join(r, f) for r, _, fs in os.walk("/kaggle/input") for f in fs if f == "panel.npz")
src = np.load(path, allow_pickle=False)
days, member = src["days"], src["member"]
o, h, lo, c, v = (src[k].astype(np.float64) for k in ("open", "high", "low", "close", "volume"))
T, N = c.shape
val = [t for t in range(T) if days[t] >= 20210101]
if SMOKE:
    val = val[:2]
dev = "cuda" if torch.cuda.is_available() else "cpu"
meta["device"] = dev


def members(t):
    """Members at t with CTX finite sessions through t."""
    if t + 1 < CTX:
        return np.array([], dtype=int)
    w = np.isfinite(c[t + 1 - CTX: t + 1]).all(axis=0) & np.isfinite(o[t + 1 - CTX: t + 1]).all(axis=0)
    return np.where(member[t] & w)[0]


def save(name, scores):
    np.savez_compressed(f"{OUT}/{name}_val.npz", days=days[val], scores=scores.astype(np.float32))


def median_path(arr, n):
    """Model output -> (n, 2) medians, whatever the nesting (list of tensors, (n, H, Q) or (n, Q, H))."""
    if isinstance(arr, (list, tuple)):
        arr = np.stack([np.asarray(a.detach().cpu() if hasattr(a, "detach") else a, dtype=float).squeeze()
                        for a in arr])
    arr = np.asarray(arr.detach().cpu() if hasattr(arr, "detach") else arr, dtype=float)
    arr = arr.reshape(n, -1)
    return arr[:, :2] if arr.shape[1] == 2 else arr.reshape(n, 2, -1)[:, :, arr.shape[1] // 2 // 2]


def run(name, fn):
    s0 = time.time()
    scores = np.full((len(val), N), np.nan)
    count = 0
    try:
        for i, t in enumerate(val):
            cols = members(t)
            if len(cols):
                scores[i, cols] = fn(t, cols)
                count += len(cols)
            if i % 50 == 0:
                print(name, i, len(val), round((time.time() - t0) / 60, 1), "min", flush=True)
        save(name, scores)
    except Exception:  # noqa: BLE001 - keep the other models
        meta["errors"][name] = traceback.format_exc()[-3000:]
        print(meta["errors"][name], flush=True)
        if count:
            save(name + "_partial", scores)
    meta["minutes"][name] = round((time.time() - s0) / 60, 1)
    meta["series"][name] = count
    json.dump(meta, open(f"{OUT}/meta.json", "w"), indent=1)


# ---------------------------------------------------------------- Chronos-2
def chronos():
    from chronos import BaseChronosPipeline

    pipe = BaseChronosPipeline.from_pretrained("amazon/chronos-2", device_map=dev)
    meta["chronos_class"] = type(pipe).__name__

    def fn(t, cols):
        ctx = [torch.tensor(c[t + 1 - CTX: t + 1, j], dtype=torch.float32) for j in cols]
        q, _ = pipe.predict_quantiles(ctx, prediction_length=2, quantile_levels=[0.5])
        m = median_path(q, len(cols))
        return np.log(m[:, 1] / m[:, 0])
    run("chronos2", fn)


# ---------------------------------------------------------------- TimesFM-2.5
def timesfm_run():
    import timesfm

    model = timesfm.TimesFM_2p5_200M_torch.from_pretrained("google/timesfm-2.5-200m-pytorch")
    model.compile(timesfm.ForecastConfig(max_context=CTX, max_horizon=128, normalize_inputs=True,
                                         use_continuous_quantile_head=True, fix_quantile_crossing=True))

    def fn(t, cols):
        ctx = [c[t + 1 - CTX: t + 1, j].astype(np.float32) for j in cols]
        point, quant = model.forecast(horizon=2, inputs=ctx)
        q = np.asarray(quant)
        m = q[:, :2, q.shape[2] // 2] if q.ndim == 3 else np.asarray(point)[:, :2]  # the median quantile
        return np.log(m[:, 1] / m[:, 0])
    run("timesfm25", fn)


# ---------------------------------------------------------------- Kronos-small
def kronos():
    import pandas as pd

    sys.path.insert(0, "/kaggle/working/Kronos")
    from model import Kronos, KronosPredictor, KronosTokenizer

    tok = KronosTokenizer.from_pretrained("NeoQuasar/Kronos-Tokenizer-base")
    mdl = Kronos.from_pretrained("NeoQuasar/Kronos-small")
    pred = KronosPredictor(mdl, tok, device=dev, max_context=CTX)
    stamps = pd.Series(pd.to_datetime(days.astype(str)))

    def fn(t, cols):
        torch.manual_seed(int(days[t]))
        np.random.seed(int(days[t]) % 2**31)
        sl = slice(t + 1 - CTX, t + 1)
        dfs = [pd.DataFrame({"open": o[sl, j], "high": h[sl, j], "low": lo[sl, j], "close": c[sl, j],
                             "volume": v[sl, j], "amount": v[sl, j] * c[sl, j]}) for j in cols]
        xs = [stamps.iloc[sl].reset_index(drop=True)] * len(cols)
        nxt = pd.Series(pd.bdate_range(stamps.iloc[t] + pd.Timedelta(days=1), periods=2))
        ys = [nxt] * len(cols)
        out = pred.predict_batch(df_list=dfs, x_timestamp_list=xs, y_timestamp_list=ys, pred_len=2, T=1.0,
                                 top_p=0.9, sample_count=3, verbose=False)
        op = np.array([np.asarray(d["open"], dtype=float)[:2] for d in out])
        return np.log(op[:, 1] / op[:, 0])
    run("kronos_small", fn)


for name, f in (("chronos2", chronos), ("timesfm25", timesfm_run), ("kronos_small", kronos)):
    try:
        f()
    except Exception:  # noqa: BLE001 - a model that does not load is recorded, the next one runs
        meta["errors"][name] = traceback.format_exc()[-3000:]
        print(meta["errors"][name], flush=True)
        json.dump(meta, open(f"{OUT}/meta.json", "w"), indent=1)
meta["total_minutes"] = round((time.time() - t0) / 60, 1)
json.dump(meta, open(f"{OUT}/meta.json", "w"), indent=1)
print("done", meta["total_minutes"], "min", meta["errors"].keys(), flush=True)
