"""Monthly factor returns from the Kenneth French data library (Fama-French 5 factors 2x3, and momentum).

The CSV files hold a monthly table (rows `YYYYMM`) and then an annual table (rows `YYYY`); only the monthly rows are
read. Values are percent in the files and decimals here. The files are fetched by the `sources` workflow (the
library answers 404 to the owner's network) into `data/sources/ff/`.
"""
from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path

import pandas as pd

MONTH_ROW = re.compile(r"^\s*(\d{6})\s*,")


def read_french(path: str | Path) -> pd.DataFrame:
    """A French-library CSV zip -> monthly table indexed by month-end (Timestamp), in decimals."""
    with zipfile.ZipFile(path) as z:
        text = z.read(z.namelist()[0]).decode("latin-1")
    lines = text.splitlines()
    head = next(i for i, ln in enumerate(lines) if ln.startswith(",") and i + 1 < len(lines)
                and MONTH_ROW.match(lines[i + 1]))
    rows = [lines[head]]
    for ln in lines[head + 1:]:
        if not MONTH_ROW.match(ln):
            break
        rows.append(ln)
    df = pd.read_csv(io.StringIO("\n".join(rows)), index_col=0)
    df.columns = [c.strip() for c in df.columns]
    df.index = pd.to_datetime(df.index.astype(str), format="%Y%m") + pd.offsets.MonthEnd(0)
    return df.astype(float) / 100.0


def load_factors(folder: str | Path) -> pd.DataFrame:
    """Mkt-RF, SMB, HML, RMW, CMA, RF and Mom, monthly, in decimals."""
    folder = Path(folder)
    ff5 = read_french(folder / "F-F_Research_Data_5_Factors_2x3_CSV.zip")
    mom = read_french(folder / "F-F_Momentum_Factor_CSV.zip")
    return ff5.join(mom, how="inner")
