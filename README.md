# Ghostdesk

![CI](https://github.com/shlokkvaishnav/ghostdesk/actions/workflows/ci.yml/badge.svg)

A quant research platform for next-day stock prediction on the S&P 500 as it was on each date. Every night every
model predicts every stock into an append-only ledger, and the ledger is scored forward against the prices that come
later. Order execution is turned off: the paper account holds nothing and no orders are sent.

## What is in it
- **Point-in-time data.** The S&P 500 membership on each date (including companies that later left), and a
  price store built from immutable Parquet batches read through DuckDB, so a backtest sees prices as they were
  known on that day.
- **Feature engine.** A small expression language (`Rank(Ref($close,5)/$close)`) parsed to an AST, with shared
  subexpressions computed once and results cached by content hash. 151 of the 158 Alpha158 factors match a plain
  pandas version to 1e-6 (the other 7 differ only by rounding in tiny values; see docs/engineering.md). On a
  50-symbol subset the engine ran 28.3x faster than pandas in the committed benchmark.
- **Models and backtests.** One interface for reversal, ridge, LightGBM, a small Transformer and zero-shot
  time-series foundation models; walk-forward folds with a purge; trading costs from a spread estimate.
- **Optimizer.** A PCA risk model and a cvxpy problem (dollar, beta and sector neutral, 2% per stock, turnover
  cost) solved in a median of 63 ms (p95 119 ms) on a laptop, 503 of 503 solves optimal.
- **Experiment registry.** Every result is keyed by data, code commit and config, and can be regenerated
  bit for bit.
- **Nightly loop.** Frozen models from a pinned release, checked by SHA-256 against a committed manifest; ledger
  written before the next open, with crash recovery and idempotent reruns. A fault-injection harness runs 500
  simulated scenarios with crashes, rate-limit storms and partial fills and checks six invariants after every step.

## Results so far
2021-2022 historical validation (501 sessions). These numbers were used to choose the models, so they are not an
independent test.

| Measure (LightGBM scores) | Decile book | Optimized book |
|---|---|---|
| Daily turnover | 2.61 | 0.83 (-68%) |
| Gross Sharpe (no costs) | 1.12 | 1.07 |
| Net Sharpe at a fixed 1 bps per unit traded | 0.67 | 0.73 |
| Net Sharpe at a fixed 2 bps per unit traded | 0.22 | 0.39 |
| Net Sharpe after the Corwin-Schultz spread estimate | -0.77 | 1.04 |
| Net at a fixed 5 bps per trade | -6.6 bps/day | -1.5 bps/day |

Both books lose money at a fixed 5 bps cost. Costs are one-way, per unit of traded value. The spread-estimate row is
the most favourable one and should not be read as the headline: the 21-day Corwin-Schultz half-spread is clipped at
zero, and it is exactly zero for 63.9% of member-days in 2021-2022. The optimizer uses the same estimate in its trading
penalty, so it trades mostly where the estimated cost is zero (implied 0.1 bps against 4.2 bps for the decile book).
The optimizer's advantage is lower trading cost; its gross Sharpe is slightly below the decile book's. Forward test (days after the models were frozen): 0 days so far.

The test period (2023-01 to 2026-10) stays locked in code until its pre-registration is final and timestamped.

## Run it
```bash
make install && make check
```

The project page: https://shlokkvaishnav.github.io/ghostdesk/. How it is built: [docs/engineering.md](docs/engineering.md).
Developers and AI agents start at [AGENTS.md](AGENTS.md).
