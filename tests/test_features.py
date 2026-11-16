"""Text-change features of a report pair: tables removed, sections found per form, missing sections are NaN."""
import math

from ghostdesk.signal.features import pair_features, parts, prose

RISK = " ".join(f"Risk sentence number {i} about our business and markets." for i in range(60))
MDNA = " ".join(f"Sales grew in region {i} because demand was strong." for i in range(60))


def report(item7_extra="", table="<table><tr><td>Revenue</td><td>1,000</td></tr></table>"):
    return (f"<html><body><p>Item 1A. Risk Factors</p><p>{RISK}</p><p>Item 7. Management's Discussion</p>"
            f"<p>{MDNA} {item7_extra}</p>{table}<p>Item 8. Financial Statements</p><p>See below.</p></body></html>")


def test_tables_are_removed():
    t = prose(report())
    assert "1,000" not in t and "Sales grew" in t


def test_sections_by_form():
    p = parts(report(), "10-K")
    assert set(p) == {"full", "risk", "mdna"} and "region 59" in p["mdna"] and "Risk sentence" not in p["mdna"]
    # in a 10-Q, MD&A is Item 2; this report has no Item 2, so the part is left out
    assert set(parts(report(), "10-Q")) == {"full", "risk"}


def test_pair_features():
    same = pair_features(parts(report(), "10-K"), parts(report(), "10-K"))
    assert all(abs(same[f"sim_{p}_{m}"] - 1) < 1e-12 for p in ("full", "risk", "mdna") for m in ("cosine", "edit"))
    new = report("A new lawsuit could cause large losses for the company in the next year.")
    f = pair_features(parts(new, "10-K"), parts(report(), "10-K"))
    assert f["sim_mdna_edit"] < 1 and abs(f["sim_risk_edit"] - 1) < 1e-12  # only MD&A changed
    assert f["words_mdna"] > f["words_mdna_prev"]
    g = pair_features(parts(report(), "10-K"), parts(report(), "10-Q"))
    assert math.isnan(g["sim_mdna_cosine"]) and not math.isnan(g["sim_full_cosine"])
