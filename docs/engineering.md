# Engineering

Ghostdesk runs with no person at the desk. This page shows how it is built, what can go wrong, and which test
proves that each problem is handled. Details of every module: [modules](dev/modules.md). Every design choice and
why: [decisions](dev/decisions.md).

## The system
```
 21:40 + 23:40 UTC each weekday            every 20 min, 13:05-16:45 UTC (trades on month start)
 ┌──────────────── score ───────────────┐   ┌──────────────────── trade ─────────────────────┐
 │ Wikipedia: today's S&P 500 (+ CIK)   │   │ gate: due? in the window? (runner.decide)       │
 │ SEC: each company's report list      │   │ formation at the last close (runner.formation)  │
 │ new report pairs -> text change      │   │ quintiles -> target shares (fractional longs)   │
 └──────────────┬───────────────────────┘   │ VWAP child orders over the first hour           │
                │                           │ fills -> reconciliation of the book             │
                ▼                           └───────────────┬────────────────────────────────┘
        data/live/ state  ◄─────────────────────────────────┘
        (Actions cache, copy in the private release `live-state`)
                │
                ▼
 site: live.json (account vs SPY, positions, reports, on-target check, health) -> GitHub Pages
```
- **One workflow** (`live.yml`) runs every mode and deploys the whole site. No server, no database, no commit.
- **State** is small files. Alpaca keeps the orders and positions; the job keeps the plan, the signal and the
  arrival prices. Both copies of the job's state (cache and release) are written after each run.
- **Library and script are separate.** `src/ghostdesk/live/` holds the logic with the broker, clock, data and
  store injected; `scripts/live.py` only wires the real ones. So a whole trading day runs in a test in a second.

## Guarantees and the tests that prove them
| Guarantee | How | Test |
|---|---|---|
| No look-ahead | A report counts from the first market open strictly after its SEC acceptance time | `test_calendar.py`, `test_panel.py::test_tradeable_time_and_window`, `test_live.py::test_latest_pairs_uses_only_reports_tradeable_by_the_close` |
| No survivorship bias | The stock list on each date is the S&P 500 on that date, mapped to SEC CIKs with evidence | `test_universe.py` (14 cases from real data: renames, mergers, ticker reuse) |
| Numbers as first reported | Each report's own XBRL; a restatement never replaces the first value | `test_xbrl.py` |
| Live = tested strategy | The live code picks the same report, signal and quintile as the study for past months | `test_parity.py` (found and fixed a tie-break difference) |
| Paper money only | The broker refuses any host but the paper API | `test_live.py::test_broker_refuses_a_live_endpoint`, `test_live.py::test_broker_error_permanence_and_exact_paper_host` |
| A rerun does no harm | A later run trades only what is left; it never overwrites the first record; order IDs carry the run time | `test_runner.py::test_month_start_rebalance_then_rerun_does_nothing` |
| A crash is recovered | A run that dies half way leaves no "done" mark; the next run in the window finishes the trades | `test_runner.py::test_a_run_that_dies_half_way_is_finished_by_the_next_run` |
| A missed day is seen and caught up | A due rebalance outside the window is an error; the next session catches up | `test_runner.py::test_missed_window_is_an_error_and_the_next_session_catches_up` |
| Orders never cross zero | A flip closes the old side first; shorts are whole shares | `test_live.py::test_child_orders_reach_target_and_never_cross_zero` (11 cases x 4 schedules) |
| Rate limits respected | At most 170 requests a minute (limit 200); 429 retried; only a real rejection stops a stock | `test_live.py::test_broker_paces_requests_and_keeps_retrying_rate_limits` |
| The book matches the plan | After each run: stocks within 20% of target, value off target, gross per side | `test_live.py::test_reconcile_target_against_positions` |
| Docs match the code | Every module, public name and script is documented | `test_docs.py` |

## Failure modes
| What fails | What the system does | Where you see it |
|---|---|---|
| SEC or Wikipedia is down | A short stock list stops the score run and keeps yesterday's state; a company whose report list fails keeps its last index rows; a pair that fails is tried again the next day | page health, `score` message |
| GitHub starts a run late or not at all | Twelve trade checks a day and two score runs; a missed rebalance is caught up in the next two sessions | red badge, `trade` message |
| The runner dies during a rebalance | The next run in the window finishes the trades with new order IDs | `rebalance_<date>_<time>.json` |
| Alpaca rate limit or server error | Paced requests, retries for about two minutes, the child order is skipped and the next bucket trades | rejected count on the page |
| A stock cannot be shorted, or is too dear for one share | Left out of the short leg and listed | rebalance record |
| The Actions cache is lost | The job restores its state from the release `live-state`. If both are lost, a trade run stops with an error, the evening score run builds the state again from SEC (about 10 min), and the catch-up trades in the next sessions | run log, red badge |
| A wrong signal or a bad market | Kill switch: `gh variable set TRADING --body off`; close all: `gh workflow run live.yml -f mode=flatten` | page health |
| Any step fails | The workflow does not fail and sends no email; the error is in `live.json` | red badge |

## Numbers
- About 500 report pairs scored from cold in about 10 minutes on a GitHub runner; about 2 minutes a day after.
- About 200 stocks and up to 12 child orders each per rebalance; a trade run takes about 1 hour.
- 150+ tests, about 15 seconds; `make check` = ruff + tests + strict docs build, the same in CI.
