"""Live predictions and the ensemble target (decision D30).

- **Frozen models:** ridge and LightGBM are fitted once on every session up to the validation end (minus the 2-session
  purge) and saved under `data/live/models/`; the reversal models need no fit. The live loop never refits them,
  so a live prediction is the pre-registered model, not a model tuned on later data.
- **Night design:** the last ~420 calendar days of adjusted bars of today's members from the store (as known now),
  the 158 Alpha158 factors, ranked across the members of the night's session.
- **Ensemble:** the rank average of the live models with weights fixed on validation (`ENSEMBLE_WEIGHTS`, by the
  pre-registered rule: proportional to each model's positive validation IC); the target weights come from the
  optimizer (`research.optimizer`) with the risk model of the last 252 sessions.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from ghostdesk.data.store import PriceStore, matrices
from ghostdesk.features.alpha158 import alpha158
from ghostdesk.features.engine import FeatureEngine
from ghostdesk.research.backtest import half_spread
from ghostdesk.research.dataset import FIELD_MAP, rolling_beta
from ghostdesk.research.models import Design, LightGBM, Reversal, Ridge, rank_features
from ghostdesk.research.optimizer import OptConfig, optimize_path

LIVE_MODELS = ("reversal_1d", "reversal_5d", "ridge", "lightgbm")


def ensemble_weights(validation: dict, models=LIVE_MODELS) -> dict[str, float]:
    """The pre-registered rule: weight = max(validation IC, 0), normalized; equal weights if none is positive."""
    ic = {m: max(float(validation["models"][m]["validation"]["ic_mean"]), 0.0) for m in models}
    tot = sum(ic.values())
    return {m: (v / tot if tot else 1.0 / len(models)) for m, v in ic.items()}


@dataclass
class Night:
    session: pd.Timestamp
    symbols: list[str]
    design: Design
    close: np.ndarray
    high: np.ndarray
    low: np.ndarray
    spy_close: np.ndarray
    sectors: np.ndarray


def save_models(models: dict, root: Path, meta: dict) -> None:
    root.mkdir(parents=True, exist_ok=True)
    np.save(root / "ridge.npy", models["ridge"].w)
    models["lightgbm"].booster.save_model(str(root / "lightgbm.txt"))
    (root / "meta.json").write_text(json.dumps(meta, indent=1, default=str))


def load_models(root: Path) -> dict:
    import lightgbm as lgb

    r = Ridge()
    r.w = np.load(root / "ridge.npy")
    g = LightGBM()
    g.booster = lgb.Booster(model_file=str(root / "lightgbm.txt"))
    return {"reversal_1d": Reversal(1), "reversal_5d": Reversal(5), "ridge": r, "lightgbm": g}


def night_design(store: PriceStore, symbols: list[str], session: pd.Timestamp, sectors: dict[str, str],
                 asof=None, days_back: int = 420) -> Night:
    rows = store.read("adj", start=pd.Timestamp(session) - pd.Timedelta(days=days_back), end=session, asof=asof,
                      symbols=sorted(set(symbols) | {"SPY"}))
    days = pd.DatetimeIndex(sorted(rows.loc[rows["symbol"] == "SPY", "day"].unique()))
    syms = sorted(set(symbols) & set(rows["symbol"]) - {"SPY"})
    m = matrices(rows, list(FIELD_MAP.values()), days, syms + ["SPY"])
    fields = {k: m[v][syms].to_numpy() for k, v in FIELD_MAP.items()}
    feats = FeatureEngine(fields).compute(alpha158())
    hist = np.isfinite(fields["close"][-61:]).all(axis=0) if len(days) >= 61 else np.zeros(len(syms), bool)
    mask = np.zeros(fields["close"].shape, dtype=bool)
    mask[-1] = hist
    X, names = rank_features(feats, mask)
    d = Design(X, np.full(mask.shape, np.nan), mask, names, fields["close"])
    return Night(days[-1], syms, d, fields["close"], fields["high"], fields["low"], m["c"]["SPY"].to_numpy(),
                 np.array([sectors.get(s, "unknown") for s in syms]))


def predict_night(night: Night, models: dict) -> pd.DataFrame:
    last = np.array([night.design.mask.shape[0] - 1])
    out = []
    for name, m in models.items():
        s = m.predict(night.design, last)[0]
        out += [{"model": name, "symbol": sym, "score": float(v), "pred_return": np.nan}
                for sym, v in zip(night.symbols, s, strict=True) if np.isfinite(v)]
    return pd.DataFrame(out)


def ensemble_score(rows: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    """Weighted mean of each model's rank (models missing for a stock are left out of its mean)."""
    r = rows[rows["model"].isin(weights)].pivot_table(index="symbol", columns="model", values="rank")
    w = pd.Series(weights).reindex(r.columns).fillna(0.0)
    num = (r.fillna(0) * w).sum(axis=1)
    den = (r.notna() * w).sum(axis=1)
    return (num / den.replace(0, np.nan)).dropna()


def optimizer_target(night: Night, score: pd.Series, held: pd.Series | None = None,
                     cfg: OptConfig | None = None) -> pd.Series:
    """Target weights (share of equity) for the night from the ensemble score; `held`: weights held now (the
    turnover penalty starts from them)."""
    idx = {s: i for i, s in enumerate(night.symbols)}
    sc = np.full((1, len(night.symbols)), np.nan)
    for s, v in score.items():
        if s in idx:
            sc[0, idx[s]] = v
    cc = np.diff(np.log(night.close), axis=0, prepend=np.nan)
    beta = rolling_beta(cc, np.diff(np.log(night.spy_close), prepend=np.nan))[-1:]
    groups = sorted(set(night.sectors))
    S = np.array([[x == g for g in groups] for x in night.sectors], dtype=float)
    hs = half_spread(night.high, night.low, night.close)[-1:]
    member = np.isfinite(sc)
    full = np.vstack([cc[:-1], cc[-1:]])
    t = full.shape[0] - 1
    scores = np.full(full.shape, np.nan)
    scores[t] = sc[0]
    mem = np.zeros(full.shape, dtype=bool)
    mem[t] = member[0]
    hsp = np.full(full.shape, np.nan)
    hsp[t] = hs[0]
    bet = np.ones(full.shape)
    bet[t] = beta[0]
    prev = np.zeros(len(night.symbols)) if held is None else held.reindex(night.symbols).fillna(0.0).to_numpy()
    W, _ = optimize_path(scores, full, bet, mem, S, hsp, np.array([t]), cfg or OptConfig(), prev0=prev)
    w = pd.Series(W[t], index=night.symbols)
    return w[w.abs() > 1e-5]
