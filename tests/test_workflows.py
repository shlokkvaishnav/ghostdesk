"""The workflows that run on a schedule or for hours stay silent (rule 8 in AGENTS.md) and keep the live guards:
every step continues on error, the kill switch gates the trade step, and only the score schedules start a score."""
import re
from pathlib import Path

import pytest
import yaml

WF = Path(__file__).resolve().parents[1] / ".github" / "workflows"
SILENT = ["live.yml", "features.yml", "sources.yml"]  # ci.yml runs on push and is meant to fail visibly


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


def test_kill_switch_gates_trading_but_not_flatten():
    steps = _steps("live.yml")
    cond = steps["trade"]["if"]
    assert "vars.TRADING != 'off'" in cond and "mode == 'flatten'" in cond
    assert "vars.TRADING == 'off'" in steps["trading is off"]["if"]


def test_only_listed_score_schedules_start_a_score():
    wf = load("live.yml")
    crons = [c["cron"] for c in wf[True]["schedule"]]  # PyYAML reads the key `on` as True
    script = _steps("live.yml")["mode"]["run"]
    score = re.findall(r'"schedule:([^"]+)"', script)
    assert score and all(c in crons for c in score)  # a renamed score cron must not turn into a trade run
    assert "schedule:*) m=trade" in script
    assert 'case "$m" in score|trade|flatten|site) ;; *) m=site ;; esac' in script
