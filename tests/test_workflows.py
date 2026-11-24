"""The workflows keep their guards (D38). nightly.yml: order execution is disabled (TRADING fixed to "off", no order or
flatten mode), the models come from the pinned release and are checked before use, a model or night failure fails
the run, the site steps never do, only encrypted state goes to the release, and a failed restore can never replace the
saved ledger. The Worker's crons fall inside Alpaca's market-on-open window and start nightly.yml."""
from pathlib import Path

import yaml

WF = Path(__file__).resolve().parents[1] / ".github" / "workflows"
FAIL_LOUD = {"install", "mode", "models cache", "models", "verify models", "restore from the release if the cache is lost",
             "night", "check the night's outputs", "keep the state in the release", "actions/checkout@v4",
             "actions/setup-python@v5", "actions/cache/restore@v4"}


def load(name: str) -> dict:
    return yaml.safe_load((WF / name).read_text())


def _steps(name: str) -> dict:
    return {s.get("name") or s.get("id") or s.get("uses"): s for s in load(name)["jobs"]["run"]["steps"]}


def test_only_ci_and_nightly_exist():
    assert sorted(p.name for p in WF.glob("*.yml")) == ["ci.yml", "nightly.yml"]


def test_execution_is_disabled_in_the_nightly_workflow():
    text = (WF / "nightly.yml").read_text()
    steps = _steps("nightly.yml")
    assert steps["night"]["env"]["TRADING"] == "off"
    assert "vars.TRADING" not in text and "flatten" not in text.split("jobs:")[1]
    assert 'case "$m" in night|site) ;; *) m=site ;; esac' in steps["mode"]["run"]
    assert "schedule) m=night" in steps["mode"]["run"]


def test_models_are_pinned_cached_and_verified_before_use():
    wf = load("nightly.yml")
    steps = _steps("nightly.yml")
    assert wf["env"]["MODELS_TAG"] == "models-v1"
    text = (WF / "nightly.yml").read_text()
    assert "releases/latest" not in text and "--latest" not in text and "download latest" not in text
    assert "hashFiles('docs/results/MODEL_MANIFEST.json')" in steps["models cache"]["with"]["key"]
    assert 'gh release download "$MODELS_TAG"' in steps["models"]["run"]
    assert "verify(" in steps["verify models"]["run"]
    order = list(steps)
    assert order.index("verify models") < order.index("night")
    assert steps["night"]["env"]["GHOSTDESK_MODELS"] == "data/models-v1"


def test_failures_of_the_pipeline_fail_the_run_and_the_site_steps_do_not():
    for name, step in _steps("nightly.yml").items():
        if name in FAIL_LOUD:
            assert not step.get("continue-on-error"), f"{name} must fail the run (D38)"
        else:
            assert step.get("continue-on-error") is True, f"{name} must not fail the run"


def test_releases_get_only_encrypted_state_and_a_failed_restore_never_overwrites_it():
    steps = _steps("nightly.yml")
    up = steps["keep the state in the release"]
    assert "openssl enc -aes-256-cbc" in up["run"] and "nightly-state.tar.enc" in up["run"]
    assert "steps.restore.outcome == 'success'" in up["if"] and "chain.jsonl" in up["if"]
    rs = steps["restore from the release if the cache is lost"]
    assert "openssl enc -d" in rs["run"] and "pipefail" in rs["shell"]


def test_worker_crons_fall_inside_the_opg_window_and_start_nightly():
    """01:30 and 11:00 UTC are 20:30/21:30 and 06:00/07:00 New York time: inside 19:00-09:28 in both seasons."""
    toml = (WF.parents[1] / "worker" / "wrangler.toml").read_text()
    assert 'crons = ["30 1 * * 2-6", "0 11 * * 2-6"]' in toml and 'WORKFLOW = "nightly.yml"' in toml
