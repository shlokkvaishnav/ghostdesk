"""The ML layer: characteristics use only data known at the formation close, the test period stays locked until
the pre-registration is committed, walk-forward models train only on earlier months, and a tree model finds a
planted signal."""
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ghostdesk.ml import split
from ghostdesk.ml.characteristics import ACCOUNTING, ALL, PRICE, add_characteristics, rank_features, report_values
from ghostdesk.ml.models import ridge, target, walk_forward
from ghostdesk.signal.panel import close_utc, month_ends

ROOT = Path(__file__).resolve().parents[1]
SYMS = ["A", "B", "C"]
DAYS = pd.bdate_range("2019-01-01", "2020-12-31")


def market(seed=0, days=DAYS):
    rng = np.random.default_rng(seed)
    rows = []
    for s in SYMS:
        r = rng.normal(0, 0.02, len(days))
        c = 50 * np.exp(np.cumsum(r))
        rows.append(pd.DataFrame({"symbol": s, "day": days, "ret": r, "flag": False, "close": c, "close_adj": c,
                                  "v": rng.integers(1e5, 1e6, len(days)).astype(float)}))
    ret = pd.concat(rows, ignore_index=True)
    raw = ret.assign(t=(ret["day"] + pd.Timedelta(hours=16)).dt.tz_localize("America/New_York").dt.tz_convert("UTC"),
                     h=ret["close"] * 1.01, l=ret["close"] * 0.99, c=ret["close"])[["symbol", "t", "h", "l", "c", "v"]]
    return ret.drop(columns="v"), raw


def reports():
    rows = []
    for cik, s in enumerate(SYMS, start=1):
        for i, end in enumerate(pd.date_range("2018-03-31", "2020-12-31", freq="QE")):
            form = "10-K" if end.month == 12 else "10-Q"
            rows.append({"cik": cik, "accession": f"{s}{i}", "form": form, "report_date": end, "error": "",
                         "accepted_utc": pd.Timestamp(end + pd.Timedelta(days=35), tz="UTC") + pd.Timedelta(hours=21),
                         "xbrl_Revenues": 100.0 * (1.1 ** i) * (4 if form == "10-K" else 1),
                         "xbrl_Assets": 1000.0 + 10 * i, "xbrl_StockholdersEquity": 400.0,
                         "xbrl_NetIncomeLoss": 10.0 * (4 if form == "10-K" else 1)})
    return pd.DataFrame(rows)


def setup(start_c="2019-01-01"):
    ret, raw = market()
    ends = month_ends(DAYS)
    members = pd.DataFrame({"ticker": SYMS, "start": pd.to_datetime(["2019-01-01", "2019-01-01", start_c]),
                            "end": pd.NaT})
    panel = pd.DataFrame([{"month": d, "cik": i + 1, "ticker": s, "price_symbol": s, "composite": 0.5,
                           "logdv": 15.0, "fwd_ret": 0.0}
                          for d in ends for i, s in enumerate(SYMS) if d >= members.loc[i, "start"]])
    return panel, members, ret, raw, reports()


def test_characteristics_do_not_change_when_the_future_changes():
    panel, members, ret, raw, feats = setup()
    d = month_ends(DAYS)[17]  # 2020-06-30
    base = add_characteristics(panel, members, ret, raw, feats).set_index(["month", "cik"]).loc[d, ALL]
    assert base[list(PRICE)].notna().all().all() and base[ACCOUNTING[:4]].notna().all().all()
    # change every price after the formation day and every report accepted after the formation close
    ret2, raw2 = ret.copy(), raw.copy()
    later = ret2["day"] > d
    ret2.loc[later, ["ret", "close", "close_adj"]] *= 3.0
    raw2.loc[raw2["t"] > close_utc(pd.DatetimeIndex([d]))[0], ["h", "l", "c", "v"]] *= 3.0
    feats2 = feats.copy()
    new = feats2["accepted_utc"] > close_utc(pd.DatetimeIndex([d]))[0]
    feats2.loc[new, [c for c in feats2 if c.startswith("xbrl_")]] *= 7.0
    after = add_characteristics(panel, members, ret2, raw2, feats2).set_index(["month", "cik"]).loc[d, ALL]
    pd.testing.assert_frame_equal(base, after)


def test_a_new_index_member_has_no_window_from_before_it_joined():
    panel, members, ret, raw, feats = setup(start_c="2020-05-01")
    x = add_characteristics(panel, members, ret, raw, feats).set_index(["month", "ticker"])
    row = x.loc[(month_ends(DAYS)[17], "C")]  # 2020-06-30: about 42 sessions in the index
    assert np.isnan(row["mom_12_1"]) and np.isnan(row["vol_63"]) and np.isnan(row["beta_252"])
    assert not np.isnan(row["rev_1"]) and not np.isnan(row["vol_21"])


def test_accounting_values_are_annualised_and_growth_uses_the_year_earlier_report():
    rv = report_values(reports())
    a = rv[rv["cik"] == 1].reset_index(drop=True)
    assert np.allclose(a["roa"], 40.0 / (1000.0 + 10 * a.index))  # 10-Q x4 equals the 10-K flow
    assert np.isnan(a.loc[0, "sales_growth"]) and np.isclose(a.loc[4, "sales_growth"], 4 * np.log(1.1))


def test_a_report_accepted_after_the_close_is_not_used():
    panel, members, ret, raw, feats = setup()
    d = month_ends(DAYS)[13]  # 2020-02-28
    feats = feats.copy()
    i = feats.index[(feats["cik"] == 1) & (feats["report_date"] == pd.Timestamp("2019-12-31"))][0]
    feats.loc[i, "accepted_utc"] = close_utc(pd.DatetimeIndex([d]))[0]  # exactly at the close: not before it
    x = add_characteristics(panel, members, ret, raw, feats).set_index(["month", "cik"])
    assert np.isclose(x.loc[(d, 1), "log_assets"], np.log(1000.0 + 10 * 6))  # the 2019-09-30 10-Q


def test_rank_features_maps_to_the_middle_and_bounds():
    p = pd.DataFrame({"month": [1, 1, 1, 2, 2], "a": [3.0, np.nan, 1.0, 5.0, 6.0]})
    r = rank_features(p, ["a"])["a"]
    assert r.between(-0.5, 0.5).all() and r.iloc[1] == 0.0 and r.iloc[0] == -r.iloc[2]


def test_the_test_period_is_locked_until_the_preregistration_is_committed(tmp_path):
    p = pd.DataFrame({"month": pd.to_datetime(["2021-12-31", "2022-01-31", "2026-01-30"])})
    assert split.dev(p)["month"].max() == split.DEV_END
    with pytest.raises(split.TestPeriodLocked):
        split.everything(p, tmp_path / "missing.md")
    with pytest.raises(split.TestPeriodLocked):
        split.everything(p, tmp_path / "x.md", check=lambda path: None)
    rows, sha = split.everything(p, tmp_path / "x.md", check=lambda path: "abc")
    assert sha == "abc" and rows["month"].max() < pd.Timestamp("2026-01-01")


def test_walk_forward_trains_only_on_earlier_months():
    months = pd.date_range("2017-01-31", periods=40, freq="ME")
    rng = np.random.default_rng(0)
    p = pd.DataFrame({"month": np.repeat(months, 50), "cik": np.tile(range(50), 40)})
    p["t"] = p["month"].map({m: i for i, m in enumerate(months)}).astype(float)
    p["fwd_ret"] = rng.normal(size=len(p))
    seen = []

    def fit(x, y):
        last = x["t"].max()
        return lambda x_new: (seen.append((last, x_new["t"].min())), np.zeros(len(x_new)))[1]

    out = walk_forward(p, ["t"], fit, first="2019-01-01", refit_every=6)
    assert seen and all(last < new for last, new in seen)
    assert (out["fit_month"] <= out["month"]).all() and out["fit_month"].nunique() == 3


def planted_ic(model: str) -> float:
    """Mean monthly IC of a walk-forward model on data with a planted non-linear signal."""
    from ghostdesk.ml.models import gbm
    rng = np.random.default_rng(1)
    months = pd.date_range("2017-01-31", periods=36, freq="ME")
    p = pd.DataFrame({"month": np.repeat(months, 200), "cik": np.tile(range(200), 36),
                      "a": rng.uniform(-0.5, 0.5, 7200), "b": rng.uniform(-0.5, 0.5, 7200)})
    p["fwd_ret"] = 0.02 * np.sin(6 * p["a"]) + 0.01 * rng.normal(size=len(p))  # non-linear in a, none in b
    p["y"] = target(p)
    fit = ridge() if model == "ridge" else gbm({"n_estimators": 100}, seeds=(0,))
    out = walk_forward(p, ["a", "b"], fit, first="2019-01-01").merge(p, on=["month", "cik"])
    return float(out.groupby("month").apply(lambda g: g["pred"].corr(g["y"]), include_groups=False).mean())


def test_ridge_finds_the_linear_part_of_a_planted_signal():
    assert planted_ic("ridge") > 0.3


def test_gbm_finds_a_planted_signal_better_than_ridge():
    """In its own process: torch (loaded by other tests) and LightGBM each bring an OpenMP runtime on macOS, and two
    in one process abort. The scripts never load both."""
    pytest.importorskip("lightgbm")
    code = "import sys; sys.path[:0] = ['tests', 'src']; import test_ml; print(test_ml.planted_ic('gbm'))"
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT, check=True)
    assert float(r.stdout.split()[-1]) > max(0.5, planted_ic("ridge"))
