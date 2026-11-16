# Data contracts

All files are in `data/` (gitignored, rebuilt by the scripts in [runbook.md](runbook.md)). Times: `*_utc` and Alpaca
`t` are UTC; `day`, `start`, `end`, `filing_date`, `report_date` are New York calendar dates without a time zone.
`tests/test_docs.py` checks the column lists below against the files when they are present.

---

### data/universe.parquet
Producer: `scripts/build_universe.py`. One row per membership interval (or part of one, after a holding-company
split). 881 rows (863 inside 2010-2025). Key: `(ticker, start)`.

| Column | Type | Meaning |
|---|---|---|
| `ticker` | str | Index ticker of the time (fja05680 spelling). |
| `start` | date | First member day. |
| `end` | date or NaT | First day not a member; NaT = member now. |
| `keys` | list[str] | Normalised company names recorded at the add or removal (may be empty). |
| `cik` | Int64 or NA | SEC CIK; NA = not confirmed (no prices, no reports). |
| `source` | str | `current`, `name`, `prefix`, `sec_ticker`, `rename`, `predecessor`, or empty. |
| `valid_from` | date or NaT | The CIK is the company only from this date (≥ `start`). |

Invariants: intervals of one ticker do not overlap; a CIK is shared by overlapping intervals only for share classes
(GOOG/GOOGL, FOX/FOXA, NWS/NWSA, DISCA/DISCK, UA/UAA).

### data/filings_index.parquet
Producer: `scripts/build_filings_index.py`. Every 10-K, 10-Q, 10-K/A, 10-Q/A of the universe CIKs since 2009.
47,719 rows. Key: `(cik, accession)` (a joint report has one accession under several CIKs).

| Column | Type | Meaning |
|---|---|---|
| `cik` | int | Filer. |
| `accession` | str | SEC accession number. |
| `form` | str | `10-K`, `10-Q`, `10-K/A`, `10-Q/A`. |
| `base_form` | str | Form without `/A`. |
| `amendment` | bool | True for `/A`. |
| `filing_date` | date | SEC filing date. |
| `report_date` | date | End of the period covered. |
| `accepted_utc` | timestamp UTC | SEC acceptance time (point-in-time anchor). |
| `primary_doc` | str | Main document file name. |
| `prev_accession` | str or None | Like-with-like earlier report (same base form, period one year earlier ± 20 days, accepted earlier). Never set for amendments. |

Invariant: `no_future_pairs` is true (checked when the file is built).

### data/features.parquet
Producer: `features` workflow → `scripts/collect_features.py`. One row per paired original report filed while its
CIK was in the index, 2009-06 to 2025. 30,514 rows. Key: `(cik, accession)`.

| Column | Type | Meaning |
|---|---|---|
| `cik` | int | |
| `accession` | str | This report. |
| `prev_accession` | str | The earlier report it is compared with. |
| `form` | str | `10-K` or `10-Q`. |
| `filing_date` | date | |
| `report_date` | date | |
| `accepted_utc` | timestamp UTC | |
| `error` | str | Empty, or the first 200 characters of the error (then the measures are NaN). |
| `sim_full_cosine` | float | Cosine similarity of the full text (tables removed). |
| `sim_full_jaccard` | float | Jaccard similarity of the full text. |
| `sim_full_edit` | float | Edit similarity of the full text. |
| `words_full` | float | Words in this report's full text. |
| `words_full_prev` | float | Words in the earlier report's full text. |
| `sim_risk_cosine` | float | Same measures on risk factors (Item 1A); NaN if missing in either report. |
| `sim_risk_jaccard` | float | |
| `sim_risk_edit` | float | |
| `words_risk` | float | |
| `words_risk_prev` | float | |
| `sim_mdna_cosine` | float | Same measures on MD&A (10-K Item 7, 10-Q Item 2). |
| `sim_mdna_jaccard` | float | |
| `sim_mdna_edit` | float | |
| `words_mdna` | float | |
| `words_mdna_prev` | float | |
| `xbrl_Revenues` | float | Own-period value from the report's own XBRL (NaN if none). |
| `xbrl_Assets` | float | |
| `xbrl_StockholdersEquity` | float | |
| `xbrl_NetIncomeLoss` | float | |

Note: the measures are similarities (1 = same text). The signal is a change, so lower similarity = more change.

### data/price_symbols.parquet
Producer: `scripts/load_prices.py`. The universe intervals of 2016-2025 with the symbol used for prices.

| Column | Type | Meaning |
|---|---|---|
| `ticker` | str | Index ticker of the time. |
| `start` | date | |
| `end` | date or NaT | |
| `cik` | Int64 or NA | |
| `price_symbol` | str or None | Alpaca symbol (see `universe.price_symbols`); None = no prices. |

### data/prices_daily.parquet and data/prices_daily_raw.parquet
Producer: `scripts/load_prices.py`. Alpaca daily bars, feed `sip`, 2016-01-01 to 2025-12-31; adjusted (`all`) and
raw. 1,556,080 rows each. Key: `(symbol, t)`.

| Column | Type | Meaning |
|---|---|---|
| `symbol` | str | Alpaca symbol. |
| `t` | timestamp UTC | Bar time (the session date at 04:00 or 05:00 UTC). |
| `o` | float | Open. |
| `h` | float | High. |
| `l` | float | Low. |
| `c` | float | Close. |
| `v` | int | Volume, all exchanges. |
| `n` | int | Number of trades. |
| `vw` | float | Volume-weighted average price. |

### data/returns_daily.parquet
Producer: `scripts/load_prices.py` (`data.returns.daily_returns`). Key: `(symbol, day)`.

| Column | Type | Meaning |
|---|---|---|
| `symbol` | str | |
| `day` | date | Session date (New York). |
| `ret` | float | Log return from adjusted closes; NaN on the first day and on flagged days. |
| `flag` | bool | Vendor corporate-action error (see [data-quality.md](data-quality.md), P2). |
| `close` | float | Raw close (for order sizes). |
| `close_adj` | float | Adjusted close. |

Use rule: a return counts only if the stock is a member (with a confirmed CIK) on both days.

### data/panel_<period>.parquet
Producer: `scripts/signal_study.py`. One row per (formation month-end, CIK). Columns: `month, cik, ticker,
price_symbol, accession, form, tradeable`, the nine `sim_*` measures, `fwd_ret, fwd_days, mom, logdv, log_assets,
sic, spread, signal_age`, then the ranked signals `sim_*_r, composite, composite_ind`. Key: `(month, cik)`.

### data/results_<period>.json
Producer: `scripts/signal_study.py`. `period, formation, primary, prereg_commit, code_commit, panel` and, per signal,
the `signal.study.summary` dictionary.

### Summary files
`universe_coverage.json`, `filings_index_summary.json`, `features_summary.json`, `prices_coverage.json`: counts
written by the producers; [docs/data.md](../data.md) quotes them.

### Caches and inputs
| Path | Content |
|---|---|
| `data/raw/` | `EdgarClient` cache (SHA-256 of the URL). Submissions JSON, folder indexes, lookup file. About 350 MB. |
| `data/sources/` | fja05680 CSV and the two Wikipedia pages, as downloaded (the universe depends on their date). |
| `data/features_run/` | Shard artifacts of the last `features` run. |
