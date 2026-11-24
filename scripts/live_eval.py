"""Forward evaluation of the prediction ledger, offline and read-only (D37).

    PYTHONPATH=src .venv/bin/python scripts/live_eval.py [--live data/live] [--validation docs/results/validation.json]

Reads the ledger, the nightly `night_*.json` books and the live price store; writes `forward_eval.json` into the live
directory and prints one line ("N days of forward data"). Places no order and calls no broker. Runs on an empty ledger.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from ghostdesk.data.store import PriceStore
from ghostdesk.live.compare import load_validation
from ghostdesk.live.forward import build_report, read_books
from ghostdesk.live.ledger import Ledger
from ghostdesk.paths import DATA_DIR, REPO_ROOT


def run(live, validation_path) -> dict:
    rows = Ledger(live / "ledger").read()
    sec_p = live / "models" / "sectors.json"
    sectors = json.loads(sec_p.read_text()) if sec_p.exists() else None
    raw = pd.DataFrame()
    if len(rows) and (live / "store").exists():
        raw = PriceStore(live / "store").read("raw", start=rows["session"].min() - pd.Timedelta(days=40))
    report = build_report(rows, read_books(live), raw, sectors, load_validation(validation_path))
    (live / "forward_eval.json").write_text(json.dumps(report, separators=(",", ":"), allow_nan=False))
    return report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", type=Path, default=DATA_DIR / "live")
    ap.add_argument("--validation", type=Path,
                    default=REPO_ROOT / "docs" / "results" / "validation.json")
    a = ap.parse_args()
    a.live.mkdir(parents=True, exist_ok=True)
    r = run(a.live, a.validation)
    print(f"{r['compare']['headline']}; book: {r['book']['days']} days", flush=True)


if __name__ == "__main__":
    main()
