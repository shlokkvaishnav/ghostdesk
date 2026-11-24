"""Write the panel that the Kaggle kernels read (Transformer training, foundation-model inference) and upload it as a
PRIVATE Kaggle dataset. Raw prices never go to git; on Kaggle the dataset stays private to the owner's account.

Contents (data/kaggle/panel/panel.npz): days (YYYYMMDD int), symbols, adjusted open/high/low/close/volume (float32,
session x symbol), member (bool), label (the residual label, `research.dataset.residual_label`), sector codes. It ends
at the validation end unless --include-test is given (which needs the test lock open).
Usage: python -u scripts/research/export_kaggle_panel.py [--upload] [--include-test]
"""
import argparse
import json
import subprocess
from pathlib import Path

import numpy as np

from ghostdesk.paths import DATA_DIR
from ghostdesk.research.dataset import load_panel, residual_label
from ghostdesk.research.holdout_lock import TEST_END, TRAIN_START, VAL_END

KAGGLE = Path.home() / ".cache" / "kaggle-cli" / "bin" / "kaggle"
SLUG = "ghostdesk-panel"

ap = argparse.ArgumentParser()
ap.add_argument("--upload", action="store_true")
ap.add_argument("--include-test", action="store_true")
args = ap.parse_args()

end = TEST_END if args.include_test else VAL_END
p = load_panel(TRAIN_START, end, include_test=args.include_test, warmup_days=0)
y = residual_label(p)
out = DATA_DIR / "kaggle" / "panel"
out.mkdir(parents=True, exist_ok=True)
codes = {s: i for i, s in enumerate(sorted(set(p.sector)))}
np.savez_compressed(out / "panel.npz", days=np.array([int(f"{d:%Y%m%d}") for d in p.days]),
                    symbols=np.array(p.symbols), member=p.member, label=y.astype(np.float32),
                    sector=np.array([codes[s] for s in p.sector]),
                    **{k: p.fields[k].astype(np.float32) for k in ("open", "high", "low", "close", "volume")})
user = subprocess.run([str(KAGGLE), "config", "view"], capture_output=True, text=True, check=False).stdout
owner = next((ln.split(":", 1)[1].strip() for ln in user.splitlines() if ln.strip().startswith("- username")), "")
meta = {"title": SLUG, "id": f"{owner}/{SLUG}", "licenses": [{"name": "other"}], "isPrivate": True}
(out / "dataset-metadata.json").write_text(json.dumps(meta, indent=1))
print(f"{len(p.days)} sessions ({p.days[0]:%Y-%m-%d} .. {p.days[-1]:%Y-%m-%d}) x {len(p.symbols)} symbols; "
      f"{(out / 'panel.npz').stat().st_size / 1e6:.1f} MB; dataset {meta['id']}", flush=True)
if args.upload:
    exists = subprocess.run([str(KAGGLE), "datasets", "status", meta["id"]], capture_output=True, text=True, check=False)
    cmd = ["datasets", "version", "-m", "panel update", "-p", str(out)] if exists.returncode == 0 and \
        "ready" in exists.stdout.lower() else ["datasets", "create", "-p", str(out)]
    r = subprocess.run([str(KAGGLE), *cmd], capture_output=True, text=True, check=False)
    print(r.stdout[-500:], r.stderr[-500:], flush=True)
