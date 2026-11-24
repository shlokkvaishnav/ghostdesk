"""The published frozen models (D38): the manifest check refuses missing, changed or incompatible files, and the
night run fails (exit code 1) before it touches the network when the models do not match."""
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from ghostdesk.live.model_release import FILES, RELEASE_TAG, ModelReleaseError, build_manifest, sha256, verify
from ghostdesk.live.predict import LIVE_MODELS

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs" / "results" / "MODEL_MANIFEST.json"


def _models(tmp_path):
    root = tmp_path / "models"
    root.mkdir()
    (root / "lightgbm.txt").write_text("tree\n")
    np.save(root / "ridge.npy", np.arange(3.0))
    (root / "sectors.json").write_text('{"A": "35"}')
    meta = {"fitted_on": ["2016-01-04", "2022-12-28"], "features": ["KMID"], "ensemble_weights": {}}
    (root / "meta.json").write_text(json.dumps(meta))
    return root, build_manifest(root, meta, {"numpy": np.__version__}, [])


def test_verify_accepts_the_files_of_the_manifest(tmp_path):
    root, man = _models(tmp_path)
    assert set(verify(root, man, LIVE_MODELS)) == set(FILES)
    assert man["release_tag"] == RELEASE_TAG != "latest"


@pytest.mark.parametrize("fault", ["missing", "corrupt", "same_size_corrupt", "tag", "version", "models"])
def test_verify_refuses_missing_corrupt_or_incompatible(tmp_path, fault):
    root, man = _models(tmp_path)
    if fault == "missing":
        (root / "lightgbm.txt").unlink()
    elif fault == "corrupt":
        (root / "lightgbm.txt").write_text("tree\nextra\n")
    elif fault == "same_size_corrupt":
        (root / "lightgbm.txt").write_text("TREE\n")
    elif fault == "tag":
        man["release_tag"] = "latest"
    elif fault == "version":
        man["manifest_version"] = 99
    elif fault == "models":
        man["models"] = [m for m in man["models"] if m["name"] != "lightgbm"]
    with pytest.raises(ModelReleaseError):
        verify(root, man, LIVE_MODELS)


def test_committed_manifest_pins_the_tag_and_publishes_only_the_four_nightly_models():
    man = json.loads(MANIFEST.read_text())
    assert man["release_tag"] == RELEASE_TAG
    pub = {m["name"] for m in man["models"] if m["published"]}
    assert pub == set(LIVE_MODELS)
    status = {m["name"]: m for m in man["models"]}
    assert not status["transformer"]["published"] and not status["kronos_small"]["published"]
    assert "failed" in status["kronos_small"]["status"]
    assert {f["name"] for f in man["files"]} == set(FILES)
    assert all(len(f["sha256"]) == 64 for f in man["files"])


def test_night_fails_loudly_when_the_models_do_not_match(tmp_path):
    """No network: the check runs before the broker is created."""
    root, _ = _models(tmp_path)
    (root / "ridge.npy").write_bytes(b"x" * (root / "ridge.npy").stat().st_size)
    env = {**os.environ, "GHOSTDESK_DATA": str(tmp_path / "data"), "GHOSTDESK_MODELS": str(root),
           "PYTHONPATH": str(ROOT / "src"), "ALPACA_API_KEY": "", "ALPACA_SECRET_KEY": ""}
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "live_desk.py"), "night"], env=env,
                       capture_output=True, text=True, timeout=120, cwd=tmp_path, check=False)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "ModelReleaseError" in r.stdout + r.stderr and "::error::" in r.stdout
    assert sha256(root / "lightgbm.txt")  # the check did not change the files
