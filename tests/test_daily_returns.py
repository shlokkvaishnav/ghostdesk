"""Bad corporate-action days are flagged; real splits, dividends and real crashes are not."""
import numpy as np
import pandas as pd

from ghostdesk.data.daily_returns import daily_returns


def bars(sym, closes):
    t = pd.date_range("2020-03-30 04:00", periods=len(closes), freq="B", tz="UTC")
    return pd.DataFrame({"symbol": sym, "t": t, "c": closes})


def test_flags_only_vendor_errors():
    adj = pd.concat([bars("SPIN", [40, 40, 4.3, 4.4]),   # spin-off booked as a split: -89% adjusted
                     bars("SPLT", [100, 100, 101, 102]),  # 4:1 split: adjusted is smooth
                     bars("CRSH", [100, 100, 45, 46])])   # a real crash: raw and adjusted agree
    raw = pd.concat([bars("SPIN", [40, 40, 17.2, 17.6]),  # raw fell 57% (value moved to the new company)
                     bars("SPLT", [400, 400, 101, 102]),
                     bars("CRSH", [100, 100, 45, 46])])
    out = daily_returns(adj, raw)
    flagged = out[out["flag"]]
    assert flagged["symbol"].tolist() == ["SPIN"] and np.isnan(flagged["ret"].iloc[0])
    crash = out[(out["symbol"] == "CRSH")]["ret"].dropna()
    assert abs(crash.iloc[1] - np.log(0.45)) < 1e-12  # the real crash is kept
    assert out[out["symbol"] == "SPLT"]["ret"].dropna().abs().max() < 0.02
