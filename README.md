# Ghostdesk: a trading desk with no people at it

![CI](https://github.com/shlokkvaishnav/ghostdesk/actions/workflows/ci.yml/badge.svg)

**Can a program read company reports, choose stocks, and trade them at a low cost, with no person at the desk?**

## What it does
A quant trading desk does three jobs. Ghostdesk does all three by itself:
1. **Signal.** It reads each annual and quarterly report (10-K, 10-Q) that a company sends to the SEC, and measures
   how much the text changed since the comparable earlier report. Research shows that companies that change their
   reports a lot often do worse later ("lazy prices", Cohen, Malloy and Nguyen, 2020). Ghostdesk tests this again,
   with no hindsight.
2. **Execution.** It splits each trade into small orders over the first hour. A reinforcement-learning agent (PPO)
   was tested against standard methods (TWAP, VWAP, Almgren-Chriss) on real minute bars. It did not beat VWAP,
   so the live desk uses VWAP.
3. **Live.** Each US trading day, one job trades with fake money (Alpaca paper trading) and updates a web page.

## Status
- **Data: done.** The S&P 500 as it was on each date (with the companies that left it), 47,719 reports with the
  exact time the SEC accepted each one, text-change scores for 30,514 report pairs, and clean daily prices for
  2016-2025. How each problem in the data was found and fixed: [data quality](docs/dev/data-quality.md).
- **Signal study: done.** In the pre-registered test (2022-2025), the effect was **not detected**: +0.09% per month
  after costs, 95% interval −0.36% to +0.54%. Over 2016-2025 the upper limit is about 0.5% per month. Details:
  [results](docs/results.md).
- **Backtest mistakes, measured:** for this signal, timing look-ahead changes little; the stock list and mixing
  annual with quarterly reports change the most.
- **Execution study: done.** On real 2024 minute bars, the PPO agent did **not** trade more cheaply than VWAP at
  any order size; at 5% of daily volume it cost about 1 bp more. The strategy can trade up to about $7.2 billion
  before costs use up its gross return. Details: [results](docs/results.md#results-the-execution-study).
- **Live job: built.** Each month, the desk buys the least-changed and sells the most-changed reports with
  fake money (Alpaca paper trading), in VWAP orders over the first hour. The live page
  (https://shlokkvaishnav.github.io/ghostdesk/) shows the account against SPY.
- **Next:** the first trades, then the research note (Step 6).

## Run it
```bash
make install && make check
```
The plan: [plan](docs/plan.md). The data method: [data](docs/data.md). Raw market data is not published; only charts and
statistics are. Developers and AI agents start at [AGENTS.md](AGENTS.md).
