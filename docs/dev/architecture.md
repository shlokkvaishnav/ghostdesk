# Architecture

## Pipeline
Each box is a script; each arrow is a data file in `data/` (gitignored). Columns are in
[data-contracts.md](data-contracts.md).

```
 public sources                          scripts/                                  data/
 ──────────────                          ────────                                  ─────
 fja05680 S&P 500 intervals ─┐
 Wikipedia current + changes ├──▶ build_universe.py ───────────────▶ universe.parquet
 SEC cik-lookup, tickers,    │      (CIK per membership interval)      universe_coverage.json
 submissions JSON ───────────┘                │
                                              ▼
 SEC submissions JSON ──────────▶ build_filings_index.py ──────────▶ filings_index.parquet
                                    (10-K/10-Q, acceptance time,       filings_index_summary.json
                                     like-with-like pairs)
                                              │
                                              ▼
 SEC report HTML + XBRL ────────▶ extract_features.py  (GitHub Actions `features`, 6 shards)
                                    └──▶ collect_features.py ──────▶ features.parquet
                                                                       features_summary.json
 Alpaca daily bars (2016-) ─────▶ load_prices.py ──────────────────▶ price_symbols.parquet
                                    (company symbols, raw and          prices_daily.parquet
                                     adjusted, vendor errors removed)  prices_daily_raw.parquet
                                                                       returns_daily.parquet
                                              │                        prices_coverage.json
                                              ▼
                                   [next] signal study (Step 3) ──▶ results JSON + charts ─▶ docs site
```

## Layers (`src/ghostdesk/`)
| Package | Role | Depends on |
|---|---|---|
| `filings/` | SEC access (rate-limited, cached), report index, report text, XBRL | — |
| `data/` | universe, trading calendar, prices, returns, spread estimate | `filings/edgar` (CIKs, `REPO_ROOT`) |
| `signal/` | text extraction and change measures | `filings/sections` |
| `execution/` | impact simulator, Gymnasium environment, TWAP/VWAP/Almgren-Chriss | — |
| `rl/` | PPO (from scratch) | `execution/`, torch |

Rules: library code in `src/` does no network I/O at import time, takes clients as arguments (so tests inject
fakes), and never reads `.env` except through `filings.edgar.user_agent` and `data.alpaca.keys`. Scripts in
`scripts/` hold the orchestration and file I/O.

## Point-in-time model
| Event | Time used | Code |
|---|---|---|
| Stock is in the list | membership interval `[start, end)`, CIK valid from `valid_from` | `data/universe.py` |
| Report is public | SEC `acceptanceDateTime` (UTC) | `filings/index.py` |
| Report is tradeable | first NYSE open strictly after acceptance | `data/calendar.py:first_open_after` |
| Number is known | first report that gave it, accepted before the decision | `filings/xbrl.py:as_of` |
| Return counts | stock is a member on both days; vendor-error days removed | `data/returns.py` |

## Execution and compute
- Short jobs (< 10 min) run locally with the SEC cache in `data/raw` (342 MB, gitignored).
- Long jobs run on GitHub Actions, started by hand (`workflow_dispatch`), inputs from a private release, outputs
  as private artifacts. See [runbook.md](runbook.md).
- The live job (Step 5, `live.yml`) runs on GitHub Actions and deploys the whole site (page + docs) with
  `upload-pages-artifact` + `deploy-pages`, with no commit.
