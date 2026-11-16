"""The stock universe: S&P 500 members as they were on each date (no survivorship bias), mapped to SEC CIKs.

Sources (public):
- membership intervals per ticker (fja05680/sp500, `sp500_ticker_start_end.csv`, MIT licence);
- Wikipedia "List of S&P 500 companies" (current members with their CIK) and "Historical components of the S&P 500"
  (each change with the name of the removed company);
- SEC `cik-lookup-data.txt` (every EDGAR entity name, former names included, with its CIK).

Tickers are reused (AAL was one company in 1996 and another from 2015), so no single source is trusted. Each
membership interval collects candidate CIKs (`candidates`): the Wikipedia CIK of a current member, every SEC entity
whose name matches the removed company's name, and today's SEC owner of the ticker. `resolve` keeps the candidate
that filed a 10-K or 10-Q during the membership (an identity check), then maps renames (an interval that ends the day
another starts, with no index change that day). Intervals that stay ambiguous or empty are left unmapped and counted
in the coverage report; they are never guessed.
"""
from __future__ import annotations

import re

import pandas as pd

SUFFIXES = {"inc", "incorporated", "corp", "corporation", "co", "company", "ltd", "limited", "plc", "the", "llc",
            "lp", "nv", "sa", "ag", "holdings", "holding", "group", "trust", "de", "new", "cl", "class", "a", "b"}


def load_intervals(csv) -> pd.DataFrame:
    """ticker, start, end (end NaT = still a member)."""
    s = pd.read_csv(csv)
    return pd.DataFrame({"ticker": s["ticker"].astype(str), "start": pd.to_datetime(s["start_date"]),
                         "end": pd.to_datetime(s["end_date"])})


def members_on(intervals: pd.DataFrame, date) -> set[str]:
    """Tickers in the index on `date` (start <= date and (end is empty or date < end))."""
    d = pd.Timestamp(date)
    m = (intervals["start"] <= d) & (intervals["end"].isna() | (d < intervals["end"]))
    return set(intervals.loc[m, "ticker"])


def normalise(name: str) -> str:
    """Lower case, no SEC state tags ('/PA/', '/NEW/'), '&' -> 'and', no punctuation, no legal suffixes:
    'The Black & Decker Corp.' -> 'black and decker', 'AETNA INC /PA/' -> 'aetna'."""
    s = re.sub(r"/[a-z ]{1,4}/?\s*$", " ", str(name).lower().strip()).replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    words = [w for w in s.split() if w not in SUFFIXES]
    return " ".join(words)


def parse_cik_lookup(text: str) -> pd.DataFrame:
    """SEC cik-lookup-data.txt lines 'NAME:CIK:' -> name, cik, key (normalised name)."""
    rows = []
    for line in text.splitlines():
        parts = line.rstrip(":").rsplit(":", 1)
        if len(parts) == 2 and parts[1].isdigit():
            rows.append((parts[0], int(parts[1])))
    df = pd.DataFrame(rows, columns=["name", "cik"])
    df["key"] = df["name"].map(normalise)
    return df


def changes_table(html_tables: list[pd.DataFrame]) -> pd.DataFrame:
    """The Wikipedia changes table -> date, add_ticker, add_name, rem_ticker, rem_name."""
    t = next(x for x in html_tables if x.shape[1] >= 6 and "Removed" in " ".join(map(str, x.columns)))
    t = t.iloc[:, :5].copy()
    t.columns = ["date", "add_ticker", "add_name", "rem_ticker", "rem_name"]
    t["date"] = pd.to_datetime(t["date"], errors="coerce")
    return t.dropna(subset=["date"])


PRIORITY = ("current", "name", "sec_ticker", "prefix", "rename")


def _name_ciks(key: str, by_key: pd.Series, keys: pd.Index, max_prefix: int = 25) -> list[tuple[int, str]]:
    """CIKs whose normalised SEC name equals `key` ("name"), and up to `max_prefix` names that start with it
    ("prefix", lower priority: 'discover financial' -> 'discover financial services')."""
    if not key:
        return []
    exact = [(k, "name") for k in by_key.get(key, [])]
    hits = keys[keys.str.startswith(key + " ")][:max_prefix]
    return exact + [(k, "prefix") for h in hits for k in by_key[h]]


def candidates(intervals: pd.DataFrame, current: pd.DataFrame, changes: pd.DataFrame, lookup: pd.DataFrame,
               sec_tickers: dict[str, int] | None = None) -> pd.DataFrame:
    """Each interval gets a list `cands` of (cik, source): the Wikipedia CIK of a current member ("current"), every SEC
    entity whose name matches the company name recorded when the ticker was removed or added ("name", or "prefix"
    when only a longer SEC name matches), and today's SEC owner of the ticker ("sec_ticker", weak: tickers are
    reused; only for open intervals and recorded removals, because after a ticker change the old ticker can go to
    another company). None of them is trusted until `resolve` checks the filings."""
    out = intervals.copy()
    cur = {str(s): int(c) for s, c in zip(current["Symbol"], current["CIK"], strict=True)}
    by_key = lookup.groupby("key")["cik"].agg(lambda c: sorted(set(c)))
    keys = pd.Index(by_key.index)
    removed = changes.dropna(subset=["rem_ticker", "rem_name"])
    added = changes.dropna(subset=["add_ticker", "add_name"])
    week = pd.Timedelta(days=7)
    sec_tickers = sec_tickers or {}
    rows, all_keys = [], []
    for tk, start, end in zip(out["ticker"], out["start"], out["end"], strict=True):
        c = []
        if pd.isna(end) and tk in cur:
            c.append((cur[tk], "current"))
        names, was_removed = [], False
        if pd.notna(end):
            hit = removed[(removed["rem_ticker"] == tk) & ((removed["date"] - end).abs() <= week)]
            names += list(hit["rem_name"][:1])
            was_removed = not hit.empty
        hit = added[(added["add_ticker"] == tk) & ((added["date"] - start).abs() <= week)]
        names += list(hit["add_name"][:1])
        found = list(dict.fromkeys(normalise(n) for n in names))
        for key in found:
            c += _name_ciks(key, by_key, keys)
        k = sec_tickers.get(tk, sec_tickers.get(tk.replace(".", "-")))
        if k is not None and (pd.isna(end) or was_removed):  # after a ticker change, the old ticker may be reused
            c.append((int(k), "sec_ticker"))
        rows.append(list(dict.fromkeys(c)))
        all_keys.append(found)
    out["cands"], out["keys"] = rows, all_keys
    return out


def names_over_time(submissions: dict) -> list[tuple[str, str, str]]:
    """(name, from, to) for an SEC entity, from its submissions JSON: the `formerNames` with their dates, and the
    current name from the end of the last former name until today ("9999-12-31")."""
    former = [(f["name"], str(f.get("from", ""))[:10], str(f.get("to", ""))[:10])
              for f in submissions.get("formerNames", [])]
    last = max((t for _, _, t in former), default="0000-01-01")
    return former + [(submissions.get("name", ""), last, "9999-12-31")]


def _pick(ok: list[tuple[int, str]]) -> tuple[int, str] | None:
    """One CIK from checked candidates: the only one; else the one named by the most sources; else the only one in the
    best source. None when still ambiguous."""
    distinct = {k for k, _ in ok}
    if not distinct:
        return None
    best = lambda k: min((s for kk, s in ok if kk == k), key=PRIORITY.index)
    if len(distinct) == 1:
        k = next(iter(distinct))
        return k, best(k)
    votes = {k: len({s for kk, s in ok if kk == k}) for k in distinct}
    top = [k for k, v in votes.items() if v == max(votes.values())]
    if len(top) == 1 and max(votes.values()) > 1:
        return top[0], best(top[0])
    for src in PRIORITY:
        ks = {k for k, s in ok if s == src}
        if ks:
            return (next(iter(ks)), src) if len(ks) == 1 else None
    return None


def _matches(name: str, keys: set[str]) -> bool:
    return any(name == k or name.startswith(k + " ") for k in keys)


def _narrow(ok, start, end, keys, has_filings, names_at, pad, now, study_start):
    """The tie-break steps of `resolve`, in order; a step that would leave no candidate is skipped."""
    def steps():
        yield lambda k: has_filings(k, max(start, study_start), end if pd.notna(end) else now)
        if pd.notna(end):
            yield lambda k: has_filings(k, end - pad, end)
        if names_at is not None and keys:
            ref = end - pd.Timedelta(days=1) if pd.notna(end) else start + pd.Timedelta(days=365)
            days = [ref - pd.Timedelta(days=d) for d in (0, 90, 180, 270, 365)]
            names = lambda k: {normalise(n) for d in days for n in names_at(k, d)}
            yield lambda k: bool(names(k) & keys)  # the exact name first
            yield lambda k: any(_matches(n, keys) for n in names(k))

    for step in steps():
        if len({k for k, _ in ok}) <= 1:
            break
        ok = [(k, s) for k, s in ok if step(k)] or ok
    return ok


def resolve(cands: pd.DataFrame, has_filings, changes: pd.DataFrame, margin_days: int = 400,
            today: str = "2026-11-15", study_start: str = "2010-01-01", names_at=None, added=None) -> pd.DataFrame:
    """Keep the candidate CIKs that filed a 10-K or 10-Q in the interval (+- `margin_days`: an identity check, not a
    timing check). If several pass, narrow them step by step (a step that would leave none is skipped): filed inside
    the part of the interval in the study; filed in the last `margin_days` before the end (the removed company still
    reported); had the exact matched name, then a longer one that starts with it, in the last year of the interval
    (names_at(cik, day) -> list of names). Then `_pick`. A current-members CIK that passes the filing check is taken
    at once.
    Renames: an unmapped interval that ends when exactly one other interval starts (+- 3 days), where neither
    ticker is in the recorded index changes, takes that interval's CIK only if there is evidence that it is the same
    company: the other interval is a current member that was added (`added`: ticker -> "Date added") at least 30
    days before its start (a new member is added on its start day); or its CIK changed its SEC name between 45 days
    before and 180 days after the switch (CenturyLink -> Lumen); or it is itself a rename (a chain). If several
    intervals start within 3 days, the only one that starts on the same day is used. The CIK must also have filed
    inside the old interval itself, at least 1 year before the switch (a merger that forms a new company has a new
    CIK, with at most a few months of reports before the merger closes: MYL -> Viatris, WRK -> Smurfit Westrock).
    has_filings(cik, lo, hi) -> bool."""
    out = cands.copy()
    out["cik"], out["source"] = pd.array([pd.NA] * len(out), dtype="Int64"), ""
    pad, now = pd.Timedelta(days=margin_days), pd.Timestamp(today)

    def window(i):
        return out.at[i, "start"] - pad, (out.at[i, "end"] if pd.notna(out.at[i, "end"]) else now) + pad

    for i in out.index:
        ok = [(int(k), s) for k, s in out.at[i, "cands"] if has_filings(int(k), *window(i))]
        cur = {k for k, s in ok if s == "current"}
        if len(cur) == 1:  # the current-members CIK, confirmed by its filings, is trusted
            out.at[i, "cik"], out.at[i, "source"] = next(iter(cur)), "current"
            continue
        ok = _narrow(ok, out.at[i, "start"], out.at[i, "end"], set(out.at[i, "keys"]) if "keys" in out else set(),
                     has_filings, names_at, pad, now, pd.Timestamp(study_start))
        got = _pick(ok)
        if got:
            out.at[i, "cik"], out.at[i, "source"] = got

    tol, month = pd.Timedelta(days=3), pd.Timedelta(days=30)
    added = {} if added is None else {str(t): pd.Timestamp(d) for t, d in added.items()}

    def in_changes(tk, day, col):
        return bool(((changes[col] == tk) & ((changes["date"] - day).abs() <= pd.Timedelta(days=7))).any())

    def continues(j):  # interval j is the same company as before its start
        tk, day = out.at[j, "ticker"], out.at[j, "start"]
        if out.at[j, "source"] == "rename" or (pd.isna(out.at[j, "end"]) and tk in added and added[tk] <= day - month):
            return True
        if names_at is None:
            return False
        k = int(out.at[j, "cik"])  # the SEC dates a name change by the next filing: allow up to 180 days after
        before, after = set(names_at(k, day - pd.Timedelta(days=45))), set(names_at(k, day + pd.Timedelta(days=180)))
        return bool(before) and bool(after) and before != after  # the SEC records a name change at the switch

    for _ in range(5):  # renames can chain (A -> B -> C)
        changed = False
        for i in out.index[out["cik"].isna() & out["end"].notna()]:
            end, tk = out.at[i, "end"], out.at[i, "ticker"]
            if in_changes(tk, end, "rem_ticker"):
                continue
            nxt = out[((out["start"] - end).abs() <= tol) & (out.index != i)]
            nxt = nxt[[not in_changes(t, d, "add_ticker") for t, d in zip(nxt["ticker"], nxt["start"], strict=True)]]
            if len(nxt) > 1 and (nxt["start"] == end).sum() == 1:  # prefer the one that starts on the same day
                nxt = nxt[nxt["start"] == end]
            if len(nxt) == 1 and pd.notna(nxt["cik"].iloc[0]) and continues(nxt.index[0]) \
                    and has_filings(int(nxt["cik"].iloc[0]), max(out.at[i, "start"], pd.Timestamp(study_start)),
                                    max(end - pd.Timedelta(days=365), out.at[i, "start"])):
                out.at[i, "cik"], out.at[i, "source"] = int(nxt["cik"].iloc[0]), "rename"
                changed = True
        if not changed:
            break
    return out.drop(columns="cands")


def add_predecessors(mapped: pd.DataFrame, first_filing, has_filings, names_at, lookup: pd.DataFrame,
                     study_start: str = "2010-01-01", lead_days: int = 120, rounds: int = 3) -> pd.DataFrame:
    """Holding-company changes: a company forms a new parent with a new CIK and keeps its name and ticker (Disney
    2019, Alphabet 2015, Cigna 2018). The reports before the change are under the old CIK. For an interval whose CIK
    first filed after the interval (in the study) started, look for the old CIK: an SEC entity that had, 30 to 365
    days before the new CIK's first report, the name that the new CIK has 180 days after it (and, when the index
    recorded names for the ticker, one of those names); that filed a 10-K or 10-Q in the interval before that day;
    and that no other ticker uses at the same time. If exactly one is found, the
    interval is split at the new CIK's first report (source "predecessor"). first_filing(cik) -> Timestamp or None."""
    def compact(n):  # names are compared without spaces: "ExxonMobil Holdings" = "Exxon Mobil Corp"
        return normalise(n).replace(" ", "")

    by_key = lookup.assign(c=lookup["key"].str.replace(" ", "")).groupby("c")["cik"].agg(lambda c: sorted(set(c)))
    s0, lead = pd.Timestamp(study_start), pd.Timedelta(days=lead_days)
    rows = mapped.to_dict("records")
    for _ in range(rounds):
        changed = False
        for r in list(rows):
            if pd.isna(r["cik"]) or r["source"] == "predecessor_done":
                continue
            k, lo = int(r["cik"]), max(r["start"], s0)
            split = first_filing(k)
            if split is None or split - lead <= lo:
                continue
            names = {compact(n) for n in names_at(k, split + pd.Timedelta(days=180))}
            cands = {int(c) for n in names for c in by_key.get(n, []) if int(c) != k}

            # share classes (GOOG, GOOGL) have the same new CIK, so they may also share the old one
            classes = {o["ticker"] for o in rows if pd.notna(o["cik"]) and int(o["cik"]) == k}

            def used_elsewhere(c, r=r, lo=lo, split=split, classes=classes):
                return any(o is not r and pd.notna(o["cik"]) and int(o["cik"]) == c and o["ticker"] not in classes
                           and o["start"] < split and (pd.isna(o["end"]) or o["end"] > lo) for o in rows)

            keys = {k.replace(" ", "") for k in (r.get("keys") or [])}  # the index's own names for this ticker, when recorded

            def old_names(c, split=split):  # the old CIK often takes a new name at the change itself
                return {compact(n) for d in (30, 90, 180, 365) for n in names_at(c, split - pd.Timedelta(days=d))}

            ok = [c for c in cands if has_filings(c, lo, split - pd.Timedelta(days=1))
                  and old_names(c) & names and (not keys or any(n.startswith(k) for n in old_names(c) for k in keys))
                  and not used_elsewhere(c)]
            if len(ok) != 1:
                continue
            old = dict(r, end=split, cik=ok[0], source="predecessor")
            r["start"] = split
            rows.insert(rows.index(r), old)
            changed = True
        if not changed:
            break
    out = pd.DataFrame(rows, columns=mapped.columns)
    out["cik"] = out["cik"].astype("Int64")
    return out.sort_values(["ticker", "start"]).reset_index(drop=True)


def add_valid_from(mapped: pd.DataFrame, first_filing: dict[int, pd.Timestamp], lead_days: int = 120) -> pd.DataFrame:
    """`valid_from`: the date from which the CIK can be the company of the interval: the interval start, or
    `lead_days` before the CIK's first 10-K/10-Q if that is later (AGN 1996-2020 is mapped to Allergan plc, whose
    reports start in 2013; Allergan Inc used the ticker before). The part before `valid_from` counts as unmapped."""
    out = mapped.copy()
    first = out["cik"].map(lambda k: first_filing.get(int(k)) if pd.notna(k) else None)
    lead = pd.to_datetime(first) - pd.Timedelta(days=lead_days)
    out["valid_from"] = pd.concat([out["start"], lead], axis=1).max(axis=1).where(out["cik"].notna())
    return out


def coverage(mapped: pd.DataFrame, start: str, end: str) -> dict:
    """Share of member-days in [start, end] that have a CIK (from `valid_from` when present), and counts by source."""
    s, e = pd.Timestamp(start), pd.Timestamp(end)
    a = mapped["start"].clip(lower=s)
    b = mapped["end"].fillna(e).clip(upper=e)
    days = (b - a).dt.days.clip(lower=0)
    inside = days > 0
    va = mapped["valid_from"].fillna(mapped["start"]).clip(lower=s) if "valid_from" in mapped else a
    ok = (b - va).dt.days.clip(lower=0).where(mapped["cik"].notna(), 0)
    m = mapped[inside]
    return {"intervals": int(inside.sum()), "mapped_intervals": int(m["cik"].notna().sum()),
            "member_day_share_mapped": float(ok[inside].sum() / days[inside].sum()),
            "by_source": m["source"].replace("", "unmapped").value_counts().to_dict()}
