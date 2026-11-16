# Data-quality log

Each entry records one problem found in the data or in our processing of it: what was seen, how it was found, the
cause, the fix, how the fix was verified, and the risk that remains. IDs: **U** universe, **F** filings and
features, **P** prices, **O** operations. Status: **fixed**, **mitigated** (reduced, with a stated remainder), or
**open**. Add new entries at the end of their group; never reuse an ID.

## Summary
| ID | Problem | Status | Effect if left |
|---|---|---|---|
| U1 | Tickers are reused by other companies | fixed | wrong company's reports and prices |
| U2 | Intervals that start after the study were dropped, so renames were not seen | fixed | BK, MMC, EQR unmapped |
| U3 | Company names do not match exactly | fixed | AET, DFS, IPG, HOT unmapped |
| U4 | Two CIKs with the same name both filed reports | mitigated | wrong or no CIK (VIAB, KRFT) |
| U5 | Unrecorded same-day swaps looked like renames | fixed | 6 wrong companies (BDK → ONEOK, …) |
| U6 | Today's owner of an old ticker is another company | fixed | PARA → a small unrelated company |
| U7 | Mergers into a new company looked like renames | fixed | MYL, WRK mapped to the new CIK |
| U8 | A name check on one day missed a recent name change | fixed | DISCA → "Discovery Energy" |
| U9 | Holding-company changes hid years of reports | mitigated | DIS, GOOGL, CI, MDT, BLK, XOM lost history |
| U10 | A CIK was used for dates before it existed | fixed | AGN 2010-2013 read Actavis reports |
| U11 | A short ambiguous name removed a confirmed CIK | fixed | CFG unmapped |
| F1 | Joint reports share one accession number | fixed | index build crashed |
| F2 | Headings split over inline HTML elements | fixed | sections found in 11-31% of reports |
| F3 | Cross-references taken as section headings | fixed | risk factors missing (Apple 2013) |
| F4 | Source line wraps cut sentences; sentence-level edit too coarse | fixed | edit similarity 0.1 for unchanged text |
| F5 | XBRL instance not found among rendered pages | fixed | no numbers for 2010-2013 reports |
| F6 | Probing for the XBRL file wrote it to the disk cache | fixed | runner disk full |
| F7 | MD&A outside the main document (Exhibit 13) | open | MD&A measure NaN for some large companies |
| F8 | Revenue under other XBRL names | open | revenue missing for 15% of reports |
| P1 | Old ticker symbols carry stale or foreign prices | fixed | FB 1.3% off; PARA another security |
| P2 | Vendor adjusts spin-offs as splits | fixed | false daily returns of -60% to -89% |
| P3 | A multi-symbol answer dropped a symbol | fixed | DOW without prices |
| P4 | Preferred share chosen as the company symbol | fixed | PCG priced as PCG.PE |
| P5 | First day of an interval compares two companies | mitigated (rule) | EVHC +210% on 2016-12-02 |
| P6 | Corwin-Schultz floor biases the mean up | fixed | spread 2.5× too high at 0.2% |
| P7 | Free price history starts in 2016 | decided | see decision D3 |
| P8 | Odd lots are missing from minute-bar volume | mitigated | false high costs for high-priced stocks |
| O1 | Long workflow green although a step may fail | mitigated | silent missing data |
| O2 | Artifact download timed out | fixed | 1 of 6 shards missing |

---

## Universe (`data/universe.py`, `scripts/build_universe.py`)

### U1 — Tickers are reused by other companies (fixed)
- **Seen:** `AAL` was one company in 1996-1997 and American Airlines Group from 2015.
- **Cause:** a ticker is not an identity; only the SEC CIK is fixed.
- **Fix:** each interval collects candidate CIKs from several sources; a candidate is kept only if it filed a 10-K or
  10-Q within ± 400 days of the interval (`resolve`).
- **Verified:** unit test (AAL 1996 unmapped, AAL 2015 → 6201); hand check of the mapped names.

### U2 — Renames after the study end were not seen (fixed)
- **Seen:** BK, MMC, EQR unmapped although they are large current companies.
- **Cause:** the script removed intervals that start after 2025. BK became BNY on 2026-05-21, MMC became MRSH on
  2026-01-14, so the rename partner was missing.
- **Fix:** keep all intervals that end after the study start; compute coverage on the study window only.

### U3 — Company names do not match exactly (fixed)
- **Seen:** AET, DFS, IPG, HOT unmapped.
- **Cause:** SEC names carry state tags (`AETNA INC /PA/`) and longer forms (`Discover Financial Services` for
  "Discover Financial").
- **Fix:** `normalise` removes state tags and legal suffixes; prefix matches are added as a lower-priority source
  (`prefix`, at most 25).

### U4 — Two CIKs with the same name both filed reports (mitigated)
- **Seen:** VIAB (Viacom Inc. and the old CBS, which used the name "Viacom" before 2005), KRFT (Kraft Foods Group
  and Mondelez, named "Kraft Foods Inc" before 2012-10), AGN, ESRX.
- **Fix:** tie-breaks in order: filed in the study part of the interval; filed in the 400 days before the removal;
  had the matched name in the last year of the interval (SEC `formerNames` dates), exact before prefix; supported by
  more sources.
- **Remaining:** DD (E. I. du Pont and DuPont de Nemours) stays ambiguous and unmapped.

### U5 — Unrecorded same-day swaps looked like renames (fixed)
- **Seen:** BDK → ONEOK, BNI → Berkshire Hathaway, JCP → Allegion, SVU → Phillips 66, ACS → Urban Outfitters,
  JAVA → NRG.
- **Detection:** hand check of every `rename` mapping against SEC entity names.
- **Cause:** a removal and an addition on the same day are missing from the Wikipedia changes table, so "one interval
  ends, one starts" looked like a ticker change. The filing check cannot reject them: both companies file reports.
- **Fix:** a rename needs evidence: the new ticker's "Date added" is at least 30 days before its start (a new member
  is added on its start day), or the SEC records a name change of that CIK between 45 days before and 180 days after
  the switch, or the partner is itself a rename.
- **Verified:** unit test (BDK/OKE not a rename; CTL → Lumen is one); all 17 remaining renames checked by hand.

### U6 — Today's owner of an old ticker is another company (fixed)
- **Seen:** PARA (Paramount, 2022-2025) mapped to "Parabolic Technologies".
- **Cause:** after Paramount became PSKY, the PARA ticker went to another company. The `sec_ticker` source uses
  today's owner.
- **Fix:** `sec_ticker` is a candidate only for open intervals and for intervals with a recorded removal.

### U7 — Mergers into a new company looked like renames (fixed)
- **Seen:** MYL → Viatris, WRK → Smurfit Westrock.
- **Cause:** the new company filed 10-Qs a few months before the merger closed, so it passed the filing check.
- **Fix:** a rename CIK must have filed at least one year before the switch.

### U8 — A name check on one day missed a recent name change (fixed)
- **Seen:** DISCA → "Discovery Energy" (a small company).
- **Cause:** Discovery became "Warner Bros. Discovery" two days before the check day; the small company's name
  started with "discovery".
- **Fix:** names over the last year of the interval; an exact name match is preferred to a prefix match.

### U9 — Holding-company changes hid years of reports (mitigated)
- **Seen:** coverage fell to 95.7% when `valid_from` was added: DIS, GOOGL, CI, MDT, BLK, XOM, ICE and others had a
  CIK whose reports start years after the interval.
- **Cause:** the company formed a new parent with a new CIK and kept its name and ticker; older reports are under
  the old CIK.
- **Fix:** `add_predecessors` finds the old CIK by name (spaces ignored: "ExxonMobil" = "Exxon Mobil"), by reports in
  the interval, and by exclusivity (no other ticker used it), and splits the interval at the new CIK's first report.
  Share classes may share the old CIK. When the index recorded names for the ticker, the old CIK must match them:
  this rejected two wrong matches found by hand (AGN → Watson/Actavis, IR → Gardner Denver).
- **Remaining:** where the earlier company had another name (Apache → APA, Walgreen → WBA, 21st Century Fox → FOXA,
  FMC Technologies → FTI, Avago → AVGO), the early part stays unmapped. Coverage after the fix: 96.8%.

### U10 — A CIK was used for dates before it existed (fixed)
- **Fix:** `valid_from` = max(start, first 10-K/10-Q − 120 days); the part before counts as unmapped.

### U11 — A short ambiguous name removed a confirmed CIK (fixed)
- **Seen:** CFG (Citizens Financial) unmapped after a change.
- **Cause:** the recorded name "Citizens" matched many entities; the name step removed the correct CIK, whose name
  is the longer "Citizens Financial Group".
- **Fix:** a current-members CIK that passes the filing check is taken at once; the name step accepts longer names.

## Filings and features (`filings/`, `signal/`)

### F1 — Joint reports share one accession number (fixed)
- **Seen:** `ValueError: cannot reindex on an axis with duplicate labels` in the index build.
- **Cause:** a parent and a subsidiary file one report; it appears under both CIKs.
- **Fix:** reports are keyed by `(cik, accession)`.

### F2 — Headings split over inline HTML elements (fixed)
- **Seen:** risk factors found in 11% and MD&A in 31% of Apple's reports.
- **Cause:** the old text extractor started a new line at every element, so `<span>Item</span> <span>1A.</span>`
  became two lines and the heading pattern failed.
- **Fix:** `signal.features.prose` (lxml) starts lines only at block elements and drops number tables but keeps
  layout tables. Result on the full run: 10-K risk 95.4%, MD&A 88.4%; 10-Q MD&A 94.7%.

### F3 — Cross-references taken as section headings (fixed)
- **Seen:** Apple's 2013 10-K: risk factors not found.
- **Cause:** a line starting "Item 7, “Management’s Discussion…” of this Form 10-K" split the section.
- **Fix:** `split_sections(max_heading=160)`: a heading must be a short line.

### F4 — Edit similarity far too low (fixed)
- **Seen:** edit similarity 0.1-0.3 for 2010-2016 reports while cosine was 0.999.
- **Cause:** (1) old reports wrap HTML source lines at about 80 columns, which cut sentences; (2) sentence-level
  alignment counts a sentence with one changed number as fully changed.
- **Fix:** whitespace collapsed before block line breaks; word alignment inside changed sentence blocks. Apple's
  10-K edit similarity is now 0.67-0.88 in all years.

### F5 — XBRL instance not found among rendered pages (fixed)
- **Seen:** no numbers for Apple's 2009-2013 reports.
- **Cause:** the folder also holds `R1.xml` … `R66.xml` and `defnref.xml`, so "the only .xml" rule failed.
- **Fix:** the instance has the schema's name (`aapl-20100925.xsd` → `.xml`); rendered pages are excluded. XBRL
  coverage after 2010: 98.6%.

### F6 — Probing for the XBRL file wrote it to the disk cache (fixed)
- **Cause:** the direct request for `<doc>_htm.xml` used the default `store=True`; 20,000 instances would fill a
  runner disk.
- **Fix:** `get_instance` returns the probe content and never stores it.

### F7 — MD&A outside the main document (open)
- JPMorgan and Exxon Mobil take MD&A from the annual report to shareholders (Exhibit 13). Their MD&A measure is NaN.
  The main measure is the full text. A fix would read Exhibit 13 (more requests).

### F8 — Revenue under other XBRL names (open)
- Revenue is present for about 85% of reports (banks and others use other concepts). The size control does not
  use revenue (it uses dollar volume and total assets), so this does not block Step 3.
- Shares outstanding are not extracted, so market value is not available from the features. Adding
  `dei:EntityCommonStockSharesOutstanding` to `ITEMS` would need a new `features` run.

## Prices (`data/alpaca.py`, `data/returns.py`, `scripts/load_prices.py`)

### P1 — Old ticker symbols carry stale or foreign prices (fixed)
- **Seen:** FB's 2018 closes 1.3% below META's for the same days; FB has bars up to 2025. PARA's series fell from
  $10 to $1.60 with reverse splits while Paramount traded near $15.
- **Cause:** Alpaca keeps a company's history under its current symbol; an old symbol is stale or reused.
- **Fix:** `price_symbols` gives each interval the company's current symbol (share classes keep their own); no
  prices for intervals without a confirmed CIK.

### P2 — Vendor adjusts spin-offs as splits (fixed)
- **Seen:** daily moves over 40% on member days; ARNC -89% on 2020-04-01 (raw -57%), WRK 2016-05-16, TGNA
  2017-06-01, APTV 2017-12-05, RTX 2020-04-03.
- **Detection:** scan of all member-day moves larger than 40%, then raw vs adjusted on those days.
- **Cause:** the adjusted series (both `all` and `split`) applies a split factor on spin-off days.
- **Fix:** `daily_returns` sets the return to NaN when `abs(adj) > 0.3` and `abs(adj) - abs(raw) > 0.2`. 8 days flagged,
  all known spin-offs.
- **Verified:** unit test (spin-off flagged; real split and real crash kept). After the fix, every member-day move
  larger than a factor of 2 is a real event (2020-03-09 oil crash, SVB, PG&E, Globe Life).

### P3 — A multi-symbol answer dropped a symbol (fixed)
- **Seen:** DOW missing from a 100-symbol batch, but complete (2,514 days) when asked alone.
- **Fix:** `AlpacaClient.bars` asks again, one by one, for each symbol missing from a batch answer.

### P4 — Preferred share chosen as the company symbol (fixed)
- **Seen:** PCG mapped to `PCG.PE`.
- **Cause:** the SEC lists only preferred shares for the old PG&E utility CIK.
- **Fix:** prefer a current ticker that the company used in the index, then one without a suffix, then the last
  index ticker.

### P5 — The first day of an interval compares two companies (mitigated by a rule)
- **Seen:** EVHC +210% on 2016-12-02: the series is the old Envision before that day and the merged company after.
- **Rule:** a return counts only if the stock is a member on both days. **To implement in Step 3** (backtest).

### P6 — Corwin-Schultz floor biases the mean up (fixed)
- **Seen:** at a true spread of 0.2%, the floored mean was 0.5%.
- **Fix:** `monthly_spread` averages unfloored estimates and floors the mean. Error ≤ 0.1 pp in simulation.

### P7 — Free price history starts in 2016 (decided)
- 2010-2015 has reports but no prices. See [decisions.md](decisions.md) D3.

### P8 — Odd lots are missing from minute-bar volume (mitigated)
- **Seen:** for high-priced, less traded stocks (IT, ZBRA, ANSS, VRSN, about $200-400), minute bars hold only 8-12% of
  the daily volume in the first hour, against 18-28% for the largest stocks, and 30-44% of first-hour minutes have
  no bar.
- **Cause:** trades under 100 shares (odd lots) do not count in consolidated bar volume or prices; at high prices
  many trades are odd lots.
- **Fix:** the smaller group of the execution study is taken from stocks under $150 (minute coverage 88-100%).
- **Remaining:** these stocks still show about 10% of daily volume in the first hour (partly real: smaller stocks
  trade more in the closing auction). Impact uses the observed volume, so costs are, if anything, too high.

## Operations

### O1 — Long workflow green although a step may fail (mitigated)
- **Cause:** `continue-on-error` (needed so that runs send no failure email) makes every run green.
- **Mitigation:** check step results by API and run `collect_features.py`, which fails if any report is missing.

### O2 — Artifact download timed out (fixed)
- **Seen:** `gh run download` stopped on shard 5 with a TCP timeout.
- **Fix:** `collect_features.py` downloads shard by shard, skips shards present, and tries each again up to 3 times.
