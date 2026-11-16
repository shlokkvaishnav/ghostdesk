"""Numbers from each report's own XBRL instance, never from the SEC companyfacts or frames APIs.

Those APIs keep the newest value of each fact, so a figure that was restated later shows the restated value: a
backtest that uses it knows the future. Here each report gives only the values for its own period (a duration that
ends on the report date, or an instant on it), with no dimensions (no segment or other breakdowns). For each company,
item and period, the value of the **first** report that gave it is kept (`first_reported`), and a decision at time t
can use only reports accepted before t (`as_of`).

The instance file: an inline-XBRL report (most reports since 2019) has an extracted instance `<doc>_htm.xml` in the
filing folder; older reports have a separate `.xml` instance with the name of the schema file (`aapl-20100925.xsd`
-> `aapl-20100925.xml`). `find_instance` picks it from the folder index.
"""
from __future__ import annotations

import json
import re

import pandas as pd
import requests
from lxml import etree

from .edgar import EdgarClient, Filing

FOLDER = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/index.json"
XBRLI = "http://www.xbrl.org/2003/instance"
SUPPORT = ("_cal.xml", "_def.xml", "_lab.xml", "_pre.xml", "FilingSummary.xml", "defnref.xml")
RENDERED = re.compile(r"^R\d+\.xml$")  # the SEC's rendered pages, not the instance

# A small, fixed set of items for the controls (size, profitability); more can be added.
ITEMS = {
    "Revenues": ("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet"),
    "NetIncomeLoss": ("NetIncomeLoss",),
    "Assets": ("Assets",),
    "StockholdersEquity": ("StockholdersEquity",),
}


def get_instance(client: EdgarClient, filing: Filing) -> bytes | None:
    """The XBRL instance of the report (not added to the disk cache), or None. For an inline-XBRL report (filed
    from mid-2019) the instance name is known, so it is requested directly; the folder index is read only if that
    fails."""
    stem = filing.primary_doc.rsplit(".", 1)[0]
    if filing.filing_date >= "2019-06-15" and filing.primary_doc.endswith(".htm"):
        try:
            return client.get(_base(filing) + f"{stem}_htm.xml", store=False)
        except requests.HTTPError:
            pass
    url = find_instance(client, filing)
    return client.get(url, store=False) if url else None


def _base(filing: Filing) -> str:
    return f"https://www.sec.gov/Archives/edgar/data/{filing.cik}/{filing.accession.replace('-', '')}/"


def find_instance(client: EdgarClient, filing: Filing) -> str | None:
    """The URL of the report's XBRL instance from the folder index, or None (reports before about 2010 often have
    none)."""
    acc = filing.accession.replace("-", "")
    base = _base(filing)
    stem = filing.primary_doc.rsplit(".", 1)[0]
    items = json.loads(client.get(FOLDER.format(cik=filing.cik, acc=acc)))["directory"]["item"]
    names = [i["name"] for i in items]
    pick = next((n for n in names if n == f"{stem}_htm.xml"), None)  # inline XBRL: the extracted instance
    if pick is None:  # a separate instance has the name of the schema file: aapl-20100925.xsd -> .xml
        xsd = [n.removesuffix(".xsd") for n in names if n.endswith(".xsd")]
        pick = next((f"{x}.xml" for x in xsd if f"{x}.xml" in names), None)
    if pick is None:
        xml = [n for n in names if n.endswith(".xml") and not n.endswith(SUPPORT) and not RENDERED.match(n)]
        pick = xml[0] if len(xml) == 1 else None
    return base + pick if pick else None


def parse_instance(xml: bytes) -> pd.DataFrame:
    """All numeric facts: concept (local name), value, unit, start, end (the instant for an instant fact), dims."""
    root = etree.fromstring(xml, parser=etree.XMLParser(huge_tree=True, recover=True))
    ctx = {}
    for c in root.iter(f"{{{XBRLI}}}context"):
        p = c.find(f"{{{XBRLI}}}period")
        inst, st, en = (p.findtext(f"{{{XBRLI}}}{t}") for t in ("instant", "startDate", "endDate"))
        dims = c.find(f".//{{{XBRLI}}}segment") is not None or c.find(f".//{{{XBRLI}}}scenario") is not None
        ctx[c.get("id")] = (None if inst else st, inst or en, dims)
    rows = []
    for el in root.iter():
        ref = el.get("contextRef") if isinstance(el.tag, str) else None
        if ref is None or ref not in ctx or el.get("unitRef") is None or el.text is None:
            continue
        try:
            v = float(el.text.strip())
        except ValueError:
            continue
        st, en, dims = ctx[ref]
        rows.append((etree.QName(el).localname, v, el.get("unitRef"), st, en, dims))
    df = pd.DataFrame(rows, columns=["concept", "value", "unit", "start", "end", "dims"])
    df["start"], df["end"] = pd.to_datetime(df["start"]), pd.to_datetime(df["end"])
    return df


def own_period_values(facts: pd.DataFrame, report_date, form: str) -> dict[str, float]:
    """The report's own-period values of ITEMS: no dimensions, ending on the report date (+- 3 days); a flow item
    must cover the report's period (about 3 months for a 10-Q, 12 for a 10-K). The first matching concept name of each
    item is used. Comparative columns (earlier periods) are ignored, so a restatement in a later report never
    replaces a value here."""
    end = pd.Timestamp(report_date)
    f = facts[~facts["dims"] & ((facts["end"] - end).abs() <= pd.Timedelta(days=3))]
    months = 12 if form.startswith("10-K") else 3
    length = (f["end"] - f["start"]).dt.days
    flow_ok = f["start"].isna() | ((length - months * 30.4).abs() <= 20)
    f = f[flow_ok]
    out = {}
    for item, names in ITEMS.items():
        for n in names:
            v = f.loc[f["concept"] == n, "value"]
            if len(v) and v.nunique() == 1:
                out[item] = float(v.iloc[0])
                break
    return out


def first_reported(values: pd.DataFrame) -> pd.DataFrame:
    """values: cik, accession, accepted_utc, period_end, item, value (one row per report and item). Keep, for each
    cik, item and period, the row of the report accepted first: the value as it was first known."""
    v = values.sort_values("accepted_utc")
    return v.drop_duplicates(["cik", "item", "period_end"], keep="first").reset_index(drop=True)


def as_of(values: pd.DataFrame, t) -> pd.DataFrame:
    """The latest first-reported value of each cik and item that was public strictly before time t (UTC)."""
    t = pd.Timestamp(t)
    t = t.tz_localize("UTC") if t.tzinfo is None else t
    v = first_reported(values)
    v = v[v["accepted_utc"] < t].sort_values(["period_end", "accepted_utc"])
    return v.drop_duplicates(["cik", "item"], keep="last").reset_index(drop=True)
