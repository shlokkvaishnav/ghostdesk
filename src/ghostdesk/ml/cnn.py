"""The chart CNN: from a 20-session price image, the probability that the next 20 sessions' return is positive
(Jiang, Kelly and Xiu 2023, "I20/R20"), as one more model in the ML harness (decision D19).

- **Training images:** every `STEP` sessions, each stock that is an index member on that session (its current
  interval started at least 20 sessions before), with a label from the next 20 sessions. The label window must end
  on or before `label_end`, so no training label overlaps the months the model predicts.
- **Network:** three blocks of 5x3 convolution, batch norm, leaky ReLU and 2x1 max pooling (16, 32, 64 channels:
  a quarter of the paper's, for a sample about 1/10 of its size and one Apple GPU; about 1.2 ms per training image),
  dropout 0.5, a linear layer to 2 classes.
- **Fit:** cross-entropy, Adam, a random 70/30 split of the training images for early stopping (patience 2, at
  most 5 epochs), the mean of `SEEDS` networks (each trained in its own run, about 6 min). Fixed settings in
  `TRAIN`.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .charts import DAYS, HEIGHT, WIDTH, draw, windows

STEP = 5
SEEDS = (0, 1, 2)
TRAIN = {"lr": 1e-4, "batch": 128, "max_epochs": 5, "patience": 2, "val_frac": 0.3, "channels": (16, 32, 64),
         "dropout": 0.5}


def training_images(mats: dict, members: pd.DataFrame, first, last, label_end, step: int = STEP):
    """Images and 0/1 labels for sessions in [first, last] (every `step`), members only, labels ending by
    `label_end`. members: price_symbol, start, end. Returns (images uint8 (n, 64, 60), labels, keys DataFrame)."""
    sessions = mats["c"].index
    cum = np.log(mats["c"]).diff().fillna(0.0).cumsum()  # adjusted close: the label return
    have = mats["c"].notna()
    pos_end = sessions.searchsorted(pd.Timestamp(label_end), side="right") - 1
    grid = np.arange(sessions.searchsorted(pd.Timestamp(first)), sessions.searchsorted(pd.Timestamp(last), "right"),
                     step)
    grid = grid[grid + DAYS <= pos_end]
    syms, ends, starts = [], [], []
    for m in members.dropna(subset=["price_symbol"]).itertuples():
        s0 = sessions.searchsorted(m.start)
        s1 = len(sessions) if pd.isna(m.end) else sessions.searchsorted(m.end)  # end is the first day out
        g = grid[(grid >= s0) & (grid < s1)]
        syms += [m.price_symbol] * len(g)
        ends.append(g)
        starts += [s0] * len(g)
    ends = np.concatenate(ends) if ends else np.array([], dtype=int)
    arr, ok = windows(mats, syms, ends, starts)
    col = mats["c"].columns.get_indexer(pd.Index(syms))
    c = np.maximum(col, 0)
    full = have.to_numpy()[np.clip(ends[:, None] + np.arange(1, DAYS + 1), 0, len(sessions) - 1), c[:, None]].all(1)
    ok &= full & (col >= 0)
    cm = cum.to_numpy()
    fwd = cm[np.clip(ends + DAYS, 0, len(sessions) - 1), c] - cm[ends, c]
    keys = pd.DataFrame({"symbol": np.array(syms)[ok], "day": sessions[ends[ok]], "fwd": fwd[ok]})
    return draw({k: v[ok] for k, v in arr.items()}), (fwd[ok] > 0).astype(np.int64), keys


def prediction_images(mats: dict, panel: pd.DataFrame, members: pd.DataFrame):
    """Images for panel rows (month, cik, ticker, price_symbol) ending on the formation session; and the mask of
    rows that have one."""
    sessions = mats["c"].index
    iv = panel[["month", "ticker"]].merge(members[["ticker", "start", "end"]], on="ticker", how="left")
    iv = iv[(iv["start"] <= iv["month"]) & (iv["end"].isna() | (iv["month"] < iv["end"]))]
    start = iv.drop_duplicates(["month", "ticker"]).set_index(["month", "ticker"])["start"]
    s = start.reindex(pd.MultiIndex.from_frame(panel[["month", "ticker"]])).to_numpy()
    starts = np.where(pd.isna(s), len(sessions), sessions.searchsorted(pd.DatetimeIndex(s)))
    ends = sessions.get_indexer(pd.DatetimeIndex(panel["month"]))
    arr, ok = windows(mats, panel["price_symbol"].to_numpy(), ends, starts)
    ok &= ends >= 0
    return draw({k: v[ok] for k, v in arr.items()}), ok


def net(channels=TRAIN["channels"], dropout=TRAIN["dropout"]):
    from torch import nn
    layers, c_in = [], 1
    for c in channels:
        layers += [nn.Conv2d(c_in, c, (5, 3), padding=(2, 1)), nn.BatchNorm2d(c), nn.LeakyReLU(0.01),
                   nn.MaxPool2d((2, 1))]
        c_in = c
    h = HEIGHT // 2 ** len(channels)
    m = nn.Sequential(*layers, nn.Flatten(), nn.Dropout(dropout), nn.Linear(c_in * h * WIDTH, 2))
    for p in m.modules():
        if isinstance(p, (nn.Conv2d, nn.Linear)):
            nn.init.xavier_uniform_(p.weight)
    return m


def device():
    import torch
    return torch.device("mps" if torch.backends.mps.is_available() else
                        "cuda" if torch.cuda.is_available() else "cpu")


def _batches(x, y, idx, batch, dev):
    import torch
    for i in range(0, len(idx), batch):
        j = idx[i:i + batch]
        xb = torch.from_numpy(x[j]).to(dev).float().div_(255.0).unsqueeze(1)
        yield xb, (torch.from_numpy(y[j]).to(dev) if y is not None else None)


def fit(images: np.ndarray, labels: np.ndarray, seed: int, cfg: dict = TRAIN, log=print):
    """One network with early stopping on a random 30% of the images; returns (model, history)."""
    import torch
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    dev = device()
    perm = rng.permutation(len(images))
    n_val = int(len(perm) * cfg["val_frac"])
    val, tr = perm[:n_val], perm[n_val:]
    model = net(cfg["channels"], cfg["dropout"]).to(dev)
    opt = torch.optim.Adam(model.parameters(), lr=cfg["lr"])
    loss_f = torch.nn.CrossEntropyLoss()
    best, best_state, wait, hist = np.inf, None, 0, []
    for epoch in range(cfg["max_epochs"]):
        model.train()
        for xb, yb in _batches(images, labels, rng.permutation(tr), cfg["batch"], dev):
            opt.zero_grad()
            loss_f(model(xb), yb).backward()
            opt.step()
        model.eval()
        with torch.no_grad():
            vl = sum(float(loss_f(model(xb), yb)) * len(yb)
                     for xb, yb in _batches(images, labels, val, 1024, dev)) / max(len(val), 1)
        hist.append(vl)
        log(f"  seed {seed} epoch {epoch}: val loss {vl:.4f}")
        if vl < best - 1e-4:
            best, wait = vl, 0
            best_state = {k: v.detach().clone() for k, v in model.state_dict().items()}
        else:
            wait += 1
            if wait >= cfg["patience"]:
                break
    model.load_state_dict(best_state)
    return model, hist


def predict(models: list, images: np.ndarray) -> np.ndarray:
    """Mean probability of an up move over the networks."""
    import torch
    dev = device()
    out = []
    for m in models:
        m.eval()
        with torch.no_grad():
            p = [torch.softmax(m(xb), 1)[:, 1].cpu().numpy() for xb, _ in
                 _batches(images, None, np.arange(len(images)), 1024, dev)]
        out.append(np.concatenate(p) if p else np.array([]))
    return np.mean(out, axis=0)
