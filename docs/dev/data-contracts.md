# Data contracts

All files are in `data/` (gitignored, rebuilt by the scripts in [runbook.md](runbook.md)). Times: `*_utc` and Alpaca
`t` are UTC; `day`, `start`, `end`, `filing_date`, `report_date` are New York calendar dates without a time zone.
`tests/test_docs.py` checks the column lists below against the files when they are present.

---

### data/universe.parquet
Producer: `scripts/data/build_universe.py`. One row per membership interval (or part of one, after a holding-company
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

### data/price_symbols.parquet
Producer: `scripts/data/load_prices.py`. The universe intervals of 2016-2025 with the symbol used for prices.

| Column | Type | Meaning |
|---|---|---|
| `ticker` | str | Index ticker of the time. |
| `start` | date | |
| `end` | date or NaT | |
| `cik` | Int64 or NA | |
| `price_symbol` | str or None | Alpaca symbol (see `sp500_universe.price_symbols`); None = no prices. |

### data/prices_daily.parquet and data/prices_daily_raw.parquet
Producer: `scripts/data/load_prices.py`. Alpaca daily bars, feed `sip`, 2016-01-01 to 2025-12-31 (the seed of the store below); adjusted (`all`) and
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
Producer: `scripts/data/load_prices.py` (`data.daily_returns.daily_returns`). Key: `(symbol, day)`.

| Column | Type | Meaning |
|---|---|---|
| `symbol` | str | |
| `day` | date | Session date (New York). |
| `ret` | float | Log return from adjusted closes; NaN on the first day and on flagged days. |
| `flag` | bool | Vendor corporate-action error (see [data-quality.md](data-quality.md), P2). |
| `close` | float | Raw close (for order sizes). |
| `close_adj` | float | Adjusted close. |

Use rule: a return counts only if the stock is a member (with a confirmed CIK) on both days.

### data/store/bars/adj/<batch>.parquet and data/store/bars/raw/<batch>.parquet
Producer: `scripts/data/update_prices.py` (`data.store`, D26). One file per ingestion batch (`seed` = the 2016-2025
load; then `<YYYYMMDDHHMM>` per run); never changed after it is written. Read only through `PriceStore.read`, which keeps
the newest row per `(symbol, day)` known at the as-of time. `data/store/ingest_log.json` lists each run's counts.

| Column | Type | Meaning |
|---|---|---|
| `symbol` | str | Alpaca symbol. |
| `day` | date | New York session date. |
| `o`, `h`, `l`, `c` | float | Open, high, low, close (adjusted in `adj`, as traded in `raw`). |
| `v`, `n`, `vw` | float | Volume, trades, VWAP. |
| `ingested_at` | timestamp UTC | When the batch was written (the as-of key). |

### data/sectors.parquet
Producer: `scripts/data/build_sectors.py`. One row per CIK with prices or in today's index (709).

| Column | Type | Meaning |
|---|---|---|
| `cik` | int | SEC CIK. |
| `sic` | str | Today's SIC code of the CIK (empty if unknown). |
| `sector` | str | `data.industry.industry_groups` over all companies: the 2-digit SIC group, or the division for small groups. |

### data/results/*.json
Measured numbers that the docs quote, one file per script (`bench_features.json`: engine and pandas times, cache
size, reuse counts, differing factors; `validation.json`: per-model validation metrics, run keys, optimizer, timing,
bit-identical check; `fault_injection.json`: scenarios, runs, crashes, violations). Copies of `bench_features.json` and
`validation.json` are committed in `docs/results/` after each run.

### Live state: data/live/ (Actions cache `nightly-state-*`, encrypted copy in the release `nightly-state`)
Producer: `scripts/live_desk.py`. `store/` (a `data.store` of about 600 days for today's members), `ledger/`
(`<YYYYMMDD>.parquet` with `live.ledger.COLUMNS`, `chain.jsonl`), `night_<YYYYMMDD>.json` (runs, ledger hash, target,
plan, orders, rejected, unreached, complete; `missed` when the next open passed before the ledger was written, D38),
`ledger_scores.parquet` and `ledger_summary.json` (derived; predictions made at or after their first realized open are
left out, D38), `members.parquet` (`symbol, cik, name, sector`),
`forward_eval.json` (derived, strict JSON: `forward` = per-model summary with `forward_days`, `daily` = per
session and model IC, hit rate, P&L, `book` = days, cumulative net return, Sharpe, max drawdown, mean turnover,
total cost, curve; `compare` = labelled validation-versus-forward rows with sample sizes; D37),
`health.json`. Output for the page: `site-data/live.json` (gitignored).
The old monthly desk's state stays in the release `live-state` (not read any more); its account record is in
`docs/archive/monthly-desk-2026-11/` (D38).

### Frozen models: the release `models-v1` and docs/results/MODEL_MANIFEST.json (D38)
Producer: `scripts/research/fit_live_models.py` (files in `data/live/models/`) and `scripts/ops/publish_models.py`
(the manifest). Release files: `lightgbm.txt` (LightGBM text model), `ridge.npy` (float64 weights), `sectors.json`
(symbol -> sector group), `meta.json` (features, ensemble weights, fit dates, code commit, data hash); the manifest is
attached too. The manifest (committed) lists each file's bytes and SHA-256, every validated model (nightly or not,
published or not, with the reason), the train and validation splits, the feature list, the ensemble weights and the
package versions. Invariant: the nightly job downloads only the pinned tag into `data/models-v1/` and runs
`live.model_release.verify` before any data is fetched; any difference fails the run. The files never change; new
models get a new tag and a new manifest.

### Caches and inputs
| Path | Content |
|---|---|
| `data/raw/` | `EdgarClient` cache (SHA-256 of the URL): submissions JSON and the lookup file for the stock list and sectors. |
| `data/cache/features/` | Feature engine results (`.npy`, SHA-256 key); safe to delete. |
| `data/sources/` | fja05680 CSV and the two Wikipedia pages, as downloaded (the universe depends on their date). |
