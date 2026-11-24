"""Kaggle GPU kernel: a small Transformer trained from scratch on the panel (decision D31).

Input per (session t, stock): the last 60 sessions of 6 price-volume features known at the close of t (log
close-to-close return, log open/previous close, log high/close, log low/close, log close/open, log volume over its
20-day mean). Target: the cross-sectional z-score of the residual label (clipped at +-3). Training uses sessions up
to 2020-06-30; 2020-07 to 2020-12 (still in the train split, minus a 2-session purge) is the early-stopping set, so
the validation split 2021-2022 is not used for training choices. Three seeds; the prediction is their mean.
Output: /kaggle/working/transformer_val.npz (scores for every validation session x symbol) and meta.json.
"""
import json
import os
import time

import numpy as np
import torch
from torch import nn

t0 = time.time()
torch.backends.cudnn.deterministic = True
dev = "cuda" if torch.cuda.is_available() else "cpu"
SMOKE = os.environ.get("SMOKE")  # a local check: a few sessions, one epoch, one seed
OUT = os.environ.get("OUT", "/kaggle/working")
src = None
for cand in (os.environ.get("PANEL", ""), "/kaggle/input/ghostdesk-panel/panel.npz", "/kaggle/input/datasets/ghostdesk-panel/panel.npz"):
    try:
        src = np.load(cand, allow_pickle=False)
        break
    except (FileNotFoundError, OSError):
        continue
if src is None:
    import glob
    src = np.load(glob.glob("/kaggle/input/**/panel.npz", recursive=True)[0], allow_pickle=False)
days, member, label = src["days"], src["member"], src["label"].astype(np.float32)
o, h, lo, c, v = (src[k].astype(np.float64) for k in ("open", "high", "low", "close", "volume"))
T, N = c.shape
L = 60

with np.errstate(divide="ignore", invalid="ignore"):
    lc = np.log(c)
    f = np.stack([
        np.diff(lc, axis=0, prepend=np.nan),
        np.log(o) - np.vstack([np.full((1, N), np.nan), lc[:-1]]),
        np.log(h) - lc,
        np.log(lo) - lc,
        lc - np.log(o),
        np.log(v + 1) - np.log(np.vstack([np.full((19, N), np.nan),
                                         np.lib.stride_tricks.sliding_window_view(v + 1, 20, axis=0).mean(-1)])),
    ], axis=-1)  # (T, N, 6), all known at the close of t
f = np.where(np.isfinite(f), f, np.nan)
scale = np.nanstd(f[: np.searchsorted(days, 20201231)], axis=(0, 1))
f = np.clip(np.nan_to_num(f / scale, nan=0.0), -10, 10).astype(np.float32)
valid_hist = np.isfinite(c)
ok_hist = np.lib.stride_tricks.sliding_window_view(valid_hist, L, axis=0).all(-1)  # (T-L+1, N)
ok = np.zeros((T, N), dtype=bool)
ok[L - 1:] = ok_hist
ok &= member

with np.errstate(invalid="ignore"):
    mu = np.nanmean(np.where(ok, label, np.nan), axis=1, keepdims=True)
    sd = np.nanstd(np.where(ok, label, np.nan), axis=1, keepdims=True)
    z = np.clip((label - mu) / sd, -3, 3)
z = np.where(ok & np.isfinite(z), z, np.nan).astype(np.float32)


def idx(d):
    return int(np.searchsorted(days, d))


train_days = [t for t in range(L, idx(20200701) - 2) if np.isfinite(z[t]).sum() > 100]
stop_days = [t for t in range(idx(20200701), idx(20210101) - 2) if np.isfinite(z[t]).sum() > 100]
val_days = list(range(idx(20210101), T))
if SMOKE:
    train_days, stop_days, val_days = train_days[:5], stop_days[:3], val_days[:3]
F = torch.tensor(f, device=dev)


def batch(t):
    cols = np.where(ok[t])[0]
    x = F[t - L + 1: t + 1, cols].permute(1, 0, 2)  # (n, L, 6)
    return cols, x


class Net(nn.Module):
    def __init__(self, d=64):
        super().__init__()
        self.inp = nn.Linear(6, d)
        self.pos = nn.Parameter(torch.zeros(L, d))
        layer = nn.TransformerEncoderLayer(d, 4, 128, dropout=0.1, batch_first=True)
        self.enc = nn.TransformerEncoder(layer, 2)
        self.out = nn.Linear(d, 1)

    def forward(self, x):
        return self.out(self.enc(self.inp(x) + self.pos)[:, -1]).squeeze(-1)


def ic(pred, y):
    m = np.isfinite(y)
    if m.sum() < 20:
        return np.nan
    a, b = pred[m].argsort().argsort(), y[m].argsort().argsort()
    return float(np.corrcoef(a, b)[0, 1])


def score(net, ts):
    net.eval()
    out = np.full((len(ts), N), np.nan, dtype=np.float32)
    with torch.no_grad():
        for i, t in enumerate(ts):
            cols, x = batch(t)
            if len(cols):
                out[i, cols] = net(x).float().cpu().numpy()
    return out


preds, log = [], []
for seed in range(1 if SMOKE else 3):
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    net = Net().to(dev)
    opt = torch.optim.AdamW(net.parameters(), lr=3e-4, weight_decay=1e-4)
    best, best_state, bad = -1e9, None, 0
    for epoch in range(1 if SMOKE else 30):
        net.train()
        for t in rng.permutation(train_days):
            cols, x = batch(t)
            y = torch.tensor(z[t, cols], device=dev)
            m = torch.isfinite(y)
            loss = ((net(x)[m] - y[m]) ** 2).mean()
            opt.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(net.parameters(), 1.0)
            opt.step()
        s = score(net, stop_days)
        stop_ic = float(np.nanmean([ic(s[i], z[t]) for i, t in enumerate(stop_days)]))
        log.append({"seed": seed, "epoch": epoch, "stop_ic": stop_ic, "min": round((time.time() - t0) / 60, 1)})
        print(log[-1], flush=True)
        if stop_ic > best:
            best, bad = stop_ic, 0
            best_state = {k: v.clone() for k, v in net.state_dict().items()}
        else:
            bad += 1
            if bad >= 4:
                break
    net.load_state_dict(best_state)
    preds.append(score(net, val_days))

pred = np.nanmean(np.stack(preds), axis=0)
np.savez_compressed(f"{OUT}/transformer_val.npz", days=days[val_days], scores=pred.astype(np.float32),
                    seeds=np.stack(preds))
json.dump({"log": log, "minutes": round((time.time() - t0) / 60, 1), "device": dev,
           "params": sum(p.numel() for p in Net().parameters()), "train_days": len(train_days),
           "stop_days": len(stop_days), "val_days": len(val_days)},
          open(f"{OUT}/meta.json", "w"), indent=1)
print("done", round((time.time() - t0) / 60, 1), "min", flush=True)
