"""The execution study: does a PPO agent, trained on 2023 days, sell an order over the first hour of 2024 days at a
lower cost than fixed schedules (TWAP, VWAP from the 2023 volume profile, Almgren-Chriss shapes)?

Order sizes 0.1%, 1% and 5% of ADV; 20 stocks (10 large, 10 smaller); replay simulator `execution.replay_simulator`.
Differences are paired (same stock, day and size) against the best fixed schedule, with 95% intervals clustered by
day. Design work uses `--eval val` (inside 2023); `--eval test` (2024) is the final run. Writes
data/execution_results_<eval>_seed<n>.json and data/ppo_execution_<eval>_seed<n>.pt (not in git).
Usage: python -u scripts/studies/run_execution_study.py [--eval val|test] [--steps 1000000] [--seed 0] [--reward impact]
"""
import argparse
import json
import time

import numpy as np
import pandas as pd
import torch

from ghostdesk.execution.ppo_agent import PPO, PPOConfig
from ghostdesk.execution.replay_simulator import (
    ETA,
    ReplayEnv,
    ac_weights,
    make_days,
    schedule_trades,
    shortfall_bps,
    twap_weights,
    volume_profile,
)
from ghostdesk.filings.edgar_client import DATA_DIR

ap = argparse.ArgumentParser()
ap.add_argument("--steps", type=int, default=300_000)
ap.add_argument("--seed", type=int, default=0)
ap.add_argument("--eval", choices=("val", "test"), default="val",
                help="val: train 2023-01..09, evaluate 2023-10..12 (design work); test: train 2023, evaluate 2024")
ap.add_argument("--reward", choices=("shortfall", "impact"), default="impact")
ap.add_argument("--log-std", type=float, default=-1.0, help="initial log std of the policy (exploration noise)")
args = ap.parse_args()
SIZES = (0.001, 0.01, 0.05)
HALF_SPREAD = 1e-4

minutes = pd.read_parquet(DATA_DIR / "minutes.parquet")
group = minutes.groupby("symbol")["group"].first().to_dict()
daily = pd.read_parquet(DATA_DIR / "prices_daily_raw.parquet", columns=["symbol", "t", "c", "v"])
daily = daily[daily["symbol"].isin(group)]
days = make_days(minutes, daily)
if args.eval == "val":
    train = [d for d in days if d.day.year == 2023 and d.day.month <= 9]
    test = [d for d in days if d.day.year == 2023 and d.day.month >= 10]
else:
    train = [d for d in days if d.day.year == 2023]
    test = [d for d in days if d.day.year == 2024]
profile = volume_profile(train)  # expected volume shape, from 2023 only
print(f"days: train {len(train)}, test {len(test)}", flush=True)

fixed = {"TWAP": lambda d: twap_weights(12), "VWAP": lambda d: profile[d.symbol],
         "AC k=1": lambda d: ac_weights(12, 1.0), "AC k=3": lambda d: ac_weights(12, 3.0)}


def run_fixed(eta=ETA) -> pd.DataFrame:
    rows = []
    for d in test:
        for s in SIZES:
            for name, w in fixed.items():
                rows.append((d.symbol, d.day, s, name, shortfall_bps(d, schedule_trades(w(d), s, d), s, HALF_SPREAD,
                                                                      eta)))
    return pd.DataFrame(rows, columns=["symbol", "day", "size", "strategy", "bps"])


def run_policy(model, observe_price) -> pd.DataFrame:
    env = ReplayEnv(test, profile, SIZES, observe_price=observe_price, half_spread=HALF_SPREAD)
    rows = []
    for d in test:
        for s in SIZES:
            env.set_episode(d, s)
            o, _ = env.reset()
            done, info = False, {}
            while not done:
                a, _, _ = model.act(o, deterministic=True)
                o, _, done, _, info = env.step(a)
            rows.append((d.symbol, d.day, s, info["shortfall_bps"]))
    return pd.DataFrame(rows, columns=["symbol", "day", "size", "bps"])


def clustered_diff(a: pd.Series, b: pd.Series, days: pd.Series) -> dict:
    """Mean of a - b with a 95% interval; standard error clustered by day (stocks on one day share market moves)."""
    diff = (a - b).to_numpy()
    m = float(diff.mean())
    sums = pd.Series(diff - m).groupby(days.to_numpy()).sum()
    n, g = len(diff), len(sums)
    se = float(np.sqrt(g / (g - 1) * np.sum(sums**2)) / n)
    return {"mean_bps": m, "ci95": [m - 1.96 * se, m + 1.96 * se], "n": int(n), "days": int(g)}


t0 = time.time()
base = run_fixed()
print(f"fixed schedules on {base['day'].nunique()} test days: {time.time() - t0:.0f} s", flush=True)
# reward scale per size: the mean VWAP cost of that size on the training days, so every size teaches the agent
scale = {s: float(np.mean([shortfall_bps(d, schedule_trades(profile[d.symbol], s, d), s, HALF_SPREAD)
                           for d in train[::10]])) for s in SIZES}
models = {}
for name, observe in (("PPO", True), ("PPO price-blind", False)):
    t1 = time.time()
    env = ReplayEnv(train, profile, SIZES, observe_price=observe, half_spread=HALF_SPREAD, seed=args.seed,
                    reward=args.reward, scale=scale)
    ppo = PPO(env, PPOConfig(n_steps=4096, batch=256, epochs=10, lr=3e-4, gamma=1.0, gae_lambda=0.95), args.seed)
    with torch.no_grad():
        ppo.model.log_std.fill_(args.log_std)
    ppo.learn(args.steps, log=lambda m: None)
    models[name] = ppo.model
    print(f"{name}: trained {args.steps} steps in {time.time() - t1:.0f} s", flush=True)
torch.save({k: m.state_dict() for k, m in models.items()}, DATA_DIR / f"ppo_execution_{args.eval}_seed{args.seed}.pt")
pol = pd.concat([run_policy(m, observe).assign(strategy=k) for (k, m), observe in
                 zip(models.items(), (True, False), strict=True)])
allr = pd.concat([base, pol], ignore_index=True)
allr["group"] = allr["symbol"].map(group)

results = {"eval": args.eval, "reward": args.reward, "log_std": args.log_std, "steps": args.steps, "seed": args.seed,
           "train_days": len({d.day for d in train}), "test_days": int(base["day"].nunique()),
           "impact": {"eta": ETA, "beta": 0.6, "gamma": 0.314, "half_spread_bps": HALF_SPREAD * 1e4},
           "mean_bps": {}, "vs_best_fixed": {}, "sensitivity_eta": {}}
for g in ("large", "small", "all"):
    sub = allr if g == "all" else allr[allr["group"] == g]
    means = sub.groupby(["size", "strategy"])["bps"].mean().unstack()
    results["mean_bps"][g] = {f"{s:g}": {k: float(v) for k, v in row.items()} for s, row in means.iterrows()}
    for s in SIZES:
        m = sub[sub["size"] == s].pivot_table(index=["symbol", "day"], columns="strategy", values="bps")
        best = min(fixed, key=lambda k: m[k].mean())
        for k in models:
            results["vs_best_fixed"].setdefault(g, {}).setdefault(f"{s:g}", {})[k] = {
                "best_fixed": best, **clustered_diff(m[k], m[best], m.index.get_level_values("day").to_series())}
for f in (0.5, 2.0):
    r = run_fixed(ETA * f)
    results["sensitivity_eta"][f"x{f:g}"] = {f"{s:g}": {k: float(v) for k, v in row.items()} for s, row in
                                             r.groupby(["size", "strategy"])["bps"].mean().unstack().iterrows()}
(DATA_DIR / f"execution_results_{args.eval}_seed{args.seed}.json").write_text(json.dumps(results, indent=1))
for g in ("large", "small"):
    print(f"\n{g}: mean cost (bps)\n", pd.DataFrame(results["mean_bps"][g]).T.round(2).to_string())
    for s, v in results["vs_best_fixed"][g].items():
        print(f"  size {s}: " + "; ".join(f"{k} - {x['best_fixed']} = {x['mean_bps']:+.2f} "
                                         f"[{x['ci95'][0]:+.2f}, {x['ci95'][1]:+.2f}]" for k, x in v.items()))
