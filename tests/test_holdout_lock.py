"""The test period stays locked until the pre-registration is final, committed and stamped."""
import pandas as pd
import pytest

from ghostdesk.research.holdout_lock import VAL_END, TestPeriodLocked, final_and_stamped, guard, research_end, unlock


def test_draft_or_unstamped_preregistration_keeps_the_lock(tmp_path):
    p = tmp_path / "prereg.md"
    p.write_text("# Pre-registration\nStatus: draft\n")
    always = lambda path: "abc" if path.exists() else None
    assert final_and_stamped(p, always) is None
    p.write_text("# Pre-registration\nStatus: final\n")
    assert final_and_stamped(p, always) is None  # no .ots proof
    (tmp_path / "prereg.md.ots").write_bytes(b"proof")
    assert unlock(p, always) == "abc"
    with pytest.raises(TestPeriodLocked):
        unlock(p, lambda path: None)  # not committed


def test_guard_refuses_test_sessions_by_default(tmp_path):
    guard(pd.bdate_range("2021-01-01", VAL_END))
    with pytest.raises(TestPeriodLocked):
        guard(pd.bdate_range("2022-12-01", "2023-01-10"))
    assert research_end()[0] == VAL_END
    with pytest.raises(TestPeriodLocked):
        research_end(include_test=True, path=tmp_path / "missing.md")
