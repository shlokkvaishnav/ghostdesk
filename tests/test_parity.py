"""Live-vs-study parity: for past month-ends, the live code (`live.runner.formation` + `select`) must choose the same
report for each company and give the same `composite` and quintile as the study panel (`signal.panel` +
`signal.study.add_signals`). Uses the local data files; skipped where they are absent (CI has no data/)."""
import numpy as np
import pandas as pd
import pytest

from ghostdesk.data.calendar import opens
from ghostdesk.filings.edgar import DATA_DIR
from ghostdesk.live.runner import formation, select
from ghostdesk.signal.panel import close_utc
from ghostdesk.signal.study import add_signals, quintiles

NEED = ["panel_pooled.parquet", "filings_index.parquet", "features.parquet", "returns_daily.parquet"]
pytestmark = pytest.mark.skipif(not all((DATA_DIR / f).exists() for f in NEED), reason="local data files absent")


@pytest.fixture(scope="module")
def data():
    panel = add_signals(pd.read_parquet(DATA_DIR / "panel_pooled.parquet"))
    index = pd.read_parquet(DATA_DIR / "filings_index.parquet")
    feats = pd.read_parquet(DATA_DIR / "features.parquet")
    feats = feats[feats["error"].fillna("") == ""]
    # the study can only use pairs that have features; the live job scores every latest pair, so the same rule
    index = index.merge(feats[["cik", "accession"]], on=["cik", "accession"], how="inner")
    days = pd.DatetimeIndex(sorted(pd.read_parquet(DATA_DIR / "returns_daily.parquet", columns=["day"])["day"].unique()))
    sessions = pd.DataFrame({"date": days, "open_utc": opens(days), "close_utc": close_utc(days)})
    return panel, index, feats, sessions


@pytest.mark.parametrize("month", ["2017-03-31", "2019-11-29", "2023-06-30", "2025-09-30"])
def test_live_formation_matches_the_study_panel(data, month):
    panel, index, feats, sessions = data
    p = panel[panel["month"] == pd.Timestamp(month)].dropna(subset=["composite"])
    assert len(p) > 300
    members = p[["cik", "price_symbol"]].rename(columns={"price_symbol": "symbol"}).assign(name="", sector="")
    today = sessions.loc[sessions["date"] > pd.Timestamp(month), "date"].iloc[0]  # the next session trades
    f, _, _ = formation(sessions, today, members, index, feats)
    one, _ = select(f, pd.Series(np.exp(p["logdv"].to_numpy()), index=p["price_symbol"].to_numpy()))
    m = p.merge(one[["cik", "accession", "composite"]], on="cik", suffixes=("_study", "_live"))
    assert len(m) == len(p) == len(one)
    assert (m["accession_study"] == m["accession_live"]).all()
    assert np.allclose(m["composite_study"], m["composite_live"])
    q_study = quintiles(p.assign(fwd_ret=0.0), "composite").set_index("cik")["q"]
    q_live = one.set_index("cik")["q"]
    assert (q_study.reindex(q_live.index) == q_live).all()
