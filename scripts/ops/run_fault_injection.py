"""Randomized nightly runs against the fake Alpaca API with injected faults (`sim.fault_injection`). Prints and writes
data/results/fault_injection.json: scenarios, runs, crashes, failed runs, orders, nights done, violations, and the
same numbers for two deliberate bugs (to show that the checks catch them).
Usage: python -u scripts/ops/run_fault_injection.py [--scenarios 500]
"""
import argparse
import json
import time

import pandas as pd

from ghostdesk.paths import DATA_DIR
from ghostdesk.sim.fault_injection import run_many

ap = argparse.ArgumentParser()
ap.add_argument("--scenarios", type=int, default=500)
args = ap.parse_args()
t0 = time.perf_counter()
main = run_many(args.scenarios)
main["seconds"] = round(time.perf_counter() - t0, 1)
print(json.dumps(main), flush=True)
bugs = {m: run_many(50, start_seed=10_000, mutate=m, **({"p_crash": 0.7} if m == "dup_ids" else {}))
        for m in ("no_window", "dup_ids")}
for m, r in bugs.items():
    print(m, json.dumps({k: v for k, v in r.items() if k != "examples"}), r["examples"][:2], flush=True)
out = {"correct_code": main, "deliberate_bugs": bugs, "at": pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds")}
(DATA_DIR / "results").mkdir(exist_ok=True)
(DATA_DIR / "results" / "fault_injection.json").write_text(json.dumps(out, indent=1))
