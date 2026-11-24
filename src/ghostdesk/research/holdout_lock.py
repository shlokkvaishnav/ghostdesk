"""The lock on the test period (decision D27). Research code sees sessions up to `VAL_END`; the test period
(2023-01 to 2026-10) opens only when the pre-registration (`docs/preregistration-platform.md`) is committed with no
local change, says `Status: final`, and its OpenTimestamps proof (`.ots`) is committed next to it. So the rules of
the test are fixed in git history, and stamped, before any test-period label is computed.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pandas as pd

TRAIN_START, TRAIN_END = pd.Timestamp("2016-01-01"), pd.Timestamp("2020-12-31")
VAL_START, VAL_END = pd.Timestamp("2021-01-01"), pd.Timestamp("2022-12-31")
TEST_START, TEST_END = pd.Timestamp("2023-01-01"), pd.Timestamp("2026-10-31")
PREREG = Path(__file__).resolve().parents[3] / "docs" / "preregistration-platform.md"
FINAL = "Status: final"


class TestPeriodLocked(RuntimeError):
    """Raised when code asks for test-period sessions before the pre-registration is final and committed."""


def committed(path: Path) -> str | None:
    """The commit that last changed `path`, or None if the file is absent, not in git, or changed locally."""
    if not path.exists():
        return None

    def git(*a):
        return subprocess.run(["git", *a], cwd=path.parent, capture_output=True, text=True, check=False)

    sha = git("log", "-1", "--format=%H", "--", path.name).stdout.strip()
    dirty = git("status", "--porcelain", "--", path.name).stdout.strip()
    return sha if sha and not dirty else None


def final_and_stamped(path: Path = PREREG, check=committed) -> str | None:
    """The pre-registration commit if the file is final (a line `Status: final`) and its `.ots` proof is committed;
    else None. A draft never opens the lock."""
    sha = check(path)
    if not sha or FINAL not in path.read_text().splitlines():
        return None
    return sha if check(path.with_name(path.name + ".ots")) else None


def unlock(path: Path = PREREG, check=committed) -> str:
    """The pre-registration commit; raises TestPeriodLocked if it is not final, committed and stamped."""
    sha = final_and_stamped(path, check)
    if not sha:
        raise TestPeriodLocked(f"the test period is locked: {path.name} must say '{FINAL}', be committed with no "
                               "local change, and have a committed .ots proof")
    return sha


def research_end(include_test: bool = False, path: Path = PREREG, check=committed) -> tuple[pd.Timestamp, str | None]:
    """The last session that research code may read, and the pre-registration commit when the test is opened."""
    if not include_test:
        return VAL_END, None
    return TEST_END, unlock(path, check)


def guard(days, include_test: bool = False, path: Path = PREREG, check=committed) -> None:
    """Raise TestPeriodLocked if `days` reach past VAL_END while the test is not opened."""
    end, _ = research_end(include_test, path, check)
    if len(days) and pd.DatetimeIndex(days).max() > end:
        raise TestPeriodLocked(f"sessions after {end:%Y-%m-%d} asked for; the test period is locked")
