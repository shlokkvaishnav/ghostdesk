"""Own-period XBRL values and the no-restatement rule, on a small made-up instance."""
import pandas as pd

from ghostdesk.filings.xbrl import as_of, first_reported, own_period_values, parse_instance

INSTANCE = b"""<?xml version="1.0"?>
<xbrl xmlns="http://www.xbrl.org/2003/instance" xmlns:us-gaap="http://fasb.org/us-gaap/2023"
      xmlns:xbrldi="http://xbrl.org/2006/xbrldi">
  <context id="FY23"><entity><identifier scheme="x">1</identifier></entity>
    <period><startDate>2022-10-01</startDate><endDate>2023-09-30</endDate></period></context>
  <context id="FY22"><entity><identifier scheme="x">1</identifier></entity>
    <period><startDate>2021-10-01</startDate><endDate>2022-09-30</endDate></period></context>
  <context id="Q4"><entity><identifier scheme="x">1</identifier></entity>
    <period><startDate>2023-07-01</startDate><endDate>2023-09-30</endDate></period></context>
  <context id="I23"><entity><identifier scheme="x">1</identifier></entity>
    <period><instant>2023-09-30</instant></period></context>
  <context id="FY23_seg"><entity><identifier scheme="x">1</identifier>
    <segment><xbrldi:explicitMember dimension="a">b</xbrldi:explicitMember></segment></entity>
    <period><startDate>2022-10-01</startDate><endDate>2023-09-30</endDate></period></context>
  <unit id="usd"><measure>iso4217:USD</measure></unit>
  <us-gaap:Revenues contextRef="FY23" unitRef="usd" decimals="-6">383000000</us-gaap:Revenues>
  <us-gaap:Revenues contextRef="FY22" unitRef="usd" decimals="-6">390000000</us-gaap:Revenues>
  <us-gaap:Revenues contextRef="Q4" unitRef="usd" decimals="-6">90000000</us-gaap:Revenues>
  <us-gaap:Revenues contextRef="FY23_seg" unitRef="usd" decimals="-6">200000000</us-gaap:Revenues>
  <us-gaap:NetIncomeLoss contextRef="FY23" unitRef="usd" decimals="-6">97000000</us-gaap:NetIncomeLoss>
  <us-gaap:Assets contextRef="I23" unitRef="usd" decimals="-6">352000000</us-gaap:Assets>
  <us-gaap:Note contextRef="FY23">text, not a number</us-gaap:Note>
</xbrl>"""


def test_own_period_only():
    facts = parse_instance(INSTANCE)
    assert set(facts["concept"]) == {"Revenues", "NetIncomeLoss", "Assets"}
    v = own_period_values(facts, "2023-09-30", "10-K")
    # the 12-month value, not the quarter, the comparative year (FY22) or the segment
    assert v == {"Revenues": 383e6, "NetIncomeLoss": 97e6, "Assets": 352e6}
    assert own_period_values(facts, "2023-09-30", "10-Q")["Revenues"] == 90e6


def table():
    t = pd.Timestamp
    return pd.DataFrame({  # FY2022 revenue first reported as 390, then restated to 380 in the next 10-K
        "cik": 1, "item": "Revenues",
        "accession": ["k22", "k23", "k23r"],
        "accepted_utc": [t("2022-10-28 20:00", tz="UTC"), t("2023-11-02 20:00", tz="UTC"),
                         t("2023-11-02 20:00", tz="UTC")],
        "period_end": [t("2022-09-30"), t("2023-09-30"), t("2022-09-30")],
        "value": [390.0, 383.0, 380.0]})


def test_restatement_never_replaces_the_first_value():
    f = first_reported(table())
    assert f.loc[f["period_end"] == pd.Timestamp("2022-09-30"), "value"].tolist() == [390.0]


def test_as_of_uses_only_earlier_reports():
    v = table()
    assert as_of(v, "2023-06-01")["value"].tolist() == [390.0]
    assert as_of(v, "2023-11-02 20:00")["value"].tolist() == [390.0]  # accepted at t is not public before t
    assert as_of(v, "2023-11-03")["value"].tolist() == [383.0]
    assert as_of(v, "2022-01-01").empty


def test_find_instance_picks_the_instance_not_rendered_pages():
    import json

    from ghostdesk.filings.edgar_client import Filing
    from ghostdesk.filings.xbrl import find_instance

    class Fake:
        def __init__(self, names):
            self.body = json.dumps({"directory": {"item": [{"name": n} for n in names]}}).encode()

        def get(self, url, store=True):
            return self.body

    old = ["d10k.htm", "aapl-20100925.xml", "aapl-20100925.xsd", "aapl-20100925_cal.xml", "defnref.xml",
           "FilingSummary.xml", "R1.xml", "R2.xml"]
    f = Filing(320193, "0001193125-10-238044", "10-K", "2010-10-27", "2010-09-25", "d10k.htm")
    assert find_instance(Fake(old), f).endswith("/aapl-20100925.xml")
    new = ["aapl-20230930.htm", "aapl-20230930_htm.xml", "aapl-20230930.xsd", "R1.htm"]
    f2 = Filing(320193, "0000320193-23-000106", "10-K", "2023-11-03", "2023-09-30", "aapl-20230930.htm")
    assert find_instance(Fake(new), f2).endswith("/aapl-20230930_htm.xml")
    assert find_instance(Fake(["x.htm", "R1.xml"]), f) is None
