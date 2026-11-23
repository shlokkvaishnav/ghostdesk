"""Statistics for the research explorer page (web/explore/index.html, address /ghostdesk/explore/).

The function `build` takes the result files of the studies and keeps only statistics: means, t values, confidence
intervals and costs. It keeps no ticker, price, date of a trade or row of data. The output is small, so it is
committed as web/data/research.json and the page works with no data/ folder.
"""
from __future__ import annotations

from statistics import mean

PERIODS = {
    "build": {"label": "Build 2016–2019", "confirmatory": False},
    "check": {"label": "Check 2020–2021", "confirmatory": False},
    "test": {"label": "Test 2022–2025", "confirmatory": True},
    "pooled": {"label": "Pooled 2016–2025", "confirmatory": False},
}
SECTIONS = {"full": "Whole report", "risk": "Risk factors", "mdna": "Management discussion"}
SIMILARITIES = {"cosine": "cosine similarity", "jaccard": "word-set overlap (Jaccard)", "edit": "edit distance"}
PITFALLS = {
    "survivors": ("Today's stock list",
                  "Uses the S&P 500 of today for every past month, so the companies that later left the index are missing."),
    "mixed_forms": ("10-K and 10-Q ranked together",
                    "Ranks annual and quarterly reports in one list instead of like with like."),
    "filing_date": ("Filing date as the time",
                    "Uses a report from its filing date instead of the exact time the SEC accepted it."),
    "period_end": ("Period end as the time",
                   "Uses a report from the end of its period, before the public could read it."),
    "vendor_errors": ("Vendor price errors kept",
                      "Keeps the price errors of the data vendor instead of removing them."),
}
STRATEGIES = ["TWAP", "VWAP", "AC k=1", "AC k=3", "PPO", "PPO price-blind"]


def measure_label(key: str) -> str:
    """A plain name for a signal measure key, such as `sim_risk_cosine_r`."""
    if key == "composite":
        return "Composite (all nine measures)"
    if key == "composite_ind":
        return "Composite, industry-neutral"
    _, section, similarity, _ = key.split("_")
    return f"{SECTIONS[section]}, {SIMILARITIES[similarity]}"


def _stat(d: dict) -> dict:
    return {"mean": d["mean"], "t": d["t"], "ci95": list(d["ci95"])}


def _measure(m: dict) -> dict:
    return {
        "months": m["months"],
        "quintiles": [m["quintile_mean_monthly"][str(q)] for q in range(1, 6)],
        "ls_gross": _stat(m["long_short_gross"]),
        "ls_net_5bps": _stat(m["long_short_net"]["5bps"]),
        "ic": _stat(m["ic"]),
        "sharpe_annual_gross": m["sharpe_annual_gross"],
        "mde_monthly_80pct_power": m["mde_monthly_80pct_power"],
    }


def signal(results: dict[str, dict]) -> dict:
    """Signal study: for each period and measure, the quintile returns and the long-short statistics."""
    measures = list(results["test"]["measures"])
    periods = {}
    for key, meta in PERIODS.items():
        r = results[key]
        p = {**meta, "formation": list(r["formation"]), "months": r["panel"]["months"],
             "measures": {k: _measure(r["measures"][k]) for k in measures}}
        if meta["confirmatory"]:
            p["prereg_commit"] = r["prereg_commit"][:7]
            p["code_commit"] = r["code_commit"][:7]
        periods[key] = p
    return {"primary": results["test"]["primary"], "measures": {k: measure_label(k) for k in measures},
            "periods": periods}


def pitfalls(table: dict) -> dict:
    """Backtest mistakes: the honest baseline and, for each mistake, the result with that one guard turned off."""
    fields = ("ls_monthly", "ls_t", "sharpe", "ic", "ic_t", "stock_months")
    v = table["variants"]
    return {
        "period": list(table["period"]),
        "baseline": {f: v["baseline"][f] for f in fields},
        "mistakes": {k: {"label": label, "explain": explain, **{f: v[k][f] for f in fields}}
                     for k, (label, explain) in PITFALLS.items()},
    }


def execution(seed_runs: list[dict]) -> dict:
    """Execution study: cost in bps per stock group, order size and strategy, the mean over the seeds."""
    groups = seed_runs[0]["mean_bps"]
    cost = {g: {size: {s: mean(run["mean_bps"][g][size][s] for run in seed_runs) for s in STRATEGIES}
                for size in groups[g]} for g in groups}
    return {"seeds": len(seed_runs), "test_days": seed_runs[0]["test_days"], "strategies": STRATEGIES,
            "groups": {"large": "10 large stocks", "small": "10 smaller stocks"}, "cost_bps": cost}


def capacity(cap: dict) -> dict:
    """Capacity: monthly trading cost by fund size, the gross edge levels, and the fund size where they meet."""
    curve = sorted((float(aum), cost) for aum, cost in cap["cost_curve"].items())
    return {"cost_curve": [[aum, cost] for aum, cost in curve], "gross_levels": dict(cap["gross_levels"]),
            "break_even_aum": dict(cap["break_even_aum"])}


def _round(x, digits: int = 6):
    if isinstance(x, float):
        return float(f"{x:.{digits}g}")
    if isinstance(x, dict):
        return {k: _round(v, digits) for k, v in x.items()}
    if isinstance(x, list):
        return [_round(v, digits) for v in x]
    return x


def build(results: dict[str, dict], pitfall_table: dict, seed_runs: list[dict], cap: dict) -> dict:
    """The whole explorer file: statistics only, rounded to 6 significant digits."""
    return _round({"signal": signal(results), "pitfalls": pitfalls(pitfall_table), "execution": execution(seed_runs),
                   "capacity": capacity(cap)})
