"""Summary of the final execution runs (2024 test, seeds 0-2): PPO and price-blind PPO against the best fixed
schedule, per stock group and order size. Reads data/execution_results_test_seed{0,1,2}.json (from
scripts/execution_study.py --eval test). Writes data/execution_summary.json and prints a Markdown table.
Usage: python -u scripts/execution_summary.py
"""
import json

from ghostdesk.filings.edgar import DATA_DIR

SEEDS = (0, 1, 2)
AGENTS = ("PPO", "PPO price-blind")
runs = [json.loads((DATA_DIR / f"execution_results_test_seed{s}.json").read_text()) for s in SEEDS]

out: dict = {"seeds": list(SEEDS), "test_days": runs[0]["test_days"], "rows": []}
print("| Stocks | Size (% ADV) | Best fixed (bps) | Agent | Agent - best fixed, mean of seeds (bps) | "
      "Per seed | Seeds worse (CI > 0) |")
print("|---|---|---|---|---|---|---|")
for group in ("large", "small", "all"):
    for size in runs[0]["vs_best_fixed"][group]:
        for agent in AGENTS:
            cells = [r["vs_best_fixed"][group][size][agent] for r in runs]
            best = {c["best_fixed"] for c in cells}
            assert len(best) == 1, (group, size, best)
            best_name = best.pop()
            best_bps = runs[0]["mean_bps"][group][size][best_name]
            diffs = [c["mean_bps"] for c in cells]
            worse = sum(c["ci95"][0] > 0 for c in cells)
            better = sum(c["ci95"][1] < 0 for c in cells)
            row = {"group": group, "size": float(size), "agent": agent, "best_fixed": best_name,
                   "best_fixed_bps": best_bps, "diff_bps_per_seed": diffs, "diff_bps_mean": sum(diffs) / len(diffs),
                   "ci95_per_seed": [c["ci95"] for c in cells], "seeds_worse": worse, "seeds_better": better}
            out["rows"].append(row)
            print(f"| {group} | {float(size) * 100:g} | {best_name} {best_bps:.2f} | {agent} | "
                  f"{row['diff_bps_mean']:+.2f} | {', '.join(f'{d:+.2f}' for d in diffs)} | {worse} of 3 |")

out["seeds_better_any"] = sum(r["seeds_better"] for r in out["rows"])
(DATA_DIR / "execution_summary.json").write_text(json.dumps(out, indent=1))
print(f"\nseed-cells where an agent is significantly better than the best fixed schedule: {out['seeds_better_any']}")
