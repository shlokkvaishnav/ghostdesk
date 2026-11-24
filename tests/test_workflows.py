"""The workflows that run on a schedule or for a long time stay silent (no failure emails): every step continues on
error. ci.yml runs on push and is meant to fail visibly."""
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
