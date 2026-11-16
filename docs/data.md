# Data

All data comes from public sources. Raw data is not kept in git; `scripts/` downloads it again and keeps a local
copy in `data/` (not in git).

## The stock list (universe)
**Rule:** on each date, the stock list contains only the companies that were in the S&P 500 on that date. Companies
that left the index later (for example after a merger or a bankruptcy) are in the list for the dates when they were
members. This prevents survivorship bias.

**Sources:**

| Source | What it gives |
|---|---|
| [fja05680/sp500](https://github.com/fja05680/sp500) `sp500_ticker_start_end.csv` (MIT licence) | each ticker's membership intervals since 1996 |
| Wikipedia "List of S&P 500 companies" | the current members, with their SEC CIK |
| Wikipedia "Historical components of the S&P 500" | each index change, with the names of the companies added and removed |
| SEC `cik-lookup-data.txt` | all EDGAR entity names (former names too), with their CIK |
| SEC `company_tickers.json` | today's owner of each ticker |
| SEC submissions JSON | the filing dates of each CIK, and its former names with their dates |

**The problem: tickers are used again.** AAL was one company in 1996 and a different company from 2015. Thus a
ticker is not an identity. Each report from the SEC is filed under a CIK (a fixed company number), so each
membership interval must get the correct CIK.

**The method** (`ghostdesk.data.universe`, run by `scripts/build_universe.py`):
1. Collect candidate CIKs for each interval:
   - the CIK in the current-members table (only for an interval that has not ended);
   - each SEC entity whose name is the same as the name recorded when the ticker was added or removed
     (and, at a lower priority, a longer SEC name that starts with it: "Discover Financial" → "Discover Financial
     Services");
   - today's SEC owner of the ticker (weak, because tickers are used again).
2. Keep only the candidates that filed a 10-K or 10-Q during the interval (± 400 days). This is an identity check.
3. If more than one candidate stays, use these tie-breaks, in this order:
   - it filed in the part of the interval that is in the study (2010 or later);
   - it still filed in the 400 days before the removal;
   - it had the matched name on the removal date (from the SEC former-names dates). Example: Mondelez had the name
     "Kraft Foods Inc" before October 2012, but not when Kraft Foods Group (KRFT) was in the index;
   - it was found by more sources than the other candidates.
4. **Renames** (UTX → RTX, BK → BNY, CTL → LUMN). An interval that ends on the day another interval starts, when
   the index-changes table does not record either ticker on that day, gets the CIK of the other interval. But only
   if there is evidence that it is the same company:
   - the other company is a current member with a "Date added" at least 30 days before its new ticker started
     (a new member is added on its start day), **or**
   - the SEC records a name change of that CIK near the switch (CenturyLink → Lumen), **or**
   - the other interval is itself a rename (a chain).

   The CIK must also have filed a report at least 1 year before the switch. This rejects mergers that form a new
   company with a new CIK (Mylan → Viatris, WestRock → Smurfit Westrock).
5. **Holding-company changes** (Disney 2019, Alphabet 2015, Cigna 2018, BlackRock 2024, Exxon Mobil 2026). The
   company forms a new parent with a new CIK and keeps its name and ticker, so its earlier reports are under the old
   CIK. The old CIK is found by its name (it had the new CIK's name before the change), by its reports in the
   interval, and because no other ticker used it at that time. The interval is split at the new CIK's first report
   (source "predecessor").
6. A CIK cannot be the company of an interval before it existed: each interval counts as mapped only from 120 days
   before its CIK's first 10-K or 10-Q (`valid_from`).
7. An interval that stays empty or ambiguous is **not guessed**. It stays unmapped, and it is counted below.

Each rule has a unit test on a small table (`tests/test_universe.py`). Samples of the result were checked by hand
against the SEC entity names; these checks found the errors that rules 4-6 now prevent.

## Coverage, 2010-2025
| | |
|---|---|
| Membership intervals in 2010-2025 | 863 (after splits at holding-company changes) |
| Intervals with a CIK | 814 |
| **Member-days with a CIK** | **96.8%** |
| Members with a CIK on 30 June 2010 / 2015 / 2020 / 2025 | 461 of 499 / 479 of 499 / 500 of 505 / 502 of 503 |

| How the CIK was found | Intervals |
|---|---|
| Current-members table, checked against the filings | 479 |
| Name of the removed or added company | 285 |
| Rename | 17 |
| Holding-company predecessor | 15 |
| Longer SEC name ("prefix") | 12 |
| Today's owner of the ticker | 6 |
| Not found | 49 |

Coverage is lowest in the early years: more of those companies were later bought or went bankrupt, and the sources
have fewer names for them.

**Unmapped intervals (years in the study):** AABA 2010-2017, ACS 2010, ANRZQ 2011-2012, ATGE 2010-2012,
BCR 2010-2017, BDK 2010, BEAM 2010-2014, BNI 2010, BTUUQ 2010-2014, CA 2010-2018, CBS 2010-2019, CCEP 2016,
CMCSK 2015, DD 2010-2017, DWDP 2017-2019, DXC 2010-2015, EKDKQ 2010, EP 2010-2012, FCPT 2015, FRC 2019-2023,
GAS 2010-2011, HCP 2010-2019, HSH 2010-2012, ITT 2010-2011, JAVA 2010, JCP 2010-2013, KDP 2010-2018, LDOS 2010-2013,
LO 2010-2015, MWV 2010-2015, MYL 2010-2020, NE 2011-2015, PARA 2022-2025, PBG 2010, PSKY 2025, PX 2010-2018,
QLGC 2010-2011, RSHCQ 2010-2011, SBNY 2021-2023, SUNEQ 2010-2011, SVU 2010-2012, SYMC 2010-2019, TMUS 2010-2013,
TSS 2010-2019, VIAC 2019-2022, VIAV 2010-2013, WIN 2010-2015, WRK 2015-2024, WYND 2010-2018.

Parts of some mapped intervals are also not covered (before `valid_from`), because the earlier company had another
name: APA (Apache, before 2021), AVGO (before 2018), FOXA and FOX (21st Century Fox, before 2019), FTI (before
2016), IR (Ingersoll-Rand plc, before 2017), WBA (Walgreen, before 2014) and AGN (Allergan Inc, before 2013).

**Why they are unmapped:**
- No name was recorded for the removal, and no rename had evidence (for example CA, SYMC, CBS → ViacomCBS →
  Paramount: none of these tickers is a current member, so the rename rule has no "Date added").
- Two SEC entities with the matched name both filed reports, and no tie-break chose one (for example DD: E. I. du
  Pont and DuPont de Nemours).
- A removal and an addition on the same day are missing from the changes table, so the case looks like a rename,
  but there is no evidence for one (BDK and OKE in 2010). These are left unmapped, not guessed.

**Effect on the study:** an unmapped interval has no filings, so it has no signal score. Thus it is not in the
portfolio on those dates. This removes stocks from the list, but it does not add future information. 3.2% of
member-days are lost, most of them in 2010-2015. Many of the lost companies were later bought or failed, so the
loss is not random. Thus the study reports its results by year, and a check on 2016-2025 alone (98.5% coverage; 2010-2015: 93.9%)
is part of the robustness tests.

## Report times
The SEC submissions JSON gives each report's `acceptanceDateTime` in UTC. This was checked against the EDGAR index
header, which gives New York time (Apple 10-K, 2024: header 06:01:36 New York, JSON 10:01:36 UTC).

**Rule:** a report can be used at the first NYSE open (09:30 New York) that is strictly after the acceptance time
(`ghostdesk.data.calendar.first_open_after`). A report accepted at 16:05 is used at the next day's open. A report
accepted at 08:00 is used at 09:30 on the same day.

## Report index
`scripts/build_filings_index.py` lists every 10-K and 10-Q (and their amendments) of the mapped CIKs since 2009,
from the SEC submissions JSON (`ghostdesk.filings.index`).

| | |
|---|---|
| CIKs | 791 |
| Reports | 47,719: 11,584 10-K, 34,783 10-Q, 1,352 amendments |
| Reports with an acceptance time | all |
| Original reports with a like-with-like earlier report | 92.6% |

**Like with like** (as in the paper): a 10-K is compared with the previous 10-K, and a 10-Q with the 10-Q for the
same fiscal quarter one year before (Q2 with Q2). The earlier report's period must end 1 year before (± 20 days),
so a change of fiscal year gives no pair, not a wrong one. Amendments are kept in the index, but they are never
paired, because an amendment often changes only a few items. A check stops the build if any report is paired with
a later one.
