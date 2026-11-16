"""The report index: every 10-K and 10-Q of the universe since 2009, with its SEC acceptance time, and the earlier
report that it is compared with.

Like with like (Cohen, Malloy and Nguyen 2020): a 10-K is compared with the previous 10-K, and a 10-Q with the 10-Q
for the same fiscal quarter one year before (Q2 with Q2). The pair is found by the report period: the earlier
report's period must end 1 year before (+- `tol_days`), so a change of fiscal year gives no pair, not a wrong one.
Amendments (10-K/A, 10-Q/A) are kept in the index with `amendment=True` but are never paired: an amendment often
changes only a few items, so its text change is not comparable.
"""
from __future__ import annotations

import pandas as pd

from .edgar import EdgarClient, list_filings

FORMS = ("10-K", "10-Q", "10-K/A", "10-Q/A")
COLUMNS = ["cik", "accession", "form", "base_form", "amendment", "filing_date", "report_date", "accepted_utc",
           "primary_doc"]


def index_for(client: EdgarClient, cik: int, since: str = "2009-01-01") -> pd.DataFrame:
    """All 10-K/10-Q filings (amendments too) of one CIK since `since`."""
    rows = [(f.cik, f.accession, f.form, f.form.removesuffix("/A"), f.form.endswith("/A"), f.filing_date,
             f.report_date, f.accepted, f.primary_doc) for f in list_filings(client, cik, forms=FORMS, since=since)]
    return frame(rows)


def frame(rows) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=COLUMNS)
    df["filing_date"] = pd.to_datetime(df["filing_date"])
    df["report_date"] = pd.to_datetime(df["report_date"], errors="coerce")
    df["accepted_utc"] = pd.to_datetime(df["accepted_utc"], utc=True, errors="coerce")
    return df


def pair_previous(index: pd.DataFrame, tol_days: int = 20) -> pd.DataFrame:
    """Add `prev_accession`: the original (not amended) report of the same CIK and form whose period ended one year
    before this one (+- tol_days), and that was accepted before this one. Empty when there is none."""
    out = index.copy()
    out["prev_accession"] = pd.Series([None] * len(out), dtype="object")
    orig = out[~out["amendment"] & out["report_date"].notna()]
    for (_, _), g in orig.groupby(["cik", "base_form"]):
        g = g.sort_values("report_date")
        for i, r in g.iterrows():
            target = r["report_date"] - pd.DateOffset(years=1)
            c = g[((g["report_date"] - target).abs() <= pd.Timedelta(days=tol_days))
                  & (g["accepted_utc"] < r["accepted_utc"])]
            if len(c):
                out.at[i, "prev_accession"] = c.loc[(c["report_date"] - target).abs().idxmin(), "accession"]
    return out


def no_future_pairs(index: pd.DataFrame) -> bool:
    """Check: each pair uses only an earlier report (by acceptance time). A joint report (parent and subsidiary)
    has one accession number under several CIKs, so reports are keyed by (cik, accession)."""
    acc = index.drop_duplicates(["cik", "accession"]).set_index(["cik", "accession"])["accepted_utc"]
    p = index.dropna(subset=["prev_accession"])
    prev = acc.reindex(pd.MultiIndex.from_arrays([p["cik"], p["prev_accession"]]))
    return bool((prev.to_numpy() < p["accepted_utc"].to_numpy()).all())
