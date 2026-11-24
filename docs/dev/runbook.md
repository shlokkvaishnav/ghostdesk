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
  engine against `features.pandas_reference` on 50 symbols. Output `data/results/bench_features.json` (a copy is committed in `docs/results/`). About 30 s.

## 6. Kaggle — `scripts/research/export_kaggle_panel.py`, `kaggle/transformer`, `kaggle/foundation`
```bash
PYTHONPATH=src .venv/bin/python -u scripts/research/export_kaggle_panel.py --upload   # private dataset ghostdesk-panel
~/.cache/kaggle-cli/bin/kaggle kernels push -p kaggle/transformer                     # GPU, about 1 h
~/.cache/kaggle-cli/bin/kaggle kernels push -p kaggle/foundation                      # GPU + internet, a few hours
~/.cache/kaggle-cli/bin/kaggle kernels status <owner>/ghostdesk-foundation           # check a few times, not in a loop
~/.cache/kaggle-cli/bin/kaggle kernels output <owner>/ghostdesk-foundation -p data/kaggle/out
```
- The panel ends at the validation end; `--include-test` needs the test lock open.
- Local check of a kernel: `SMOKE=1 PANEL=data/kaggle/panel/panel.npz OUT=/tmp/x python kaggle/transformer/kernel.py`.

## 6b. Frozen live models — `scripts/research/fit_live_models.py`
- Ridge and LightGBM on 2016-2022; writes `data/live/models/` (about 2 min).

## 7. Validation study — `scripts/research/run_validation.py`
- Walk-forward 2018-2022 of every local model, plus Kaggle scores in `data/kaggle/out/`; registry rows; optimizer
  against the decile book on 2021-2022; `--verify` reruns LightGBM for the bit-identical check. Needs a clean
  commit (the registry refuses a dirty tree). Output `data/results/validation.json`.

## 8. Nightly job — `scripts/live_desk.py` (GitHub Actions `nightly.yml`, D30, D38)
Order execution is disabled. The workflow sets `TRADING` to `off` itself (it does not read the repository
variable), and it has no flatten or order mode. The old `live.yml` is removed.

| Mode | What it does |
|---|---|
| `night` | download and check the pinned models (`models-v1` against `docs/results/MODEL_MANIFEST.json`), members, new bars into `data/live/store`, predictions into the ledger, ledger scoring, `forward_eval.json`; no order |
| `site` | `site-data/live.json` and the whole Pages site |

- Triggers: the Worker at 01:30 and 11:00 UTC Tuesday to Saturday ([trigger-setup.md](trigger-setup.md)); the
  GitHub schedule at 02:00 and 11:30 UTC as a backup; a push to `docs/**`, `web/**`, `mkdocs.yml` or the workflow
  (site only); manual: `gh workflow run nightly.yml -f mode=night` (or `-f mode=site`).
- A night that already has its ledger file does nothing new. Predictions for a session are written only before its
  open (the timing guard); a late run records the session as `missed`.
- State: the ledger and the live store are kept in the Actions cache and, encrypted with `STATE_KEY`, in the release
  `nightly-state` (D25). The old `live-state` release is not read.
- Failures (D38): a missing, changed or incompatible model, a failed night, a missing ledger or evaluation, or a lost
  state upload fails the run, and GitHub sends its normal failure notice. A good run is quiet. The site steps do not
  fail the run.

### `scripts/ops/publish_models.py` — the frozen models (once per model version)
```bash
PYTHONPATH=src .venv/bin/python -u scripts/research/fit_live_models.py   # writes data/live/models/
PYTHONPATH=src .venv/bin/python -u scripts/ops/publish_models.py         # writes docs/results/MODEL_MANIFEST.json
gh release create models-v1 data/live/models/{lightgbm.txt,ridge.npy,sectors.json,meta.json} \
    docs/results/MODEL_MANIFEST.json --title "Frozen models v1"
```
- The manifest holds the SHA-256 and size of each file, the training window and the package versions; the script
  checks the files against it and that the models load. The workflow pins the tag in `MODELS_TAG`; a new model
  version is a new tag (`models-v2`), a new manifest and a reviewed change to the workflow, never a replaced asset.

### `scripts/ops/archive_account.py` — archive of the monthly paper desk (done 2026-11-24)
```bash
PYTHONPATH=src .venv/bin/python -u scripts/ops/archive_account.py [--out DIR] [--final]
```
- Read-only (GET requests only). Writes positions, open orders, account values, every order, every fill and the
  portfolio history to `docs/archive/monthly-desk-2026-11/`, without account number, account id or keys. `--final`
  writes only `final_state.json` after the account is closed.

### Before execution is turned on
Execution stays off until every item is done, in a reviewed change of its own:
1. A forward sample in `forward_eval.json` that the owner judges long enough (the page shows the number of days),
   with no session written after its open.
2. The book still earns more than its costs in that forward sample; at a fixed 5 bps it lost in validation.
3. An order mode (and a flatten mode) added back to the workflow, with `TRADING` read as exactly `on` and a test for
   it; position and order limits in the code, with tests.
4. A decision record that says why, and an updated page, README and this runbook.
5. One night run by hand with the new mode, then watched.

## 8a. Forward evaluation — `scripts/live_eval.py` (D37)
- `PYTHONPATH=src .venv/bin/python scripts/live_eval.py [--live data/live] [--validation docs/results/validation.json]`
  reads the ledger, `night_*.json` and the live store, writes `data/live/forward_eval.json` and prints
  "N days of forward data". Read-only: no broker, no order, no network. Works on an empty ledger (0 days). The nightly
  job writes the same file after scoring (`score_ledger` in `live_desk.py`) and the page reads it from `live.json`.
- Type check of these modules only: `make typecheck` (mypy, scoped in `pyproject.toml`; the rest of the code is not
  type-checked).

## 8b. Fault injection — `scripts/ops/run_fault_injection.py`
- 500 random scenarios of 10 nights (about 2.5 min) and two deliberate bugs; output
  `data/results/fault_injection.json`.

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
| `ci.yml` | push, pull request | ruff + pytest + docs |
| `nightly.yml` | Worker dispatch (main), schedule 02:00 and 11:30 UTC (backup), push to `docs/**`, `web/**`, `mkdocs.yml` or the workflow, manual (`night` or `site`) | nightly predictions and scoring (no orders), the whole Pages site |
