# AGENTS.md — start here

This file is the entry point for any agent (or person) who works on Ghostdesk. Read it first, then only the document
that your task needs. The documents describe the code; you should rarely need to search the code to find out what
exists.

## 1. The project in short
Ghostdesk is a quant research platform for next-day cross-sectional prediction on the survivorship-free S&P 500,
with a nightly prediction ledger that is scored forward (decision D26). Order execution is disabled (D38): the paper
account on Alpaca is flat and the nightly workflow fixes `TRADING` to `off`. Parts:
1. **Data** — the point-in-time S&P 500 (`data/sp500_universe.py`) and a point-in-time price store with as-of reads
   (`data/store.py`).
2. **Features** — a small expression language compiled to vectorized numpy, with a content-hashed cache.
3. **Models and backtests** — one model interface, a walk-forward backtester with costs, a portfolio optimizer and
   an experiment registry (`research/`).
4. **Live** — each night after the close every model (frozen, from the release `models-v1`, checked against
   `docs/results/MODEL_MANIFEST.json`) predicts every member into an append-only ledger before the next open, and the
   ledger is scored forward (`forward_eval.json`). The market-on-open order code exists but is not run; turning it on
   is a separate, reviewed change (runbook, "Before execution is turned on").

## 2. Where to find what
| Need | Document |
|---|---|
| What is done, what is next, acceptance criteria | [docs/dev/status.md](docs/dev/status.md) |
| How the parts connect (pipeline, layers) | [docs/dev/architecture.md](docs/dev/architecture.md) |
| Every module and its public functions | [docs/dev/modules.md](docs/dev/modules.md) |
| Every data file: producer, columns, keys, invariants | [docs/dev/data-contracts.md](docs/dev/data-contracts.md) |
| How to rebuild each data file; secrets; workflows | [docs/dev/runbook.md](docs/dev/runbook.md) |
| Data problems found, their causes and fixes | [docs/dev/data-quality.md](docs/dev/data-quality.md) |
| Design decisions and why | [docs/dev/decisions.md](docs/dev/decisions.md) |
| Rules for code, commits, secrets, writing | [docs/dev/conventions.md](docs/dev/conventions.md) |
| Data method and coverage (public) | [docs/data.md](docs/data.md) |

## 3. Hard rules (do not break)
1. **No look-ahead.** Features use data through the close of day t; the label is the open(t+1) to open(t+2) residual
   return. Research reads prices only through `data.store.PriceStore`.
2. **No survivorship bias.** The stock list on a date is the S&P 500 on that date (`data/sp500_universe.py`).
3. **The test period 2023-01 to 2026-10 is used once**, after the pre-registration is final, committed and stamped
   (`research/holdout_lock.py`). Train 2016-2020, validate 2021-2022. Do not tune anything on test data.
4. **Secrets.** Never print, log, commit or echo `.env` values. Check a key only by name:
   `grep -c "^NAME=" .env`. GitHub secrets: `SEC_USER_AGENT`, `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`, `STATE_KEY` (encrypts release files,
   D25; a copy is in `.env`).
5. **No raw data in git.** `data/` is gitignored. Publish only statistics and charts.
6. **SEC fair access.** At most 8 requests per second, with the declared User-Agent. Use `EdgarClient`.
7. **No long jobs on the owner's Mac.** A job of more than about 10 minutes runs on GitHub Actions or Kaggle.
8. **Quiet automation.** A successful scheduled run sends nothing. Site steps use `continue-on-error`; a failure
   of the night itself (models missing or changed, no ledger, no evaluation, state not saved) fails the run (D38).
9. **Commits** use the owner's GitHub noreply address and **never** a `Co-Authored-By` line.
10. **Writing.** README, repo description and public docs use plain, normal English.
11. **No orders.** Never set `TRADING=on`, enable the old `live` workflow, or add an order step without the owner's
   reviewed change (D38).

## 4. Commands
```bash
make install          # .venv with the package and dev tools
make check            # ruff + all tests + strict docs build (run before every commit)
make test             # tests only
make universe         # rebuild data/universe.parquet          (about 10 min with a warm SEC cache)
make prices           # the 2016-2025 seed load (Alpaca)        (about 5 min)
make update           # append new sessions to the price store   (under a minute a day)
make sectors          # data/sectors.parquet from the SEC cache
```
Without `make`: `PYTHONPATH=src .venv/bin/python -u scripts/<name>.py` (macOS hides `.pth` files, so set
`PYTHONPATH=src`).

## 5. Definition of done for a change
- `make check` passes (ruff, tests, `mkdocs build --strict`).
- A new public function or module is listed in `docs/dev/modules.md`; a new or changed data file is in
  `docs/dev/data-contracts.md`; a new script is in `docs/dev/runbook.md`. `tests/test_docs.py` enforces this.
- A data problem that you find and fix gets an entry in `docs/dev/data-quality.md`.
- A choice between real alternatives gets an entry in `docs/dev/decisions.md`.
- `docs/dev/status.md` reflects the new state.
