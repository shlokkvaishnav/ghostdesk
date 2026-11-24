"""The published frozen models (decision D38): the GitHub release `models-v1` and its manifest.

`docs/results/MODEL_MANIFEST.json` lists every published file with its SHA-256 and size, the training period, the
feature configuration and the package versions used to fit. The live job downloads the files of the pinned tag
(`RELEASE_TAG`, never "latest") and calls `verify` before `predict.load_models`; a missing, changed or incompatible
file raises `ModelReleaseError`, and the night run then fails with that message (D38). `build_manifest` writes the
manifest from a model folder; it is run once by `scripts/ops/publish_models.py`.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

RELEASE_TAG = "models-v1"
MANIFEST_VERSION = 1
FILES = ("lightgbm.txt", "ridge.npy", "sectors.json", "meta.json")


class ModelReleaseError(RuntimeError):
    """A published model file is missing, has another SHA-256, or does not match the running code."""


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def verify(root: Path, manifest: dict, live_models: tuple[str, ...] | None = None) -> dict[str, str]:
    """Check every manifest file under `root` (exists, size, SHA-256) and that the manifest's nightly models are the
    ones the code runs. Returns file -> SHA-256. Raises `ModelReleaseError` with all problems found."""
    problems = []
    if manifest.get("manifest_version") != MANIFEST_VERSION:
        problems.append(f"manifest version {manifest.get('manifest_version')!r}, code expects {MANIFEST_VERSION}")
    if manifest.get("release_tag") != RELEASE_TAG:
        problems.append(f"manifest is for {manifest.get('release_tag')!r}, code pins {RELEASE_TAG}")
    if live_models is not None:
        nightly = tuple(m["name"] for m in manifest.get("models", []) if m.get("nightly"))
        if set(nightly) != set(live_models):
            problems.append(f"manifest nightly models {sorted(nightly)} != code {sorted(live_models)}")
    out = {}
    for f in manifest.get("files", []):
        p = Path(root) / f["name"]
        if not p.is_file():
            problems.append(f"{f['name']}: missing")
            continue
        if p.stat().st_size != f["bytes"]:
            problems.append(f"{f['name']}: {p.stat().st_size} bytes, manifest {f['bytes']}")
            continue
        h = sha256(p)
        if h != f["sha256"]:
            problems.append(f"{f['name']}: SHA-256 {h[:12]}..., manifest {f['sha256'][:12]}...")
            continue
        out[f["name"]] = h
    if not manifest.get("files"):
        problems.append("manifest lists no files")
    if problems:
        raise ModelReleaseError("; ".join(problems))
    return out


def load_manifest(path: Path) -> dict:
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError) as e:
        raise ModelReleaseError(f"manifest {path}: {type(e).__name__}: {e}") from e


def build_manifest(root: Path, meta: dict, versions: dict[str, str], extra_models: list[dict]) -> dict:
    """The manifest for the files `FILES` under `root`. `meta` is the models' meta.json; `extra_models` describes
    the validated models that are not published (validation only, or failed)."""
    root = Path(root)
    files = [{"name": n, "bytes": (root / n).stat().st_size, "sha256": sha256(root / n)} for n in FILES]
    fitted = meta["fitted_on"]
    models = [
        {"name": "reversal_1d", "nightly": True, "published": True, "kind": "rule (minus 1-day return)",
         "files": [], "trained_on": None},
        {"name": "reversal_5d", "nightly": True, "published": True, "kind": "rule (minus 5-day return)",
         "files": [], "trained_on": None},
        {"name": "ridge", "nightly": True, "published": True, "kind": "ridge regression on ranked Alpha158",
         "files": ["ridge.npy"], "format": "numpy .npy (float64 weights)", "trained_on": fitted},
        {"name": "lightgbm", "nightly": True, "published": True, "kind": "LightGBM regressor on ranked Alpha158",
         "files": ["lightgbm.txt"], "format": "LightGBM native text model", "trained_on": fitted},
    ] + extra_models
    return {
        "manifest_version": MANIFEST_VERSION,
        "release_tag": RELEASE_TAG,
        "models": models,
        "files": files,
        "training": {"fitted_on": fitted, "train_split": "2016-01-04..2020-12-31",
                     "validation_split": "2021-01-04..2022-12-30",
                     "note": "the frozen nightly models are refitted once on train + validation (minus the "
                             "2-session purge) with the validated settings; never refitted after that",
                     "code_commit": meta.get("code_commit"), "data_hash": meta.get("data_hash"),
                     "validation_run_keys": meta.get("validation_run_keys"), "fitted_at": meta.get("at")},
        "features": {"set": "Alpha158", "count": len(meta.get("features", [])), "names": meta.get("features"),
                     "transform": "cross-sectional percentile rank per session",
                     "engine": "ghostdesk.features.engine (engine version 2)"},
        "ensemble_weights": meta.get("ensemble_weights"),
        "dependencies": versions,
    }
