"""Universe membership and CIK mapping on small made-up tables."""
import io

import pandas as pd

from ghostdesk.data.universe import (
    add_predecessors,
    add_valid_from,
    candidates,
    coverage,
    load_intervals,
    members_on,
    normalise,
    parse_cik_lookup,
    price_symbols,
    resolve,
)

CSV = """ticker,start_date,end_date
AAL,1996-01-02,1997-01-15
AAL,2015-03-23,
OLD,2005-01-01,2018-06-01
NEW,2018-06-01,
GONE,2008-01-01,2012-03-01
TWIN,2009-01-01,2014-01-01
KEEP,2001-01-01,
"""
CURRENT = pd.DataFrame({"Symbol": ["AAL", "NEW", "KEEP"], "CIK": [6201, 111, 222]})
CHANGES = pd.DataFrame({"date": pd.to_datetime(["2012-03-01", "2014-01-01", "2015-03-23"]),
                        "add_ticker": ["X", "Y", "AAL"], "add_name": ["", "", "American Airlines"],
                        "rem_ticker": ["GONE", "TWIN", "Z"], "rem_name": ["Gone Industries, Inc.", "Twin Co", "Zed"]})
LOOKUP = parse_cik_lookup("GONE INDUSTRIES INC:333:\nTWIN CORP:444:\nTWIN COMPANY:445:\nAMERICAN AIRLINES INC:6201:\n")


def intervals():
    return load_intervals(io.StringIO(CSV))


def test_members_on_respects_dates_and_reuse():
    iv = intervals()
    assert "AAL" not in members_on(iv, "2010-01-01") and "AAL" in members_on(iv, "1996-06-01")
    assert members_on(iv, "2018-06-01") >= {"NEW"} and "OLD" not in members_on(iv, "2018-06-01")


def test_normalise():
    assert normalise("The Black & Decker Corp.") == "black and decker"
    assert normalise("GONE INDUSTRIES INC") == normalise("Gone Industries, Inc.")


FILERS = {6201: ("2013", "2026"), 111: ("2004", "2026"), 222: ("2000", "2026"), 333: ("2007", "2012"),
           444: ("2009", "2014"), 445: ("2009", "2014"), 999: ("2020", "2026")}


def has_filings(cik, lo, hi):
    a, b = FILERS.get(cik, ("9999", "0000"))
    return pd.Timestamp(a) <= hi and lo <= pd.Timestamp(b)


def mapped():
    sec = {"AAL": 6201, "KEEP": 222, "GONE": 999}  # GONE is today another company's ticker
    return resolve(candidates(intervals(), CURRENT, CHANGES, LOOKUP, sec), has_filings, CHANGES,
                   added={"AAL": "2015-03-23", "NEW": "1990-01-01", "KEEP": "2001-01-01"})


def test_mapping_rules_and_no_guessing():
    m = mapped().set_index(["ticker", "start"])
    assert m.loc[("AAL", pd.Timestamp("2015-03-23")), "cik"] == 6201
    assert pd.isna(m.loc[("AAL", pd.Timestamp("1996-01-02")), "cik"])  # 6201 did not file in 1995-1998 here
    assert m.loc[("OLD", pd.Timestamp("2005-01-01")), ["cik", "source"]].tolist() == [111, "rename"]
    # the name match wins over today's (reused) ticker owner, which did not file in 2008-2012
    assert m.loc[("GONE", pd.Timestamp("2008-01-01")), ["cik", "source"]].tolist() == [333, "name"]
    assert pd.isna(m.loc[("TWIN", pd.Timestamp("2009-01-01")), "cik"])  # two filers share the name: ambiguous


def test_coverage_counts_member_days():
    c = coverage(mapped(), "2010-01-01", "2020-01-01")
    assert c["intervals"] == 6 and 0 < c["member_day_share_mapped"] < 1
    assert c["by_source"]["unmapped"] == 1


def test_state_tags_are_removed():
    assert normalise("AETNA INC /PA/") == normalise("Aetna") == "aetna"


def test_tie_breaks_last_filer_and_name_at_the_time():
    csv = "ticker,start_date,end_date\nVIA,2006-01-03,2019-12-05\nKFG,2012-10-02,2015-07-06\nDSC,2007-07-02,2025-05-19\n"
    changes = pd.DataFrame({"date": pd.to_datetime(["2019-12-05", "2015-07-06", "2025-05-19"]),
                            "add_ticker": ["A1", "A2", "A3"], "add_name": ["", "", ""],
                            "rem_ticker": ["VIA", "KFG", "DSC"],
                            "rem_name": ["Viacom", "Kraft Foods Group", "Discover Financial"]})
    lookup = parse_cik_lookup("VIACOM INC:1:\nVIACOM INC.:2:\nKRAFT FOODS INC:3:\nKRAFT FOODS GROUP, INC.:4:\n"
                              "DISCOVER FINANCIAL SERVICES:5:\n")
    filers = {1: ("2006", "2026"), 2: ("2006", "2019-11-30"), 3: ("2001", "2026"), 4: ("2012", "2015-08"),
              5: ("2007", "2025-04")}
    names = {1: [("VIACOM INC", "1990-01-01", "2005-12-31"), ("CBS CORP", "2005-12-31", "2019-12-04"),
                 ("VIACOMCBS INC", "2019-12-04", "9999-12-31")],
             2: [("VIACOM INC.", "2005-12-31", "9999-12-31")],
             3: [("KRAFT FOODS INC", "2001-01-01", "2012-10-01"), ("MONDELEZ", "2012-10-01", "9999-12-31")],
             4: [("KRAFT FOODS GROUP, INC.", "2012-01-01", "9999-12-31")]}

    def hf(cik, lo, hi):
        a, b = filers[cik]
        return pd.Timestamp(a) <= hi and lo <= pd.Timestamp(b)

    def names_at(cik, day):
        d = f"{day:%Y-%m-%d}"
        return [n for n, a, b in names.get(cik, []) if a <= d <= b]

    iv = load_intervals(io.StringIO(csv))
    m = resolve(candidates(iv, CURRENT.iloc[:0], changes, lookup), hf, changes, names_at=names_at)
    got = dict(zip(m["ticker"], m["cik"], strict=True))
    assert got["VIA"] == 2  # both filed until the end; only cik 2 had the name "Viacom" then (cik 1 was CBS)
    assert got["KFG"] == 4  # cik 3 still files, but it was "Kraft Foods Inc" only before the interval
    assert got["DSC"] == 5  # matched by a longer SEC name ("prefix")


def test_rename_on_a_day_with_other_changes():
    csv = "ticker,start_date,end_date\nUTX,1996-01-02,2020-04-03\nRTX,2020-04-03,\nOTIS,2020-04-03,\n"
    changes = pd.DataFrame({"date": pd.to_datetime(["2020-04-03"]), "add_ticker": ["OTIS"],
                            "add_name": ["Otis Worldwide"], "rem_ticker": [None], "rem_name": [None]})
    current = pd.DataFrame({"Symbol": ["RTX", "OTIS"], "CIK": [101829, 1781686]})
    m = resolve(candidates(load_intervals(io.StringIO(csv)), current, changes, LOOKUP.iloc[:0]),
                lambda k, lo, hi: True, changes, added={"RTX": "1957-03-04", "OTIS": "2020-04-03"})
    assert m.set_index("ticker").loc["UTX", ["cik", "source"]].tolist() == [101829, "rename"]


def test_unrecorded_swap_is_not_a_rename():
    """BDK left and OKE joined on the same day, and the changes table has neither: OKE's "Date added" is its start
    day, so it is a new member, not BDK under a new ticker."""
    csv = "ticker,start_date,end_date\nBDK,1996-01-02,2010-03-12\nOKE,2010-03-12,\n"
    current = pd.DataFrame({"Symbol": ["OKE"], "CIK": [1039684]})
    m = resolve(candidates(load_intervals(io.StringIO(csv)), current, CHANGES.iloc[:0], LOOKUP.iloc[:0]),
                lambda k, lo, hi: True, CHANGES.iloc[:0], added={"OKE": "2010-03-15"})
    assert pd.isna(m.set_index("ticker").loc["BDK", "cik"])


def test_old_ticker_owner_is_not_used_after_a_ticker_change():
    csv = "ticker,start_date,end_date\nPARA,2022-02-17,2025-08-08\n"
    m = resolve(candidates(load_intervals(io.StringIO(csv)), CURRENT.iloc[:0], CHANGES.iloc[:0], LOOKUP.iloc[:0],
                           {"PARA": 1826011}), lambda k, lo, hi: True, CHANGES.iloc[:0])
    assert pd.isna(m["cik"].iloc[0])


def test_rename_found_by_an_sec_name_change():
    csv = "ticker,start_date,end_date\nCTL,1999-03-01,2020-09-21\nLUMN,2020-09-21,2023-03-20\n"
    changes = pd.DataFrame({"date": pd.to_datetime(["2023-03-20"]), "add_ticker": ["X"], "add_name": ["X"],
                            "rem_ticker": ["LUMN"], "rem_name": ["Lumen Technologies"]})
    lookup = parse_cik_lookup("LUMEN TECHNOLOGIES, INC.:18926:\n")

    def names_at(cik, day):
        return ["CENTURYLINK, INC"] if day < pd.Timestamp("2020-09-18") else ["Lumen Technologies, Inc."]

    m = resolve(candidates(load_intervals(io.StringIO(csv)), CURRENT.iloc[:0], changes, lookup),
                lambda k, lo, hi: True, changes, names_at=names_at, added={})
    assert m.set_index("ticker").loc["CTL", ["cik", "source"]].tolist() == [18926, "rename"]


def test_merger_into_a_new_company_is_not_a_rename():
    csv = "ticker,start_date,end_date\nWRK,2015-07-02,2024-07-08\nSW,2024-07-08,\n"
    current = pd.DataFrame({"Symbol": ["SW"], "CIK": [2005951]})
    filers = {2005951: ("2024-06-07", "2026")}  # the new company filed its first 10-Q a month before the merger

    def hf(cik, lo, hi):
        a, b = filers[cik]
        return pd.Timestamp(a) <= hi and lo <= pd.Timestamp(b)

    m = resolve(candidates(load_intervals(io.StringIO(csv)), current, CHANGES.iloc[:0], LOOKUP.iloc[:0]), hf,
                CHANGES.iloc[:0], added={"SW": "2014-01-01"})
    assert pd.isna(m.set_index("ticker").loc["WRK", "cik"])


def test_valid_from_cuts_the_part_before_the_cik_existed():
    m = pd.DataFrame({"ticker": ["AGN"], "start": pd.to_datetime(["1996-01-02"]), "end": pd.to_datetime(["2020-05-12"]),
                      "cik": pd.array([1578845], dtype="Int64"), "source": ["name"]})
    v = add_valid_from(m, {1578845: pd.Timestamp("2013-10-01")})
    assert v["valid_from"].iloc[0] == pd.Timestamp("2013-06-03")
    c = coverage(v, "2010-01-01", "2020-01-01")
    assert abs(c["member_day_share_mapped"] - (pd.Timestamp("2020-01-01") - pd.Timestamp("2013-06-03")).days / 3652) < 1e-3


def test_predecessor_cik_for_a_holding_company_change():
    """Disney formed a new parent in 2019: old reports are under the old CIK (renamed TWDC Enterprises 18)."""
    m = pd.DataFrame({"ticker": ["DIS", "GOOG", "GOOGL"], "start": pd.to_datetime(["1996-01-02", "2014-04-03",
                      "2006-04-03"]), "end": pd.NaT, "cik": pd.array([1744489, 1652044, 1652044], dtype="Int64"),
                      "source": "current", "keys": [[], [], []]})
    first = {1744489: pd.Timestamp("2019-05-08"), 1652044: pd.Timestamp("2015-10-29"), 1001039: pd.Timestamp("2008"),
             1288776: pd.Timestamp("2008")}
    names = {1744489: [("TWDC HOLDCO 613 CORP", "2018", "2019-03-20"), ("Walt Disney Co", "2019-03-20", "9999")],
             1001039: [("WALT DISNEY CO/", "1996", "2019-03-20"), ("TWDC Enterprises 18 Corp.", "2019-03-20", "9999")],
             1652044: [("Alphabet Inc.", "2015-08-01", "9999")], 1288776: [("Alphabet Inc.", "2015-01-01", "9999")]}

    def names_at(cik, day):
        d = f"{day:%Y-%m-%d}"
        return [n for n, a, b in names.get(cik, []) if a <= d <= b]

    lookup = parse_cik_lookup("WALT DISNEY CO/:1001039:\nWALT DISNEY CO:1744489:\nALPHABET INC.:1288776:\n")
    out = add_predecessors(m, first.get, lambda k, lo, hi: k in (1001039, 1288776), names_at, lookup)
    dis = out[out["ticker"] == "DIS"].sort_values("start")
    assert dis["cik"].tolist() == [1001039, 1744489] and dis["source"].tolist() == ["predecessor", "current"]
    assert dis["end"].iloc[0] == dis["start"].iloc[1] == pd.Timestamp("2019-05-08")
    for t in ("GOOG", "GOOGL"):  # share classes share the old CIK
        assert out[out["ticker"] == t].sort_values("start")["cik"].tolist() == [1288776, 1652044]


def test_price_symbols_follow_the_company_not_the_ticker():
    m = pd.DataFrame({"ticker": ["FB", "META", "GOOG", "GOOGL", "BBBY", "OLD", "NOCIK", "PCG"],
                      "start": pd.to_datetime(["2013-12-23", "2022-06-09", "2014-04-03", "2006-04-03", "1999-10-01",
                                               "2001-01-01", "2001-01-01", "1996-01-02"]),
                      "cik": pd.array([1326801, 1326801, 1652044, 1652044, 886158, 5, None, 75488], dtype="Int64")})
    cur = {1326801: ["META"], 1652044: ["GOOGL", "GOOG"], 75488: ["PCG-PE", "PCG-PD"]}  # BBBY, OLD: no ticker
    got = price_symbols(m, cur)
    assert got.drop(6).tolist() == ["META", "META", "GOOG", "GOOGL", "BBBY", "OLD", "PCG"] and pd.isna(got[6])
