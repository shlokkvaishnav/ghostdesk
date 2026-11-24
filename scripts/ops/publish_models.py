"""Write docs/results/MODEL_MANIFEST.json for the frozen models in data/live/models/ (decision D38).

The release itself is made by hand once, with the files and the manifest:
    PYTHONPATH=src .venv/bin/python -u scripts/ops/publish_models.py
    gh release create models-v1 data/live/models/{lightgbm.txt,ridge.npy,sectors.json,meta.json} \
        docs/results/MODEL_MANIFEST.json --title "Frozen models v1"
The script checks the files against the manifest it writes (`model_release.verify`) and that the models load.
"""
import json
import platform
from importlib.metadata import version

from ghostdesk.live.model_release import build_manifest, verify
from ghostdesk.live.predict import LIVE_MODELS, load_models
from ghostdesk.paths import DATA_DIR, REPO_ROOT

ROOT = DATA_DIR / "live" / "models"
OUT = REPO_ROOT / "docs" / "results" / "MODEL_MANIFEST.json"
PACKAGES = ("lightgbm", "numpy", "pandas", "scipy", "cvxpy", "osqp", "duckdb", "pyarrow")

EXTRA = [
    {"name": "transformer", "nightly": False, "published": False, "kind": "small Transformer, trained from scratch "
     "on Kaggle GPU (71,297 parameters, 3 seeds)", "trained_on": ["2016-01-04", "2020-12-31"],
     "status": "validation scores only; the training kernel did not save weights, so there is nothing to publish "
               "(kaggle/transformer/kernel.py)"},
    {"name": "chronos2", "nightly": False, "published": False, "kind": "zero-shot foundation model",
     "checkpoint": "https://huggingface.co/amazon/chronos-2",
     "revision": "not recorded (the Hugging Face default branch on 2026-11-24)",
     "status": "validation scores only (zero-shot, not fine-tuned); the maker's checkpoint is not redistributed"},
    {"name": "timesfm25", "nightly": False, "published": False, "kind": "zero-shot foundation model",
     "checkpoint": "https://huggingface.co/google/timesfm-2.5-200m-pytorch",
     "revision": "not recorded (the Hugging Face default branch on 2026-11-24)",
     "status": "validation scores only (zero-shot, not fine-tuned); the maker's checkpoint is not redistributed"},
    {"name": "kronos_small", "nightly": False, "published": False, "kind": "zero-shot foundation model",
     "checkpoint": "https://huggingface.co/NeoQuasar/Kronos-small",
     "status": "failed: CUDA out of memory on Kaggle; no validation scores; not published"},
]

meta = json.loads((ROOT / "meta.json").read_text())
versions = {"python": platform.python_version(), **{p: version(p) for p in PACKAGES}}
man = build_manifest(ROOT, meta, versions, EXTRA)
verify(ROOT, man, LIVE_MODELS)
models = load_models(ROOT)
assert set(models) == set(LIVE_MODELS), sorted(models)
OUT.write_text(json.dumps(man, indent=1) + "\n")
print(json.dumps({f["name"]: f["sha256"] for f in man["files"]}, indent=1))
