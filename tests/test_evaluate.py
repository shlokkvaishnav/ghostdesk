"""Forward evaluation on a made-up ledger: the numbers are synthetic and only test the code (D37)."""
import json

import numpy as np
import pandas as pd
import pytest

from ghostdesk.live.compare import compare, load_validation
from ghostdesk.live.evaluate import daily_metrics, summarize
from ghostdesk.live.ledger import Ledger, score
from ghostdesk.live.portfolio import book_days, book_summary, curve

N_DAYS, N_SYM = 30, 60


def world(seed=0):
    """opens (N_DAYS x N_SYM) from planted open-to-open returns, and a ledger over sessions 0..N_DAYS-2."""
    rng = np.random.default_rng(seed)
    days = pd.bdate_range("2030-01-02", periods=N_DAYS)
    syms = [f"S{i:02d}" for i in range(N_SYM)]
    r = rng.normal(0, 0.02, (N_DAYS, N_SYM))  # r[j]: open[j] -> open[j+1]
    opens = pd.DataFrame(100 * np.cumprod(np.vstack([np.ones((1, N_SYM)), 1 + r[:-1]]), axis=0), index=days,
                         columns=syms)
    return days, syms, r, opens


def fill(root, days, syms, r, seed=1):
    rng = np.random.default_rng(seed)
    led = Ledger(root)
    for k in range(N_DAYS - 1):
        future = r[k + 1]  # session k is traded at open k+1 and held to open k+2
        preds = []
        for model, sc in (("good", future + rng.normal(0, 0.01, N_SYM)), ("noise", rng.normal(size=N_SYM)),
                          ("inverse", -future + rng.normal(0, 0.01, N_SYM)),
                          ("reversal_1d", rng.normal(size=N_SYM)), ("reversal_5d", rng.normal(size=N_SYM))):
            preds.append(pd.DataFrame({"model": model, "symbol": syms, "score": sc, "pred_return": np.nan}))
        led.append(days[k], days[k] + pd.Timedelta(hours=21), pd.concat(preds, ignore_index=True))
    return led


@pytest.fixture
def scored(tmp_path):
    days, syms, r, opens = world()
    led = fill(tmp_path / "ledger", days, syms, r)
    return led, score(led.read(), opens, None, None)


def test_only_matured_sessions_are_scored(scored):
    led, sc = scored
    assert led.read()["session"].nunique() == N_DAYS - 1
    assert sc["session"].nunique() == N_DAYS - 2  # the last ledger session has no open(t+2) yet
    assert sc["realized"].notna().all()


def test_good_model_beats_noise_and_inverse_loses(scored):
    _, sc = scored
    s = summarize(daily_metrics(sc))
    m = s["models"]
    assert s["forward_days"] == N_DAYS - 2
    assert m["good"]["ic_mean"] > 0.5 and m["good"]["ic_t"] > 10
    assert abs(m["noise"]["ic_mean"]) < 0.1
    assert m["inverse"]["ic_mean"] < -0.5
    assert m["good"]["hit_rate"] > 0.8 and m["inverse"]["hit_rate"] < 0.2
    assert m["good"]["pnl_total"] > 0 > m["inverse"]["pnl_total"]
    # baselines: zero signal is exactly 0; differences to the reversal models are given
    assert s["baselines"]["zero_signal"]["pnl_total"] == 0.0
    assert m["good"]["vs_zero_signal_pnl"] == m["good"]["pnl_total"]
    expect = round(m["good"]["ic_mean"] - m["reversal_1d"]["ic_mean"], 5)
    assert m["good"]["vs_reversal_1d_ic"] == pytest.approx(expect, abs=2e-5)
    assert m["reversal_1d"]["vs_reversal_1d_ic"] == 0.0


def test_a_model_without_return_forecast_has_no_error_value(scored):
    assert summarize(daily_metrics(scored[1]))["models"]["good"]["abs_error"] is None


def test_empty_ledger_runs_cleanly(tmp_path):
    led = Ledger(tmp_path / "ledger")
    sc = score(led.read(), pd.DataFrame(), None, None)
    daily = daily_metrics(sc)
    s = summarize(daily)
    assert daily.empty and s["forward_days"] == 0 and s["models"] == {}
    assert book_summary(book_days({}, pd.DataFrame()))["days"] == 0
    assert curve(book_days({}, pd.DataFrame())) == []
    c = compare(load_validation(tmp_path / "missing.json"), s)
    assert c["headline"] == "0 days of forward data" and c["rows"] == []
    assert c["labels"] == {"validation": "historical validation", "forward": "independent forward test"}


def test_all_unmatured_ledger_is_zero_days(tmp_path):
    days, syms, r, opens = world()
    led = Ledger(tmp_path / "ledger")
    led.append(days[N_DAYS - 2], days[N_DAYS - 2], pd.DataFrame({"model": "good", "symbol": syms, "score": r[0],
                                                                  "pred_return": np.nan}))
    assert summarize(daily_metrics(score(led.read(), opens, None, None)))["forward_days"] == 0


def test_tampering_with_the_ledger_is_still_caught(scored):
    led, _ = scored
    assert led.verify()[0]
    p = led.path(pd.Timestamp("2030-01-02"))
    df = pd.read_parquet(p)
    df.loc[0, "score"] += 1
    df.to_parquet(p, index=False)
    assert not led.verify()[0]


def test_book_return_turnover_cost_and_drawdown_by_hand():
    days = pd.bdate_range("2030-01-02", periods=6)
    opens = pd.DataFrame({"A": [100.0, 100, 110, 99, 99, 99], "B": [50.0, 50, 50, 50, 55, 44]}, index=days)
    # session 0: shares bought at open 1, held to open 2: A +10%, B 0
    books = {days[0]: {"equity": 1000.0, "target": {"A": 5.0}},        # w_A = 0.5
             days[1]: {"equity": 1000.0, "target": {"A": 5.0, "B": -10.0}},  # A 110 -> 99 (-10%), B 50 -> 50
             days[2]: {"equity": 1000.0, "target": {"B": -10.0}},       # B 50 -> 55 (+10%), short -> -50
             days[3]: {"equity": 1000.0, "target": {"B": -10.0}}}       # B 55 -> 44 (-20%), short +110
    d = book_days(books, opens, None, fixed_bps=10.0)
    assert d["gross"].iloc[0] == pytest.approx(5 * 10 / 1000)
    assert d["gross"].iloc[1] == pytest.approx(5 * (99 - 110) / 1000)
    assert d["gross"].iloc[2] == pytest.approx(-10 * (55 - 50) / 1000)
    assert d["gross"].iloc[3] == pytest.approx(-10 * (44 - 55) / 1000)
    # turnover: day 0 from cash 5 x 100 / 1000; day 1 trades B only: 10 x 50 / 1000; day 2 closes A: 5 x 99 / 1000
    assert d["turnover"].iloc[0] == pytest.approx(0.5)
    assert d["turnover"].iloc[1] == pytest.approx(10 * 50 / 1000)
    assert d["turnover"].iloc[2] == pytest.approx(5 * 99 / 1000)
    assert d["turnover"].iloc[3] == pytest.approx(0.0)
    assert d["cost"].iloc[0] == pytest.approx(0.5 * 10 / 1e4)
    s = book_summary(d)
    net = d["net"].to_numpy()
    c = np.cumprod(1 + net)
    assert s["days"] == 4 and s["cum_return"] == pytest.approx(c[-1] - 1)
    assert s["max_drawdown"] == pytest.approx(min(c / np.maximum.accumulate(np.maximum(c, 1.0)) - 1))
    assert s["sharpe"] == pytest.approx(net.mean() / net.std(ddof=1) * np.sqrt(252))
    assert len(curve(d)) == 4


def test_book_with_one_day_has_no_sharpe_and_unmatured_days_are_skipped():
    days = pd.bdate_range("2030-01-02", periods=4)
    opens = pd.DataFrame({"A": [100.0, 100, 101, 102]}, index=days)
    books = {days[0]: {"equity": 1000.0, "target": {"A": 1.0}}, days[2]: {"equity": 1000.0, "target": {"A": 1.0}}}
    d = book_days(books, opens)
    assert len(d) == 1  # session 2 needs opens 3 and 4
    s = book_summary(d)
    assert s["days"] == 1 and s["sharpe"] is None


def test_compare_uses_both_labels_and_sample_sizes(tmp_path, scored):
    val = {"validation": ["2021-01-01", "2022-12-31"],
           "models": {"good": {"validation": {"sessions": 501, "ic_mean": 0.01, "ic_t": 1.4, "hit_rate": 0.5}}}}
    p = tmp_path / "v.json"
    p.write_text(json.dumps(val))
    fwd = summarize(daily_metrics(scored[1]))
    c = compare(load_validation(p), fwd)
    row = next(r for r in c["rows"] if r["model"] == "good" and r["metric"] == "rank IC (mean)")
    assert row["validation"] == 0.01 and row["validation_sessions"] == 501
    assert row["forward"] == fwd["models"]["good"]["ic_mean"] and row["forward_days"] == N_DAYS - 2
    assert c["headline"] == f"{N_DAYS - 2} days of forward data"
    only_val = compare(val, {"forward_days": 0, "models": {}})
    assert all(r["forward"] is None for r in only_val["rows"])
