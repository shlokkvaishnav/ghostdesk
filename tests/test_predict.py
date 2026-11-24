"""The live ensemble: weights by the pre-registered rule, the weighted rank average, and a night's optimized target
from a small store."""
import numpy as np
import pandas as pd
import pytest

from ghostdesk.data.store import PriceStore, bars_to_rows
from ghostdesk.live.predict import ensemble_score, ensemble_weights, night_design, optimizer_target, predict_night
from ghostdesk.research.models import Reversal


def test_weights_follow_validation_ic_and_ignore_negative():
    val = {"models": {m: {"validation": {"ic_mean": v}} for m, v in
                      {"a": 0.01, "b": 0.03, "c": -0.02}.items()}}
    w = ensemble_weights(val, ("a", "b", "c"))
    assert w == pytest.approx({"a": 0.25, "b": 0.75, "c": 0.0})
    w0 = ensemble_weights({"models": {"a": {"validation": {"ic_mean": -1}}}}, ("a",))
    assert w0 == {"a": 1.0}


def test_ensemble_score_is_the_weighted_rank_mean():
    rows = pd.DataFrame({"model": ["a", "a", "b", "b"], "symbol": ["X", "Y", "X", "Y"], "rank": [1.0, 0.5, 0.5, 1.0]})
    e = ensemble_score(rows, {"a": 0.75, "b": 0.25})
    assert e["X"] == pytest.approx(0.875) and e["Y"] == pytest.approx(0.625)


def test_night_design_predicts_and_the_target_is_neutral(tmp_path):
    rng = np.random.default_rng(0)
    days = pd.bdate_range("2025-06-02", "2026-11-23")
    syms = [f"S{i:02d}" for i in range(40)]
    store = PriceStore(tmp_path)
    frames = []
    for s in [*syms, "SPY"]:
        c = 100 * np.exp(np.cumsum(rng.normal(0, 0.015, len(days))))
        frames.append(pd.DataFrame({"symbol": s, "t": (days + pd.Timedelta(hours=5)).tz_localize("UTC"),
                                    "o": c * 0.999, "h": c * 1.01, "l": c * 0.99, "c": c, "v": 1e6, "n": 100.0,
                                    "vw": c}))
    store.write_batch("adj", bars_to_rows(pd.concat(frames), pd.Timestamp("2026-11-24", tz="UTC")), "seed")
    sectors = {s: "ab"[i % 2] for i, s in enumerate(syms)}
    n = night_design(store, syms, pd.Timestamp("2026-11-23"), sectors)
    assert n.session == pd.Timestamp("2026-11-23") and len(n.symbols) == 40 and n.design.mask[-1].all()
    preds = predict_night(n, {"reversal_1d": Reversal(1)})
    assert len(preds) == 40 and preds["score"].notna().all()
    preds["rank"] = preds["score"].rank(pct=True)
    w = optimizer_target(n, ensemble_score(preds, {"reversal_1d": 1.0}))
    assert abs(w.sum()) < 1e-4 and w.abs().max() <= 0.02 + 1e-4 and len(w) > 10
