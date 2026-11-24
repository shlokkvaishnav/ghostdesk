# Runbook

How to rebuild every data file from nothing, in order.

## 0. Setup
```bash
make install                     # Python 3.12 venv, package, ruff, pytest
make install-ml                  # also torch (only for local checks of the Kaggle kernels)
```
`.env` (gitignored, never printed) must hold `SEC_USER_AGENT` (a name and a contact address), `ALPACA_API_KEY`,
`ALPACA_SECRET_KEY`. Check by name only: `grep -c "^SEC_USER_AGENT=" .env`.

The same three values are GitHub repository secrets. To copy one without showing it:
`grep '^NAME=' .env | cut -d= -f2- | gh secret set NAME`.

## 1. Universe — `scripts/data/build_universe.py`
```bash
make universe        # = PYTHONPATH=src .venv/bin/python -u scripts/data/build_universe.py
```
- Inputs: fja05680 CSV and two Wikipedia pages (saved once in `data/sources/`; delete them to refresh), SEC
  `cik-lookup-data.txt`, `company_tickers.json`, and the submissions JSON of about 3,550 candidate CIKs.
- Output: `universe.parquet`, `universe_coverage.json`; prints the unmapped intervals.
- Time: about 10 min warm; about 15 min cold (about 3,600 SEC requests at 8 per second).
- Check: member-day coverage 2010-2025 is 0.968 (2026-11-16). A large change means a source changed: diff the
  unmapped list before you accept it.

## 2. Seed prices (once) and returns — `scripts/data/load_prices.py`
```bash
make prices
```
- Gets adjusted and raw daily bars for about 690 symbols plus SPY (2016-2025), maps intervals to company symbols,
  and writes the clean returns.
- Output: `price_symbols.parquet`, `prices_daily.parquet`, `prices_daily_raw.parquet`, `returns_daily.parquet`,
  `prices_coverage.json`; prints the flagged vendor-error days.
- Time: about 5 min (14 requests of 100 symbols, plus single requests for dropped symbols).
- Check: coverage 0.980 of 2016-2025 member-days, 8 flagged days (2026-11-16).

## 3. Price store — `scripts/data/update_prices.py` (daily)
```bash
PYTHONPATH=src .venv/bin/python -u scripts/data/update_prices.py            # up to the last completed session
```
- First run: seeds `data/store/` from `prices_daily{,_raw}.parquet` (batch `seed`). Each run then appends the new
  sessions for every member of the last 30 days, SPY and today's members, and refetches the whole adjusted history of
  a symbol whose overlap closes changed (a new dividend or split).
- Time: about 35 s for 2026-01-01 to 2026-11-23 (527 symbols; 35 refetched; 2026-11-24).
- The free plan refuses a bare end date for recent SIP data; the code sends an end time at least 16 minutes old.

## 4. Sectors — `scripts/data/build_sectors.py`
- SIC code per CIK from the SEC submissions JSON (through the `data/raw` cache: 6 network calls on 2026-11-24),
  grouped by `data.industry.industry_groups`: 709 companies, 25 groups. Output `sectors.parquet`.

## 5. Feature benchmark — `scripts/research/bench_features.py`
- The 158 factors on 2016 to the validation end (1,762 sessions x 635 symbols): engine cold, engine warm (cache), and
  engine against `features.pandas_reference` on 50 symbols. Output `data/results/bench_features.json`. About 30 s.

## 9. Checks before a commit
```bash
make check     # ruff + pytest + mkdocs build --strict
```

## External limits
| Service | Limit | How the code stays inside it |
|---|---|---|
| SEC EDGAR | 10 requests/s per user; declared User-Agent | `EdgarClient` at 8/s; shards share 7.8/s |
| Alpaca market data (free) | 200 requests/min; SIP history except the last 15 min; from 2016 | `AlpacaClient` at 180/min |
| Kaggle | free GPU hours per week | Transformer training and foundation-model inference only |

## Workflows
| Workflow | Trigger | Purpose |
|---|---|---|
| `ci.yml` | push, pull request | ruff + pytest |
