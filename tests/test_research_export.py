"""The research explorer data: built from statistics only, small, and equal to the numbers in docs/results.md."""
import json
import re
from pathlib import Path

from ghostdesk.explorer.research_export import STRATEGIES, build, measure_label

ROOT = Path(__file__).resolve().parents[1]
COMMITTED = ROOT / "web" / "data" / "research.json"
FORBIDDEN_KEYS = {"ticker", "tickers", "symbol", "symbols", "price", "prices", "qty", "orders", "fills",
                  "positions", "cik", "accession", "rows_data", "fwd_ret"}


def _stat(m):
    return {"mean": m, "t": 1.0, "n": 10, "ci95": [m - 0.01, m + 0.01]}


def _measure(m):
    return {"months": 10, "quintile_mean_monthly": {str(q): q / 1000 for q in range(1, 6)},
            "long_short_gross": _stat(m), "long_short_net": {"2bps": _stat(m), "5bps": _stat(m - 0.0005)},
            "ic": _stat(0.01), "sharpe_annual_gross": 0.3, "mde_monthly_80pct_power": 0.005,
            "ic_by_year": {"2022": 0.1}, "fama_macbeth": {}}


def _inputs():
    results = {p: {"formation": ["2016-01-01", "2019-12-31"], "panel": {"rows": 5, "months": 10},
                   "primary": "composite", "prereg_commit": "e4d66bb6", "code_commit": "cce3d21a",
                   "measures": {"composite": _measure(0.002), "sim_risk_cosine_r": _measure(0.001)}}
               for p in ("build", "check", "test", "pooled")}
    variant = {"ls_monthly": 0.002, "ls_t": 0.8, "sharpe": 0.3, "ic": 0.017, "ic_t": 1.8, "stock_months": 100,
               "ls_change_vs_baseline": 0.0}
    names = ("baseline", "survivors", "mixed_forms", "filing_date", "period_end", "vendor_errors")
    pit = {"period": ["2016-01-01", "2021-12-31"], "variants": {n: dict(variant) for n in names}}
    seeds = [{"test_days": 252, "mean_bps": {"large": {"0.01": {s: 5.0 + i for s in STRATEGIES}}}} for i in range(3)]
    cap = {"cost_curve": {"1000000": 6e-5, "100000000": 1.3e-4}, "gross_levels": {"pooled estimate": 0.0016},
           "break_even_aum": {"pooled estimate": 7.2e9}}
    return results, pit, seeds, cap


def _keys(x):
    if isinstance(x, dict):
        for k, v in x.items():
            yield k
            yield from _keys(v)
    elif isinstance(x, list):
        for v in x:
            yield from _keys(v)


def test_build_keeps_only_statistics():
    out = build(*_inputs())
    test = out["signal"]["periods"]["test"]
    assert test["confirmatory"] is True and test["prereg_commit"] == "e4d66bb"
    assert "prereg_commit" not in out["signal"]["periods"]["build"]
    composite = test["measures"]["composite"]
    assert composite["quintiles"] == [0.001, 0.002, 0.003, 0.004, 0.005]
    assert composite["ls_net_5bps"]["mean"] == 0.0015
    assert "ic_by_year" not in composite and "fama_macbeth" not in composite  # only the fields the page shows
    assert set(out["pitfalls"]["mistakes"]) == {"survivors", "mixed_forms", "filing_date", "period_end", "vendor_errors"}
    assert out["execution"]["cost_bps"]["large"]["0.01"]["VWAP"] == 6.0  # mean of 5, 6, 7 over the seeds
    assert out["capacity"]["cost_curve"][0] == [1e6, 6e-5]
    assert not FORBIDDEN_KEYS & set(_keys(out))


def test_measure_labels_are_plain_words():
    assert measure_label("composite") == "Composite (all nine measures)"
    assert measure_label("sim_mdna_edit_r") == "Management discussion, edit distance"


def test_committed_file_is_small_and_has_no_raw_data():
    text = COMMITTED.read_text()
    assert len(text.encode()) < 100_000
    data = json.loads(text)
    assert set(data) == {"signal", "pitfalls", "execution", "capacity"}
    assert not FORBIDDEN_KEYS & set(_keys(data))


def test_committed_file_agrees_with_docs_results():
    """The page and docs/results.md show the same numbers (run scripts/explorer/export_research.py after a study)."""
    data = json.loads(COMMITTED.read_text())
    docs = (ROOT / "docs" / "results.md").read_text()
    h1 = data["signal"]["periods"]["test"]["measures"]["composite"]["ls_net_5bps"]
    row = f"+{h1['mean'] * 100:.2f}% ({h1['t']:.2f}) | [{h1['ci95'][0] * 100:+.2f}%, {h1['ci95'][1] * 100:+.2f}%]"
    assert row in docs, row
    for name, variant in [("baseline", data["pitfalls"]["baseline"]), ("survivors", data["pitfalls"]["mistakes"]["survivors"])]:
        assert re.search(rf"\| {name} \| {variant['ls_monthly'] * 100:.2f} \| {variant['ls_t']:.2f} \|", docs), name
    vwap = data["execution"]["cost_bps"]["large"]["0.05"]["VWAP"]
    assert f"| Large | 5 | {vwap:.2f} |" in docs
