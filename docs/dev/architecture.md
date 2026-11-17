# Architecture

## Pipeline
Each box is a script in `scripts/data/` (data) or `scripts/studies/` (studies); each arrow is a data file in
`data/` (gitignored). Columns are in
[data-contracts.md](data-contracts.md).

```
 public sources                          scripts/                                  data/
 ──────────────                          ────────                                  ─────
 fja05680 S&P 500 intervals ─┐
 Wikipedia current + changes ├──▶ build_universe.py ───────────────▶ universe.parquet
 SEC cik-lookup, tickers,    │      (CIK per membership interval)      universe_coverage.json
 submissions JSON ───────────┘                │
                                              ▼
 SEC submissions JSON ──────────▶ build_filing_index.py ──────────▶ filings_index.parquet
                                    (10-K/10-Q, acceptance time,       filings_index_summary.json
                                     like-with-like pairs)
                                              │
                                              ▼
 SEC report HTML + XBRL ────────▶ extract_text_features.py  (GitHub Actions `features`, 6 shards)
                                    └──▶ merge_feature_shards.py ──────▶ features.parquet
                                                                       features_summary.json
 Alpaca daily bars (2016-) ─────▶ load_prices.py ──────────────────▶ price_symbols.parquet
                                    (company symbols, raw and          prices_daily.parquet
                                     adjusted, vendor errors removed)  prices_daily_raw.parquet
                                                                       returns_daily.parquet
                                              │                        prices_coverage.json
                                              ▼
                     scripts/studies/run_signal_study.py, run_ml_study.py, run_cnn_study.py, ...
                                   ──▶ results JSON ─▶ docs/results.md
 scripts/live_desk.py (GitHub Actions `live`) ──▶ data/live/ ──▶ the web page
```

## Layers (`src/ghostdesk/`)
| Package | Role | Depends on |
|---|---|---|
| `filings/` | SEC access (rate-limited, cached), report index, report sections, XBRL | — |
| `data/` | S&P 500 universe, market calendar, Alpaca prices, daily returns, spread estimate, Fama-French factors, industries | `filings/edgar_client` (CIKs, `REPO_ROOT`) |
| `text_signal/` | text change measures, features per report pair, the stock-month panel | `filings/`, `data/` |
| `evaluation/` | portfolio statistics shared by every study (`portfolio_stats`) | `data/` |
| `return_models/` | point-in-time stock features, the holdout lock, walk-forward models, chart images and the chart CNN | `text_signal/`, `data/`, LightGBM, torch |
| `execution/` | order schedules, impact and replay simulators, Gymnasium environment, PPO agent, capacity | `evaluation/`, torch |
| `live/` | Alpaca paper broker, live signal, order planning, the rebalance run, dashboard data | `text_signal/`, `evaluation/` |

Rules: library code in `src/` does no network I/O at import time, takes clients as arguments (so tests inject
fakes), and never reads `.env` except through `filings.edgar_client.user_agent` and `data.alpaca_client.keys`. Scripts in
`scripts/` hold the orchestration and file I/O.

## Point-in-time model
| Event | Time used | Code |
|---|---|---|
| Stock is in the list | membership interval `[start, end)`, CIK valid from `valid_from` | `data/sp500_universe.py` |
| Report is public | SEC `acceptanceDateTime` (UTC) | `filings/filing_index.py` |
| Report is tradeable | first NYSE open strictly after acceptance | `data/market_calendar.py:first_open_after` |
| Number is known | first report that gave it, accepted before the decision | `filings/xbrl.py:as_of` |
| Return counts | stock is a member on both days; vendor-error days removed | `data/daily_returns.py` |

## Execution and compute
- Short jobs (< 10 min) run locally with the SEC cache in `data/raw` (342 MB, gitignored).
- Long jobs run on GitHub Actions, started by hand (`workflow_dispatch`), inputs from a private release, outputs
  as private artifacts. See [runbook.md](runbook.md).
- The live job (Step 5, `live.yml`) runs on GitHub Actions and deploys the whole site (page + docs) with
  `upload-pages-artifact` + `deploy-pages`, with no commit.
