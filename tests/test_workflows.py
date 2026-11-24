"""The workflows that run on a schedule or for a long time stay silent (no failure emails): every step continues on
error. ci.yml runs on push and is meant to fail visibly. The live workflow keeps its guards: the kill switch reaches
the night run, only known modes run, only encrypted state goes to the release, and the Worker's crons fall inside
Alpaca's market-on-open window."""
from pathlib import Path

import pytest
import yaml

WF = Path(__file__).resolve().parents[1] / ".github" / "workflows"
SILENT = sorted(p.name for p in WF.glob("*.yml") if p.name != "ci.yml")


def load(name: str) -> dict:
    return yaml.safe_load((WF / name).read_text())


@pytest.mark.parametrize("name", SILENT)
def test_every_step_continues_on_error(name):
    for job, spec in load(name)["jobs"].items():
        for step in spec["steps"]:
            label = step.get("name") or step.get("uses") or step.get("run", "")[:40]
            assert step.get("continue-on-error") is True, f"{name}: job {job}, step {label!r} can fail the run"


def _steps(name: str) -> dict:
    return {s.get("name") or s.get("id") or s.get("uses"): s for s in load(name)["jobs"]["run"]["steps"]}


def test_kill_switch_reaches_the_night_run_and_flatten_is_separate():
    steps = _steps("live.yml")
    assert steps["night"]["env"]["TRADING"] == "${{ vars.TRADING }}"
    assert "mode == 'flatten'" in steps["flatten"]["if"] and "TRADING" not in steps["flatten"].get("env", {})


def test_only_known_modes_and_schedules_run_the_night():
    script = _steps("live.yml")["mode"]["run"]
    assert "schedule) m=night" in script
    assert 'case "$m" in night|flatten|site) ;; *) m=site ;; esac' in script


def test_releases_get_only_the_encrypted_state():
    live = _steps("live.yml")
    up = live["keep the live state in the release"]["run"]
    assert 'if [ -z "$STATE_KEY" ]' in up and "openssl enc -aes-256-cbc" in up and "live-state.tar.enc" in up
    assert "openssl enc -d" in live["restore from the release if the cache is lost"]["run"]


def test_worker_crons_fall_inside_the_opg_window():
    """01:30 and 11:00 UTC are 20:30/21:30 and 06:00/07:00 New York time: inside 19:00-09:28 in both seasons."""
    toml = (WF.parents[1] / "worker" / "wrangler.toml").read_text()
    assert 'crons = ["30 1 * * 2-6", "0 11 * * 2-6"]' in toml
