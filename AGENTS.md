# AGENTS.md — start here

This file is the entry point for any agent (or person) who works on Ghostdesk. Read it first, then only the document
that your task needs. The documents describe the code; you should rarely need to search the code to find out what
exists.

## 1. The project in five lines
Ghostdesk is a research and paper-trading system for US stocks, with three parts:
1. **Signal** — how much a company's 10-K/10-Q text changed since its comparable earlier report ("lazy prices",
   Cohen, Malloy and Nguyen 2020), tested without look-ahead or survivorship bias.
2. **Execution** — VWAP child orders over the first hour. A PPO agent was compared with TWAP, VWAP and
   Almgren-Chriss on replayed real minute bars (Step 4); it did not beat VWAP, so the live desk uses VWAP.
3. **Live** — one GitHub Actions job per US trading day on Alpaca paper trading, and a static GitHub Pages site.

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
| The research plan (public) | [docs/plan.md](docs/plan.md) |
| Data method and coverage (public) | [docs/data.md](docs/data.md) |

## 3. Hard rules (do not break)
1. **No look-ahead.** A report is usable only at the first NYSE open strictly after its SEC acceptance time
   (`data/market_calendar.py:first_open_after`). Numbers come from each report's own XBRL, first reported value only
   (`filings/xbrl.py`). Never use the SEC companyfacts or frames APIs.
2. **No survivorship bias.** The stock list on a date is the S&P 500 on that date (`data/sp500_universe.py`).
3. **The test period 2022-2025 is used once**, after the pre-registration is committed. Build 2016-2019, check
   2020-2021. Do not tune anything on 2022-2025 data.
4. **Secrets.** Never print, log, commit or echo `.env` values. Check a key only by name:
   `grep -c "^NAME=" .env`. GitHub secrets: `SEC_USER_AGENT`, `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`.
5. **No raw data in git.** `data/` is gitignored. Publish only statistics and charts.
6. **SEC fair access.** At most 8 requests per second in total (all parallel jobs together), with the declared
   User-Agent. Use `EdgarClient`; never call SEC URLs with plain `requests`.
7. **No long jobs on the owner's Mac.** A job of more than about 10 minutes runs on GitHub Actions (or Kaggle CPU).
8. **Silent automation.** Scheduled or long workflows must not fail visibly (no notification emails): steps use
   `continue-on-error`, and health is written to a file or the site.
9. **Commits** use the owner's GitHub noreply address and **never** a `Co-Authored-By` line.
10. **Writing.** README, repo description and public docs use plain ASD-STE100 English.

## 4. Commands
```bash
make install          # .venv with the package and dev tools
make check            # ruff + all tests + strict docs build (run before every commit)
make test             # tests only
make universe         # rebuild data/universe.parquet          (about 10 min with a warm SEC cache)
make index            # rebuild data/filings_index.parquet     (about 2 min with a warm cache)
make prices           # rebuild prices and returns (Alpaca)   (about 5 min)
make features RUN=<id># join the shards of a `features` workflow run
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
