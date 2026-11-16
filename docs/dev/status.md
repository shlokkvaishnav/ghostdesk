# Status and next work

Updated 2026-11-16. Steps follow [docs/plan.md](../plan.md).

## Done
| Step | Result | Evidence |
|---|---|---|
| 1. Repo | Tested parts copied in; CI and docs green | commits `3c13a3c`… |
| 2a. Universe | 96.8% of 2010-2025 member-days mapped to a CIK | `universe_coverage.json`, [data.md](../data.md) |
| 2b. Report index | 47,719 reports, all with acceptance time; 92.6% paired | `filings_index_summary.json` |
| 2c. Text features + XBRL | 30,514 pairs, 765 CIKs, 44 errors | `features_summary.json`, run 43854092158 |
| 2d. Prices and returns | 98.0% of 2016-2025 member-days with a bar; 8 vendor-error days removed | `prices_coverage.json` |
| 2e. Spread estimate | Corwin-Schultz, ±0.1 pp in simulation | `tests/test_spread_similarity.py` |

## Next: Step 3 — the signal study
Work in this order. Each item lists what "done" means.

1. **Pre-registration** — `docs/preregistration.md`, committed **before** any 2022-2025 return is read.
   - Fixed: universe rule, signal (primary: `sim_full_edit`, lower = more change; secondary: Jaccard, cosine, and the
     risk and MD&A parts), event time (`first_open_after`), holding period (primary: 3 months), portfolio
     (quintiles, equal weight, monthly rebalance), costs (Corwin-Schultz half-spread per trade, plus 5 bps), controls
     (size = log 63-day average dollar volume and log total assets; 12-1 month momentum; GICS sector from the current
     constituents table, a stated limit for removed companies), tests and the
     significance level, and the exact command that will produce the test result.
   - Done when: the file is committed and its commit hash is quoted in the results.
2. **Panel builder** — `src/ghostdesk/signal/panel.py`.
   - One row per (stock, month-end): latest signal known before the month-end (by tradeable time), member on that
     date, return over the next month (members on both days, flagged days excluded).
   - Tests: a report accepted after the month-end is not used; a non-member is not in the panel; a flagged day
     does not enter a return; EVHC-type first-day returns are excluded (data-quality P5).
   - Done when: tests pass and the panel's coverage is in `docs/data.md`.
3. **Backtest on 2016-2019 only** — `scripts/signal_study.py --period build`.
   - Outputs (JSON + charts): IC by year, quintile spreads, long-short return before and after costs, turnover,
     break-even cost, Fama-French 5-factor + momentum alpha with Newey-West t-statistic.
   - Fama-French factors: Kenneth French data library (monthly), cached in `data/sources/`.
   - Done when: the script runs from the cached data in under 10 minutes and writes `data/results_build.json`.
4. **Check period 2020-2021**, same script, `--period check`. Choices may change only on build data.
5. **Test period 2022-2025**, once, with the pre-registered command. Report the result as it is (a null result is a
   valid result).

## Later
- Step 4 — execution study: calibrate `execution/impact.py` per stock (daily volatility and volume from
  `prices_daily.parquet`, spread from `data/spread.py`); PPO vs TWAP/VWAP/Almgren-Chriss at 0.1%, 1%, 5% of daily
  volume; main chart: RL gain by order size. Needs minute bars (Alpaca, a sample of stocks).
- Step 4b — optional world model behind the gates of decision D2.
- Step 5 — live job and site: daily GitHub Actions job, Alpaca paper orders over 30-60 min after the open, site from
  JSON with `deploy-pages`, no commit, no failure emails.
- Step 6 — research note, one-page summary, filing-diff visual, `make figures`.

## Known open items
- data-quality F7 (MD&A in Exhibit 13), F8 (revenue concept names): not blocking.
- 44 feature errors (network): can be retried with `extract_features.py --ciks ...`.
