# Runbook

How to rebuild every data file from nothing, in order. Times are with a warm SEC cache (`data/raw/`) unless noted.

## 0. Setup
```bash
make install                     # Python 3.12 venv, package, ruff, pytest
make install-ml                  # also torch + stable-baselines3 (execution and RL work)
```
`.env` (gitignored, never printed) must hold `SEC_USER_AGENT` (a name and a contact address), `ALPACA_API_KEY`,
`ALPACA_SECRET_KEY`. Check by name only: `grep -c "^SEC_USER_AGENT=" .env`.

The same three values are GitHub repository secrets. To copy one without showing it:
`grep '^NAME=' .env | cut -d= -f2- | gh secret set NAME`.

## 1. Universe — `scripts/build_universe.py`
```bash
make universe        # = PYTHONPATH=src .venv/bin/python -u scripts/build_universe.py
```
- Inputs: fja05680 CSV and two Wikipedia pages (saved once in `data/sources/`; delete them to refresh), SEC
  `cik-lookup-data.txt`, `company_tickers.json`, and the submissions JSON of about 3,550 candidate CIKs.
- Output: `universe.parquet`, `universe_coverage.json`; prints the unmapped intervals.
- Time: about 10 min warm; about 15 min cold (about 3,600 SEC requests at 8 per second).
- Check: member-day coverage 2010-2025 is 0.968 (2026-11-16). A large change means a source changed: diff the
  unmapped list before you accept it.

## 2. Report index — `scripts/build_filings_index.py`
```bash
make index
```
- Output: `filings_index.parquet`, `filings_index_summary.json`. Stops with an error if any pair points to a later
  report.
- Time: about 2 min warm.

## 3. Text features — GitHub Actions `features`, then `scripts/collect_features.py`
`scripts/extract_features.py` reads about 30,500 reports (about 100,000 SEC requests). This is too long for a
laptop, so it runs on GitHub Actions in 6 parallel shards at 1.3 requests per second each (7.8 per second in total).
1. Publish the inputs as a private release (once per rebuild of steps 1-2):
   ```bash
   gh release create inputs-YYYY-MM-DD data/universe.parquet data/filings_index.parquet --title "Inputs YYYY-MM-DD" --notes "SEC metadata; no prices."
   ```
2. Start the run: `gh workflow run features.yml -f release=inputs-YYYY-MM-DD`.
3. Wait: about 3-4 hours. GitHub may hold the run in the queue for some minutes first.
4. Join and check: `make features RUN=<run id>`. It downloads the 6 artifacts (tries again on a timeout), joins
   them, and fails if any target report is missing.
- Expected (run 43854092158): 30,514 reports, 765 CIKs, 0 missing, 44 errors.
- Cost: about 1,300 of the 2,000 free Actions minutes per month of a private repo.
- Every step has `continue-on-error`, so the run is green even if a step failed. **Always check** the step results
  (`gh api repos/<owner>/ghostdesk/actions/runs/<id>/jobs`) and the `collect_features.py` summary.
- Local test on one company (about 20-120 s): `PYTHONPATH=src .venv/bin/python -u scripts/extract_features.py --ciks 320193 --out /tmp/feat`.

## 4. Prices and returns — `scripts/load_prices.py`
```bash
make prices
```
- Gets adjusted and raw daily bars for about 690 symbols plus SPY (2016-2025), maps intervals to company symbols,
  and writes the clean returns.
- Output: `price_symbols.parquet`, `prices_daily.parquet`, `prices_daily_raw.parquet`, `returns_daily.parquet`,
  `prices_coverage.json`; prints the flagged vendor-error days.
- Time: about 5 min (14 requests of 100 symbols, plus single requests for dropped symbols).
- Check: coverage 0.980 of 2016-2025 member-days, 8 flagged days (2026-11-16).

## 5. Signal study — `scripts/signal_study.py`
Needs the Fama-French files in `data/sources/ff/`. The French library answers 404 to the owner's network, so the
`sources` workflow fetches them: `gh workflow run sources.yml`, then
`gh run download <id> -n sources --dir data/sources/ff`.
```bash
PYTHONPATH=src .venv/bin/python -u scripts/signal_study.py --period build    # 2016-2019, about 10 s
PYTHONPATH=src .venv/bin/python -u scripts/signal_study.py --period check    # 2020-2021
PYTHONPATH=src .venv/bin/python -u scripts/signal_study.py --period test --prereg <commit>    # once
```
- Output: `data/panel_<period>.parquet`, `data/results_<period>.json`.
- `test` and `pooled` refuse to run unless `docs/preregistration.md` is committed, unchanged, and `--prereg` is the
  commit that last changed it. **Do not run them** unless the owner asks; read
  [preregistration.md](../preregistration.md) first.

### Pitfall-bias table — `scripts/pitfalls.py`
Reruns the study on 2016-2021 with one guard off at a time; refuses dates in the test period. About 1 min.

## 6. Execution study
```bash
PYTHONPATH=src .venv/bin/python -u scripts/load_minutes.py        # 20 stocks, 2023-2024, first hour; about 4 min
PYTHONPATH=src .venv/bin/python -u scripts/execution_study.py --eval val --steps 1000000   # design work, about 4 min
PYTHONPATH=src .venv/bin/python -u scripts/execution_study.py --eval test --steps 600000 --seed 0   # final, x3 seeds
PYTHONPATH=src .venv/bin/python -u scripts/capacity.py            # needs the pooled signal study
PYTHONPATH=src .venv/bin/python -u scripts/execution_summary.py   # table of the 3 test seeds; seconds
```
Design changes use `--eval val` only (train 2023-01..09, evaluate 2023-10..12). `--eval test` (2024) is the final run.

## 7. Live job (Step 5, decision D15)
Runs on GitHub Actions (`.github/workflows/live.yml`); state in the Actions cache `live-state-*` (`data/live/`).
```bash
PYTHONPATH=src .venv/bin/python -u scripts/live.py score --limit 12   # local test: 12 companies, about 30 s
PYTHONPATH=src .venv/bin/python -u scripts/live.py trade --dry-run    # the plan; never sends an order
PYTHONPATH=src .venv/bin/python -u scripts/live.py site               # site-data/live.json
gh workflow run live.yml -f mode=score                                # full score on Actions (about 12 min cold)
gh workflow run live.yml -f mode=trade                                # trade now (only acts on a rebalance day)
gh variable set TRADING --body off                                    # stop: no new orders from the next run
gh workflow run live.yml -f mode=flatten                              # close every position (during market hours)
gh variable set TRADING --body on                                     # start again
```
The page source is `web/` (product page; `web/data/live.json` comes from the job). The whole site (page at the root,
mkdocs under `/docs/`) is built and deployed only by `live.yml`. A scheduled workflow stops after 60 days without a
commit in the repository; the page shows the time of each mode's last run.

## 8. Checks before a commit
```bash
make check     # ruff + pytest + mkdocs build --strict
```

## External limits
| Service | Limit | How the code stays inside it |
|---|---|---|
| SEC EDGAR | 10 requests/s per user; declared User-Agent | `EdgarClient` at 8/s; shards share 7.8/s |
| Alpaca market data (free) | 200 requests/min; SIP history except the last 15 min; from 2016 | `AlpacaClient` at 180/min |
| GitHub Actions (private) | 2,000 min/month; 6 h per job | `features` uses 6 × ≤ 345 min |
| GitHub artifacts | download can time out | `collect_features.py` tries again |

## Workflows
| Workflow | Trigger | Purpose |
|---|---|---|
| `ci.yml` | push, pull request | ruff + pytest (torch CPU) |
| `live.yml` | weekday schedules, push to `docs/**` or `web/**`, manual | live job (score, trade, flatten, site) and the whole Pages site |
| `features.yml` | manual | text features in 6 shards |
| `sources.yml` | manual | Fama-French factor files (blocked from the owner's network) |
