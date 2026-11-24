# Ghostdesk

![CI](https://github.com/shlokkvaishnav/ghostdesk/actions/workflows/ci.yml/badge.svg)

A quant research platform for next-day stock prediction on the S&P 500 as it was on each date, with a nightly
paper-trading loop. Every night every model predicts every stock into an append-only ledger, and a paper account
trades the ensemble at the next open.

## What is in it
- **Point-in-time data.** The S&P 500 membership on each date (including companies that later left), and a
  price store built from immutable Parquet batches read through DuckDB, so a backtest sees prices as they were
  known on that day.
- **Feature engine.** A small expression language (`Rank(Ref($close,5)/$close)`) parsed to an AST, with shared
  subexpressions computed once and results cached by content hash. The 158 Alpha158 factors match a plain pandas
  version exactly and run about 24-30x faster.
- **Models and backtests.** One interface for reversal, ridge, LightGBM, a small Transformer and zero-shot
  time-series foundation models; walk-forward folds with a purge; trading costs from a spread estimate.
- **Optimizer.** A PCA risk model and a cvxpy problem (dollar, beta and sector neutral, 2% per stock, turnover
  cost) solved in about 60 ms a night.
- **Experiment registry.** Every result is keyed by data, code commit and config, and can be regenerated
  bit for bit.
- **Nightly loop.** Ledger first, then market-on-open orders, with crash recovery, idempotent reruns and a kill
  switch. A fault-injection harness runs thousands of simulated nights with crashes, rate-limit storms and partial
  fills and checks six invariants after every step.

The test period (2023-01 to 2026-10) stays locked in code until its pre-registration is final and timestamped.

## Run it
```bash
make install && make check
```

The live page: https://shlokkvaishnav.github.io/ghostdesk/. How it is built: [docs/engineering.md](docs/engineering.md).
Developers and AI agents start at [AGENTS.md](AGENTS.md).
