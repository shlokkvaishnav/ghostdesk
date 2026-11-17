# Conventions

## Code
- Python 3.12, `src/` layout, package `ghostdesk`. Ruff: line length 120, import sorting (`I`).
- Library code (`src/`) is pure where possible: network clients are passed in (`EdgarClient`, `AlpacaClient`) and
  accept injected `session`, `sleep`, `clock`, so tests never touch the network.
- Scripts (`scripts/`) do orchestration and file I/O, print one summary line, and write a `*_summary.json` or
  `*_coverage.json` with the numbers that the docs quote.
- No `NotImplementedError` stubs; no dead code. Code that the plan does not use is deleted (git keeps history).
- Docstrings state the contract and the reason for any non-obvious rule (for example why a threshold exists).

## Tests
- Every rule that protects against look-ahead, survivorship or a data error has a unit test on a small made-up
  table (see `tests/test_sp500_universe.py`, `tests/test_daily_returns.py`, `tests/test_xbrl.py`).
- A bug found in real data gets a test that reproduces it before the fix (named after the case, e.g. ARNC, DOW).
- `tests/test_docs.py` keeps the developer docs true to the code.

## Data
- `data/` is never committed. Inputs that a workflow needs go to a private release; outputs come back as artifacts.
- A threshold or rule that changes data is written in the docstring and in `docs/dev/data-quality.md`.
- Missing is NaN, never a guess. Coverage is measured and published.

## Git
- Commit email: the owner's GitHub noreply address (global git config). **No `Co-Authored-By` lines.**
- Message: a short summary line, then what changed and why, with the numbers that changed.
- Run `make check` before a commit. Check the diff for secrets:
  `git diff --cached | grep -inE "@gmail|ALPACA_|SEC_USER_AGENT="`.
- The repo is private until the project is finished; then public.
- Exactly 5 GitHub topics, all computer-science terms.

## Secrets
- `.env` values are never printed, logged, echoed or written to a file in git. Check by name only.
- A value is moved into GitHub secrets with a pipe, never shown:
  `grep '^NAME=' .env | cut -d= -f2- | gh secret set NAME`.

## Automation
- Scheduled and long workflows send no failure emails: steps use `continue-on-error`; health goes into the
  outputs (a summary file, or the site's JSON). Always check step results after a run.

## Writing
- README, repo description and public docs (`docs/*.md`): plain ASD-STE100 English (short sentences, active voice,
  one meaning per word), result first.
- Developer docs (`docs/dev/`): precise and short; tables over prose; numbers with dates.
