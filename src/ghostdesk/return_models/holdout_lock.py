"""The lock on the test period. Model development sees only formation months up to `DEV_END`; the test period
(2022-2025) opens only when the ML pre-registration (`docs/preregistration-ml.md`) is committed with no local
change, so the rules of the test are fixed in git history before any test-period return is computed (decision D18).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pandas as pd

DEV_END = pd.Timestamp("2021-12-31")
TEST_START, TEST_END = pd.Timestamp("2022-01-01"), pd.Timestamp("2025-12-31")
PREREG = Path(__file__).resolve().parents[3] / "docs" / "preregistration-ml.md"


class TestPeriodLocked(RuntimeError):
    """Raised when code asks for test-period rows before the pre-registration is committed."""


def dev(panel: pd.DataFrame) -> pd.DataFrame:
    """Rows with formation months up to DEV_END (build 2016-2019 and check 2020-2021)."""
    return panel[panel["month"] <= DEV_END].copy()


def committed(path: Path) -> str | None:
    """The commit that last changed `path`, or None if the file is absent, not in git, or changed locally."""
    if not path.exists():
        return None
    root = path.parent

    def git(*a):
        return subprocess.run(["git", *a], cwd=root, capture_output=True, text=True, check=False)

    sha = git("log", "-1", "--format=%H", "--", path.name).stdout.strip()
    dirty = git("status", "--porcelain", "--", path.name).stdout.strip()
    return sha if sha and not dirty else None


def unlock(path: Path = PREREG, check=committed) -> str:
    """The pre-registration commit; raises TestPeriodLocked if there is none."""
    sha = check(path)
    if not sha:
        raise TestPeriodLocked(f"the test period is locked: commit {path.name} first (no local changes)")
    return sha


def everything(panel: pd.DataFrame, path: Path = PREREG, check=committed) -> tuple[pd.DataFrame, str]:
    """All rows up to TEST_END, with the pre-registration commit. A walk-forward test needs the earlier months to
    train; only the months from TEST_START are scored as test results."""
    sha = unlock(path, check)
    return panel[panel["month"] <= TEST_END].copy(), sha
